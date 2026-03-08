"""Tool registry: define, register, dispatch"""

import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Tool handler signature: async (arguments: dict) -> str
ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


class ToolRegistry:
    """Central registry for all agent tools."""

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: ToolHandler,
    ):
        """Register a tool with its OpenAI-format definition and handler."""
        self._tools[name] = {
            "definition": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
            "handler": handler,
        }
        logger.info("Registered tool: %s", name)

    def get_definitions(self) -> list[dict]:
        """Return OpenAI-format tool definitions for the API call."""
        return [t["definition"] for t in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name, return string result."""
        if name not in self._tools:
            return f"Error: Unknown tool '{name}'"
        try:
            handler = self._tools[name]["handler"]
            result = await handler(arguments)
            return str(result)
        except Exception as e:
            logger.error("Tool '%s' failed: %s", name, e, exc_info=True)
            return f"Error executing tool '{name}': {e}"
