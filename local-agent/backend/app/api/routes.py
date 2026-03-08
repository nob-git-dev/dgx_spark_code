"""API routes for the agent"""

import hashlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.agents.react import run_agent
from app.config import get_settings
from app.llm.client import create_embedding
from app.memory.conversation import ConversationStore
from app.tools import create_registry
from app.tools.rag import get_chroma, chunk_text, COLLECTION_NAME
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agent"])

# Global instances (initialized via setup())
_store: ConversationStore | None = None
_registry: ToolRegistry | None = None


def setup(store: ConversationStore):
    """Initialize global instances."""
    global _store, _registry
    _store = store
    _registry = create_registry()


@router.post("/chat")
async def chat(request: Request):
    """Send a message to the agent. Returns SSE stream of AgentStep events."""
    body = await request.json()
    message = body.get("message", "").strip()
    conversation_id = body.get("conversation_id")

    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    # Get or create conversation
    if conversation_id:
        conversation = _store.get(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = _store.create()

    async def generate():
        try:
            # Send conversation ID first
            yield {
                "data": json.dumps({
                    "type": "conversation_id",
                    "conversation_id": conversation.id,
                })
            }

            # Run agent loop
            async for step in run_agent(message, conversation, _registry):
                yield {
                    "data": json.dumps(
                        step.model_dump(exclude_none=True)
                    )
                }

            # Signal completion
            yield {"data": json.dumps({"type": "done"})}

        except Exception as e:
            logger.error("Chat error: %s", e, exc_info=True)
            yield {
                "data": json.dumps({
                    "type": "error",
                    "error": str(e),
                })
            }

    return EventSourceResponse(generate())


@router.get("/conversations")
async def list_conversations():
    """List all conversations."""
    return _store.list_all()


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get a conversation by ID."""
    conv = _store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation."""
    _store.delete(conversation_id)
    return {"ok": True}


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload a document for RAG indexing."""
    settings = get_settings()
    uploads_dir = Path(settings.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    text = content.decode("utf-8", errors="replace")

    # Save file
    file_path = uploads_dir / file.filename
    file_path.write_bytes(content)

    # Chunk and embed
    chunks = chunk_text(text)
    chroma = get_chroma()
    collection = chroma.get_or_create_collection(COLLECTION_NAME)

    ids = []
    embeddings = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(
            f"{file.filename}:{i}".encode()
        ).hexdigest()
        embedding = await create_embedding(chunk)
        ids.append(chunk_id)
        embeddings.append(embedding)
        documents.append(chunk)
        metadatas.append({"source": file.filename, "chunk_index": i})

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )

    return {
        "filename": file.filename,
        "chunks": len(chunks),
        "status": "indexed",
    }
