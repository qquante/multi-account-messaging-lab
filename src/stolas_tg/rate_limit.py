from __future__ import annotations

import asyncio
import time

from .storage import Storage


class RateLimiter:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _lock_for(self, account_id: str, peer: str) -> asyncio.Lock:
        key = (account_id, peer)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def wait_for_slot(
        self,
        *,
        account_id: str,
        peer: str,
        min_interval_seconds: float,
        dry_run: bool = False,
    ) -> None:
        async with self._lock_for(account_id, peer):
            last_sent_at = self.storage.get_last_sent_at(account_id, peer)
            now = time.monotonic()
            if last_sent_at is not None:
                wait_seconds = min_interval_seconds - (now - last_sent_at)
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
            if not dry_run:
                self.storage.set_last_sent_at(account_id, peer, time.monotonic())
