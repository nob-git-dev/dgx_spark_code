"""テスト: /logs, /check-endpoint, /service/start, /service/stop"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_logs(mock_app: AsyncClient):
    """GET /logs?service=xxx&lines=10 → 200"""
    r = await mock_app.get("/logs?service=sglang-llm&lines=10")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_check_endpoint(mock_app: AsyncClient):
    """GET /check-endpoint?url=xxx → 200"""
    r = await mock_app.get("/check-endpoint?url=http://localhost:1")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_start_service_unknown_returns_404(mock_app: AsyncClient):
    """POST /service/start (存在しないサービス) → 404"""
    r = await mock_app.post("/service/start", json={"name": "nonexistent_xyz_service"})
    assert r.status_code == 404
    body = r.json()
    # 利用可能サービス一覧が含まれる
    detail = str(body)
    assert "available" in detail.lower() or "unknown" in detail.lower()


@pytest.mark.asyncio
async def test_stop_service_unknown_returns_404(mock_app: AsyncClient):
    """POST /service/stop (存在しないサービス) → 404"""
    r = await mock_app.post("/service/stop", json={"name": "nonexistent_xyz_service"})
    assert r.status_code == 404
