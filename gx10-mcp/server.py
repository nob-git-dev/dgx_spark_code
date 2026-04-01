"""GX10 MCP Server — infrastructure management for ASUS Ascent GX10."""

import logging
import os
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from lib.config import MCP_PORT
from lib.kanban_store import KanbanStore
from tools import coordination, environment, history, kanban, live, recording

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("gx10-mcp")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

SERVER_INSTRUCTIONS = """\
GX10 MCP Server — ASUS Ascent GX10 (ARM64, 128GB unified memory) infrastructure management.

Standard workflow:
1. get_activity() — check if other agents are working
2. get_environment() — understand what's available (summary by default, verbose=true for full docs)
3. get_contract(name) — read API specs before calling any service
4. set_activity() — declare your work before making changes
5. write_decision() / write_journal() — record important decisions and work summaries

Agent Kanban System (Toyota Kanban-based coordination):
- board() — view the kanban board (visual management)
- card() — create a work card
- claim() — pull a card when you have capacity
- done() — mark a card as complete
- reserve() / release() / resources() — manage shared resources
- andon() — stop-the-line signal for critical issues
- signal() / watch() — event-driven coordination

Safety: start_service/stop_service have built-in guardrails (memory check, conflict detection).
All write operations auto-commit to Git.\
"""

# Kanban store (Redis-backed)
store = KanbanStore(REDIS_URL)


@asynccontextmanager
async def lifespan(app):
    """Connect to Redis on startup, disconnect on shutdown."""
    try:
        await store.connect()
        logger.info("Kanban store ready (Redis: %s)", REDIS_URL)
    except Exception as e:
        logger.warning(
            "Kanban store unavailable (Redis: %s): %s — kanban tools will error",
            REDIS_URL, e,
        )
    yield
    await store.close()
    logger.info("Kanban store disconnected")


mcp = FastMCP(
    name="gx10",
    instructions=SERVER_INSTRUCTIONS,
    lifespan=lifespan,
)

# Register all tool modules
environment.register(mcp)    # Phase 1: 6 tools
recording.register(mcp)      # Phase 2: 4 tools
live.register(mcp)           # Phase 3: 4 tools
coordination.register(mcp)   # Phase 3: 2 tools
history.register(mcp)        # Phase 4: 2 tools
kanban.register(mcp, store)  # Kanban: 10 tools


if __name__ == "__main__":
    transport = os.getenv("TRANSPORT", "stdio")

    if transport == "streamable-http":
        logger.info("Starting GX10 MCP server on port %d (Streamable HTTP)", MCP_PORT)
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=MCP_PORT,
        )
    else:
        logger.info("Starting GX10 MCP server (stdio)")
        mcp.run(transport="stdio")
