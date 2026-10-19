from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path("config/accounts.local.json")
DEFAULT_ALLOWLIST = Path("config/allowlist.local.json")


class ConfigError(RuntimeError):
    pass


@dataclass(slots=True)
class AccountConfig:
    id: str
    phone: str = ""
    label: str = ""
    session_name: str = ""
    enabled: bool = False
    api_id: int | None = None
    api_hash: str | None = None
    default_peer: str = ""
    rate_limit_seconds: float | None = None
    receive_enabled: bool = True

    @property
    def safe_label(self) -> str:
        return self.label or self.id


@dataclass(slots=True)
class RuntimeConfig:
    api_id: int | None
    api_hash: str | None
    session_dir: Path = Path("var/sessions")
    db_path: Path = Path("var/stolas_tg.sqlite3")
    jsonl_path: Path = Path("var/events.jsonl")
    default_rate_limit_seconds: float = 12.0
    connect_delay_seconds: float = 1.5
    max_parallel_connects: int = 8
    accounts: list[AccountConfig] = field(default_factory=list)


@dataclass(slots=True)
class Allowlist:
    strict: bool = True
    allowed_peers: list[str] = field(default_factory=list)

    def _norm(self, value: str | int) -> str:
        text = str(value).strip()
        if text.startswith("@"):
            return text.lower()
        return text

    def validate_peer_input(self, peer: str | int) -> None:
        if not self.strict:
            return
        allowed = {self._norm(item) for item in self.allowed_peers}
        if self._norm(peer) not in allowed:
            raise ConfigError(
                f"Peer {peer!r} bloqueado pela allowlist. Edite config/allowlist.local.json."
            )

    async def is_event_allowed(self, event: Any) -> bool:
        if not self.strict:
            return True
        if not self.allowed_peers:
            return False

        allowed = {self._norm(item) for item in self.allowed_peers}
        chat_id = getattr(event, "chat_id", None)
        if chat_id is not None and self._norm(chat_id) in allowed:
            return True

        try:
            chat = await event.get_chat()
        except Exception:
            return False

        username = getattr(chat, "username", None)
        if username and self._norm(f"@{username}") in allowed:
            return True
        return False


def load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _resolve_env(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("${") and text.endswith("}"):
        return os.environ.get(text[2:-1], "")
    return value


def _optional_int(value: Any, field_name: str) -> int | None:
    value = _resolve_env(value)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} precisa ser inteiro.") from exc


def _optional_str(value: Any) -> str | None:
    value = _resolve_env(value)
    if value in (None, ""):
        return None
    return str(value)


def load_config(path: Path | None = None) -> RuntimeConfig:
    load_env()
    config_path = path or Path(os.environ.get("STOLAS_TG_CONFIG", DEFAULT_CONFIG))
    if not config_path.exists():
        raise ConfigError(f"Config nao encontrada: {config_path}")

    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    root_api_id = _optional_int(data.get("api_id") or os.environ.get("TELEGRAM_API_ID"), "api_id")
    root_api_hash = _optional_str(data.get("api_hash") or os.environ.get("TELEGRAM_API_HASH"))

    accounts: list[AccountConfig] = []
    seen: set[str] = set()
    for raw in data.get("accounts", []):
        account_id = str(raw.get("id", "")).strip()
        if not account_id:
            raise ConfigError("Conta sem id.")
        if account_id in seen:
            raise ConfigError(f"Conta duplicada: {account_id}")
        seen.add(account_id)
        account_api_id = _optional_int(raw.get("api_id"), f"accounts.{account_id}.api_id")
        account_api_hash = _optional_str(raw.get("api_hash"))
        accounts.append(
            AccountConfig(
                id=account_id,
                phone=str(raw.get("phone", "")).strip(),
                label=str(raw.get("label", "")).strip(),
                session_name=str(raw.get("session_name") or account_id).strip(),
                enabled=bool(raw.get("enabled", False)),
                api_id=account_api_id,
                api_hash=account_api_hash,
                default_peer=str(raw.get("default_peer", "")).strip(),
                rate_limit_seconds=raw.get("rate_limit_seconds"),
                receive_enabled=bool(raw.get("receive_enabled", True)),
            )
        )

    cfg = RuntimeConfig(
        api_id=root_api_id,
        api_hash=root_api_hash,
        session_dir=Path(data.get("session_dir", "var/sessions")),
        db_path=Path(data.get("db_path", "var/stolas_tg.sqlite3")),
        jsonl_path=Path(data.get("jsonl_path", "var/events.jsonl")),
        default_rate_limit_seconds=float(data.get("default_rate_limit_seconds", 12.0)),
        connect_delay_seconds=float(data.get("connect_delay_seconds", 1.5)),
        max_parallel_connects=int(data.get("max_parallel_connects", 8)),
        accounts=accounts,
    )
    return cfg


def load_allowlist(path: Path | None = None) -> Allowlist:
    load_env()
    allowlist_path = path or Path(os.environ.get("STOLAS_TG_ALLOWLIST", DEFAULT_ALLOWLIST))
    if not allowlist_path.exists():
        return Allowlist(strict=True, allowed_peers=[])
    data = json.loads(allowlist_path.read_text(encoding="utf-8-sig"))
    return Allowlist(
        strict=bool(data.get("strict", True)),
        allowed_peers=[str(item).strip() for item in data.get("allowed_peers", []) if str(item).strip()],
    )


def account_credentials(cfg: RuntimeConfig, account: AccountConfig) -> tuple[int, str]:
    api_id = account.api_id or cfg.api_id
    api_hash = account.api_hash or cfg.api_hash
    if not api_id or not api_hash:
        raise ConfigError(
            f"Credenciais ausentes para {account.id}. Configure TELEGRAM_API_ID/TELEGRAM_API_HASH ou api_id/api_hash na conta."
        )
    return api_id, api_hash


def select_accounts(
    cfg: RuntimeConfig,
    selector: str = "enabled",
    *,
    include_disabled: bool = False,
) -> list[AccountConfig]:
    if selector == "all":
        selected = cfg.accounts
    elif selector == "enabled":
        selected = [item for item in cfg.accounts if item.enabled]
    else:
        wanted = {part.strip() for part in selector.split(",") if part.strip()}
        selected = [item for item in cfg.accounts if item.id in wanted]
        missing = sorted(wanted - {item.id for item in selected})
        if missing:
            raise ConfigError(f"Conta(s) nao encontrada(s): {', '.join(missing)}")

    if not include_disabled:
        selected = [item for item in selected if item.enabled]
    return selected


def get_account(cfg: RuntimeConfig, account_id: str, *, allow_disabled: bool = False) -> AccountConfig:
    for account in cfg.accounts:
        if account.id == account_id:
            if not allow_disabled and not account.enabled:
                raise ConfigError(f"Conta {account_id} esta disabled no config.")
            return account
    raise ConfigError(f"Conta nao encontrada: {account_id}")


def scaffold_accounts(count: int) -> dict[str, Any]:
    accounts = []
    for idx in range(1, count + 1):
        account_id = f"acc{idx:03d}"
        accounts.append(
            {
                "id": account_id,
                "label": f"Agent {idx:03d}",
                "phone": "",
                "session_name": account_id,
                "enabled": False,
                "default_peer": "",
                "rate_limit_seconds": 12,
                "receive_enabled": True,
            }
        )
    return {
        "api_id": "${TELEGRAM_API_ID}",
        "api_hash": "${TELEGRAM_API_HASH}",
        "session_dir": "var/sessions",
        "db_path": "var/stolas_tg.sqlite3",
        "jsonl_path": "var/events.jsonl",
        "default_rate_limit_seconds": 12,
        "connect_delay_seconds": 1.5,
        "max_parallel_connects": 8,
        "accounts": accounts,
    }
