"""環境参照ルーター (Phase 1): 6 エンドポイント."""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lib.config import DOCS_DIR, PROJECTS_DIR
from lib.docker import get_containers, get_system_resources
from lib.nvidia import get_gpu_detail, get_gpu_summary

logger = logging.getLogger("gx10-mcp")

router = APIRouter()


class TextResponse(BaseModel):
    content: str


@router.get("/environment", response_model=TextResponse)
async def get_environment(verbose: bool = False) -> TextResponse:
    """環境サマリーを返す（verbose=true で全文）."""
    if verbose:
        parts = []
        for name in ("hardware.md", "services.md", "policies.md"):
            path = DOCS_DIR / name
            try:
                parts.append(f"# {name}\n\n{path.read_text()}")
            except FileNotFoundError:
                parts.append(f"# {name}\n\n[unavailable: file not found]")
        return TextResponse(content="\n\n---\n\n".join(parts))

    # Summary mode
    lines = ["# GX10 Environment Summary", ""]

    hw_path = DOCS_DIR / "hardware.md"
    if hw_path.exists():
        lines.append(
            "**Hardware:** ASUS Ascent GX10 — GB10 (Grace + Blackwell), "
            "ARM64, 128GB unified memory"
        )
    else:
        lines.append("**Hardware:** [unavailable: hardware.md not found]")

    lines.append(f"**{await get_gpu_summary()}**")

    containers = await get_containers()
    lines.append("")
    lines.append("## Running Services")
    lines.append(f"```\n{containers}\n```")

    lines.append("")
    lines.append("## Key Policies")
    lines.append("- Docker-first (no pip install on host)")
    lines.append("- ARM64 only (no x86 binaries)")
    lines.append("- LLM via shared SGLang (:30000) or Ollama (:11434)")

    contracts_dir = DOCS_DIR / "contracts"
    if contracts_dir.is_dir():
        contracts = [f.stem for f in contracts_dir.glob("*.md")]
        if contracts:
            lines.append("")
            lines.append(f"## Available API Contracts: {', '.join(contracts)}")

    return TextResponse(content="\n".join(lines))


@router.get("/contract", response_model=TextResponse)
async def get_contract(name: str | None = None) -> TextResponse:
    """API コントラクト一覧または個別コントラクトを返す."""
    contracts_dir = DOCS_DIR / "contracts"
    if not contracts_dir.is_dir():
        return TextResponse(content="No contracts directory found.")

    if name is None:
        files = sorted(contracts_dir.glob("*.md"))
        if not files:
            return TextResponse(content="No contracts available.")
        lines = ["# Available Contracts", ""]
        for f in files:
            first_line = f.read_text().split("\n", 1)[0].strip("# ")
            lines.append(f"- **{f.stem}** — {first_line}")
        return TextResponse(content="\n".join(lines))

    path = contracts_dir / f"{name}.md"
    if not path.exists():
        available = ", ".join(f.stem for f in contracts_dir.glob("*.md"))
        raise HTTPException(
            status_code=404,
            detail=f"Contract '{name}' not found. Available: {available}",
        )
    return TextResponse(content=path.read_text())


@router.get("/service-status", response_model=TextResponse)
async def get_service_status() -> TextResponse:
    """コンテナ・メモリ・ディスク状態を返す."""
    containers = await get_containers()
    resources = await get_system_resources()
    return TextResponse(content=f"## Running Containers\n```\n{containers}\n```\n\n{resources}")


@router.get("/gpu-status", response_model=TextResponse)
async def get_gpu_status() -> TextResponse:
    """GPU 詳細メトリクスを返す."""
    return TextResponse(content=await get_gpu_detail())


@router.get("/project-context", response_model=TextResponse)
async def get_project_context(name: str) -> TextResponse:
    """指定プロジェクトの CLAUDE.md を返す."""
    if not re.match(r"^[a-zA-Z0-9_\-]+$", name):
        raise HTTPException(status_code=400, detail="Invalid project name: only alphanumeric, hyphens, and underscores are allowed")
    path = PROJECTS_DIR / name / "CLAUDE.md"
    resolved = path.resolve()
    if not str(resolved).startswith(str(PROJECTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Error: path traversal not allowed")
    if not path.exists():
        available = [
            d.name
            for d in PROJECTS_DIR.iterdir()
            if d.is_dir() and (d / "CLAUDE.md").exists()
        ]
        return TextResponse(
            content=(
                f"CLAUDE.md not found for project '{name}'. "
                f"Projects with CLAUDE.md: {', '.join(available)}"
            )
        )
    return TextResponse(content=path.read_text())


@router.get("/doc", response_model=TextResponse)
async def read_doc(path: str) -> TextResponse:
    """docs リポジトリ内任意ファイルを返す."""
    if ".." in path:
        raise HTTPException(status_code=400, detail="Error: path traversal not allowed (contains '..')")
    full_path = DOCS_DIR / path
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    try:
        resolved = full_path.resolve()
        if not str(resolved).startswith(str(DOCS_DIR.resolve())):
            raise HTTPException(status_code=400, detail="Error: path traversal not allowed")
        return TextResponse(content=resolved.read_text())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading {path}: {e}")
