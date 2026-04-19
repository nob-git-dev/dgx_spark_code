"""テスト: /environment 系エンドポイント"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_environment_returns_200(mock_app: AsyncClient):
    """GET /environment → 200 + テキスト"""
    r = await mock_app.get("/environment")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body
    assert isinstance(body["content"], str)
    assert len(body["content"]) > 0


@pytest.mark.asyncio
async def test_get_environment_verbose(mock_app: AsyncClient):
    """GET /environment?verbose=true → 200"""
    r = await mock_app.get("/environment?verbose=true")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_get_contract_list(mock_app: AsyncClient):
    """GET /contract → 200 (コントラクト一覧)"""
    r = await mock_app.get("/contract")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_get_contract_not_found(mock_app: AsyncClient):
    """GET /contract?name=nonexistent → 404"""
    r = await mock_app.get("/contract?name=nonexistent_xyz_abc")
    assert r.status_code == 404
    body = r.json()
    # 利用可能なコントラクト名リストが含まれる
    assert "available" in body.get("detail", "").lower() or "available" in str(body).lower()


@pytest.mark.asyncio
async def test_get_service_status(mock_app: AsyncClient):
    """GET /service-status → 200"""
    r = await mock_app.get("/service-status")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_get_gpu_status(mock_app: AsyncClient):
    """GET /gpu-status → 200"""
    r = await mock_app.get("/gpu-status")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_get_project_context(mock_app: AsyncClient):
    """GET /project-context?name=gx10-mcp → 200"""
    r = await mock_app.get("/project-context?name=gx10-mcp")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_get_doc_path_traversal(mock_app: AsyncClient):
    """GET /doc?path=../etc/passwd → エラー (path traversal 拒否)"""
    r = await mock_app.get("/doc?path=../etc/passwd")
    # 400 または 404 を期待（エラーレスポンス）
    assert r.status_code in (400, 404)
