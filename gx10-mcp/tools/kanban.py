"""Agent Kanban System — MCP tools for card lifecycle, resources, and signals.

10 tools based on Toyota Kanban principles:
  Board:     card, claim, done, board
  Resources: reserve, release, resources
  Signals:   andon, signal, watch
"""

import logging

from fastmcp import FastMCP

from lib.kanban_store import KanbanStore

logger = logging.getLogger("gx10-mcp")

# Module-level store instance, initialized by register()
_store: KanbanStore | None = None


def get_store() -> KanbanStore:
    if _store is None:
        raise RuntimeError("Kanban store not initialized. Is Redis running?")
    return _store


def register(mcp: FastMCP, store: KanbanStore) -> None:
    global _store
    _store = store

    # ─── Board operations ─────────────────────────────

    @mcp.tool(
        description=(
            "Create a kanban card (work unit). The card enters the backlog and "
            "auto-promotes to ready when dependencies are resolved and resources "
            "are available. Cards carry context — include everything the claiming "
            "agent needs in desc.\n\n"
            "Params:\n"
            "- title (required): What needs to be done\n"
            "- agent (required): Your agent name (gx10-claude / mac-claude / nanoclaw)\n"
            "- desc: Full context for whoever claims this card\n"
            "- board: Board name (default/devops/research)\n"
            "- lane: Priority class (expedite/standard/research)\n"
            "- size: S/M/L/XL — XL triggers a split warning\n"
            "- requires: JSON dict of resources needed, e.g. '{\"gpu-memory\": 110}'\n"
            "- depends_on: JSON list of card IDs that must complete first"
        )
    )
    async def card(
        title: str,
        agent: str,
        desc: str = "",
        board: str = "default",
        lane: str = "standard",
        size: str = "M",
        requires: str = "{}",
        depends_on: str = "[]",
    ) -> str:
        import json
        s = get_store()
        try:
            req_dict = json.loads(requires) if isinstance(requires, str) else requires
            dep_list = json.loads(depends_on) if isinstance(depends_on, str) else depends_on
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON — {e}"

        try:
            result = await s.card_create(
                title, agent,
                desc=desc, board=board, lane=lane, size=size,
                requires=req_dict, depends_on=dep_list,
            )
            msg = f"Card created: {result['card_id']} → [{result['column']}]"
            if result.get("warning"):
                msg += result["warning"]
            return msg
        except ValueError as e:
            return f"Error: {e}"

    @mcp.tool(
        description=(
            "Claim (pull) a card from the ready column. You become the owner "
            "and the card moves to active. Resources specified in 'requires' "
            "are automatically reserved. Respects WIP limits.\n\n"
            "This is the Kanban 'pull' principle — only claim when you have capacity."
        )
    )
    async def claim(card_id: str, agent: str) -> str:
        s = get_store()
        try:
            result = await s.card_claim(card_id, agent)
            return f"Claimed: {card_id} → [{result['column']}] (owner: {agent})"
        except ValueError as e:
            return f"Error: {e}"

    @mcp.tool(
        description=(
            "Mark a card as done. Resources are auto-released, dependent cards "
            "are auto-promoted, and cycle time is recorded.\n\n"
            "- result: Summary of what was accomplished (carried on the card for future reference)"
        )
    )
    async def done(card_id: str, agent: str, result: str = "") -> str:
        s = get_store()
        try:
            res = await s.card_done(card_id, agent, result)
            cycle = f" (cycle: {res['cycle_time']})" if res.get("cycle_time") else ""
            return f"Done: {card_id} → [{res['column']}]{cycle}"
        except ValueError as e:
            return f"Error: {e}"

    @mcp.tool(
        description=(
            "View the kanban board — cards, resources, and flow metrics. "
            "This is 'visual management' (目で見る管理).\n\n"
            "- board_name: Which board to view (default/devops/research)\n"
            "- lane: Filter by lane (expedite/standard/research)\n"
            "- column: Filter by specific column"
        )
    )
    async def board(
        board_name: str = "default",
        lane: str = "",
        column: str = "",
    ) -> str:
        s = get_store()
        return await s.board_view(
            board=board_name,
            lane=lane or None,
            column=column or None,
        )

    # ─── Resource operations ──────────────────────────

    @mcp.tool(
        description=(
            "Reserve a shared resource (Kanban 'supermarket' pattern). "
            "If the resource is exhausted, you'll be told your queue position.\n\n"
            "Resources are defined in kanban.yml. Types:\n"
            "- capacity: numeric (gpu-memory, deploy-lock)\n"
            "- pool: discrete items (port)\n"
            "- named: arbitrary named locks (edit-lock)\n\n"
            "Params:\n"
            "- resource (required): Resource name\n"
            "- agent (required): Your agent name\n"
            "- amount: How much to reserve (capacity type, default=1)\n"
            "- name: Lock name (named type, e.g. 'src/auth/')\n"
            "- reason: Why you need it (for visibility)"
        )
    )
    async def reserve(
        resource: str,
        agent: str,
        amount: int = 1,
        name: str = "",
        reason: str = "",
    ) -> str:
        s = get_store()
        try:
            result = await s.resource_reserve(resource, agent, amount, name, reason)
            return f"Reserved: {resource} ({result['amount']}) by {agent}"
        except ValueError as e:
            return f"Error: {e}"

    @mcp.tool(
        description=(
            "Release a previously reserved resource. If other agents are waiting "
            "in the queue, they will be notified automatically."
        )
    )
    async def release(resource: str, agent: str, name: str = "") -> str:
        s = get_store()
        try:
            await s.resource_release(resource, agent, name)
            return f"Released: {resource} by {agent}"
        except ValueError as e:
            return f"Error: {e}"

    @mcp.tool(
        description="View the current state of all shared resources (the 'supermarket' inventory)."
    )
    async def resources() -> str:
        s = get_store()
        return await s.resource_list()

    # ─── Signal operations ────────────────────────────

    @mcp.tool(
        description=(
            "Trigger an Andon (異常停止) signal. All active cards move to 'blocked' "
            "and all agents are notified. Use when something is broken and work "
            "should stop until the issue is resolved.\n\n"
            "Resolve by calling done() on the blocking issue."
        )
    )
    async def andon(reason: str, agent: str) -> str:
        s = get_store()
        result = await s.andon(agent, reason)
        blocked = result["blocked_cards"]
        return (
            f"ANDON triggered by {agent}: {reason}\n"
            f"Blocked cards: {blocked if blocked else '(none active)'}"
        )

    @mcp.tool(
        description=(
            "Emit a custom signal/event. Other agents can watch() for it. "
            "Also triggers any matching rules in kanban.yml.\n\n"
            "Examples: 'build.passed', 'deploy.started', 'research.found'"
        )
    )
    async def signal(event: str, agent: str, data: str = "") -> str:
        s = get_store()
        result = await s.signal_emit(event, agent, data)
        return f"Signal emitted: {event} ({result['event_id']})"

    @mcp.tool(
        description=(
            "Wait for an event/signal matching a pattern. Blocks efficiently "
            "(no CPU usage) until a matching event occurs or timeout.\n\n"
            "- filter: Event pattern ('card.*', 'resource.released', 'andon.*', '*')\n"
            "- timeout: Max seconds to wait (default=30)"
        )
    )
    async def watch(filter: str = "*", timeout: int = 30) -> str:
        s = get_store()
        result = await s.watch(filter, timeout)
        if result.get("status") == "timeout":
            return result["message"]
        return (
            f"Event: {result['type']} by {result['agent']}\n"
            f"Data: {result['data']}"
        )
