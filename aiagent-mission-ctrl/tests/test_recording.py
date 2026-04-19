"""テスト: /recording/* エンドポイント"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_journal_success(mock_app: AsyncClient):
    """POST /recording/journal → 200 + 成功メッセージ"""
    r = await mock_app.post("/recording/journal", json={
        "title": "TDD テスト実行",
        "content": "テスト内容",
        "agent": "gx10-claude",
    })
    assert r.status_code == 200
    body = r.json()
    assert "message" in body
    assert "journal" in body["message"].lower() or "saved" in body["message"].lower() or "committed" in body["message"].lower()


@pytest.mark.asyncio
async def test_post_journal_empty_title_returns_422(mock_app: AsyncClient):
    """POST /recording/journal (title が空) → 422"""
    r = await mock_app.post("/recording/journal", json={
        "title": "",
        "content": "内容",
        "agent": "gx10-claude",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_decision_success(mock_app: AsyncClient):
    """POST /recording/decision → 200"""
    r = await mock_app.post("/recording/decision", json={
        "title": "TDD テスト判断",
        "context": "コンテキスト",
        "decision": "決定内容",
        "reason": "理由",
        "agent": "gx10-claude",
    })
    assert r.status_code == 200
    body = r.json()
    assert "message" in body


@pytest.mark.asyncio
async def test_post_decision_empty_title_returns_422(mock_app: AsyncClient):
    """POST /recording/decision (title が空) → 422"""
    r = await mock_app.post("/recording/decision", json={
        "title": "",
        "context": "ctx",
        "decision": "dec",
        "reason": "rsn",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_issue_success(mock_app: AsyncClient):
    """POST /recording/issue → 200"""
    r = await mock_app.post("/recording/issue", json={
        "service": "sglang",
        "description": "TDD テスト用 OOM",
        "agent": "gx10-claude",
    })
    assert r.status_code == 200
    body = r.json()
    assert "message" in body
