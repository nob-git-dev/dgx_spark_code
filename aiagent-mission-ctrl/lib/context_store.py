"""Context store — note/suspend の Redis I/O 専用モジュール.

ADR-1: KanbanStore は変更しない。note/suspend の文脈記録は本モジュールに分離。
ADR-3: Redis 必須系は 503 / FS のみ系は 200 を返す。

Redis キー: kanban:card:{id}:notes (List, RPUSH)
上限: 100件 (LTRIM で自動切り詰め)
TTL: なし
"""

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

logger = logging.getLogger("gx10-mcp")

NOTES_KEY = "kanban:card:{}:notes"
NOTES_MAX = 100


class ContextStore:
    """note/suspend エントリの Redis I/O を担当するクラス."""

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self.r = redis_client

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    async def append_note(self, card_id: str, agent: str, content: str) -> None:
        """note エントリを Redis List に追記する."""
        entry = json.dumps({
            "type": "note",
            "agent": agent,
            "content": content,
            "at": self._now_iso(),
        })
        key = NOTES_KEY.format(card_id)
        await self.r.rpush(key, entry)
        await self.r.ltrim(key, -NOTES_MAX, -1)

    async def append_suspend(
        self, card_id: str, agent: str, resume_hint: str, pending: str = ""
    ) -> None:
        """suspend エントリを Redis List に追記する."""
        entry = json.dumps({
            "type": "suspend",
            "agent": agent,
            "resume_hint": resume_hint,
            "pending": pending,
            "at": self._now_iso(),
        })
        key = NOTES_KEY.format(card_id)
        await self.r.rpush(key, entry)
        await self.r.ltrim(key, -NOTES_MAX, -1)

    async def get_card_history(self, card_id: str) -> list[dict]:
        """カードの note/suspend 履歴を時系列順（古い順）で返す."""
        key = NOTES_KEY.format(card_id)
        raw_entries = await self.r.lrange(key, 0, -1)
        result = []
        for raw in raw_entries:
            try:
                result.append(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in %s: %r", key, raw)
        return result

    async def get_latest_suspend(self, card_id: str) -> dict | None:
        """直近の suspend エントリを返す（末尾10件のみ走査）."""
        key = NOTES_KEY.format(card_id)
        raw_entries = await self.r.lrange(key, -10, -1)
        for raw in reversed(raw_entries):
            try:
                entry = json.loads(raw)
                if entry.get("type") == "suspend":
                    return entry
            except json.JSONDecodeError:
                pass
        return None
