"""Web search tool using duckduckgo-search"""

import asyncio
import logging

from duckduckgo_search import DDGS

from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


async def _search(args: dict) -> str:
    query = args["query"]
    max_results = args.get("max_results", 5)

    def _run_search():
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    # duckduckgo_search is synchronous, run in thread
    results = await asyncio.to_thread(_run_search)

    if not results:
        return "No search results found."

    formatted = []
    for i, r in enumerate(results, 1):
        formatted.append(
            f"{i}. **{r['title']}**\n"
            f"   URL: {r['href']}\n"
            f"   {r['body']}"
        )
    return "\n\n".join(formatted)


def register(registry: ToolRegistry):
    """Register web search tool."""
    registry.register(
        name="web_search",
        description=(
            "Search the web using DuckDuckGo. "
            "Returns titles, URLs, and snippets."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 5)",
                },
            },
            "required": ["query"],
        },
        handler=_search,
    )
