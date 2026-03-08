"""Sandboxed command execution via Docker containers"""

import asyncio
import logging

import docker

from app.config import get_settings
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_docker_client: docker.DockerClient | None = None


def _get_docker() -> docker.DockerClient:
    """Get or create Docker client."""
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


async def _execute_command(args: dict) -> str:
    command = args["command"]
    settings = get_settings()

    def _run():
        client = _get_docker()
        try:
            result = client.containers.run(
                image=settings.sandbox_image,
                command=["bash", "-c", command],
                volumes={
                    settings.workspace_host_path: {
                        "bind": "/workspace",
                        "mode": "rw",
                    }
                },
                mem_limit=settings.sandbox_memory_limit,
                network_disabled=settings.sandbox_network_disabled,
                remove=True,
                stderr=True,
                stdout=True,
                detach=False,
                # timeout in docker SDK = seconds
            )
            output = result.decode("utf-8", errors="replace")
            if len(output) > 10000:
                output = output[:10000] + "\n... (truncated)"
            return output
        except docker.errors.ContainerError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
            return f"Command exited with code {e.exit_status}:\n{stderr}"
        except Exception as e:
            return f"Sandbox error: {e}"

    return await asyncio.to_thread(_run)


def register(registry: ToolRegistry):
    """Register sandboxed command execution tool."""
    registry.register(
        name="execute_command",
        description=(
            "Execute a shell command in a sandboxed Docker environment. "
            "The workspace directory is available at /workspace. "
            "Network access is disabled. Timeout: 30 seconds. "
            "Python 3.12, curl, jq, and git are available."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
            },
            "required": ["command"],
        },
        handler=_execute_command,
    )
