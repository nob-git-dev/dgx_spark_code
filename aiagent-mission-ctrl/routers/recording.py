"""記録ルーター (Phase 2): 4 エンドポイント."""

import logging
import re
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from lib.config import DOCS_DIR
from lib.git import commit_file

logger = logging.getLogger("gx10-mcp")

router = APIRouter(prefix="/recording")


class MessageResponse(BaseModel):
    message: str


class JournalRequest(BaseModel):
    title: str
    content: str
    agent: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be empty")
        return v


class DecisionRequest(BaseModel):
    title: str
    context: str
    decision: str
    reason: str
    agent: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be empty")
        return v


class ContractRequest(BaseModel):
    name: str
    content: str


class IssueRequest(BaseModel):
    service: str
    description: str
    agent: str | None = None


def _safe_slug(text: str, max_len: int = 60) -> str:
    """タイトルからファイル名に安全なスラッグを生成する.

    英数字・ひらがな・カタカナ・漢字以外の ASCII 記号（/ . ~ \\ 等）を除去する。
    """
    slug = text.lower().replace(" ", "-")
    # ファイルシステムに危険な文字を除去（/ . \ ~ : * ? " < > |）
    slug = re.sub(r'[/\\.~:*?"<>|]', "", slug)
    return slug[:max_len] or "untitled"


def _frontmatter(agent: str | None, extra: dict | None = None) -> str:
    fields = {"agent": agent or "unknown", "date": str(date.today())}
    if extra:
        fields.update(extra)
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


@router.post("/journal", response_model=MessageResponse)
async def write_journal(req: JournalRequest) -> MessageResponse:
    """作業記録を保存し Git コミットする."""
    journal_dir = DOCS_DIR / "journal"
    journal_dir.mkdir(exist_ok=True)

    slug = _safe_slug(req.title)
    filename = f"{date.today()}-{slug}.md"
    filepath = journal_dir / filename

    fm = _frontmatter(req.agent)
    filepath.write_text(f"{fm}\n# {req.title}\n\n{req.content}\n")

    err = await commit_file(f"journal/{filename}", f"journal: {req.title}")
    if err:
        return MessageResponse(message=f"File written to journal/{filename} but git commit failed: {err}")
    return MessageResponse(message=f"Journal entry saved and committed: journal/{filename}")


@router.post("/decision", response_model=MessageResponse)
async def write_decision(req: DecisionRequest) -> MessageResponse:
    """ADR 記録を保存し Git コミットする."""
    decisions_dir = DOCS_DIR / "decisions"
    decisions_dir.mkdir(exist_ok=True)

    existing = sorted(decisions_dir.glob("*.md"))
    number = len(existing) + 1
    slug = _safe_slug(req.title)
    filename = f"{number:03d}-{slug}.md"
    filepath = decisions_dir / filename

    fm = _frontmatter(req.agent)
    body = (
        f"{fm}\n"
        f"# {number}. {req.title}\n\n"
        f"## ステータス\n承認済み — {date.today()}\n\n"
        f"## コンテキスト\n{req.context}\n\n"
        f"## 決定\n{req.decision}\n\n"
        f"## 理由\n{req.reason}\n"
    )
    filepath.write_text(body)

    err = await commit_file(f"decisions/{filename}", f"decision: {req.title}")
    if err:
        return MessageResponse(message=f"File written to decisions/{filename} but git commit failed: {err}")
    return MessageResponse(message=f"Decision recorded and committed: decisions/{filename}")


@router.post("/contract", response_model=MessageResponse)
async def update_contract(req: ContractRequest) -> MessageResponse:
    """API コントラクトを作成・更新し Git コミットする."""
    # name にパストラバーサル文字が含まれていないか検証
    if not re.match(r'^[a-zA-Z0-9_\-]+$', req.name):
        raise HTTPException(
            status_code=422,
            detail="Contract name must contain only alphanumeric characters, hyphens, and underscores",
        )

    contracts_dir = DOCS_DIR / "contracts"
    contracts_dir.mkdir(exist_ok=True)

    filename = f"{req.name}.md"
    filepath = contracts_dir / filename
    is_new = not filepath.exists()
    filepath.write_text(req.content)

    action = "create" if is_new else "update"
    err = await commit_file(f"contracts/{filename}", f"contract: {action} {req.name}")
    if err:
        return MessageResponse(message=f"File written to contracts/{filename} but git commit failed: {err}")
    return MessageResponse(message=f"Contract {'created' if is_new else 'updated'} and committed: contracts/{filename}")


@router.post("/issue", response_model=MessageResponse)
async def report_issue(req: IssueRequest) -> MessageResponse:
    """問題報告を journal に記録し Git コミットする."""
    journal_dir = DOCS_DIR / "journal"
    journal_dir.mkdir(exist_ok=True)

    safe_service = _safe_slug(req.service)
    filename = f"{date.today()}-issue-{safe_service}.md"
    filepath = journal_dir / filename

    if filepath.exists():
        existing = filepath.read_text()
        filepath.write_text(
            f"{existing}\n---\n\n## {req.description[:80]}\n\n{req.description}\n"
        )
    else:
        fm = _frontmatter(req.agent, {"type": "issue", "service": req.service})
        filepath.write_text(
            f"{fm}\n# Issue: {req.service}\n\n## {req.description[:80]}\n\n{req.description}\n"
        )

    short_desc = req.description[:50].replace("\n", " ")
    err = await commit_file(f"journal/{filename}", f"issue: {req.service} — {short_desc}")
    if err:
        return MessageResponse(message=f"Issue recorded in journal/{filename} but git commit failed: {err}")
    return MessageResponse(message=f"Issue reported and committed: journal/{filename}")
