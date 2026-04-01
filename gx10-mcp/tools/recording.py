"""Recording tools (Phase 2): write_journal, write_decision, update_contract, report_issue."""

import logging
from datetime import date
from pathlib import Path

from fastmcp import FastMCP

from lib.config import DOCS_DIR
from lib.git import commit_file

logger = logging.getLogger("gx10-mcp")


def _frontmatter(agent: str | None, extra: dict | None = None) -> str:
    fields = {"agent": agent or "unknown", "date": str(date.today())}
    if extra:
        fields.update(extra)
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        description=(
            "Record a work entry — what was done, what was learned, and outcomes. "
            "Call at the end of a significant work session. Auto-commits to Git."
        )
    )
    async def write_journal(
        title: str, content: str, agent: str | None = None
    ) -> str:
        journal_dir = DOCS_DIR / "journal"
        journal_dir.mkdir(exist_ok=True)

        slug = title.lower().replace(" ", "-")[:60]
        filename = f"{date.today()}-{slug}.md"
        filepath = journal_dir / filename

        fm = _frontmatter(agent)
        filepath.write_text(f"{fm}\n# {title}\n\n{content}\n")

        err = await commit_file(
            f"journal/{filename}", f"journal: {title}"
        )
        if err:
            return f"File written to journal/{filename} but git commit failed: {err}"
        return f"Journal entry saved and committed: journal/{filename}"

    @mcp.tool(
        description=(
            "Record an architecture decision (ADR format) — context, decision, "
            "and reasoning. Call whenever you make a significant technical choice. "
            "Auto-commits to Git."
        )
    )
    async def write_decision(
        title: str,
        context: str,
        decision: str,
        reason: str,
        agent: str | None = None,
    ) -> str:
        decisions_dir = DOCS_DIR / "decisions"
        decisions_dir.mkdir(exist_ok=True)

        existing = sorted(decisions_dir.glob("*.md"))
        number = len(existing) + 1
        slug = title.lower().replace(" ", "-")[:60]
        filename = f"{number:03d}-{slug}.md"
        filepath = decisions_dir / filename

        fm = _frontmatter(agent)
        body = (
            f"{fm}\n"
            f"# {number}. {title}\n\n"
            f"## ステータス\n承認済み — {date.today()}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 決定\n{decision}\n\n"
            f"## 理由\n{reason}\n"
        )
        filepath.write_text(body)

        err = await commit_file(
            f"decisions/{filename}", f"decision: {title}"
        )
        if err:
            return f"File written to decisions/{filename} but git commit failed: {err}"
        return f"Decision recorded and committed: decisions/{filename}"

    @mcp.tool(
        description=(
            "Create or update an API contract/specification. Call when a service's "
            "API changes — parameters, prompts, or constraints."
        )
    )
    async def update_contract(name: str, content: str) -> str:
        contracts_dir = DOCS_DIR / "contracts"
        contracts_dir.mkdir(exist_ok=True)

        filename = f"{name}.md"
        filepath = contracts_dir / filename
        is_new = not filepath.exists()
        filepath.write_text(content)

        action = "create" if is_new else "update"
        err = await commit_file(
            f"contracts/{filename}", f"contract: {action} {name}"
        )
        if err:
            return f"File written to contracts/{filename} but git commit failed: {err}"
        return f"Contract {'created' if is_new else 'updated'} and committed: contracts/{filename}"

    @mcp.tool(
        description=(
            "Report a problem discovered with a service. Creates a journal entry "
            "tagged as an issue. Use when you encounter unexpected behavior or errors."
        )
    )
    async def report_issue(
        service: str, description: str, agent: str | None = None
    ) -> str:
        journal_dir = DOCS_DIR / "journal"
        journal_dir.mkdir(exist_ok=True)

        filename = f"{date.today()}-issue-{service}.md"
        filepath = journal_dir / filename

        if filepath.exists():
            # Append to existing issue file for the same day/service
            existing = filepath.read_text()
            filepath.write_text(
                f"{existing}\n---\n\n## {description[:80]}\n\n{description}\n"
            )
        else:
            fm = _frontmatter(agent, {"type": "issue", "service": service})
            filepath.write_text(
                f"{fm}\n# Issue: {service}\n\n## {description[:80]}\n\n{description}\n"
            )

        short_desc = description[:50].replace("\n", " ")
        err = await commit_file(
            f"journal/{filename}", f"issue: {service} — {short_desc}"
        )
        if err:
            return f"Issue recorded in journal/{filename} but git commit failed: {err}"
        return f"Issue reported and committed: journal/{filename}"
