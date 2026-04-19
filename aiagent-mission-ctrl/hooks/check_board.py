#!/usr/bin/env python3
"""Claude Code PreToolUse hook — check kanban board for pending items.

Connects directly to Redis (no MCP dependency) for speed.
Outputs notification text to stdout if there are actionable items.
Exit code 0 always (never block the tool call).

Usage in Claude Code settings.json:
  "hooks": {
    "PreToolUse": [{
      "command": "uv --project /YOUR/INSTALL/PATH run python3 /YOUR/INSTALL/PATH/hooks/check_board.py your-agent-name",
      "timeout": 3
    }]
  }

NOTE: Replace /YOUR/INSTALL/PATH with the actual directory where you cloned this repo.
      This hook requires redis-py (included in uv env). Unlike other hooks, must run via uv.
"""

import json
import os
import sys
import time

try:
    import redis
except ImportError:
    # redis-py not available — skip silently
    sys.exit(0)

AGENT = sys.argv[1] if len(sys.argv) > 1 else "unknown"
REDIS_URL = os.environ.get("KANBAN_REDIS_URL", "redis://localhost:6379")


def main() -> None:
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        r.ping()
    except (redis.ConnectionError, redis.TimeoutError):
        # Redis not running — skip silently
        return

    notifications: list[str] = []

    # 1. Check for andon
    events = r.xrevrange("kanban:events", count=20)
    andon_active = False
    for event_id, data in events:
        if data.get("type") == "andon.resolved":
            break
        if data.get("type") == "andon.triggered":
            event_data = json.loads(data.get("data", "{}"))
            notifications.append(
                f"ANDON active: {event_data.get('reason', '?')} "
                f"(by {data.get('agent', '?')})"
            )
            andon_active = True
            break

    # 2. Check for ready cards (across all boards)
    ready_cards: list[str] = []
    for key in r.scan_iter(match="kanban:col:*:ready"):
        card_ids = r.zrange(key, 0, -1)
        for cid in card_ids:
            card = r.hgetall(f"kanban:card:{cid}")
            if card:
                ready_cards.append(f"{cid} \"{card.get('title', '?')}\"")

    if ready_cards:
        notifications.append(f"{len(ready_cards)} card(s) ready to claim:")
        for c in ready_cards[:5]:  # Limit to 5
            notifications.append(f"  - {c}")

    # 3. Check for cards assigned to this agent that are still active
    active_cards: list[str] = []
    for key in r.scan_iter(match="kanban:col:*:active"):
        # Also check non-standard active columns (dev, exploring, etc.)
        card_ids = r.zrange(key, 0, -1)
        for cid in card_ids:
            card = r.hgetall(f"kanban:card:{cid}")
            if card and card.get("owner") == AGENT:
                claimed_at = float(card.get("claimed_at", 0))
                elapsed = int((time.time() - claimed_at) / 60) if claimed_at else 0
                active_cards.append(f"{cid} \"{card.get('title', '?')}\" ({elapsed}m)")

    # Only show as notification if none, since active is expected
    # Skip — this would be noise

    if notifications:
        print(f"[Kanban] {AGENT}")
        for n in notifications:
            print(f"  {n}")


if __name__ == "__main__":
    main()
