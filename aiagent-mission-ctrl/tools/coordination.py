"""Agent coordination tools (Phase 3): set_activity, get_activity."""

import fcntl
import json
import logging
import time
from pathlib import Path

from fastmcp import FastMCP

logger = logging.getLogger("gx10-mcp")

ACTIVITY_FILE = Path(__file__).parent.parent / "activity.json"
EXPIRY_SECONDS = 30 * 60  # 30 minutes


def _read_activities() -> dict:
    if not ACTIVITY_FILE.exists():
        return {}
    try:
        return json.loads(ACTIVITY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_activities(data: dict) -> None:
    ACTIVITY_FILE.parent.mkdir(exist_ok=True)
    with open(ACTIVITY_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2)
        fcntl.flock(f, fcntl.LOCK_UN)


def _purge_expired(data: dict) -> dict:
    now = time.time()
    return {
        k: v for k, v in data.items()
        if now - v.get("timestamp", 0) < EXPIRY_SECONDS
    }


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        description=(
            "Declare what you are currently doing on GX10. Call before starting "
            "service changes or long operations to prevent conflicts with other "
            "agents. Entries auto-expire after 30 minutes."
        )
    )
    async def set_activity(agent: str, description: str) -> str:
        data = _purge_expired(_read_activities())
        data[agent] = {
            "description": description,
            "timestamp": time.time(),
        }
        _write_activities(data)
        return f"Activity registered for {agent}: {description}"

    @mcp.tool(
        description=(
            "Check what other agents are currently doing on GX10. "
            "Call before any service start/stop operation to avoid conflicts."
        )
    )
    async def get_activity() -> str:
        data = _purge_expired(_read_activities())
        _write_activities(data)  # Persist purge

        if not data:
            return "No active agents."

        lines = ["# Active Agents", ""]
        now = time.time()
        for agent, info in data.items():
            elapsed = int((now - info["timestamp"]) / 60)
            lines.append(
                f"- **{agent}**: {info['description']} ({elapsed}m ago)"
            )
        return "\n".join(lines)
