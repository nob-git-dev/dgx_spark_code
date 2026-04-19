"""テスト: /kanban/* エンドポイント"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_kanban_board_redis_unavailable_returns_503(mock_app_no_redis: AsyncClient):
    """Redis 未接続: GET /kanban/board → 503"""
    r = await mock_app_no_redis.get("/kanban/board")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_kanban_card_create_redis_unavailable_returns_503(mock_app_no_redis: AsyncClient):
    """Redis 未接続: POST /kanban/card → 503"""
    r = await mock_app_no_redis.post("/kanban/card", json={"title": "テスト", "agent": "gx10-claude"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_kanban_board_with_redis(mock_app_with_redis: AsyncClient):
    """Redis 接続済み: GET /kanban/board → 200"""
    r = await mock_app_with_redis.get("/kanban/board")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_kanban_card_create_with_redis(mock_app_with_redis: AsyncClient):
    """Redis 接続済み: POST /kanban/card → 200 + カードID"""
    r = await mock_app_with_redis.post("/kanban/card", json={
        "title": "TDD テストカード",
        "agent": "gx10-claude",
    })
    assert r.status_code == 200
    body = r.json()
    assert "message" in body
    assert "c-" in body["message"] or "card" in body["message"].lower()


@pytest.mark.asyncio
async def test_environment_works_when_kanban_unavailable(mock_app_no_redis: AsyncClient):
    """Redis 未接続でも /environment は正常動作する（Graceful Degradation）"""
    r = await mock_app_no_redis.get("/environment")
    assert r.status_code == 200
