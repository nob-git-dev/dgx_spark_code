FROM python:3.12-slim

# uv only (no pip)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (cache layer)
COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

# Application code
COPY . .

# Directories
RUN mkdir -p /app/workspace /app/uploads

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:8090/health || exit 1

CMD [".venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--log-level", "info"]
