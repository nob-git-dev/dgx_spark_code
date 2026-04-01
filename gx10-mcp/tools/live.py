"""Live operation tools (Phase 3): get_server_logs, check_endpoint, start_service, stop_service."""

import logging

from fastmcp import FastMCP

from lib.config import SUBPROCESS_TIMEOUT
from lib.services import get_service_def, list_service_names
from lib.subprocess_utils import collect_with_fallback, run
from lib.systemd import is_active, start_unit, stop_unit

logger = logging.getLogger("gx10-mcp")


async def _check_memory_available(required_gb: int) -> tuple[bool, str]:
    """Check if enough memory is available."""
    stdout, _, rc = await run(["free", "-b"], timeout=5)
    if rc != 0:
        return True, ""  # Can't check, proceed anyway
    for line in stdout.split("\n"):
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 7:
                available_gb = int(parts[6]) / (1024**3)
                if available_gb < required_gb:
                    return False, (
                        f"Memory insufficient: {available_gb:.0f}GB available "
                        f"< {required_gb}GB required"
                    )
    return True, ""


async def _check_conflicts(svc_def: dict) -> tuple[bool, str]:
    """Check if conflicting services are running."""
    conflicts = svc_def.get("conflicts_with", [])
    for conflict_name in conflicts:
        conflict_def = get_service_def(conflict_name)
        if not conflict_def:
            continue
        container = conflict_def.get("container_name", "")
        if container:
            stdout, _, _ = await run(
                ["docker", "ps", "--filter", f"name={container}", "--format", "{{.Names}}"],
                timeout=10,
            )
            if container in stdout:
                return False, (
                    f"Conflict: {conflict_def.get('display_name', conflict_name)} "
                    f"is running. Stop it first with stop_service('{conflict_name}')."
                )
    return True, ""


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        description=(
            "Get recent logs from a Docker container or service. "
            "Use for debugging startup failures, errors, or performance issues."
        )
    )
    async def get_server_logs(service: str, lines: int = 30) -> str:
        svc_def = get_service_def(service)
        container = svc_def.get("container_name", service) if svc_def else service
        return await collect_with_fallback(
            "docker-logs",
            ["docker", "logs", container, "--tail", str(lines)],
        )

    @mcp.tool(
        description=(
            "Test if an API endpoint is reachable and responding. "
            "Use after starting a service or when connectivity issues are suspected."
        )
    )
    async def check_endpoint(url: str) -> str:
        stdout, stderr, rc = await run(
            ["curl", "-sf", "-o", "/dev/null", "-w",
             "HTTP %{http_code} (%{time_total}s)", url],
            timeout=10,
        )
        if rc != 0:
            return f"FAILED: {url} — {stderr or 'connection refused'}"
        return f"OK: {url} — {stdout}"

    @mcp.tool(
        description=(
            "Start a service (Docker Compose or systemd). Has built-in guardrails: "
            "checks memory, conflicts, and other agents' activity before proceeding."
        )
    )
    async def start_service(name: str) -> str:
        svc_def = get_service_def(name)
        if not svc_def:
            available = list_service_names()
            return f"Unknown service '{name}'. Available: {', '.join(available)}"

        display = svc_def.get("display_name", name)

        # Guardrails
        mem_ok, mem_msg = await _check_memory_available(
            svc_def.get("memory_required_gb", 0)
        )
        if not mem_ok:
            return f"⚠ Guardrail: {mem_msg}"

        conflict_ok, conflict_msg = await _check_conflicts(svc_def)
        if not conflict_ok:
            return f"⚠ Guardrail: {conflict_msg}"

        svc_type = svc_def.get("type", "docker-compose")

        if svc_type == "systemd":
            unit = svc_def["systemd_unit"]
            scope = svc_def.get("systemd_scope", "user")
            ok, msg = await start_unit(unit, scope)
            return msg

        # docker-compose
        compose_file = svc_def.get("compose_file", "")
        compose_service = svc_def.get("compose_service", "")
        if not compose_file:
            return f"No compose_file defined for {name}"

        compose_file = compose_file.replace("~", str(__import__("pathlib").Path.home()))

        logger.info("Starting %s via docker compose", display)
        stdout, stderr, rc = await run(
            ["docker", "compose", "-f", compose_file, "up", compose_service, "-d"],
            timeout=SUBPROCESS_TIMEOUT,
        )
        if rc != 0:
            return f"Failed to start {display}: {stderr}"
        return f"Started {display}. {stdout}"

    @mcp.tool(
        description=(
            "Stop a running service (graceful stop, not destroy). "
            "Checks if the service is actually running and warns about "
            "other agents' activity."
        )
    )
    async def stop_service(name: str) -> str:
        svc_def = get_service_def(name)
        if not svc_def:
            available = list_service_names()
            return f"Unknown service '{name}'. Available: {', '.join(available)}"

        display = svc_def.get("display_name", name)
        svc_type = svc_def.get("type", "docker-compose")

        if svc_type == "systemd":
            unit = svc_def["systemd_unit"]
            scope = svc_def.get("systemd_scope", "user")
            if not await is_active(unit, scope):
                return f"{display} is already stopped."
            ok, msg = await stop_unit(unit, scope)
            return msg

        # docker-compose: check if running
        container = svc_def.get("container_name", "")
        if container:
            stdout, _, _ = await run(
                ["docker", "ps", "--filter", f"name={container}", "--format", "{{.Names}}"],
                timeout=10,
            )
            if container not in stdout:
                return f"{display} is already stopped."

        compose_file = svc_def.get("compose_file", "")
        compose_service = svc_def.get("compose_service", "")
        if not compose_file:
            return f"No compose_file defined for {name}"

        compose_file = compose_file.replace("~", str(__import__("pathlib").Path.home()))

        logger.info("Stopping %s via docker compose", display)
        stdout, stderr, rc = await run(
            ["docker", "compose", "-f", compose_file, "stop", compose_service],
            timeout=SUBPROCESS_TIMEOUT,
        )
        if rc != 0:
            return f"Failed to stop {display}: {stderr}"
        return f"Stopped {display}."
