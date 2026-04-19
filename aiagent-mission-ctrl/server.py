"""GX10 MCP Server — REST API + WebSocket (FastAPI).

フェーズB: カットオーバー済み。FastMCP から FastAPI REST API に移行。
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from lib.config import MCP_PORT
from lib.kanban_store import KanbanStore
from routers import environment, history, live, recording
from routers.coordination import make_router as make_coordination_router
from routers.context import make_router as make_context_router
from routers.kanban import make_router as make_kanban_router
from ws.manager import WebSocketManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("gx10-mcp")


def create_app(redis_url: str | None = None) -> FastAPI:
    """アプリケーションファクトリ（テスト・本番共用）."""
    if redis_url is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    ws_manager = WebSocketManager()
    store = KanbanStore(redis_url)
    _redis_client: aioredis.Redis | None = None
    _subscriber_task: asyncio.Task | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal _redis_client, _subscriber_task

        # Redis 接続試行（失敗しても起動は続行）
        try:
            _redis_client = aioredis.from_url(redis_url, decode_responses=True)
            await _redis_client.ping()
            logger.info("Redis connected: %s", redis_url)
        except Exception as e:
            logger.warning(
                "Redis unavailable (%s): %s — kanban/activity will return 503",
                redis_url, e,
            )
            _redis_client = None

        # Kanban store 接続試行
        if _redis_client is not None:
            try:
                await store.connect()
                logger.info("Kanban store ready")
            except Exception as e:
                logger.warning("Kanban store connect failed: %s", e)
        else:
            # Redis 未接続でも store._redis を None に保っておく（503 判定用）
            pass

        # WebSocket subscriber タスク起動
        if _redis_client is not None:
            _subscriber_task = asyncio.create_task(
                ws_manager.start_subscriber(_redis_client)
            )

        yield

        # Cleanup
        if _subscriber_task:
            _subscriber_task.cancel()
            try:
                await _subscriber_task
            except asyncio.CancelledError:
                pass

        await store.close()
        if _redis_client:
            await _redis_client.aclose()
        logger.info("Server shutdown complete")

    app = FastAPI(
        title="GX10 MCP Server",
        description="ASUS Ascent GX10 infrastructure management — REST API",
        lifespan=lifespan,
    )

    def get_redis():
        return _redis_client

    # ルーター登録
    app.include_router(environment.router)
    app.include_router(recording.router)
    app.include_router(live.router)
    app.include_router(history.router)
    app.include_router(make_coordination_router(ws_manager, get_redis))
    app.include_router(make_kanban_router(store, ws_manager))
    app.include_router(make_context_router(store, get_redis))

    @app.get("/health")
    async def health():
        redis_status = "connected" if _redis_client is not None else "unavailable"
        status = "ok" if _redis_client is not None else "degraded"
        return {"status": status, "redis": redis_status}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket, agent: str = "unknown"):
        await ws_manager.connect(agent, ws)
        try:
            while True:
                # クライアントからのメッセージを受け付け（ping 等）
                data = await ws.receive_text()
                logger.debug("WS message from %s: %s", agent, data[:100])
        except WebSocketDisconnect:
            await ws_manager.disconnect(agent)
            logger.info("WebSocket disconnected: %s", agent)
        except Exception as e:
            logger.warning("WebSocket error for %s: %s", agent, e)
            await ws_manager.disconnect(agent)

    return app


# デフォルトアプリインスタンス（uvicorn server:app で直接起動用）
app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", str(MCP_PORT)))
    logger.info("Starting GX10 REST API server on port %d", port)
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
