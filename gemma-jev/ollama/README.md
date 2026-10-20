# Gemma 4 (Docker) on GX10

Runs Ollama + Gemma 4 inside Docker. Nothing is installed on the host; models are stored in the `ollama-models` volume.

```bash
bash ollama/setup.sh              # gemma4:26b (recommended)
bash ollama/setup.sh gemma4:e4b   # lighter model
```

API: `http://localhost:11434` (bound to localhost only)

```bash
docker exec -it gemma4-ollama ollama run gemma4:26b   # chat
docker compose -f ollama/compose.yaml down     # stop
docker compose -f ollama/compose.yaml down -v  # stop and delete models
```

Pin the Ollama version with `OLLAMA_VERSION=x.y.z docker compose ... up -d` (Gemma 4 needs >= 0.20.0).

To use this Gemma 4 as a Jev-style decision API (`POST /v1/systemone`), see the [top-level README](../README.md).
