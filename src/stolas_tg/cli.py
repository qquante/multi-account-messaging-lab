from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

from .config import (
    ConfigError,
    DEFAULT_ALLOWLIST,
    DEFAULT_CONFIG,
    get_account,
    load_allowlist,
    load_config,
    scaffold_accounts,
    select_accounts,
)
from .storage import Storage
from .telegram_stack import (
    arena,
    authenticate_account,
    listen,
    mark_read,
    pin_message,
    react_message,
    send_message,
    status_accounts,
)
from .tdata import export_tdata, import_tdata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stolas-tg")
    parser.add_argument("--config", default=None, help="Caminho do accounts config.")
    parser.add_argument("--allowlist", default=None, help="Caminho da allowlist.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scaffold-accounts", help="Gera config com N slots de conta.")
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--out", default=str(DEFAULT_CONFIG))
    p.add_argument("--force", action="store_true")

    sub.add_parser("init", help="Cria diretorios, DB e allowlist local se necessario.")
    sub.add_parser("config-check", help="Valida config e allowlist.")

    p = sub.add_parser("auth", help="Login interativo de uma conta.")
    p.add_argument("--account", required=True)

    p = sub.add_parser("auth-all", help="Login interativo das contas selecionadas.")
    p.add_argument("--accounts", default="enabled", help="enabled, all ou acc001,acc002.")

    p = sub.add_parser("import-tdata", help="Importa Telegram Desktop tdata para uma sessao Telethon do stack.")
    p.add_argument("--account", required=True)
    p.add_argument("--tdata-path", required=True, help="Pasta tdata ou pasta Telegram Desktop que contem tdata.")
    p.add_argument("--mode", choices=["create-new", "use-current"], default="create-new")
    p.add_argument("--passcode", default=None, help="Local passcode do Telegram Desktop, se existir.")
    p.add_argument("--password", default=None, help="Senha 2FA do Telegram, se CreateNewSession pedir.")
    p.add_argument("--system", default="windows", choices=["windows", "macos", "linux"])
    p.add_argument("--force", action="store_true", help="Faz backup da sessao existente e sobrescreve.")
    p.add_argument("--ack-api-risk", action="store_true", help="Obrigatorio para mode=use-current.")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("export-tdata", help="Exporta uma sessao Telethon do stack para pasta tdata.")
    p.add_argument("--account", required=True)
    p.add_argument("--out-tdata-path", required=True)
    p.add_argument("--passcode", default=None, help="Local passcode para proteger o TDATA exportado.")
    p.add_argument("--password", default=None, help="Senha 2FA do Telegram, se necessaria.")
    p.add_argument("--system", default="windows", choices=["windows", "macos", "linux"])
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("status", help="Checa autorizacao/conexao.")
    p.add_argument("--accounts", default="enabled", help="enabled, all ou acc001,acc002.")

    p = sub.add_parser("listen", help="Recebe mensagens das contas selecionadas.")
    p.add_argument("--accounts", default="enabled", help="enabled, all ou acc001,acc002.")
    p.add_argument("--auto-reply-mentions", default=None)
    p.add_argument("--duration", type=float, default=None, help="Segundos para rodar; vazio roda ate Ctrl+C.")

    p = sub.add_parser("send", help="Envia mensagem.")
    p.add_argument("--account", required=True)
    p.add_argument("--peer", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--reply-to", type=int, default=None)
    p.add_argument("--parse-mode", choices=["md", "markdown", "html", "none"], default="none")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("react", help="Adiciona reaction/emoji em mensagem.")
    p.add_argument("--account", required=True)
    p.add_argument("--peer", required=True)
    p.add_argument("--message-id", type=int, required=True)
    p.add_argument("--emoji", required=True)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("pin", help="Fixa mensagem.")
    p.add_argument("--account", required=True)
    p.add_argument("--peer", required=True)
    p.add_argument("--message-id", type=int, required=True)
    p.add_argument("--notify", dest="notify", action="store_true", default=False)
    p.add_argument("--no-notify", dest="notify", action="store_false")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("read", help="Marca mensagens como lidas ate message-id.")
    p.add_argument("--account", required=True)
    p.add_argument("--peer", required=True)
    p.add_argument("--message-id", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("arena", help="Rodada controlada entre contas habilitadas.")
    p.add_argument("--accounts", default="enabled", help="enabled, all ou acc001,acc002.")
    p.add_argument("--peer", required=True)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--min-delay", type=float, default=20)
    p.add_argument("--max-delay", type=float, default=45)
    p.add_argument("--messages-file", default="config/arena_prompts.example.json")
    p.add_argument("--dry-run", action="store_true")

    return parser


def _path(value: str | None) -> Path | None:
    return None if value is None else Path(value)


def _load(args: argparse.Namespace):
    cfg = load_config(_path(args.config))
    allowlist = load_allowlist(_path(args.allowlist))
    storage = Storage(cfg.db_path, cfg.jsonl_path)
    return cfg, allowlist, storage


def _parse_mode(value: str) -> str | None:
    if value == "none":
        return None
    if value == "md":
        return "markdown"
    return value


def cmd_scaffold(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if out.exists() and not args.force:
        raise ConfigError(f"{out} ja existe. Use --force para sobrescrever.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scaffold_accounts(args.count), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] gerado {out} com {args.count} contas placeholder.")


def cmd_init(args: argparse.Namespace) -> None:
    cfg, _allowlist, storage = _load(args)
    cfg.session_dir.mkdir(parents=True, exist_ok=True)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_ALLOWLIST.exists() and Path("config/allowlist.example.json").exists():
        shutil.copyfile("config/allowlist.example.json", DEFAULT_ALLOWLIST)
        print(f"[OK] criado {DEFAULT_ALLOWLIST}")
    storage.init()
    storage.close()
    print(f"[OK] init: sessions={cfg.session_dir} db={cfg.db_path} jsonl={cfg.jsonl_path}")


def cmd_config_check(args: argparse.Namespace) -> None:
    cfg, allowlist, storage = _load(args)
    storage.close()
    enabled = [item for item in cfg.accounts if item.enabled]
    print(f"[OK] contas={len(cfg.accounts)} enabled={len(enabled)} allowlist_strict={allowlist.strict} peers={len(allowlist.allowed_peers)}")
    if allowlist.strict and not allowlist.allowed_peers:
        print("[WARN] allowlist strict vazia: envio e recebimento efetivo ficarao bloqueados.")


def load_messages(path: Path) -> list[str]:
    if not path.exists():
        return ["Agent {account_id}: ping controlado."]
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(item) for item in data.get("messages", []) if str(item).strip()]


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "scaffold-accounts":
            cmd_scaffold(args)
            return
        if args.cmd == "init":
            cmd_init(args)
            return
        if args.cmd == "config-check":
            cmd_config_check(args)
            return

        cfg, allowlist, storage = _load(args)
        try:
            if args.cmd == "auth":
                account = get_account(cfg, args.account, allow_disabled=True)
                asyncio.run(authenticate_account(cfg, account, storage))
            elif args.cmd == "auth-all":
                accounts = select_accounts(cfg, args.accounts, include_disabled=False)
                for account in accounts:
                    asyncio.run(authenticate_account(cfg, account, storage))
            elif args.cmd == "import-tdata":
                account = get_account(cfg, args.account, allow_disabled=True)
                asyncio.run(
                    import_tdata(
                        cfg,
                        storage,
                        account,
                        tdata_path=Path(args.tdata_path),
                        mode=args.mode,
                        passcode=args.passcode,
                        password=args.password,
                        system=args.system,
                        force=args.force,
                        ack_api_risk=args.ack_api_risk,
                        dry_run=args.dry_run,
                    )
                )
            elif args.cmd == "export-tdata":
                account = get_account(cfg, args.account, allow_disabled=True)
                asyncio.run(
                    export_tdata(
                        cfg,
                        storage,
                        account,
                        out_tdata_path=Path(args.out_tdata_path),
                        passcode=args.passcode,
                        password=args.password,
                        system=args.system,
                        dry_run=args.dry_run,
                    )
                )
            elif args.cmd == "status":
                accounts = select_accounts(cfg, args.accounts, include_disabled=False)
                asyncio.run(status_accounts(cfg, accounts, storage))
            elif args.cmd == "listen":
                accounts = select_accounts(cfg, args.accounts, include_disabled=False)
                asyncio.run(
                    listen(
                        cfg,
                        storage,
                        allowlist,
                        accounts,
                        auto_reply_mentions=args.auto_reply_mentions,
                        duration_seconds=args.duration,
                    )
                )
            elif args.cmd == "send":
                account = get_account(cfg, args.account)
                asyncio.run(
                    send_message(
                        cfg,
                        storage,
                        allowlist,
                        account,
                        peer=args.peer,
                        text=args.text,
                        reply_to=args.reply_to,
                        parse_mode=_parse_mode(args.parse_mode),
                        dry_run=args.dry_run,
                    )
                )
            elif args.cmd == "react":
                account = get_account(cfg, args.account)
                asyncio.run(
                    react_message(
                        cfg,
                        storage,
                        allowlist,
                        account,
                        peer=args.peer,
                        message_id=args.message_id,
                        emoji=args.emoji,
                        dry_run=args.dry_run,
                    )
                )
            elif args.cmd == "pin":
                account = get_account(cfg, args.account)
                asyncio.run(
                    pin_message(
                        cfg,
                        storage,
                        allowlist,
                        account,
                        peer=args.peer,
                        message_id=args.message_id,
                        notify=args.notify,
                        dry_run=args.dry_run,
                    )
                )
            elif args.cmd == "read":
                account = get_account(cfg, args.account)
                asyncio.run(
                    mark_read(
                        cfg,
                        storage,
                        allowlist,
                        account,
                        peer=args.peer,
                        message_id=args.message_id,
                        dry_run=args.dry_run,
                    )
                )
            elif args.cmd == "arena":
                accounts = select_accounts(cfg, args.accounts, include_disabled=False)
                asyncio.run(
                    arena(
                        cfg,
                        storage,
                        allowlist,
                        accounts,
                        peer=args.peer,
                        messages=load_messages(Path(args.messages_file)),
                        rounds=args.rounds,
                        min_delay=args.min_delay,
                        max_delay=args.max_delay,
                        dry_run=args.dry_run,
                    )
                )
            else:
                parser.error(f"Comando desconhecido: {args.cmd}")
        finally:
            storage.close()
    except KeyboardInterrupt:
        print("\nInterrompido.")
    except ConfigError as exc:
        raise SystemExit(f"[CONFIG] {exc}") from exc


if __name__ == "__main__":
    main()
