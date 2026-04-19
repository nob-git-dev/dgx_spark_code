"""systemd service operations."""

from .subprocess_utils import run


async def start_unit(unit: str, scope: str = "user") -> tuple[bool, str]:
    """Start a systemd unit. Returns (success, message)."""
    _, stderr, rc = await run(
        ["systemctl", f"--{scope}", "start", unit]
    )
    if rc != 0:
        return False, f"Failed to start {unit}: {stderr}"
    return True, f"Started {unit}"


async def stop_unit(unit: str, scope: str = "user") -> tuple[bool, str]:
    """Stop a systemd unit. Returns (success, message)."""
    _, stderr, rc = await run(
        ["systemctl", f"--{scope}", "stop", unit]
    )
    if rc != 0:
        return False, f"Failed to stop {unit}: {stderr}"
    return True, f"Stopped {unit}"


async def is_active(unit: str, scope: str = "user") -> bool:
    """Check if a systemd unit is active."""
    stdout, _, rc = await run(
        ["systemctl", f"--{scope}", "is-active", unit], timeout=5
    )
    return stdout.strip() == "active"
