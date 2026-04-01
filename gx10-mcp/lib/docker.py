"""Docker operations."""

from .subprocess_utils import collect_with_fallback


async def get_containers() -> str:
    """Get running containers list."""
    return await collect_with_fallback(
        "docker-ps",
        ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
    )


async def get_system_resources() -> str:
    """Get memory and disk usage."""
    memory = await collect_with_fallback("free", ["free", "-h"], timeout=5)
    disk = await collect_with_fallback("df", ["df", "-h", "/"], timeout=5)

    lines = ["## Memory", "```", memory, "```", "", "## Disk", "```", disk, "```"]

    # Disk space warning
    if not disk.startswith("[unavailable"):
        for line in disk.split("\n"):
            parts = line.split()
            if len(parts) >= 4 and parts[3].endswith("G"):
                try:
                    avail_gb = float(parts[3].rstrip("G"))
                    if avail_gb < 10:
                        lines.append(
                            f"\n**WARNING:** Disk space low ({avail_gb}GB available)"
                        )
                except ValueError:
                    pass

    return "\n".join(lines)
