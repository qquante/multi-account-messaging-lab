from __future__ import annotations

import asyncio
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Iterable

from telethon import TelegramClient, events, functions, types
from telethon.errors import FloodWaitError, RPCError, SessionPasswordNeededError

from .config import AccountConfig, Allowlist, RuntimeConfig, account_credentials
from .rate_limit import RateLimiter
from .storage import Storage


@dataclass(slots=True)
class ConnectedAccount:
    account: AccountConfig
    client: TelegramClient


def session_path(cfg: RuntimeConfig, account: AccountConfig) -> Path:
    return cfg.session_dir / account.session_name


def account_rate_limit(cfg: RuntimeConfig, account: AccountConfig) -> float:
    return float(account.rate_limit_seconds or cfg.default_rate_limit_seconds)


def make_client(cfg: RuntimeConfig, account: AccountConfig) -> TelegramClient:
    api_id, api_hash = account_credentials(cfg, account)
    cfg.session_dir.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(session_path(cfg, account)),
        api_id,
        api_hash,
        sequential_updates=True,
        connection_retries=5,
        retry_delay=3,
        auto_reconnect=True,
    )


async def authenticate_account(cfg: RuntimeConfig, account: AccountConfig, storage: Storage) -> None:
    client = make_client(cfg, account)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            phone = account.phone or input(f"Telefone para {account.id}: ").strip()
            await client.send_code_request(phone)
            code = input(f"Codigo Telegram para {account.id}: ").strip()
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                password = getpass(f"Senha 2FA para {account.id}: ")
                await client.sign_in(password=password)

        me = await client.get_me()
        storage.set_status(
            account.id,
            authorized=True,
            user_id=getattr(me, "id", None),
            username=getattr(me, "username", None),
            phone=getattr(me, "phone", None),
        )
        print(f"[OK] {account.id} autorizado como {getattr(me, 'username', None) or getattr(me, 'id', None)}")
    except Exception as exc:
        storage.set_status(account.id, authorized=False, error=str(exc))
        raise
    finally:
        await client.disconnect()


async def connect_account(
    cfg: RuntimeConfig,
    account: AccountConfig,
    storage: Storage,
) -> ConnectedAccount:
    client = make_client(cfg, account)
    await client.connect()
    authorized = await client.is_user_authorized()
    if not authorized:
        storage.set_status(account.id, authorized=False, error="not_authorized")
        await client.disconnect()
        raise RuntimeError(f"{account.id} nao autorizada. Rode auth primeiro.")

    me = await client.get_me()
    storage.set_status(
        account.id,
        authorized=True,
        user_id=getattr(me, "id", None),
        username=getattr(me, "username", None),
        phone=getattr(me, "phone", None),
    )
    return ConnectedAccount(account=account, client=client)


async def disconnect_all(connections: Iterable[ConnectedAccount]) -> None:
    for conn in connections:
        try:
            await conn.client.disconnect()
        except Exception:
            pass


async def status_accounts(cfg: RuntimeConfig, accounts: list[AccountConfig], storage: Storage) -> None:
    for account in accounts:
        client = make_client(cfg, account)
        try:
            await client.connect()
            authorized = await client.is_user_authorized()
            if authorized:
                me = await client.get_me()
                storage.set_status(
                    account.id,
                    authorized=True,
                    user_id=getattr(me, "id", None),
                    username=getattr(me, "username", None),
                    phone=getattr(me, "phone", None),
                )
                print(f"{account.id}: authorized user_id={getattr(me, 'id', None)} username={getattr(me, 'username', None)}")
            else:
                storage.set_status(account.id, authorized=False, error="not_authorized")
                print(f"{account.id}: not_authorized")
        except Exception as exc:
            storage.set_status(account.id, authorized=False, error=str(exc))
            print(f"{account.id}: error={exc}")
        finally:
            await client.disconnect()


async def send_message(
    cfg: RuntimeConfig,
    storage: Storage,
    allowlist: Allowlist,
    account: AccountConfig,
    *,
    peer: str,
    text: str,
    reply_to: int | None = None,
    parse_mode: str | None = None,
    dry_run: bool = False,
) -> int | None:
    allowlist.validate_peer_input(peer)
    limiter = RateLimiter(storage)
    await limiter.wait_for_slot(
        account_id=account.id,
        peer=peer,
        min_interval_seconds=account_rate_limit(cfg, account),
        dry_run=dry_run,
    )
    if dry_run:
        print(f"[DRY-RUN] {account.id} -> {peer}: {text!r} reply_to={reply_to}")
        return None

    conn = await connect_account(cfg, account, storage)
    try:
        msg = await conn.client.send_message(peer, text, reply_to=reply_to, parse_mode=parse_mode)
        storage.record_event(
            account_id=account.id,
            direction="out",
            action="send",
            peer_id=peer,
            message_id=msg.id,
            reply_to_message_id=reply_to,
            text=text,
        )
        print(f"[OK] {account.id} enviou message_id={msg.id}")
        return int(msg.id)
    except FloodWaitError as exc:
        storage.record_event(
            account_id=account.id,
            direction="out",
            action="flood_wait",
            peer_id=peer,
            text=text,
            raw={"seconds": exc.seconds},
        )
        raise
    finally:
        await conn.client.disconnect()


async def react_message(
    cfg: RuntimeConfig,
    storage: Storage,
    allowlist: Allowlist,
    account: AccountConfig,
    *,
    peer: str,
    message_id: int,
    emoji: str,
    dry_run: bool = False,
) -> None:
    allowlist.validate_peer_input(peer)
    limiter = RateLimiter(storage)
    await limiter.wait_for_slot(
        account_id=account.id,
        peer=peer,
        min_interval_seconds=account_rate_limit(cfg, account),
        dry_run=dry_run,
    )
    if dry_run:
        print(f"[DRY-RUN] {account.id} react {emoji!r} em {peer}/{message_id}")
        return

    conn = await connect_account(cfg, account, storage)
    try:
        entity = await conn.client.get_input_entity(peer)
        await conn.client(
            functions.messages.SendReactionRequest(
                peer=entity,
                msg_id=message_id,
                reaction=[types.ReactionEmoji(emoticon=emoji)],
            )
        )
        storage.record_event(
            account_id=account.id,
            direction="out",
            action="react",
            peer_id=peer,
            message_id=message_id,
            text=emoji,
        )
        print(f"[OK] {account.id} reagiu {emoji} em message_id={message_id}")
    finally:
        await conn.client.disconnect()


async def pin_message(
    cfg: RuntimeConfig,
    storage: Storage,
    allowlist: Allowlist,
    account: AccountConfig,
    *,
    peer: str,
    message_id: int,
    notify: bool,
    dry_run: bool = False,
) -> None:
    allowlist.validate_peer_input(peer)
    if dry_run:
        print(f"[DRY-RUN] {account.id} pin {peer}/{message_id} notify={notify}")
        return
    conn = await connect_account(cfg, account, storage)
    try:
        await conn.client.pin_message(peer, message_id, notify=notify)
        storage.record_event(
            account_id=account.id,
            direction="out",
            action="pin",
            peer_id=peer,
            message_id=message_id,
        )
        print(f"[OK] {account.id} fixou message_id={message_id}")
    finally:
        await conn.client.disconnect()


async def mark_read(
    cfg: RuntimeConfig,
    storage: Storage,
    allowlist: Allowlist,
    account: AccountConfig,
    *,
    peer: str,
    message_id: int | None,
    dry_run: bool = False,
) -> None:
    allowlist.validate_peer_input(peer)
    if dry_run:
        print(f"[DRY-RUN] {account.id} read {peer} max_id={message_id}")
        return
    conn = await connect_account(cfg, account, storage)
    try:
        await conn.client.send_read_acknowledge(peer, max_id=message_id)
        storage.record_event(
            account_id=account.id,
            direction="out",
            action="read",
            peer_id=peer,
            message_id=message_id,
        )
        print(f"[OK] {account.id} marcou como lido max_id={message_id}")
    finally:
        await conn.client.disconnect()


def render_template(template: str, *, account_id: str, sender_id: str | int | None, text: str | None) -> str:
    return template.format(account_id=account_id, sender_id=sender_id or "", text=text or "")


async def listen(
    cfg: RuntimeConfig,
    storage: Storage,
    allowlist: Allowlist,
    accounts: list[AccountConfig],
    *,
    auto_reply_mentions: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    limiter = RateLimiter(storage)
    connections: list[ConnectedAccount] = []

    async def connect_one(account: AccountConfig) -> None:
        conn = await connect_account(cfg, account, storage)
        connections.append(conn)
        print(f"[OK] conectado {account.id}")

        @conn.client.on(events.NewMessage(incoming=True))
        async def handler(event: events.NewMessage.Event, account_id: str = account.id) -> None:
            if not await allowlist.is_event_allowed(event):
                return
            reply_to_id = None
            if event.message.reply_to:
                reply_to_id = event.message.reply_to.reply_to_msg_id
            storage.record_event(
                account_id=account_id,
                direction="in",
                action="message",
                peer_id=event.chat_id,
                message_id=event.id,
                reply_to_message_id=reply_to_id,
                sender_id=event.sender_id,
                text=event.raw_text,
                raw={
                    "mentioned": bool(getattr(event, "mentioned", False)),
                    "is_private": bool(event.is_private),
                    "is_group": bool(event.is_group),
                    "is_channel": bool(event.is_channel),
                },
            )
            print(f"[IN] {account_id} chat={event.chat_id} msg={event.id} sender={event.sender_id}: {event.raw_text[:120]!r}")

            if auto_reply_mentions and getattr(event, "mentioned", False):
                peer = str(event.chat_id)
                await limiter.wait_for_slot(
                    account_id=account_id,
                    peer=peer,
                    min_interval_seconds=account_rate_limit(cfg, account),
                )
                text = render_template(
                    auto_reply_mentions,
                    account_id=account_id,
                    sender_id=event.sender_id,
                    text=event.raw_text,
                )
                try:
                    sent = await event.reply(text)
                    storage.record_event(
                        account_id=account_id,
                        direction="out",
                        action="auto_reply_mention",
                        peer_id=event.chat_id,
                        message_id=sent.id,
                        reply_to_message_id=event.id,
                        text=text,
                    )
                except RPCError as exc:
                    storage.record_event(
                        account_id=account_id,
                        direction="out",
                        action="auto_reply_error",
                        peer_id=event.chat_id,
                        reply_to_message_id=event.id,
                        text=str(exc),
                    )

    try:
        for index, account in enumerate(accounts):
            if not account.receive_enabled:
                continue
            await connect_one(account)
            if index < len(accounts) - 1:
                await asyncio.sleep(cfg.connect_delay_seconds)

        if not connections:
            print("Nenhuma conta conectada.")
            return

        print(f"Escutando {len(connections)} conta(s). Ctrl+C para parar.")
        if duration_seconds:
            await asyncio.sleep(duration_seconds)
        else:
            await asyncio.Event().wait()
    finally:
        await disconnect_all(connections)


async def arena(
    cfg: RuntimeConfig,
    storage: Storage,
    allowlist: Allowlist,
    accounts: list[AccountConfig],
    *,
    peer: str,
    messages: list[str],
    rounds: int,
    min_delay: float,
    max_delay: float,
    dry_run: bool,
) -> None:
    allowlist.validate_peer_input(peer)
    if not accounts:
        print("Nenhuma conta selecionada.")
        return
    delay = max(min_delay, 0)
    for round_idx in range(1, rounds + 1):
        print(f"[ARENA] rodada {round_idx}/{rounds}")
        for idx, account in enumerate(accounts):
            template = messages[idx % len(messages)] if messages else "Agent {account_id}: ping controlado."
            text = render_template(template, account_id=account.id, sender_id=None, text=None)
            await send_message(
                cfg,
                storage,
                allowlist,
                account,
                peer=peer,
                text=text,
                dry_run=dry_run,
            )
            if idx < len(accounts) - 1:
                await asyncio.sleep(delay)
                if max_delay > min_delay:
                    delay = min(max_delay, delay + 1)
