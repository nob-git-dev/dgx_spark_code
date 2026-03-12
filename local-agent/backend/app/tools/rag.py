"""RAG tool: document vector search via ChromaDB"""

from __future__ import annotations

import logging

import chromadb

from app.config import get_settings
from app.llm.client import create_embedding
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_chroma_client: chromadb.HttpClient | None = None
COLLECTION_NAME = "documents"


def get_chroma() -> chromadb.HttpClient:
    """Get or create ChromaDB HTTP client."""
    global _chroma_client
    if _chroma_client is None:
        settings = get_settings()
        _chroma_client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
    return _chroma_client


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


async def _search_documents(args: dict) -> str:
    query = args.get("query", "").strip()
    n_results = args.get("n_results", 5)

    if not query:
        return (
            "Error: A non-empty search query is required. "
            "Please provide a specific topic or keyword to search for."
        )

    client = get_chroma()
    collection = client.get_or_create_collection(COLLECTION_NAME)

    doc_count = collection.count()
    if doc_count == 0:
        return "No documents have been uploaded yet."

    query_embedding = await create_embedding(query)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["distances", "documents", "metadatas"],
    )

    if not results["documents"] or not results["documents"][0]:
        return "No relevant documents found."

    # Filter out low-relevance results (distance > 0.8 in cosine space)
    max_distance = 0.8
    formatted = []
    for i, (doc, meta, dist) in enumerate(
        zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ),
        1,
    ):
        if dist > max_distance:
            continue
        source = meta.get("source", "unknown")
        relevance = f"{(1 - dist) * 100:.0f}%"
        formatted.append(
            f"[{i}] (source: {source}, relevance: {relevance})\n{doc}"
        )

    if not formatted:
        return (
            f"No sufficiently relevant documents found for this query. "
            f"({doc_count} chunks indexed, but none matched well enough.)"
        )

    return "\n\n---\n\n".join(formatted)


def register(registry: ToolRegistry):
    """Register document search tool."""
    registry.register(
        name="search_documents",
        description=(
            "Search through uploaded documents using semantic similarity. "
            "ALWAYS use this tool when the user mentions uploaded files, "
            "shared documents, or asks about content from their documents. "
            "Also use this for any question that might be answered by "
            "previously uploaded materials."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "n_results": {
                    "type": "integer",
                    "description": "Number of results (default: 5)",
                },
            },
            "required": ["query"],
        },
        handler=_search_documents,
    )
