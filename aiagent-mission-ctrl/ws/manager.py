"""WebSocket 接続管理・Redis pub/sub・ブロードキャスト."""

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger("gx10-mcp")

REDIS_CHANNEL = "gx10:events"


class WebSocketManager:
    """WebSocket 接続管理とイベントブロードキャスト.

    - _connections: dict[str, WebSocket]（agent → WS）
    - connect / disconnect
    - broadcast（全接続クライアントにJSON送信）
    - publish（Redis gx10:eventsチャンネルにパブリッシュ）
    - start_subscriber（起動時にcreate_taskで常駐）
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, agent: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[agent] = ws
        logger.info("WebSocket connected: %s (total: %d)", agent, len(self._connections))

    async def disconnect(self, agent: str) -> None:
        self._connections.pop(agent, None)
        logger.info("WebSocket disconnected: %s (total: %d)", agent, len(self._connections))

    async def broadcast(self, event: dict) -> None:
        """接続中の全 WebSocket クライアントに JSON 送信."""
        disconnected = []
        for agent, ws in list(self._connections.items()):
            try:
                await ws.send_json(event)
            except Exception:
                disconnected.append(agent)
        for agent in disconnected:
            await self.disconnect(agent)

    async def publish(self, redis_client, event: dict) -> None:
        """Redis の gx10:events チャンネルに JSON パブリッシュ.

        Redis 接続時は pub/sub 経由でブロードキャスト（start_subscriber が受信して broadcast）。
        Redis 未接続の場合は直接 broadcast にフォールバック（二重送信を避けるため
        Redis 接続時は直接 broadcast しない）。
        """
        if redis_client is None:
            # Redis 未接続: 直接ブロードキャスト（フォールバック）
            await self.broadcast(event)
            return
        try:
            await redis_client.publish(REDIS_CHANNEL, json.dumps(event, ensure_ascii=False))
        except Exception as e:
            logger.warning("Redis publish failed: %s — falling back to direct broadcast", e)
            await self.broadcast(event)

    async def start_subscriber(self, redis_client) -> None:
        """Redis pub/sub 購読タスク（サーバー起動時に create_task で常駐）.

        Redis pub/sub から受信したメッセージを broadcast() に転送する。
        Redis 未接続の場合はすぐに終了（Graceful Degradation）。
        """
        if redis_client is None:
            logger.info("WebSocket subscriber: Redis not connected, skipping pub/sub")
            return

        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(REDIS_CHANNEL)
            logger.info("WebSocket subscriber started on channel: %s", REDIS_CHANNEL)

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        await self.broadcast(event)
                    except (json.JSONDecodeError, Exception) as e:
                        logger.warning("Subscriber broadcast error: %s", e)
        except asyncio.CancelledError:
            logger.info("WebSocket subscriber cancelled")
        except Exception as e:
            logger.warning("WebSocket subscriber error: %s", e)
