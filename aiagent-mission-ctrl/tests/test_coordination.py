"""テスト: /activity エンドポイント (Redis 専用, ADR-3)"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_activity_redis_unavailable_returns_503(mock_app_no_redis: AsyncClient):
    """Redis 未接続: POST /activity → 503"""
    r = await mock_app_no_redis.post("/activity", json={
        "agent": "gx10-claude",
        "description": "テスト中",
    })
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_get_activity_redis_unavailable_returns_503(mock_app_no_redis: AsyncClient):
    """Redis 未接続: GET /activity → 503"""
    r = await mock_app_no_redis.get("/activity")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_post_activity_returns_message(mock_app_with_redis: AsyncClient):
    """Redis 接続済み: POST /activity → 200 + メッセージ"""
    r = await mock_app_with_redis.post("/activity", json={
        "agent": "gx10-claude",
        "description": "SGLang 再起動中",
    })
    assert r.status_code == 200
    body = r.json()
    assert "message" in body
    assert "gx10-claude" in body["message"]
    assert "SGLang" in body["message"] or "再起動" in body["message"]


@pytest.mark.asyncio
async def test_get_activity_returns_list(mock_app_with_redis: AsyncClient):
    """Redis 接続済み: GET /activity → 200 + エージェント一覧"""
    # 先に POST
    await mock_app_with_redis.post("/activity", json={
        "agent": "gx10-claude",
        "description": "テスト中",
    })
    r = await mock_app_with_redis.get("/activity")
    assert r.status_code == 200
    body = r.json()
    assert "agents" in body
