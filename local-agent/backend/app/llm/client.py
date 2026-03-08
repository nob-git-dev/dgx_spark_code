"""Async LLM client for Ollama OpenAI-compatible API"""

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Get or create the shared async HTTP client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            # GPT-OSS-120B: initial load can take 5+ min, inference up to 5 min
            timeout=httpx.Timeout(connect=30, read=600, write=30, pool=30),
        )
    return _client


async def chat_completion(
    messages: list[dict],
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Call Ollama's OpenAI-compatible chat completion endpoint.

    When tools are provided, GPT-OSS may return:
    - finish_reason="tool_calls" with tool_calls in the message
    - finish_reason="stop" with content (final answer)
    """
    settings = get_settings()
    client = get_client()

    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "messages": messages,
        "max_tokens": settings.max_tokens,
        "temperature": settings.temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    logger.debug("LLM request: model=%s, messages=%d, tools=%d",
                 settings.ollama_model, len(messages), len(tools or []))

    response = await client.post("/v1/chat/completions", json=payload)
    response.raise_for_status()
    return response.json()


async def create_embedding(text: str) -> list[float]:
    """Create an embedding using Ollama's OpenAI-compatible endpoint."""
    settings = get_settings()
    client = get_client()

    payload = {
        "model": settings.embedding_model,
        "input": text,
    }
    response = await client.post("/v1/embeddings", json=payload)
    response.raise_for_status()
    data = response.json()
    return data["data"][0]["embedding"]
