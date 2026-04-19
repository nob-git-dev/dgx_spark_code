"""テスト: /health エンドポイント"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(mock_app: AsyncClient):
    """GET /health → {"status": "ok"} or {"status": "degraded"} (200)"""
    r = await mock_app.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "redis" in body


@pytest.mark.asyncio
async def test_health_redis_unavailable(mock_app: AsyncClient):
    """Redis 未接続: {"status": "degraded", "redis": "unavailable"}"""
    r = await mock_app.get("/health")
    assert r.status_code == 200
    body = r.json()
    # Redis 未接続（port 9999）なので degraded になるはず
    assert body["status"] == "degraded"
    assert body["redis"] == "unavailable"
