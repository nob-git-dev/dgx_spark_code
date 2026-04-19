"""協調ルーター (Phase 3): activity Redis 移行.

ADR-3: activity は Redis 専用。Redis 未接続時は 503 を返す（フォールバックなし）。
"""

import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ws.manager import WebSocketManager

logger = logging.getLogger("gx10-mcp")

ACTIVITY_KEY_PREFIX = "gx10:activity:"
ACTIVITY_TTL = 1800  # 30 分


class ActivityRequest(BaseModel):
    agent: str
    description: str


class MessageResponse(BaseModel):
    message: str


class ActivityResponse(BaseModel):
    agents: list[dict]


def make_router(ws_manager: WebSocketManager, get_redis):
    """ルーターファクトリ — ws_manager と Redis ゲッターを注入."""
    router = APIRouter()

    @router.post("/activity", response_model=MessageResponse)
    async def set_activity(req: ActivityRequest) -> MessageResponse:
        """作業を宣言する。Redis に保存し WebSocket で全接続エージェントに push する。"""
        redis = get_redis()
        if redis is None:
            raise HTTPException(
                status_code=503,
                detail="Activity service unavailable: Redis not connected (ADR-3)",
            )

        key = f"{ACTIVITY_KEY_PREFIX}{req.agent}"
        timestamp = str(time.time())
        await redis.hset(key, mapping={
            "description": req.description,
            "timestamp": timestamp,
        })
        await redis.expire(key, ACTIVITY_TTL)

        # WebSocket + Redis pub/sub にブロードキャスト
        event = {
            "type": "activity",
            "agent": req.agent,
            "description": req.description,
            "timestamp": timestamp,
        }
        await ws_manager.publish(redis, event)

        return MessageResponse(
            message=f"Activity registered for {req.agent}: {req.description}"
        )

    @router.get("/activity", response_model=ActivityResponse)
    async def get_activity() -> ActivityResponse:
        """現在のアクティブエージェント一覧を Redis から取得する。"""
        redis = get_redis()
        if redis is None:
            raise HTTPException(
                status_code=503,
                detail="Activity service unavailable: Redis not connected (ADR-3)",
            )

        agents = []
        now = time.time()
        keys = await redis.keys(f"{ACTIVITY_KEY_PREFIX}*")
        for key in keys:
            data = await redis.hgetall(key)
            if not data:
                continue
            agent_name = key.replace(ACTIVITY_KEY_PREFIX, "")
            ts = float(data.get("timestamp", 0))
            elapsed_min = int((now - ts) / 60)
            agents.append({
                "agent": agent_name,
                "description": data.get("description", ""),
                "timestamp": ts,
                "elapsed_minutes": elapsed_min,
            })

        return ActivityResponse(agents=agents)

    return router
