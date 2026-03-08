"""Local Agent — FastAPI entry point

Endpoints:
  GET  /                             -> Frontend (index.html)
  GET  /health                       -> Health check
  POST /api/v1/chat                  -> SSE agent chat
  GET  /api/v1/conversations         -> List conversations
  GET  /api/v1/conversations/{id}    -> Get conversation
  DELETE /api/v1/conversations/{id}  -> Delete conversation
  POST /api/v1/upload                -> Upload document for RAG
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes
from app.memory.conversation import ConversationStore

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path("/app/frontend")

# Global instances
store = ConversationStore()
routes.setup(store)

app = FastAPI(
    title="Local Agent",
    description="Local Agentic AI with ReAct pattern",
    version="0.1.0",
)

# API router
app.include_router(routes.router)

# Frontend static files
if FRONTEND_DIR.exists():
    css_dir = FRONTEND_DIR / "css"
    js_dir = FRONTEND_DIR / "js"
    if css_dir.exists():
        app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
    if js_dir.exists():
        app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")


@app.get("/", include_in_schema=False)
async def root():
    """Serve the frontend."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse(
        "<h1>Local Agent</h1><p>Frontend not found.</p>"
    )


@app.get("/health", include_in_schema=False)
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
