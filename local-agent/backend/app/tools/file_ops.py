"""File operations tool (restricted to workspace directory)"""

from pathlib import Path

from app.config import get_settings
from app.tools.registry import ToolRegistry


def _safe_path(relative_path: str) -> Path:
    """Resolve path within workspace, prevent directory traversal."""
    settings = get_settings()
    workspace = Path(settings.workspace_dir).resolve()
    target = (workspace / relative_path).resolve()
    if not str(target).startswith(str(workspace)):
        raise ValueError(f"Path traversal detected: {relative_path}")
    return target


async def _read_file(args: dict) -> str:
    path = _safe_path(args["path"])
    if not path.exists():
        return f"Error: File not found: {args['path']}"
    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) > 50000:
        content = content[:50000] + "\n... (truncated)"
    return content


async def _write_file(args: dict) -> str:
    path = _safe_path(args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"], encoding="utf-8")
    return f"File written: {args['path']} ({len(args['content'])} chars)"


async def _list_files(args: dict) -> str:
    directory = args.get("directory", ".")
    path = _safe_path(directory)
    if not path.exists():
        return f"Error: Directory not found: {directory}"
    if not path.is_dir():
        return f"Error: Not a directory: {directory}"

    entries = []
    for item in sorted(path.iterdir()):
        if item.is_dir():
            entries.append(f"[DIR]  {item.name}/")
        else:
            size = item.stat().st_size
            entries.append(f"[FILE] {item.name}  ({size} bytes)")
    return "\n".join(entries) if entries else "(empty directory)"


def register(registry: ToolRegistry):
    """Register file operation tools."""
    registry.register(
        name="read_file",
        description="Read the contents of a file in the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within workspace",
                },
            },
            "required": ["path"],
        },
        handler=_read_file,
    )
    registry.register(
        name="write_file",
        description=(
            "Write content to a file in the workspace. "
            "Creates parent directories if needed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within workspace",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write",
                },
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
    )
    registry.register(
        name="list_files",
        description="List files and directories in a workspace directory.",
        parameters={
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Relative directory path (default: root)",
                },
            },
            "required": [],
        },
        handler=_list_files,
    )
