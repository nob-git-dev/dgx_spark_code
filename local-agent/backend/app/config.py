"""Application settings (pydantic_settings)"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "gpt-oss-120b-128k"
    embedding_model: str = "nemotron-3-nano"
    max_tokens: int = 4096
    temperature: float = 0.7

    # Agent
    max_iterations: int = 10
    max_tool_output_chars: int = 8000

    # ChromaDB
    chroma_host: str = "chroma"
    chroma_port: int = 8000

    # Sandbox
    sandbox_image: str = "local-agent-sandbox"
    sandbox_timeout: int = 30
    sandbox_memory_limit: str = "256m"
    sandbox_network_disabled: bool = True
    workspace_host_path: str = ""  # Set via WORKSPACE_HOST_PATH env var

    # Paths
    workspace_dir: str = "/app/workspace"
    uploads_dir: str = "/app/uploads"

    # Server
    agent_port: int = 8090
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
