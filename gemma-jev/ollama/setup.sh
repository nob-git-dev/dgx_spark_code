#!/usr/bin/env bash
# Start Ollama in Docker on the GX10 and pull Gemma 4.
# Usage: bash ollama/setup.sh [model-tag]   (default: gemma4:26b)
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${1:-gemma4:26b}"

echo "== Checking Docker GPU access =="
docker run --rm --gpus all ubuntu:24.04 nvidia-smi -L \
  || { echo "Docker cannot see the GPU: install/configure nvidia-container-toolkit"; exit 1; }

docker compose up -d

echo "== Waiting for Ollama =="
until docker exec gemma4-ollama ollama list >/dev/null 2>&1; do sleep 1; done
docker exec gemma4-ollama ollama --version

echo "== Pulling $MODEL =="
docker exec gemma4-ollama ollama pull "$MODEL"

echo "== Smoke test =="
docker exec gemma4-ollama ollama run "$MODEL" "日本語で一文だけ自己紹介してください。"
docker exec gemma4-ollama ollama ps   # PROCESSOR column should read 100% GPU
