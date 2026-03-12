"""Web page fetch tool using trafilatura for content extraction."""

import asyncio
import logging

import httpx
import trafilatura
import html2text

from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 8000
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


async def _fetch_url(args: dict) -> str:
    url = args["url"]

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return f"HTTP error {e.response.status_code}: {url}"
    except httpx.RequestError as e:
        return f"Request failed: {e}"

    html = response.text

    # Primary: trafilatura (high-quality main content extraction)
    content = await asyncio.to_thread(
        trafilatura.extract,
        html,
        output_format="markdown",
        include_tables=True,
        include_links=True,
    )

    # Fallback: html2text (full page conversion)
    if not content:
        converter = html2text.HTML2Text()
        converter.ignore_images = True
        converter.body_width = 0
        content = await asyncio.to_thread(converter.handle, html)

    if not content:
        return "Could not extract content from the page."

    # Truncate to fit tool output limit
    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS] + "\n\n... (truncated)"

    return content


def register(registry: ToolRegistry):
    """Register web fetch tool."""
    registry.register(
        name="fetch_url",
        description=(
            "Fetch a web page and extract its main content as Markdown. "
            "Use this after web_search to read the full content of a page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
            },
            "required": ["url"],
        },
        handler=_fetch_url,
    )
