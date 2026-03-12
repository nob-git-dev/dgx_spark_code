"""Initialize tool registry with all tools."""

from app.tools.registry import ToolRegistry
from app.tools.web_search import register as register_web_search
from app.tools.file_ops import register as register_file_ops
from app.tools.shell import register as register_shell
from app.tools.rag import register as register_rag
from app.tools.web_fetch import register as register_web_fetch


def create_registry() -> ToolRegistry:
    """Create and populate the tool registry."""
    registry = ToolRegistry()
    register_web_search(registry)
    register_file_ops(registry)
    register_shell(registry)
    register_rag(registry)
    register_web_fetch(registry)
    return registry
