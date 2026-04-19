"""Subprocess execution with timeout and graceful error handling."""

import asyncio
import logging
import subprocess

from .config import SUBPROCESS_TIMEOUT

logger = logging.getLogger("gx10-mcp")


async def run(
    cmd: list[str],
    *,
    timeout: int = SUBPROCESS_TIMEOUT,
    cwd: str | None = None,
) -> tuple[str, str, int]:
    """Run a subprocess and return (stdout, stderr, returncode).

    Never raises on non-zero exit — callers decide how to handle errors.
    On timeout, returns a descriptive error in stderr.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return (
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
            proc.returncode or 0,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return "", f"Timeout after {timeout}s: {' '.join(cmd)}", -1
    except FileNotFoundError:
        return "", f"Command not found: {cmd[0]}", -1


async def collect_with_fallback(label: str, cmd: list[str], **kwargs) -> str:
    """Run a command and return output, or '[unavailable: reason]' on failure."""
    stdout, stderr, rc = await run(cmd, **kwargs)
    if rc != 0:
        reason = stderr or f"exit code {rc}"
        logger.warning("[%s] %s", label, reason)
        return f"[unavailable: {reason}]"
    return stdout
