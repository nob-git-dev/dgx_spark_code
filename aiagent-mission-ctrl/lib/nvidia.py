"""nvidia-smi output parsing.

Note: GB10 (DGX Spark) uses unified memory, so --query-gpu=memory.used
returns [N/A]. We parse the full nvidia-smi table output instead.
"""

from .subprocess_utils import collect_with_fallback, run


async def get_gpu_summary() -> str:
    """One-line GPU summary for get_environment."""
    stdout, _, rc = await run(
        ["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu",
         "--format=csv,noheader"],
        timeout=10,
    )
    if rc != 0:
        return "[unavailable: nvidia-smi failed]"
    # Also get system memory (unified memory = GPU memory on GB10)
    mem_stdout, _, mem_rc = await run(["free", "-h", "--si"], timeout=5)
    mem_line = ""
    if mem_rc == 0:
        for line in mem_stdout.split("\n"):
            if line.startswith("Mem:"):
                parts = line.split()
                if len(parts) >= 3:
                    mem_line = f", System Memory: {parts[2]} used / {parts[1]} total"
    return f"GPU: {stdout.strip()}{mem_line}"


async def get_gpu_detail() -> str:
    """Detailed GPU status for get_gpu_status tool."""
    # Full nvidia-smi table (most informative for unified memory)
    table = await collect_with_fallback(
        "nvidia-smi", ["nvidia-smi"], timeout=10
    )

    # System memory (= unified memory on GB10)
    memory = await collect_with_fallback(
        "free", ["free", "-h", "--si"], timeout=5
    )

    lines = [
        "## GPU Status (GB10 — Unified Memory)",
        "",
        "```",
        table,
        "```",
        "",
        "## System Memory (= GPU Memory on unified architecture)",
        "```",
        memory,
        "```",
    ]
    return "\n".join(lines)
