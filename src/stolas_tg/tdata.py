from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import AccountConfig, ConfigError, RuntimeConfig, account_credentials
from .storage import Storage
from .telegram_stack import session_path


@dataclass(slots=True)
class TDataResult:
    account_id: str
    session_base: Path
    session_file: Path
    user_id: int | None
    username: str | None
    phone: str | None


def _import_opentele():
    try:
        from opentele.api import API, APIData, CreateNewSession, UseCurrentSession
        from opentele.td import TDesktop
        from opentele.tl import TelegramClient as OpenTeleTelegramClient
    except ImportError as exc:
        raise ConfigError(
            "TDATA requer opentele. Instale com: .\\.venv\\Scripts\\python.exe -m pip install -e .[tdata]"
        ) from exc
    return API, APIData, CreateNewSession, UseCurrentSession, TDesktop, OpenTeleTelegramClient


def _session_file_from_base(base: Path) -> Path:
    text = str(base)
    if text.endswith(".session"):
        return base
    return Path(text + ".session")


def _backup_existing_session(session_file: Path) -> list[Path]:
    backed_up: list[Path] = []
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidates = [
        session_file,
        Path(str(session_file) + "-journal"),
        Path(str(session_file) + "-wal"),
        Path(str(session_file) + "-shm"),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        backup = candidate.with_name(candidate.name + f".bak.{stamp}")
        candidate.replace(backup)
        backed_up.append(backup)
    return backed_up


def _resolve_tdata_path(path: Path) -> Path:
    raw = path.expanduser()
    if raw.name.lower() == "tdata":
        return raw
    nested = raw / "tdata"
    if nested.exists():
        return nested
    return raw


def _stack_api_data(cfg: RuntimeConfig, account: AccountConfig):
    _api, APIData, _create_new, _use_current, _tdesktop, _client = _import_opentele()
    api_id, api_hash = account_credentials(cfg, account)
    return APIData(
        api_id=api_id,
        api_hash=api_hash,
        device_model="Stolas Telegram Stack",
        system_version="Windows",
        app_version="0.1.0",
        lang_code="en",
        system_lang_code="en-US",
    )


def _desktop_api(system: str, unique_id: str):
    API, _api_data, _create_new, _use_current, _tdesktop, _client = _import_opentele()
    return API.TelegramDesktop.Generate(system=system, unique_id=unique_id)


async def import_tdata(
    cfg: RuntimeConfig,
    storage: Storage,
    account: AccountConfig,
    *,
    tdata_path: Path,
    mode: str,
    passcode: str | None,
    password: str | None,
    system: str,
    force: bool,
    ack_api_risk: bool,
    dry_run: bool,
) -> TDataResult | None:
    API, _api_data, CreateNewSession, UseCurrentSession, TDesktop, _client = _import_opentele()
    resolved_tdata = _resolve_tdata_path(tdata_path)
    if not resolved_tdata.exists() or not resolved_tdata.is_dir():
        raise ConfigError(f"TDATA nao encontrado ou nao e diretorio: {resolved_tdata}")

    session_base = session_path(cfg, account)
    session_file = _session_file_from_base(session_base)
    if session_file.exists() and not force:
        raise ConfigError(f"Sessao ja existe: {session_file}. Use --force para criar backup e sobrescrever.")

    if mode == "create-new":
        pass
    elif mode == "use-current":
        if not ack_api_risk:
            raise ConfigError(
                "use-current reaproveita a auth key do Telegram Desktop. Use --ack-api-risk para confirmar."
            )
    else:
        raise ConfigError("mode precisa ser create-new ou use-current.")

    print(f"[TDATA] account={account.id} tdata={resolved_tdata} session={session_file} mode={mode}")
    if dry_run:
        return None

    cfg.session_dir.mkdir(parents=True, exist_ok=True)
    if force:
        backups = _backup_existing_session(session_file)
        for backup in backups:
            print(f"[BACKUP] {backup}")

    tdesk = TDesktop(
        str(resolved_tdata),
        api=_desktop_api(system, str(resolved_tdata.resolve())),
        passcode=passcode,
    )
    if mode == "create-new":
        flag = CreateNewSession
        api = _stack_api_data(cfg, account)
    else:
        flag = UseCurrentSession
        api = API.TelegramDesktop.Generate(system=system, unique_id=str(resolved_tdata.resolve()))
    client = await tdesk.ToTelethon(
        session=str(session_base),
        flag=flag,
        api=api,
        password=password,
        sequential_updates=True,
        connection_retries=5,
        retry_delay=3,
        auto_reconnect=True,
    )

    try:
        await client.connect()
        authorized = await client.is_user_authorized()
        if not authorized:
            raise ConfigError("TDATA importado, mas a sessao resultante nao esta autorizada.")
        me = await client.get_me()
        user_id = getattr(me, "id", None)
        username = getattr(me, "username", None)
        phone = getattr(me, "phone", None)
        storage.set_status(
            account.id,
            authorized=True,
            user_id=user_id,
            username=username,
            phone=phone,
        )
        storage.record_event(
            account_id=account.id,
            direction="local",
            action="import_tdata",
            peer_id=str(resolved_tdata),
            raw={"mode": mode, "user_id": user_id, "username": username},
        )
        print(f"[OK] TDATA importado para {account.id}: user_id={user_id} username={username}")
        return TDataResult(account.id, session_base, session_file, user_id, username, phone)
    finally:
        await client.disconnect()


async def export_tdata(
    cfg: RuntimeConfig,
    storage: Storage,
    account: AccountConfig,
    *,
    out_tdata_path: Path,
    passcode: str | None,
    password: str | None,
    system: str,
    dry_run: bool,
) -> Path | None:
    _api, _api_data, CreateNewSession, _use_current, _tdesktop, OpenTeleTelegramClient = _import_opentele()
    target = out_tdata_path.expanduser()
    if target.exists() and any(target.iterdir()):
        raise ConfigError(f"Destino TDATA ja existe e nao esta vazio: {target}")

    session_base = session_path(cfg, account)
    session_file = _session_file_from_base(session_base)
    if not session_file.exists():
        raise ConfigError(f"Sessao Telethon nao encontrada para exportar: {session_file}")

    print(f"[TDATA] export account={account.id} session={session_file} out={target}")
    if dry_run:
        return None

    target.mkdir(parents=True, exist_ok=True)
    client = OpenTeleTelegramClient(str(session_base), api=_stack_api_data(cfg, account))
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise ConfigError(f"Sessao {session_file} nao esta autorizada.")
        tdesk = await client.ToTDesktop(
            flag=CreateNewSession,
            api=_desktop_api(system, account.session_name),
            password=password,
        )
        saved = tdesk.SaveTData(str(target), passcode=passcode)
        if not saved:
            raise ConfigError(f"Falha ao salvar TDATA em: {target}")
        me = await client.get_me()
        storage.record_event(
            account_id=account.id,
            direction="local",
            action="export_tdata",
            peer_id=str(target),
            raw={"user_id": getattr(me, "id", None), "username": getattr(me, "username", None)},
        )
        print(f"[OK] TDATA exportado: {target}")
        return target
    except Exception:
        if target.exists() and not any(target.iterdir()):
            shutil.rmtree(target)
        raise
    finally:
        await client.disconnect()
