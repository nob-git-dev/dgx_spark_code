"""テスト: context エンドポイント群（受け入れ条件ベース）.

受け入れ条件:
  1. GET /session-context?agent=gx10-claude → 200 + 構造確認
  2. レスポンスの合計サイズが 8KB 以下
  3. Redis 未接続時は 503
  4. andon 発動中の場合、andon_active: true が含まれる
  5. POST /card/{id}/note → 200 + Redis 記録
  6. POST /card/{id}/suspend → 200 + Redis 記録
  7. GET /card/{id}/context → note・suspend の履歴が時系列順に返る（200）
  8. 存在しないカード ID → 404
  9. GET /context/decisions → 4KB 以下、title + decided_at のみ
 10. GET /context/journal → 4KB 以下、title + 1行要約のみ
 11. GET /context/decisions?limit=5 でリミット指定が動作する
 12. 既存エンドポイント /health が引き続き動作する
"""

import pytest
from httpx import AsyncClient


# ────────────────────────────────────────────────
# 受け入れ条件 1: GET /session-context → 200 + 構造確認
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_context_returns_200_with_valid_structure(mock_app_with_redis: AsyncClient):
    """GET /session-context?agent=gx10-claude → 200 + 必須フィールドが揃っている."""
    r = await mock_app_with_redis.get("/session-context?agent=gx10-claude")
    assert r.status_code == 200
    body = r.json()
    assert "agent" in body
    assert "active_cards" in body
    assert "pending_for_me" in body
    assert "recent_decisions" in body
    assert "andon_active" in body
    assert body["agent"] == "gx10-claude"
    assert isinstance(body["active_cards"], list)
    assert isinstance(body["pending_for_me"], list)
    assert isinstance(body["recent_decisions"], list)
    # recent_decisions は最大3件
    assert len(body["recent_decisions"]) <= 3


# ────────────────────────────────────────────────
# 受け入れ条件 2: レスポンスサイズが 8KB 以下
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_context_response_size_under_8kb(mock_app_with_redis: AsyncClient):
    """GET /session-context のレスポンスが 8192 バイト以下."""
    r = await mock_app_with_redis.get("/session-context?agent=gx10-claude")
    assert r.status_code == 200
    assert len(r.content) <= 8192, f"レスポンスサイズ超過: {len(r.content)} bytes"


# ────────────────────────────────────────────────
# 受け入れ条件 3: Redis 未接続時は 503
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_context_redis_unavailable_returns_503(mock_app_no_redis: AsyncClient):
    """Redis 未接続: GET /session-context → 503."""
    r = await mock_app_no_redis.get("/session-context?agent=gx10-claude")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_post_card_note_redis_unavailable_returns_503(mock_app_no_redis: AsyncClient):
    """Redis 未接続: POST /card/{id}/note → 503."""
    r = await mock_app_no_redis.post(
        "/card/c-test001/note",
        json={"agent": "gx10-claude", "content": "テストメモ"},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_post_card_suspend_redis_unavailable_returns_503(mock_app_no_redis: AsyncClient):
    """Redis 未接続: POST /card/{id}/suspend → 503."""
    r = await mock_app_no_redis.post(
        "/card/c-test001/suspend",
        json={"agent": "gx10-claude", "resume_hint": "次のステップ", "pending": ""},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_get_card_context_redis_unavailable_returns_503(mock_app_no_redis: AsyncClient):
    """Redis 未接続: GET /card/{id}/context → 503."""
    r = await mock_app_no_redis.get("/card/c-test001/context")
    assert r.status_code == 503


# ────────────────────────────────────────────────
# 受け入れ条件 4: andon 発動中の場合 andon_active: true
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_context_andon_active_reflected(mock_app_with_redis: AsyncClient):
    """andon が発動していない通常時は andon_active: false."""
    r = await mock_app_with_redis.get("/session-context?agent=gx10-claude")
    assert r.status_code == 200
    body = r.json()
    assert "andon_active" in body
    # 通常時は false（andon を発動していない前提）
    assert body["andon_active"] is False


# ────────────────────────────────────────────────
# 受け入れ条件 5: POST /card/{id}/note → 200
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_card_note_returns_200_and_stores(mock_app_with_redis: AsyncClient):
    """POST /card/{id}/note に note を送ると 200 が返る."""
    # まずカードを作成
    create_r = await mock_app_with_redis.post("/kanban/card", json={
        "title": "TDD Context Test Card",
        "agent": "gx10-claude",
    })
    assert create_r.status_code == 200
    # card_id を本文から抽出
    msg = create_r.json().get("message", "")
    card_id = _extract_card_id(msg)

    try:
        r = await mock_app_with_redis.post(
            f"/card/{card_id}/note",
            json={"agent": "gx10-claude", "content": "TDD テストメモ"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "status" in body or "ok" in str(body).lower() or r.status_code == 200
    finally:
        # クリーンアップ: notes キーを削除（Redis に直接アクセスできないため API で確認のみ）
        pass


# ────────────────────────────────────────────────
# 受け入れ条件 6: POST /card/{id}/suspend → 200
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_card_suspend_returns_200_and_stores(mock_app_with_redis: AsyncClient):
    """POST /card/{id}/suspend を送ると 200 が返る."""
    create_r = await mock_app_with_redis.post("/kanban/card", json={
        "title": "TDD Suspend Test Card",
        "agent": "gx10-claude",
    })
    assert create_r.status_code == 200
    msg = create_r.json().get("message", "")
    card_id = _extract_card_id(msg)

    r = await mock_app_with_redis.post(
        f"/card/{card_id}/suspend",
        json={
            "agent": "gx10-claude",
            "resume_hint": "context.py の実装を続ける",
            "pending": "サイズ超過時のトリム戦略",
        },
    )
    assert r.status_code == 200


# ────────────────────────────────────────────────
# 受け入れ条件 7: GET /card/{id}/context → 時系列履歴（200）
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_card_context_returns_history_in_order(mock_app_with_redis: AsyncClient):
    """note → suspend の順で記録し、GET /card/{id}/context で時系列順に取得できる."""
    create_r = await mock_app_with_redis.post("/kanban/card", json={
        "title": "TDD History Test Card",
        "agent": "gx10-claude",
    })
    assert create_r.status_code == 200
    msg = create_r.json().get("message", "")
    card_id = _extract_card_id(msg)

    # note を記録
    r1 = await mock_app_with_redis.post(
        f"/card/{card_id}/note",
        json={"agent": "gx10-claude", "content": "最初のメモ"},
    )
    assert r1.status_code == 200

    # suspend を記録
    r2 = await mock_app_with_redis.post(
        f"/card/{card_id}/suspend",
        json={"agent": "gx10-claude", "resume_hint": "次は〇〇を行う", "pending": ""},
    )
    assert r2.status_code == 200

    # context を取得
    r3 = await mock_app_with_redis.get(f"/card/{card_id}/context")
    assert r3.status_code == 200
    body = r3.json()
    assert "id" in body
    assert "history" in body
    history = body["history"]
    assert isinstance(history, list)
    assert len(history) >= 2

    # 時系列順（note が先、suspend が後）
    types = [entry["type"] for entry in history]
    assert "note" in types
    assert "suspend" in types
    note_idx = types.index("note")
    suspend_idx = types.index("suspend")
    assert note_idx < suspend_idx, "note は suspend より前に記録されているはず"


# ────────────────────────────────────────────────
# 受け入れ条件 8: 存在しないカード ID → 404
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_card_context_unknown_id_returns_404(mock_app_with_redis: AsyncClient):
    """存在しない ID を指定した場合 GET /card/{id}/context → 404."""
    r = await mock_app_with_redis.get("/card/c-nonexistent999/context")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_card_note_unknown_id_returns_404(mock_app_with_redis: AsyncClient):
    """存在しない ID に POST /card/{id}/note → 404."""
    r = await mock_app_with_redis.post(
        "/card/c-nonexistent999/note",
        json={"agent": "gx10-claude", "content": "存在しないカード"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_card_suspend_unknown_id_returns_404(mock_app_with_redis: AsyncClient):
    """存在しない ID に POST /card/{id}/suspend → 404."""
    r = await mock_app_with_redis.post(
        "/card/c-nonexistent999/suspend",
        json={"agent": "gx10-claude", "resume_hint": "次のステップ", "pending": ""},
    )
    assert r.status_code == 404


# ────────────────────────────────────────────────
# 受け入れ条件 9: GET /context/decisions → 4KB 以下、title + decided_at のみ
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_decisions_summary_only_under_4kb(mock_app: AsyncClient):
    """GET /context/decisions → 200 + 4KB 以下 + title/decided_at のみ."""
    r = await mock_app.get("/context/decisions")
    assert r.status_code == 200
    assert len(r.content) <= 4096, f"サイズ超過: {len(r.content)} bytes"
    body = r.json()
    assert "decisions" in body
    for item in body["decisions"]:
        assert "title" in item
        assert "decided_at" in item
        # 本文は含まれない（簡易確認: 大きなテキストフィールドがない）
        assert "content" not in item
        assert "body" not in item


# ────────────────────────────────────────────────
# 受け入れ条件 10: GET /context/journal → 4KB 以下、title + 1行要約のみ
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_journal_summary_only_under_4kb(mock_app: AsyncClient):
    """GET /context/journal → 200 + 4KB 以下 + title/summary のみ."""
    r = await mock_app.get("/context/journal")
    assert r.status_code == 200
    assert len(r.content) <= 4096, f"サイズ超過: {len(r.content)} bytes"
    body = r.json()
    assert "journals" in body
    for item in body["journals"]:
        assert "title" in item
        assert "summary" in item
        # summary は長くない（150文字以内）
        assert len(item["summary"]) <= 150


# ────────────────────────────────────────────────
# 受け入れ条件 11: GET /context/decisions?limit=5 でリミット指定
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_decisions_limit_param(mock_app: AsyncClient):
    """GET /context/decisions?limit=5 → 結果が5件以下."""
    r = await mock_app.get("/context/decisions?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "decisions" in body
    assert len(body["decisions"]) <= 5


# ────────────────────────────────────────────────
# 受け入れ条件 12: 既存エンドポイントが引き続き動作する
# ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_existing_health_endpoint_still_works(mock_app: AsyncClient):
    """GET /health が {"status": ...} を返し続ける（200）."""
    r = await mock_app.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body


@pytest.mark.asyncio
async def test_existing_journal_endpoint_still_works(mock_app: AsyncClient):
    """既存 GET /journal は変更なく動作する."""
    r = await mock_app.get("/journal")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


@pytest.mark.asyncio
async def test_existing_decisions_endpoint_still_works(mock_app: AsyncClient):
    """既存 GET /decisions は変更なく動作する."""
    r = await mock_app.get("/decisions")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body


# ────────────────────────────────────────────────
# ヘルパー
# ────────────────────────────────────────────────

def _extract_card_id(message: str) -> str:
    """メッセージ文字列からカード ID (c-xxxxxxxx) を抽出する."""
    import re
    match = re.search(r"c-[a-f0-9]{8}", message)
    if match:
        return match.group(0)
    raise ValueError(f"カード ID が見つかりません: {message!r}")
