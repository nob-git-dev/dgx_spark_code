#!/usr/bin/env python3
"""Claude Code SessionStart hook — MCP connectivity check and workflow reminder.

Checks if the GX10 MCP server is reachable and outputs the standard
workflow as a reminder. Non-blocking (always exits 0).

Usage in Claude Code settings.json:
  "hooks": {
    "SessionStart": [{
      "matcher": "startup",
      "hooks": [{
        "type": "command",
        "command": "python3 ~/projects/gx10-mcp/hooks/session_start.py",
        "timeout": 5
      }]
    }]
  }
"""

import json
import sys
import urllib.request
import urllib.error


HEALTH_URL = "http://localhost:9100/health"
ACTIVITY_URL = "http://localhost:9100/activity"


def check_mcp_reachable() -> bool:
    """Check if the REST API server is up via GET /health (200 OK = reachable)."""
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def read_activities() -> list:
    """Fetch active agents from REST API GET /activity.

    Returns the 'agents' list: [{"agent": "mac-claude", "description": "...", "timestamp": ...}, ...]
    """
    try:
        req = urllib.request.Request(ACTIVITY_URL, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            return data.get("agents", [])
    except Exception:
        return []


def main() -> None:
    lines: list[str] = []

    # 1. MCP connectivity
    reachable = check_mcp_reachable()
    if reachable:
        lines.append("[GX10 MCP] Server reachable (:9100)")
    else:
        lines.append("[GX10 MCP] WARNING: Server unreachable on :9100")
        lines.append("  Run: systemctl --user start gx10-mcp")

    # 2. Current activity
    activities = read_activities()
    if activities:
        lines.append("[GX10 MCP] Active agents:")
        for entry in activities:
            lines.append(f"  - {entry.get('agent', '?')}: {entry.get('description', '?')}")
    else:
        lines.append("[GX10 MCP] No active agents.")

    # 3. Workflow reminder
    lines.append("[GX10 MCP] Standard flow: get_activity() → set_activity() → work → write_journal()")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
