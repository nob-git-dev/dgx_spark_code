"""Environment reference tools (Phase 1): 6 tools."""

import logging
from pathlib import Path

from fastmcp import FastMCP

from lib.config import DOCS_DIR, PROJECTS_DIR
from lib.docker import get_containers, get_system_resources
from lib.nvidia import get_gpu_detail, get_gpu_summary

logger = logging.getLogger("gx10-mcp")


def register(mcp: FastMCP) -> None:
    """Register all environment tools on the MCP server."""

    @mcp.tool(
        description=(
            "Get a summary of the GX10 environment — hardware, running services, "
            "GPU memory, and dev policies. Call this first when starting a new "
            "project or session."
        )
    )
    async def get_environment(verbose: bool = False) -> str:
        if verbose:
            parts = []
            for name in ("hardware.md", "services.md", "policies.md"):
                path = DOCS_DIR / name
                try:
                    parts.append(f"# {name}\n\n{path.read_text()}")
                except FileNotFoundError:
                    parts.append(f"# {name}\n\n[unavailable: file not found]")
            return "\n\n---\n\n".join(parts)

        # Summary mode
        lines = ["# GX10 Environment Summary", ""]

        # Hardware (one-liner from hardware.md)
        hw_path = DOCS_DIR / "hardware.md"
        if hw_path.exists():
            lines.append(
                "**Hardware:** ASUS Ascent GX10 — GB10 (Grace + Blackwell), "
                "ARM64, 128GB unified memory"
            )
        else:
            lines.append("**Hardware:** [unavailable: hardware.md not found]")

        # GPU
        lines.append(f"**{await get_gpu_summary()}**")

        # Running services
        containers = await get_containers()
        lines.append("")
        lines.append("## Running Services")
        lines.append(f"```\n{containers}\n```")

        # Key policies
        lines.append("")
        lines.append("## Key Policies")
        lines.append("- Docker-first (no pip install on host)")
        lines.append("- ARM64 only (no x86 binaries)")
        lines.append("- LLM via shared SGLang (:30000) or Ollama (:11434)")

        # Available contracts
        contracts_dir = DOCS_DIR / "contracts"
        if contracts_dir.is_dir():
            contracts = [f.stem for f in contracts_dir.glob("*.md")]
            if contracts:
                lines.append("")
                lines.append(
                    f"## Available API Contracts: {', '.join(contracts)}"
                )

        return "\n".join(lines)

    @mcp.tool(
        description=(
            "Get API contract/specification for a service. Call before using "
            "any GX10 service API to understand parameters, constraints, "
            "and prompts."
        )
    )
    async def get_contract(name: str | None = None) -> str:
        contracts_dir = DOCS_DIR / "contracts"
        if not contracts_dir.is_dir():
            return "No contracts directory found."

        if name is None:
            files = sorted(contracts_dir.glob("*.md"))
            if not files:
                return "No contracts available."
            lines = ["# Available Contracts", ""]
            for f in files:
                first_line = f.read_text().split("\n", 1)[0].strip("# ")
                lines.append(f"- **{f.stem}** — {first_line}")
            return "\n".join(lines)

        path = contracts_dir / f"{name}.md"
        if not path.exists():
            return f"Contract '{name}' not found. Available: {', '.join(f.stem for f in contracts_dir.glob('*.md'))}"
        return path.read_text()

    @mcp.tool(
        description=(
            "Get live server status — running containers, memory usage, "
            "and disk space. Use before starting services or when diagnosing "
            "issues."
        )
    )
    async def get_service_status() -> str:
        containers = await get_containers()
        resources = await get_system_resources()
        return f"## Running Containers\n```\n{containers}\n```\n\n{resources}"

    @mcp.tool(
        description=(
            "Get detailed GPU metrics — memory usage, utilization, temperature, "
            "and processes. Essential before loading large models on the 128GB "
            "unified memory system."
        )
    )
    async def get_gpu_status() -> str:
        return await get_gpu_detail()

    @mcp.tool(
        description=(
            "Get a project's CLAUDE.md to understand its rules, structure, "
            "and conventions. Use when working across projects or referencing "
            "another project's setup."
        )
    )
    async def get_project_context(name: str) -> str:
        path = PROJECTS_DIR / name / "CLAUDE.md"
        if not path.exists():
            available = [
                d.name
                for d in PROJECTS_DIR.iterdir()
                if d.is_dir() and (d / "CLAUDE.md").exists()
            ]
            return (
                f"CLAUDE.md not found for project '{name}'. "
                f"Projects with CLAUDE.md: {', '.join(available)}"
            )
        return path.read_text()

    @mcp.tool(
        description=(
            "Read any file from the docs repository (articles, snapshots, "
            "designs, etc.). Use when you need content not covered by "
            "specialized tools."
        )
    )
    async def read_doc(path: str) -> str:
        if ".." in path:
            return "Error: path traversal not allowed (contains '..')"
        full_path = DOCS_DIR / path
        if not full_path.is_file():
            return f"File not found: {path}"
        try:
            resolved = full_path.resolve()
            if not str(resolved).startswith(str(DOCS_DIR.resolve())):
                return "Error: path traversal not allowed"
            return resolved.read_text()
        except Exception as e:
            return f"Error reading {path}: {e}"
