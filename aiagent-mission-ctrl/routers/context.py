"""Context ルーター: エージェント間文脈共有 6エンドポイント.

ADR-1: KanbanStore は変更しない。context_store.py に I/O を委譲。
ADR-2: /session-context は KanbanStore._get_card() + store.r で Redis 直接走査。
ADR-3: Redis 必須系は 503 / FS のみ系（decisions/journal）は 200。
ADR-4: _extract_frontmatter() を context.py 内でインライン再定義。
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lib.config import DOCS_DIR
from lib.context_store import ContextStore
from lib.kanban_store import KanbanStore

logger = logging.getLogger("gx10-mcp")

# Redis キー（KanbanStore と同一の名前空間）
K_CARD_PREFIX = "kanban:card:"
K_COL_PREFIX = "kanban:col:"
ANDON_KEY = "kanban:andon"


# ─── Pydantic モデル ──────────────────────────────


class NoteRequest(BaseModel):
    agent: str
    content: str


class SuspendRequest(BaseModel):
    agent: str
    resume_hint: str
    pending: str = ""


# ─── ADR-4: frontmatter インライン再定義 ──────────


def _extract_frontmatter(text: str) -> dict:
    """YAML-like frontmatter を抽出する（history.py からコピー）."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm: dict = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def _extract_title(text: str) -> str:
    """Markdown テキストから最初の "# " 行をタイトルとして抽出する."""
    for line in text.split("\n"):
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return ""


def _extract_summary(text: str) -> str:
    """frontmatter 除去後の先頭段落の最初の行を要約として返す（150文字まで）."""
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]
    # タイトル行をスキップ
    lines = [line for line in body.strip().split("\n") if line.strip() and not line.startswith("#")]
    if lines:
        return lines[0][:150]
    return ""


# ─── ルーターファクトリ ───────────────────────────


def make_router(store: KanbanStore, get_redis) -> APIRouter:
    """context ルーターを返す。store と get_redis を依存注入する."""
    router = APIRouter()

    def _get_context_store() -> ContextStore:
        redis = get_redis()
        if redis is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "context unavailable", "reason": "redis"},
            )
        return ContextStore(redis)

    def _require_redis():
        redis = get_redis()
        if redis is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "context unavailable", "reason": "redis"},
            )
        return redis

    # ─── GET /session-context ────────────────────

    @router.get("/session-context")
    async def get_session_context(agent: str = "gx10-claude") -> dict:
        """セッション開始時の軽量コンテキスト取得."""
        redis = _require_redis()
        ctx_store = ContextStore(redis)

        # 1. カード一覧を走査 (kanban:col:{board}:{column} の sorted set)
        active_cards = []
        pending_for_me = []

        # board は kanban.yml に依存するが、デフォルト "default" を前提に走査
        # store.config.boards から全ボード名を取得する
        for board_name, board_cfg in store.config.boards.items():
            cols = board_cfg.columns
            if len(cols) < 2:
                continue

            ready_col = cols[1]   # ready (2列目)
            active_col = cols[2] if len(cols) > 2 else cols[1]   # active (3列目)

            # active カード（owner == agent のもの）
            active_col_key = f"kanban:col:{board_name}:{active_col}"
            active_ids = await redis.zrange(active_col_key, 0, -1)
            for card_id in active_ids:
                card = await store._get_card(card_id)
                if card and card.get("owner") == agent:
                    suspend = await ctx_store.get_latest_suspend(card_id)
                    resume_hint = suspend["resume_hint"] if suspend else ""
                    last_note_at = suspend["at"] if suspend else ""
                    active_cards.append({
                        "id": card_id,
                        "title": card.get("title", ""),
                        "status": "active",
                        "resume_hint": resume_hint,
                        "last_note_at": last_note_at,
                    })

            # ready カード（全件）
            ready_col_key = f"kanban:col:{board_name}:{ready_col}"
            ready_ids = await redis.zrange(ready_col_key, 0, -1)
            for card_id in ready_ids:
                card = await store._get_card(card_id)
                if card:
                    pending_for_me.append({
                        "id": card_id,
                        "title": card.get("title", ""),
                        "lane": card.get("lane", ""),
                        "ready_since": "",
                    })

        # 2. 直近3件の判断サマリー
        recent_decisions = []
        decisions_dir = DOCS_DIR / "decisions"
        if decisions_dir.is_dir():
            # 直近3件 = sorted 昇順の末尾3件
            files = sorted(decisions_dir.glob("*.md"))
            # sorted は昇順（ADR 番号順）なので、全件取って末尾3件を reversed で返す
            all_files = list(files)
            for f in all_files[-3:]:
                text = f.read_text(encoding="utf-8")[:400]
                fm = _extract_frontmatter(text)
                title = _extract_title(text) or f.stem
                decided_at = fm.get("date", "")
                recent_decisions.append({"title": title, "decided_at": decided_at})
            # 新しい順（末尾 = 最新のADRが先頭）にする
            recent_decisions.reverse()

        # 3. andon 確認
        andon_data = await redis.hgetall(ANDON_KEY)
        andon_active = bool(andon_data)
        andon_reason = andon_data.get("reason", "") if andon_data else ""

        result: dict = {
            "agent": agent,
            "active_cards": active_cards,
            "pending_for_me": pending_for_me,
            "recent_decisions": recent_decisions,
            "andon_active": andon_active,
        }
        if andon_active and andon_reason:
            result["andon_reason"] = andon_reason

        # 5. サイズチェック（8KB 超過時はトリム）
        encoded = json.dumps(result, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 8192:
            # フィールドをトリム
            result["pending_for_me"] = result["pending_for_me"][:5]
            result["active_cards"] = result["active_cards"][:3]
            for card in result["active_cards"]:
                if card.get("resume_hint") and len(card["resume_hint"]) > 100:
                    card["resume_hint"] = card["resume_hint"][:100]

        return result

    # ─── POST /card/{id}/note ────────────────────

    @router.post("/card/{card_id}/note")
    async def post_card_note(card_id: str, req: NoteRequest) -> dict:
        """カードに文脈メモを追記する."""
        ctx_store = _get_context_store()

        # カード存在確認
        card = await store._get_card(card_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"Card not found: {card_id}")

        await ctx_store.append_note(card_id, req.agent, req.content)
        return {"status": "ok", "card_id": card_id, "type": "note"}

    # ─── POST /card/{id}/suspend ─────────────────

    @router.post("/card/{card_id}/suspend")
    async def post_card_suspend(card_id: str, req: SuspendRequest) -> dict:
        """中断ポイントを記録する."""
        ctx_store = _get_context_store()

        # カード存在確認
        card = await store._get_card(card_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"Card not found: {card_id}")

        await ctx_store.append_suspend(card_id, req.agent, req.resume_hint, req.pending)
        return {"status": "ok", "card_id": card_id, "type": "suspend"}

    # ─── GET /card/{id}/context ──────────────────

    @router.get("/card/{card_id}/context")
    async def get_card_context(card_id: str) -> dict:
        """カード1枚の完全な文脈（note/suspend 履歴）を返す."""
        ctx_store = _get_context_store()

        # カード存在確認
        card = await store._get_card(card_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"Card not found: {card_id}")

        history = await ctx_store.get_card_history(card_id)

        return {
            "id": card_id,
            "title": card.get("title", ""),
            "desc": card.get("desc", ""),
            "history": history,
        }

    # ─── GET /context/decisions ──────────────────

    @router.get("/context/decisions")
    async def get_context_decisions(limit: int | None = None) -> dict:
        """ADR サマリー（title + decided_at のみ、本文なし）."""
        decisions_dir = DOCS_DIR / "decisions"
        if not decisions_dir.is_dir():
            return {"decisions": []}

        files = sorted(decisions_dir.glob("*.md"), reverse=True)
        if limit is not None:
            files = files[:limit]

        items = []
        for f in files:
            text = f.read_text(encoding="utf-8")[:400]
            fm = _extract_frontmatter(text)
            title = _extract_title(text) or f.stem
            decided_at = fm.get("date", "")
            items.append({"title": title, "decided_at": decided_at})

        return {"decisions": items}

    # ─── GET /context/journal ────────────────────

    @router.get("/context/journal")
    async def get_context_journal(limit: int = 20) -> dict:
        """ジャーナルサマリー（title + 1行要約のみ、本文なし）."""
        journal_dir = DOCS_DIR / "journal"
        if not journal_dir.is_dir():
            return {"journals": []}

        files = sorted(journal_dir.glob("*.md"), reverse=True)[:limit]

        items = []
        for f in files:
            text = f.read_text(encoding="utf-8")[:500]
            fm = _extract_frontmatter(text)
            title = _extract_title(text) or f.stem
            summary = _extract_summary(text)
            date_str = fm.get("date", "")
            items.append({"title": title, "summary": summary, "date": date_str})

        return {"journals": items}

    return router
