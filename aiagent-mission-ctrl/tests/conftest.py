"""テスト用フィクスチャ — server_new.py アプリ起動ヘルパー."""

import os
import sys
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient, ASGITransport

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@asynccontextmanager
async def app_client(redis_url: str):
    """指定 Redis URL でアプリを起動し AsyncClient を返すコンテキストマネージャ."""
    from server_new import create_app
    app = create_app(redis_url=redis_url)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.fixture
async def mock_app():
    """Redis 接続なし（Graceful Degradation）で動作するアプリのクライアント."""
    from server_new import create_app
    app = create_app(redis_url="redis://localhost:9999")  # 存在しないRedis
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.fixture
async def mock_app_no_redis():
    """明示的に Redis 未接続のアプリのクライアント."""
    from server_new import create_app
    app = create_app(redis_url="redis://localhost:9999")  # 存在しないRedis
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.fixture
async def mock_app_with_redis():
    """実際の kanban-redis に接続するアプリのクライアント（統合テスト用）."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    from server_new import create_app
    app = create_app(redis_url=redis_url)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
