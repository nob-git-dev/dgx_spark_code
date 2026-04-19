"""ライブ操作ルーター (Phase 3): logs, check-endpoint, service start/stop."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lib.config import SUBPROCESS_TIMEOUT
from lib.services import get_service_def, list_service_names
from lib.subprocess_utils import collect_with_fallback, run
from lib.systemd import is_active, start_unit, stop_unit

logger = logging.getLogger("gx10-mcp")

router = APIRouter()


class TextResponse(BaseModel):
    content: str


class MessageResponse(BaseModel):
    message: str


class ServiceRequest(BaseModel):
    name: str


async def _check_memory_available(required_gb: int) -> tuple[bool, str]:
    stdout, _, rc = await run(["free", "-b"], timeout=5)
    if rc != 0:
        return True, ""
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


@router.get("/logs", response_model=TextResponse)
async def get_logs(service: str, lines: int = 30) -> TextResponse:
    """コンテナログを取得する（?service=xxx&lines=30）."""
    svc_def = get_service_def(service)
    container = svc_def.get("container_name", service) if svc_def else service
    content = await collect_with_fallback(
        "docker-logs",
        ["docker", "logs", container, "--tail", str(lines)],
    )
    return TextResponse(content=content)


@router.get("/check-endpoint", response_model=TextResponse)
async def check_endpoint(url: str) -> TextResponse:
    """API 疎通確認（?url=xxx）."""
    stdout, stderr, rc = await run(
        ["curl", "-sf", "-o", "/dev/null", "-w",
         "HTTP %{http_code} (%{time_total}s)", url],
        timeout=10,
    )
    if rc != 0:
        return TextResponse(content=f"FAILED: {url} — {stderr or 'connection refused'}")
    return TextResponse(content=f"OK: {url} — {stdout}")


@router.post("/service/start", response_model=MessageResponse)
async def start_service(req: ServiceRequest) -> MessageResponse:
    """サービスを起動する（ガードレール付き）."""
    svc_def = get_service_def(req.name)
    if not svc_def:
        available = list_service_names()
        raise HTTPException(
            status_code=404,
            detail=f"Unknown service '{req.name}'. Available: {', '.join(available)}",
        )

    display = svc_def.get("display_name", req.name)

    # Guardrails
    mem_ok, mem_msg = await _check_memory_available(svc_def.get("memory_required_gb", 0))
    if not mem_ok:
        return MessageResponse(message=f"Guardrail: {mem_msg}")

    conflict_ok, conflict_msg = await _check_conflicts(svc_def)
    if not conflict_ok:
        return MessageResponse(message=f"Guardrail: {conflict_msg}")

    svc_type = svc_def.get("type", "docker-compose")

    if svc_type == "systemd":
        unit = svc_def["systemd_unit"]
        scope = svc_def.get("systemd_scope", "user")
        ok, msg = await start_unit(unit, scope)
        return MessageResponse(message=msg)

    compose_file = svc_def.get("compose_file", "")
    compose_service = svc_def.get("compose_service", "")
    if not compose_file:
        return MessageResponse(message=f"No compose_file defined for {req.name}")

    compose_file = compose_file.replace("~", str(__import__("pathlib").Path.home()))
    logger.info("Starting %s via docker compose", display)
    stdout, stderr, rc = await run(
        ["docker", "compose", "-f", compose_file, "up", compose_service, "-d"],
        timeout=SUBPROCESS_TIMEOUT,
    )
    if rc != 0:
        return MessageResponse(message=f"Failed to start {display}: {stderr}")
    return MessageResponse(message=f"Started {display}. {stdout}")


@router.post("/service/stop", response_model=MessageResponse)
async def stop_service(req: ServiceRequest) -> MessageResponse:
    """サービスを停止する（graceful stop）."""
    svc_def = get_service_def(req.name)
    if not svc_def:
        available = list_service_names()
        raise HTTPException(
            status_code=404,
            detail=f"Unknown service '{req.name}'. Available: {', '.join(available)}",
        )

    display = svc_def.get("display_name", req.name)
    svc_type = svc_def.get("type", "docker-compose")

    if svc_type == "systemd":
        unit = svc_def["systemd_unit"]
        scope = svc_def.get("systemd_scope", "user")
        if not await is_active(unit, scope):
            return MessageResponse(message=f"{display} is already stopped.")
        ok, msg = await stop_unit(unit, scope)
        return MessageResponse(message=msg)

    container = svc_def.get("container_name", "")
    if container:
        stdout, _, _ = await run(
            ["docker", "ps", "--filter", f"name={container}", "--format", "{{.Names}}"],
            timeout=10,
        )
        if container not in stdout:
            return MessageResponse(message=f"{display} is already stopped.")

    compose_file = svc_def.get("compose_file", "")
    compose_service = svc_def.get("compose_service", "")
    if not compose_file:
        return MessageResponse(message=f"No compose_file defined for {req.name}")

    compose_file = compose_file.replace("~", str(__import__("pathlib").Path.home()))
    logger.info("Stopping %s via docker compose", display)
    stdout, stderr, rc = await run(
        ["docker", "compose", "-f", compose_file, "stop", compose_service],
        timeout=SUBPROCESS_TIMEOUT,
    )
    if rc != 0:
        return MessageResponse(message=f"Failed to stop {display}: {stderr}")
    return MessageResponse(message=f"Stopped {display}.")
