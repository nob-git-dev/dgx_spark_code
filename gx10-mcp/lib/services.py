"""services.yaml loading and guardrail logic."""

import logging
from pathlib import Path

import yaml

from .config import SERVICES_YAML

logger = logging.getLogger("gx10-mcp")


def load_mcp_services() -> dict:
    """Load mcp.services from services.yaml. Returns empty dict on failure."""
    try:
        data = yaml.safe_load(SERVICES_YAML.read_text())
        return data.get("mcp", {}).get("services", {})
    except Exception as e:
        logger.error("Failed to load services.yaml: %s", e)
        return {}


def get_service_def(name: str) -> dict | None:
    """Get a single service definition by name."""
    services = load_mcp_services()
    return services.get(name)


def list_service_names() -> list[str]:
    """List all available service names."""
    return list(load_mcp_services().keys())
