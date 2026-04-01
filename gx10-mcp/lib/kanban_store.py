"""Kanban store — Redis-backed card lifecycle, resource pool, and event sourcing."""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
import yaml

logger = logging.getLogger("gx10-mcp")

CONFIG_PATH = Path(__file__).parent.parent / "kanban.yml"

# Redis key prefixes
K_CARD = "kanban:card:{}"
K_COL = "kanban:col:{}:{}"
K_EVENTS = "kanban:events"
K_RESOURCE = "kanban:resource:{}"
K_LOCK = "kanban:lock:{}:{}"
K_PRESENCE = "kanban:presence:{}"

PRESENCE_TTL = 30 * 60  # 30 minutes


# ─── Configuration ───────────────────────────────────────


@dataclass
class BoardConfig:
    columns: list[str]
    wip: dict[str, int] = field(default_factory=dict)


@dataclass
class LaneConfig:
    wip: int | None = None
    preempt: bool = False


@dataclass
class ResourceConfig:
    capacity: int = 0
    unit: str = ""
    type: str = "capacity"  # capacity | pool | named
    items: list[str] = field(default_factory=list)
    refill: str = ""


@dataclass
class RuleConfig:
    name: str
    on: str
    do: str
    condition: str = ""


@dataclass
class Config:
    boards: dict[str, BoardConfig]
    lanes: dict[str, LaneConfig]
    resources: dict[str, ResourceConfig]
    agents: dict[str, dict]
    rules: list[RuleConfig]


def load_config() -> Config:
    raw = yaml.safe_load(CONFIG_PATH.read_text())

    boards = {
        name: BoardConfig(
            columns=b["columns"],
            wip=b.get("wip") or {},
        )
        for name, b in raw.get("boards", {}).items()
    }
    lanes = {
        name: LaneConfig(
            wip=l.get("wip"),
            preempt=l.get("preempt", False),
        )
        for name, l in raw.get("lanes", {}).items()
    }
    resources = {
        name: ResourceConfig(
            capacity=r.get("capacity", 0),
            unit=r.get("unit", ""),
            type=r.get("type", "capacity"),
            items=[str(i) for i in r.get("items", [])],
            refill=r.get("refill", ""),
        )
        for name, r in raw.get("resources", {}).items()
    }
    agents = raw.get("agents", {})
    rules = [
        RuleConfig(
            name=r["name"],
            on=r["on"],
            do=r["do"],
            condition=r.get("if", ""),
        )
        for r in raw.get("rules", [])
    ]
    return Config(boards=boards, lanes=lanes, resources=resources, agents=agents, rules=rules)


# ─── Store ───────────────────────────────────────────────


class KanbanStore:
    """Redis-backed kanban store with event sourcing."""

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis: aioredis.Redis | None = None
        self._redis_url = redis_url
        self.config = load_config()

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        await self._redis.ping()
        logger.info("Kanban store connected to Redis")

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    @property
    def r(self) -> aioredis.Redis:
        if not self._redis:
            raise RuntimeError("KanbanStore not connected. Call connect() first.")
        return self._redis

    # ─── Events (Event Sourcing) ──────────────────────

    async def _emit(self, event_type: str, agent: str, data: dict | None = None) -> str:
        entry = {
            "type": event_type,
            "agent": agent,
            "ts": str(time.time()),
            "data": json.dumps(data or {}),
        }
        event_id = await self.r.xadd(K_EVENTS, entry)
        logger.info("Event %s: %s by %s", event_id, event_type, agent)
        await self._evaluate_rules(event_type, agent, data or {})
        return event_id

    async def _evaluate_rules(self, event_type: str, agent: str, data: dict) -> None:
        for rule in self.config.rules:
            if not self._event_matches(rule.on, event_type):
                continue
            if rule.condition and not self._eval_condition(rule.condition, data):
                continue
            logger.info("Rule '%s' triggered by %s", rule.name, event_type)
            await self._execute_action(rule.do, data)

    @staticmethod
    def _event_matches(pattern: str, event_type: str) -> bool:
        if pattern == event_type:
            return True
        if pattern.endswith(".*"):
            return event_type.startswith(pattern[:-1])
        return False

    @staticmethod
    def _eval_condition(condition: str, data: dict) -> bool:
        try:
            card = data.get("_card", {})
            event = data.get("_event", {})
            ctx = {"card": type("Card", (), card)(), "event": type("Event", (), event)()}
            return bool(eval(condition, {"__builtins__": {}}, ctx))  # noqa: S307
        except Exception as e:
            logger.warning("Condition eval failed: %s — %s", condition, e)
            return False

    async def _execute_action(self, action: str, data: dict) -> None:
        card_id = data.get("card_id", "")
        if action == "release_all":
            if card_id:
                await self._release_card_resources(card_id)
        elif action == "andon":
            await self.andon(data.get("agent", "system"), "auto-rule triggered")
        elif action == "write_journal":
            pass  # Handled by tools layer which has access to the journal tool
        elif action == "notify":
            pass  # Future: push notification to all agents
        else:
            logger.warning("Unknown rule action: %s", action)

    # ─── Cards ────────────────────────────────────────

    async def card_create(
        self,
        title: str,
        agent: str,
        *,
        desc: str = "",
        board: str = "default",
        lane: str = "standard",
        size: str = "M",
        requires: dict[str, int] | None = None,
        depends_on: list[str] | None = None,
    ) -> dict:
        board_cfg = self.config.boards.get(board)
        if not board_cfg:
            raise ValueError(f"Unknown board: {board}. Available: {list(self.config.boards.keys())}")
        if lane not in self.config.lanes:
            raise ValueError(f"Unknown lane: {lane}. Available: {list(self.config.lanes.keys())}")

        card_id = f"c-{uuid.uuid4().hex[:8]}"
        now = time.time()
        card_data = {
            "id": card_id,
            "title": title,
            "desc": desc,
            "board": board,
            "lane": lane,
            "size": size,
            "column": "backlog",
            "owner": "",
            "requires": json.dumps(requires or {}),
            "depends_on": json.dumps(depends_on or []),
            "result": "",
            "created_at": str(now),
            "updated_at": str(now),
            "created_by": agent,
        }
        first_col = board_cfg.columns[0]

        await self.r.hset(K_CARD.format(card_id), mapping=card_data)
        await self.r.zadd(K_COL.format(board, first_col), {card_id: now})

        await self._emit("card.created", agent, {
            "card_id": card_id,
            "title": title,
            "board": board,
            "lane": lane,
            "_card": {"lane": lane, "board": board, "size": size, "owner": ""},
        })

        # Try auto-promote to ready
        await self._try_promote(card_id)

        warning = ""
        if size == "XL":
            warning = " [WARNING: size=XL — consider splitting into smaller cards]"

        return {"card_id": card_id, "column": first_col, "warning": warning}

    async def _try_promote(self, card_id: str) -> bool:
        """Promote card from backlog to ready if dependencies resolved and resources available."""
        card = await self._get_card(card_id)
        if not card or card["column"] != "backlog":
            return False

        board_cfg = self.config.boards.get(card["board"])
        if not board_cfg or len(board_cfg.columns) < 2:
            return False

        # Check dependencies
        depends = json.loads(card["depends_on"])
        for dep_id in depends:
            dep = await self._get_card(dep_id)
            if not dep or dep["column"] != "done":
                return False

        # Check resource availability (don't reserve yet, just check)
        requires = json.loads(card["requires"])
        for res_name, amount in requires.items():
            if not await self._check_resource_available(res_name, amount):
                return False

        # Promote
        ready_col = board_cfg.columns[1]  # second column = ready
        await self._move_card(card_id, card["board"], card["column"], ready_col)
        return True

    async def card_claim(self, card_id: str, agent: str) -> dict:
        card = await self._get_card(card_id)
        if not card:
            raise ValueError(f"Card not found: {card_id}")

        board_cfg = self.config.boards.get(card["board"])
        if not board_cfg:
            raise ValueError(f"Unknown board: {card['board']}")

        # Find the "active" column (third column by convention)
        cols = board_cfg.columns
        ready_col = cols[1] if len(cols) > 1 else cols[0]
        active_col = cols[2] if len(cols) > 2 else cols[1] if len(cols) > 1 else cols[0]

        if card["column"] != ready_col:
            raise ValueError(
                f"Card {card_id} is in '{card['column']}', not '{ready_col}'. "
                f"Only cards in '{ready_col}' can be claimed."
            )

        # Check WIP limit
        wip_limit = board_cfg.wip.get(active_col)
        if wip_limit is not None:
            current_wip = await self.r.zcard(K_COL.format(card["board"], active_col))
            if current_wip >= wip_limit:
                raise ValueError(
                    f"WIP limit reached for '{active_col}' ({current_wip}/{wip_limit}). "
                    f"Complete existing cards first."
                )

        # Reserve resources
        requires = json.loads(card["requires"])
        reserved = []
        try:
            for res_name, amount in requires.items():
                await self._reserve_resource(res_name, amount, agent, f"card:{card_id}")
                reserved.append((res_name, amount))
        except ValueError:
            # Rollback reserved resources
            for res_name, amount in reserved:
                await self._release_resource(res_name, amount, agent)
            raise

        # Move to active
        await self._move_card(card_id, card["board"], ready_col, active_col)
        await self.r.hset(K_CARD.format(card_id), mapping={
            "owner": agent,
            "updated_at": str(time.time()),
            "claimed_at": str(time.time()),
        })

        await self._emit("card.claimed", agent, {
            "card_id": card_id,
            "title": card["title"],
            "_card": {"lane": card["lane"], "board": card["board"], "owner": agent},
        })

        # Update presence
        await self.presence_update(agent, "active", card["title"])

        return {"card_id": card_id, "column": active_col}

    async def card_done(self, card_id: str, agent: str, result: str = "") -> dict:
        card = await self._get_card(card_id)
        if not card:
            raise ValueError(f"Card not found: {card_id}")
        if card["owner"] != agent:
            raise ValueError(f"Card {card_id} is owned by '{card['owner']}', not '{agent}'")

        board_cfg = self.config.boards.get(card["board"])
        if not board_cfg:
            raise ValueError(f"Unknown board: {card['board']}")

        done_col = board_cfg.columns[-1]  # last column = done

        await self._move_card(card_id, card["board"], card["column"], done_col)
        await self.r.hset(K_CARD.format(card_id), mapping={
            "result": result,
            "column": done_col,
            "updated_at": str(time.time()),
            "done_at": str(time.time()),
        })

        cycle_time = ""
        created = float(card.get("created_at", 0))
        if created:
            cycle_secs = time.time() - created
            cycle_time = self._format_duration(cycle_secs)

        await self._emit("card.done", agent, {
            "card_id": card_id,
            "title": card["title"],
            "result": result,
            "cycle_time": cycle_time,
            "_card": {"lane": card["lane"], "board": card["board"], "owner": agent},
        })
        # Note: resource release is handled by the 'auto-release-on-done' rule in kanban.yml.
        # _emit() above evaluates rules synchronously, so resources are released before we proceed.

        # Promote dependent cards
        await self._promote_dependents(card_id)

        return {"card_id": card_id, "column": done_col, "cycle_time": cycle_time}

    async def _promote_dependents(self, done_card_id: str) -> None:
        """Find cards that depend on done_card_id and try to promote them."""
        # Scan all backlog cards across boards for depends_on references
        for board_name, board_cfg in self.config.boards.items():
            first_col = board_cfg.columns[0]
            card_ids = await self.r.zrange(K_COL.format(board_name, first_col), 0, -1)
            for cid in card_ids:
                card = await self._get_card(cid)
                if not card:
                    continue
                depends = json.loads(card["depends_on"])
                if done_card_id in depends:
                    await self._try_promote(cid)

    async def board_view(
        self,
        board: str = "default",
        lane: str | None = None,
        column: str | None = None,
    ) -> str:
        board_cfg = self.config.boards.get(board)
        if not board_cfg:
            return f"Unknown board: {board}. Available: {list(self.config.boards.keys())}"

        lines = [f"=== Board: {board} ===", ""]

        cols_to_show = [column] if column and column in board_cfg.columns else board_cfg.columns

        for col in cols_to_show:
            card_ids = await self.r.zrange(K_COL.format(board, col), 0, -1)
            cards = []
            for cid in card_ids:
                card = await self._get_card(cid)
                if card and (lane is None or card["lane"] == lane):
                    cards.append(card)

            wip_limit = board_cfg.wip.get(col)
            wip_str = f"  {len(cards)}/{wip_limit} WIP" if wip_limit else f"  {len(cards)} cards"
            lines.append(f"[{col}]{wip_str}")

            for c in cards:
                parts = [f"  {c['id']}  \"{c['title']}\"  lane:{c['lane']}"]
                if c["owner"]:
                    parts.append(f"owner:{c['owner']}")
                deps = json.loads(c["depends_on"])
                if deps:
                    parts.append(f"depends:{deps}")
                reqs = json.loads(c["requires"])
                if reqs:
                    parts.append(f"requires:{reqs}")
                if c["size"] != "M":
                    parts.append(f"size:{c['size']}")
                if c.get("claimed_at"):
                    elapsed = time.time() - float(c["claimed_at"])
                    parts.append(f"elapsed:{self._format_duration(elapsed)}")
                if c.get("done_at") and c.get("created_at"):
                    cycle = float(c["done_at"]) - float(c["created_at"])
                    parts.append(f"cycle:{self._format_duration(cycle)}")
                if c["result"]:
                    result_preview = c["result"][:80]
                    parts.append(f"result:\"{result_preview}\"")
                lines.append("  ".join(parts))

            if not cards:
                lines.append("  (empty)")
            lines.append("")

        # Resources summary
        lines.append("--- Resources ---")
        for res_name in self.config.resources:
            lines.append(await self._resource_summary(res_name))
        lines.append("")

        # Flow metrics (24h)
        metrics = await self._flow_metrics(board)
        lines.append("--- Flow (24h) ---")
        lines.append(f"  throughput: {metrics['throughput']} cards")
        lines.append(f"  avg cycle:  {metrics['avg_cycle']}")
        if metrics["bottleneck"]:
            lines.append(f"  bottleneck: {metrics['bottleneck']}")

        return "\n".join(lines)

    async def _flow_metrics(self, board: str) -> dict:
        now = time.time()
        day_ago = now - 86400
        day_ago_ms = int(day_ago * 1000)

        # Count done events in last 24h
        events = await self.r.xrange(K_EVENTS, min=str(day_ago_ms), max="+")
        done_events = [
            e for e in events
            if e[1].get("type") == "card.done"
            and json.loads(e[1].get("data", "{}")).get("_card", {}).get("board") == board
        ]
        throughput = len(done_events)

        # Average cycle time
        cycle_times = []
        for e in done_events:
            data = json.loads(e[1].get("data", "{}"))
            ct = data.get("cycle_time", "")
            if ct:
                cycle_times.append(ct)

        avg_cycle = cycle_times[0] if len(cycle_times) == 1 else (
            "N/A" if not cycle_times else self._avg_cycle_str(done_events)
        )

        return {
            "throughput": throughput,
            "avg_cycle": avg_cycle,
            "bottleneck": "",  # TODO: compute from column transition times
        }

    def _avg_cycle_str(self, done_events: list) -> str:
        total = 0.0
        count = 0
        for e in done_events:
            data = json.loads(e[1].get("data", "{}"))
            card_id = data.get("card_id")
            if card_id:
                # cycle_time is a string, but we stored created_at separately
                ct = data.get("cycle_time", "")
                if ct:
                    count += 1
                    # Parse back the duration — simplified
                    total += self._parse_duration(ct)
        if count == 0:
            return "N/A"
        return self._format_duration(total / count)

    # ─── Resources ────────────────────────────────────

    async def resource_reserve(
        self, resource: str, agent: str, amount: int = 1, name: str = "", reason: str = ""
    ) -> dict:
        await self._reserve_resource(resource, amount, agent, reason, name)
        await self._emit("resource.reserved", agent, {
            "resource": resource, "amount": amount, "name": name, "reason": reason,
        })
        return {"resource": resource, "amount": amount, "status": "reserved"}

    async def resource_release(self, resource: str, agent: str, name: str = "") -> dict:
        res_cfg = self.config.resources.get(resource)
        if not res_cfg:
            raise ValueError(f"Unknown resource: {resource}")

        if res_cfg.type == "named":
            lock_key = K_LOCK.format(resource, name)
            lock_data = await self.r.hgetall(lock_key)
            if not lock_data or lock_data.get("owner") != agent:
                raise ValueError(f"Lock {resource}:{name} not held by {agent}")
            await self.r.delete(lock_key)
        elif res_cfg.type == "pool":
            # Return item to pool
            pool_key = K_RESOURCE.format(resource)
            held = await self.r.hget(pool_key, f"held:{agent}")
            if held:
                await self.r.hdel(pool_key, f"held:{agent}")
                await self.r.sadd(f"{pool_key}:free", held)
        else:
            pool_key = K_RESOURCE.format(resource)
            held_str = await self.r.hget(pool_key, f"held:{agent}")
            if not held_str:
                raise ValueError(f"Resource {resource} not held by {agent}")
            held_amount = int(held_str)
            await self.r.hdel(pool_key, f"held:{agent}")
            await self.r.hincrbyfloat(pool_key, "used", -held_amount)

        await self._emit("resource.released", agent, {"resource": resource, "name": name})

        # Check if queued cards can now be promoted
        await self._promote_queued_for_resource(resource)

        return {"resource": resource, "status": "released"}

    async def resource_list(self) -> str:
        lines = []
        for res_name in self.config.resources:
            lines.append(await self._resource_summary(res_name))
        return "\n".join(lines)

    async def _reserve_resource(
        self, resource: str, amount: int, agent: str, reason: str = "", name: str = ""
    ) -> None:
        res_cfg = self.config.resources.get(resource)
        if not res_cfg:
            raise ValueError(f"Unknown resource: {resource}. Available: {list(self.config.resources.keys())}")

        if res_cfg.type == "named":
            lock_key = K_LOCK.format(resource, name)
            existing = await self.r.hgetall(lock_key)
            if existing:
                raise ValueError(
                    f"Lock {resource}:{name} held by {existing.get('owner')} "
                    f"(reason: {existing.get('reason')})"
                )
            await self.r.hset(lock_key, mapping={
                "owner": agent, "reason": reason, "ts": str(time.time()),
            })
        elif res_cfg.type == "pool":
            pool_key = K_RESOURCE.format(resource)
            # Initialize free set if needed
            free_count = await self.r.scard(f"{pool_key}:free")
            held_keys = [k async for k in self.r.scan_iter(match=f"{pool_key}:held:*")]
            if free_count == 0 and not held_keys:
                # First use: populate pool
                for item in res_cfg.items:
                    await self.r.sadd(f"{pool_key}:free", item)

            item = await self.r.spop(f"{pool_key}:free")
            if not item:
                raise ValueError(f"Resource pool {resource} exhausted. All items in use.")
            await self.r.hset(pool_key, f"held:{agent}", item)
        else:
            pool_key = K_RESOURCE.format(resource)
            used_str = await self.r.hget(pool_key, "used") or "0"
            used = float(used_str)
            if used + amount > res_cfg.capacity:
                raise ValueError(
                    f"Resource {resource}: {used}/{res_cfg.capacity} {res_cfg.unit} used. "
                    f"Cannot reserve {amount} more."
                )
            await self.r.hincrbyfloat(pool_key, "used", amount)
            await self.r.hset(pool_key, f"held:{agent}", str(amount))

    async def _check_resource_available(self, resource: str, amount: int) -> bool:
        res_cfg = self.config.resources.get(resource)
        if not res_cfg:
            return False
        if res_cfg.type == "named":
            return True  # Named locks are always "available" in a generic sense
        if res_cfg.type == "pool":
            pool_key = K_RESOURCE.format(resource)
            free_count = await self.r.scard(f"{pool_key}:free")
            # If pool not initialized yet, all items are free
            held_keys = [k async for k in self.r.scan_iter(match=f"{pool_key}:held:*")]
            if free_count == 0 and not held_keys:
                return len(res_cfg.items) >= amount
            return free_count >= amount

        pool_key = K_RESOURCE.format(resource)
        used_str = await self.r.hget(pool_key, "used") or "0"
        return float(used_str) + amount <= res_cfg.capacity

    async def _release_card_resources(self, card_id: str) -> None:
        card = await self._get_card(card_id)
        if not card:
            return
        requires = json.loads(card["requires"])
        agent = card["owner"]
        if not agent or not requires:
            return
        for res_name, amount in requires.items():
            try:
                await self.resource_release(res_name, agent)
            except ValueError as e:
                logger.warning("Failed to release %s for card %s: %s", res_name, card_id, e)

    async def _release_resource(self, resource: str, amount: int, agent: str) -> None:
        """Low-level release for rollback during failed claim."""
        try:
            await self.resource_release(resource, agent)
        except ValueError:
            pass

    async def _promote_queued_for_resource(self, resource: str) -> None:
        """After a resource is released, check if backlog cards can be promoted."""
        for board_name, board_cfg in self.config.boards.items():
            first_col = board_cfg.columns[0]
            card_ids = await self.r.zrange(K_COL.format(board_name, first_col), 0, -1)
            for cid in card_ids:
                card = await self._get_card(cid)
                if not card:
                    continue
                requires = json.loads(card["requires"])
                if resource in requires:
                    await self._try_promote(cid)

    async def _resource_summary(self, res_name: str) -> str:
        res_cfg = self.config.resources.get(res_name)
        if not res_cfg:
            return f"  {res_name}: [unknown]"

        if res_cfg.type == "named":
            # Count active locks
            pattern = K_LOCK.format(res_name, "*").replace("*", "*")
            locks = []
            async for key in self.r.scan_iter(match=f"kanban:lock:{res_name}:*"):
                data = await self.r.hgetall(key)
                lock_name = key.split(":")[-1]
                locks.append(f"{lock_name}: {data.get('owner', '?')}")
            if locks:
                return f"  {res_name}:  {len(locks)} active  [{', '.join(locks)}]"
            return f"  {res_name}:  0 active"

        if res_cfg.type == "pool":
            pool_key = K_RESOURCE.format(res_name)
            free = await self.r.smembers(f"{pool_key}:free")
            holders = {}
            async for key in self.r.scan_iter(match=f"{pool_key}:held:*"):
                agent = key.split(":")[-1]
                item = await self.r.hget(pool_key, f"held:{agent}")
                holders[agent] = item
            # If pool never initialized
            if not free and not holders:
                free = set(res_cfg.items)
            used_count = len(holders)
            total = len(res_cfg.items)
            used_items = [str(v) for v in holders.values()]
            free_items = list(free)
            return (
                f"  {res_name}:  {used_count}/{total} used"
                f"  [{', '.join(used_items)}]"
                f"  free: [{', '.join(free_items)}]"
            )

        pool_key = K_RESOURCE.format(res_name)
        used_str = await self.r.hget(pool_key, "used") or "0"
        used = float(used_str)
        # Collect holders
        holders = {}
        async for key in self.r.scan_iter(match=f"{pool_key}:held:*"):
            # key format: kanban:resource:{name}:held:{agent} — but we used hset inside the hash
            pass
        # Simpler: list held keys from the hash
        all_fields = await self.r.hgetall(pool_key)
        held_parts = []
        for k, v in all_fields.items():
            if k.startswith("held:"):
                agent = k[5:]
                held_parts.append(f"{agent}: {v}{res_cfg.unit}")
        held_str = f"  [{', '.join(held_parts)}]" if held_parts else ""
        return f"  {res_name}:  {int(used)}/{res_cfg.capacity} {res_cfg.unit}{held_str}"

    # ─── Signals ──────────────────────────────────────

    async def andon(self, agent: str, reason: str) -> dict:
        blocked_cards = []
        for board_name, board_cfg in self.config.boards.items():
            if len(board_cfg.columns) < 3:
                continue
            active_col = board_cfg.columns[2]
            card_ids = await self.r.zrange(K_COL.format(board_name, active_col), 0, -1)
            for cid in card_ids:
                await self._move_card(cid, board_name, active_col, "blocked")
                await self.r.hset(K_CARD.format(cid), "column", "blocked")
                blocked_cards.append(cid)

        await self._emit("andon.triggered", agent, {
            "reason": reason,
            "blocked_cards": blocked_cards,
        })

        return {"status": "andon", "reason": reason, "blocked_cards": blocked_cards}

    async def signal_emit(self, event: str, agent: str, data: str = "") -> dict:
        event_id = await self._emit(event, agent, {"custom_data": data})
        return {"event_id": event_id, "event": event}

    async def watch(self, filter_pattern: str = "*", timeout: int = 30) -> dict:
        last_id = "$"  # Only new events
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining_ms = max(int((deadline - time.time()) * 1000), 100)
            result = await self.r.xread(
                {K_EVENTS: last_id}, block=min(remaining_ms, 5000), count=10
            )
            if not result:
                continue
            for stream_name, entries in result:
                for entry_id, entry_data in entries:
                    last_id = entry_id
                    event_type = entry_data.get("type", "")
                    if self._event_matches(filter_pattern, event_type):
                        return {
                            "event_id": entry_id,
                            "type": event_type,
                            "agent": entry_data.get("agent", ""),
                            "data": entry_data.get("data", "{}"),
                            "ts": entry_data.get("ts", ""),
                        }

        return {"status": "timeout", "message": f"No events matched '{filter_pattern}' within {timeout}s"}

    # ─── Presence ─────────────────────────────────────

    async def presence_update(self, agent: str, status: str, focus: str = "") -> dict:
        key = K_PRESENCE.format(agent)
        await self.r.hset(key, mapping={
            "status": status,
            "focus": focus,
            "updated_at": str(time.time()),
        })
        await self.r.expire(key, PRESENCE_TTL)
        return {"agent": agent, "status": status}

    async def presence_who(self) -> str:
        lines = ["# Active Agents", ""]
        for agent_name in self.config.agents:
            key = K_PRESENCE.format(agent_name)
            data = await self.r.hgetall(key)
            if data:
                elapsed = int((time.time() - float(data.get("updated_at", 0))) / 60)
                focus = data.get("focus", "")
                focus_str = f" — {focus}" if focus else ""
                lines.append(f"- **{agent_name}**: {data.get('status', '?')}{focus_str} ({elapsed}m ago)")
            else:
                lines.append(f"- **{agent_name}**: offline")
        return "\n".join(lines)

    # ─── Internal helpers ─────────────────────────────

    async def _get_card(self, card_id: str) -> dict | None:
        data = await self.r.hgetall(K_CARD.format(card_id))
        return data if data else None

    async def _move_card(self, card_id: str, board: str, from_col: str, to_col: str) -> None:
        await self.r.zrem(K_COL.format(board, from_col), card_id)
        await self.r.zadd(K_COL.format(board, to_col), {card_id: time.time()})
        await self.r.hset(K_CARD.format(card_id), mapping={
            "column": to_col,
            "updated_at": str(time.time()),
        })

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds / 60)}m"
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        return f"{hours}h{mins}m"

    @staticmethod
    def _parse_duration(s: str) -> float:
        s = s.strip()
        if s.endswith("s"):
            return float(s[:-1])
        if "h" in s and "m" in s:
            parts = s.replace("m", "").split("h")
            return float(parts[0]) * 3600 + float(parts[1]) * 60
        if s.endswith("m"):
            return float(s[:-1]) * 60
        if s.endswith("h"):
            return float(s[:-1]) * 3600
        return 0.0
