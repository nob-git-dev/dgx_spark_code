"""Path definitions and constants."""

import os
from pathlib import Path

HOME = Path.home()
DOCS_DIR = HOME / "projects" / "docs"
PROJECTS_DIR = HOME / "projects"
SERVICES_YAML = DOCS_DIR / "services.yaml"

MCP_PORT = int(os.environ.get("MCP_PORT", "9100"))
SUBPROCESS_TIMEOUT = 120
