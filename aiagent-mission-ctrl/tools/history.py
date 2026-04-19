"""History tools (Phase 4): get_journal, get_decisions."""

import logging
from pathlib import Path

from fastmcp import FastMCP

from lib.config import DOCS_DIR

logger = logging.getLogger("gx10-mcp")


def _extract_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from markdown text."""
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


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        description=(
            "Search or list work journal entries. Returns previews "
            "(title + date + first 200 chars). Use read_doc() for full content."
        )
    )
    async def get_journal(topic: str | None = None, limit: int = 10) -> str:
        journal_dir = DOCS_DIR / "journal"
        if not journal_dir.is_dir():
            return "No journal entries yet. Directory does not exist."

        files = sorted(journal_dir.glob("*.md"), reverse=True)
        if not files:
            return "No journal entries yet."

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
                return f"No journal entries matching '{topic}'."
            files_and_content = matches
        else:
            files_and_content = [(f, f.read_text()) for f in files[:limit]]

        lines = [f"# Journal Entries ({len(files_and_content)} shown)", ""]
        for f, content in files_and_content:
            fm = _extract_frontmatter(content)
            agent = fm.get("agent", "?")
            # Strip frontmatter for preview
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

        return "\n".join(lines)

    @mcp.tool(
        description=(
            "List all architecture decision records (ADRs). "
            "Review past decisions before making similar choices "
            "to maintain consistency."
        )
    )
    async def get_decisions() -> str:
        decisions_dir = DOCS_DIR / "decisions"
        if not decisions_dir.is_dir():
            return "No decisions recorded yet. Directory does not exist."

        files = sorted(decisions_dir.glob("*.md"))
        if not files:
            return "No decisions recorded yet."

        lines = [f"# Architecture Decision Records ({len(files)})", ""]
        for f in files:
            content = f.read_text()
            fm = _extract_frontmatter(content)
            agent = fm.get("agent", "?")
            date_str = fm.get("date", "?")
            # Get title from first heading
            title = f.stem
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line.lstrip("# ").strip()
                    break
            lines.append(f"- **{title}** — {date_str} (agent: {agent})")

        return "\n".join(lines)
