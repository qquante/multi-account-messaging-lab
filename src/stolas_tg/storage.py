from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, db_path: Path, jsonl_path: Path) -> None:
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.init()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS account_status (
                    account_id TEXT PRIMARY KEY,
                    authorized INTEGER NOT NULL,
                    user_id INTEGER,
                    username TEXT,
                    phone TEXT,
                    last_checked_at TEXT NOT NULL,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    peer_id TEXT,
                    message_id INTEGER,
                    reply_to_message_id INTEGER,
                    sender_id TEXT,
                    action TEXT NOT NULL,
                    text_preview TEXT,
                    raw_json TEXT
                );
                CREATE TABLE IF NOT EXISTS rate_limits (
                    account_id TEXT NOT NULL,
                    peer TEXT NOT NULL,
                    last_sent_at REAL NOT NULL,
                    PRIMARY KEY (account_id, peer)
                );
                """
            )
            self._conn.commit()

    def set_status(
        self,
        account_id: str,
        *,
        authorized: bool,
        user_id: int | None = None,
        username: str | None = None,
        phone: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO account_status (
                    account_id, authorized, user_id, username, phone, last_checked_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    authorized=excluded.authorized,
                    user_id=excluded.user_id,
                    username=excluded.username,
                    phone=excluded.phone,
                    last_checked_at=excluded.last_checked_at,
                    last_error=excluded.last_error
                """,
                (account_id, 1 if authorized else 0, user_id, username, phone, utc_now(), error),
            )
            self._conn.commit()

    def record_event(
        self,
        *,
        account_id: str,
        direction: str,
        action: str,
        peer_id: str | int | None = None,
        message_id: int | None = None,
        reply_to_message_id: int | None = None,
        sender_id: str | int | None = None,
        text: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        text_preview = (text or "")[:500]
        payload = {
            "created_at": utc_now(),
            "account_id": account_id,
            "direction": direction,
            "action": action,
            "peer_id": None if peer_id is None else str(peer_id),
            "message_id": message_id,
            "reply_to_message_id": reply_to_message_id,
            "sender_id": None if sender_id is None else str(sender_id),
            "text_preview": text_preview,
            "raw": raw or {},
        }
        raw_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO events (
                    created_at, account_id, direction, peer_id, message_id,
                    reply_to_message_id, sender_id, action, text_preview, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["created_at"],
                    account_id,
                    direction,
                    payload["peer_id"],
                    message_id,
                    reply_to_message_id,
                    payload["sender_id"],
                    action,
                    text_preview,
                    raw_json,
                ),
            )
            self._conn.commit()
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(raw_json + "\n")

    def get_last_sent_at(self, account_id: str, peer: str) -> float | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_sent_at FROM rate_limits WHERE account_id=? AND peer=?",
                (account_id, peer),
            ).fetchone()
        return None if row is None else float(row["last_sent_at"])

    def set_last_sent_at(self, account_id: str, peer: str, timestamp: float) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO rate_limits (account_id, peer, last_sent_at)
                VALUES (?, ?, ?)
                ON CONFLICT(account_id, peer) DO UPDATE SET last_sent_at=excluded.last_sent_at
                """,
                (account_id, peer, timestamp),
            )
            self._conn.commit()
