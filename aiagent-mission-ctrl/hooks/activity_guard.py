#!/usr/bin/env python3
"""Claude Code PreToolUse hook — remind to set_activity before code changes.

Checks REST API GET /activity for a recent gx10-claude entry. If absent or expired,
outputs a reminder as additionalContext. Never blocks (always exits 0).

Usage in Claude Code settings.json:
  "hooks": {
    "PreToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "python3 ~/projects/gx10-mcp/hooks/activity_guard.py",
        "timeout": 3
      }]
    }]
  }
"""

import json
import os
import sys
import time
import urllib.request

AGENT = "gx10-claude"
ACTIVITY_URL = "http://localhost:9100/activity"
EXPIRY_SECONDS = 30 * 60  # 30 minutes
# Track per-session so we only warn once
SESSION_FLAG = "/tmp/gx10-activity-warned-{}.flag"


def read_activities() -> list:
    """Fetch active agents from REST API GET /activity.

    Returns the 'agents' list: [{"agent": "gx10-claude", "description": "...", "timestamp": ...}, ...]
    """
    try:
        req = urllib.request.Request(ACTIVITY_URL, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            return data.get("agents", [])
    except Exception:
        return []


def main() -> None:
    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    session_id = hook_input.get("session_id", "unknown")
    flag_file = SESSION_FLAG.format(session_id[:12])

    # Skip if already warned this session
    if os.path.exists(flag_file):
        return

    agents = read_activities()
    entry = next((a for a in agents if a.get("agent") == AGENT), None)
    now = time.time()

    if entry and (now - entry.get("timestamp", 0)) < EXPIRY_SECONDS:
        # Activity is set and fresh — no warning needed
        return

    # Output reminder as additionalContext
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                "[GX10 MCP] set_activity() が未宣言です。"
                "コード変更前に set_activity(agent='gx10-claude', description='...') "
                "を呼んでください（第9条）。"
            ),
        }
    }
    print(json.dumps(output))

    # Mark as warned for this session
    try:
        with open(flag_file, "w") as f:
            f.write(str(now))
    except OSError:
        pass


if __name__ == "__main__":
    main()
