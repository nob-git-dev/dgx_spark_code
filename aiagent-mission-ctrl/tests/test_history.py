"""テスト: /journal, /decisions エンドポイント"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_journal(mock_app: AsyncClient):
    """GET /journal → 200"""
    r = await mock_app.get("/journal")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_get_journal_with_topic(mock_app: AsyncClient):
    """GET /journal?topic=test&limit=5 → 200"""
    r = await mock_app.get("/journal?topic=test&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_get_decisions(mock_app: AsyncClient):
    """GET /decisions → 200"""
    r = await mock_app.get("/decisions")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body
