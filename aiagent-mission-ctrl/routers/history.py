"""履歴ルーター (Phase 4): journal・decisions 参照."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from lib.config import DOCS_DIR

logger = logging.getLogger("gx10-mcp")

router = APIRouter()


class TextResponse(BaseModel):
    content: str


def _extract_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


@router.get("/journal", response_model=TextResponse)
async def get_journal(topic: str | None = None, limit: int = 10) -> TextResponse:
    """ジャーナル検索・一覧（?topic=xxx&limit=10）."""
    journal_dir = DOCS_DIR / "journal"
    if not journal_dir.is_dir():
        return TextResponse(content="No journal entries yet. Directory does not exist.")

    files = sorted(journal_dir.glob("*.md"), reverse=True)
    if not files:
        return TextResponse(content="No journal entries yet.")

    if topic:
        topic_lower = topic.lower()
        matches = []
        for f in files:
            content = f.read_text()
            if topic_lower in f.name.lower() or topic_lower in content.lower():
                matches.append((f, content))
            if len(matches) >= limit:
                break
        if not matches:
            return TextResponse(content=f"No journal entries matching '{topic}'.")
        files_and_content = matches
    else:
        files_and_content = [(f, f.read_text()) for f in files[:limit]]

    lines = [f"# Journal Entries ({len(files_and_content)} shown)", ""]
    for f, content in files_and_content:
        fm = _extract_frontmatter(content)
        agent = fm.get("agent", "?")
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                body = parts[2]
        preview = body.strip()[:200].replace("\n", " ")
        lines.append(f"### {f.stem}")
        lines.append(f"**Agent:** {agent}")
        lines.append(f"{preview}...")
        lines.append("")

    return TextResponse(content="\n".join(lines))


@router.get("/decisions", response_model=TextResponse)
async def get_decisions() -> TextResponse:
    """ADR 一覧を返す."""
    decisions_dir = DOCS_DIR / "decisions"
    if not decisions_dir.is_dir():
        return TextResponse(content="No decisions recorded yet. Directory does not exist.")

    files = sorted(decisions_dir.glob("*.md"))
    if not files:
        return TextResponse(content="No decisions recorded yet.")

    lines = [f"# Architecture Decision Records ({len(files)})", ""]
    for f in files:
        content = f.read_text()
        fm = _extract_frontmatter(content)
        agent = fm.get("agent", "?")
        date_str = fm.get("date", "?")
        title = f.stem
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break
        lines.append(f"- **{title}** — {date_str} (agent: {agent})")

    return TextResponse(content="\n".join(lines))
