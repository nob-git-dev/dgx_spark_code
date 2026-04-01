# Agent Kanban System — Multi-Agent Coordination via MCP

**Toyota Kanban principles applied to AI agent coordination.**

Multiple Claude Code instances (or any MCP-compatible AI agents) running on different machines can collaborate through a shared Kanban board — no direct messaging required.

## The Problem

When multiple AI agents work on the same infrastructure:
- **No conversation:** Agents can share files, but can't coordinate in real-time
- **No task delegation:** "Do this for me" requires manual copy-paste between sessions
- **Resource conflicts:** Two agents may try to use the same GPU simultaneously
- **Offline fragility:** If one agent is idle, the other's requests are lost

## The Solution: Kanban, not Chat

Instead of building a messaging system, we applied **Toyota's Kanban method** — a pull-based flow control system proven over decades in manufacturing.

```
┌─ Kanban Board ──────────────────────────────────────────────┐
│                                                              │
│  [backlog]         [ready]          [active]      [done]     │
│                                      WIP: 3                  │
│  ┌───────────┐   ┌───────────┐   ┌───────────┐              │
│  │ Model swap │   │ OCR batch │   │ API design│              │
│  │ depends:   │   │ requires: │   │ owner:    │              │
│  │  [OCR job] │   │  gpu:110GB│   │  agent-1  │              │
│  └───────────┘   └───────────┘   └───────────┘              │
│                                                              │
│  Resources: gpu-memory 110/128GB | model-slot 1/1            │
│  Flow: throughput 5/day | avg cycle 18m                      │
└──────────────────────────────────────────────────────────────┘
```

**Cards carry context, not conversations.** An agent creates a card with full instructions in the description. Another agent pulls it when ready. No back-and-forth needed.

## Why Kanban > Messaging

| Messaging approach | Kanban approach |
|---|---|
| 4 round-trips to negotiate GPU access | Card declares resource needs; auto-queued until available |
| Both agents must be online | Cards persist; offline agents catch up |
| Ad-hoc, unstructured | Visible board with WIP limits and flow metrics |
| No resource arbitration | Built-in supermarket pattern for shared resources |
| No failure handling | Andon signal stops all work instantly |

## Key Concepts from Toyota Production System

| Toyota concept | Implementation |
|---|---|
| **Kanban card** | Task card with context, requirements, and dependencies |
| **Pull principle** | Agents `claim()` work when they have capacity — never pushed |
| **WIP limits** | Configurable per column — prevents overload |
| **Supermarket** | Resource pool with capacity tracking and automatic queuing |
| **Andon** | `andon()` signal blocks all active cards and notifies all agents |
| **Visual management** | `board()` shows cards, resources, and flow metrics at a glance |
| **Kaizen** | Automatic cycle time, throughput, and bottleneck tracking |

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│  Agent A         │         │  Agent B         │
│  (any machine)   │         │  (any machine)   │
└────────┬────────┘         └────────┬─────────┘
         │ MCP (HTTP)                │ MCP (stdio)
         ▼                           ▼
┌──────────────────────────────────────────────┐
│            MCP Server (FastMCP)              │
│                                              │
│  10 Kanban Tools                             │
│  ┌────────────────────────────────────────┐  │
│  │ Board:     card / claim / done / board │  │
│  │ Resources: reserve / release / resources│ │
│  │ Signals:   andon / signal / watch      │  │
│  └────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────┘
                       │ redis.asyncio
                       ▼
              ┌──────────────┐
              │  Redis 7     │  Docker container
              │  (Streams +  │  AOF persistence
              │   Hash +     │
              │   SortedSet) │
              └──────────────┘
```

## MCP Tools (10)

### Board Operations
| Tool | Description |
|------|-------------|
| `card(title, agent, ...)` | Create a work card → enters backlog, auto-promotes to ready when dependencies resolve |
| `claim(card_id, agent)` | Pull a card from ready → active. Reserves required resources. Respects WIP limits |
| `done(card_id, agent, result)` | Complete a card. Auto-releases resources, promotes dependent cards |
| `board(board_name)` | Visual board — cards, resources, flow metrics |

### Resource Management (Supermarket Pattern)
| Tool | Description |
|------|-------------|
| `reserve(resource, agent, amount)` | Reserve a shared resource. Queued if exhausted |
| `release(resource, agent)` | Return a resource. Waiting agents notified automatically |
| `resources()` | View resource pool inventory |

### Signals (Andon + Events)
| Tool | Description |
|------|-------------|
| `andon(reason, agent)` | Stop-the-line. All active cards → blocked |
| `signal(event, agent, data)` | Emit a custom event. Triggers matching rules |
| `watch(filter, timeout)` | Block until a matching event occurs (Redis XREAD BLOCK, zero CPU) |

## Configuration: Mechanism, not Policy

The 10 tools are **domain-agnostic**. All domain knowledge lives in `kanban.yml`:

```yaml
boards:
  default:
    columns: [backlog, ready, active, done]
    wip:
      active: 3

  devops:
    columns: [todo, dev, review, staging, production]
    wip: { dev: 2, review: 3 }

resources:
  gpu-memory:
    capacity: 128
    unit: GB
  model-slot:
    capacity: 1
  deploy-lock:
    capacity: 1
  edit-lock:
    type: named    # File-level locks to prevent conflicts
  api-rate:
    capacity: 60
    unit: req/min
    refill: 60s    # Token bucket auto-refill

lanes:
  expedite:
    wip: 1
    preempt: true  # Overrides other cards
  standard:
    wip: ~
  research:
    wip: ~

rules:
  - name: auto-release-on-done
    "on": card.done
    "do": release_all
  - name: andon-on-expedite-failure
    "on": card.failed
    "if": "card.lane == 'expedite'"
    "do": andon
```

**Change the YAML, not the code.** The same tools work for GPU workload management, web app development, infrastructure operations, or research projects.

## Card Lifecycle

```
card() ──→ backlog ──→ ready ──→ active ──→ done
              │           ↑         │
              │           │         │ andon()
              │           │         ▼
              │           │      blocked ──→ active
              │           │
              │     Auto-promote when:
              │     ✓ All depends_on cards are done
              └──── ✓ All required resources are available
```

## Event Sourcing

Every state change is recorded in a Redis Stream:

```
14:30:00  card.created   agent-1   "OCR batch processing"
14:30:05  card.claimed   agent-2   "OCR batch processing"
14:35:00  card.done      agent-2   result: "95.6% accuracy"
14:35:01  resource.released  agent-2   gpu-memory: 110GB
14:35:01  card.promoted  system    "Model swap" → ready
```

This enables: full audit trail, cycle time metrics, bottleneck detection, and rule engine triggers.

## Quick Start

```bash
# 1. Start Redis
docker compose up -d

# 2. Install dependencies
uv sync

# 3. Run MCP server (stdio mode for local Claude Code)
uv run server.py

# 4. Or run as HTTP server for remote agents
TRANSPORT=streamable-http uv run server.py
```

### Connect Claude Code

**Local (same machine):**
```json
// ~/.claude/.mcp.json
{
  "mcpServers": {
    "kanban": {
      "command": "uv",
      "args": ["run", "server.py"],
      "cwd": "/path/to/gx10-mcp"
    }
  }
}
```

**Remote (another machine):**
```json
{
  "mcpServers": {
    "kanban": {
      "type": "streamable-http",
      "url": "http://<server-ip>:9100/mcp"
    }
  }
}
```

### Auto-notification via Hooks

```json
// Claude Code settings.json
{
  "hooks": {
    "PreToolUse": [{
      "command": "python3 /path/to/hooks/check_board.py my-agent-name",
      "timeout": 3000
    }]
  }
}
```

The hook checks the board before every tool call and notifies the agent of ready cards or active andons.

### Install as systemd Service

```bash
cp gx10-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gx10-mcp
```

## Software Engineering Patterns Applied

- **Event Sourcing** — All state changes recorded as immutable events in Redis Streams
- **DAG Dependencies** — Cards can depend on other cards, forming execution pipelines
- **Named Locks** — File-level locking to prevent Git conflicts before they happen
- **Token Bucket** — Rate limiting for external API access as a managed resource
- **Strategy Pattern** — Rules in YAML, not code. Swap domain behavior without touching implementation

## Requirements

- Python 3.11+
- Redis 7+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker + Docker Compose (for Redis)

## License

MIT
