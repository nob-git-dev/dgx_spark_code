#!/usr/bin/env bash
# ---------------------------------------------------------------
# Download txn545/Qwen3.5-122B-A10B-NVFP4 model weights
# Uses Docker to avoid installing pip packages on host
# ---------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MODEL_DIR="${PROJECT_DIR}/models/txn545_Qwen3.5-122B-A10B-NVFP4"
MODEL_REPO="txn545/Qwen3.5-122B-A10B-NVFP4"

# Read HF_TOKEN from .env if not set in environment
if [ -z "${HF_TOKEN:-}" ]; then
    if [ -f "${PROJECT_DIR}/.env" ]; then
        HF_TOKEN=$(grep '^HF_TOKEN=' "${PROJECT_DIR}/.env" | cut -d'=' -f2)
    fi
fi

if [ -z "${HF_TOKEN:-}" ]; then
    echo "ERROR: HF_TOKEN not set. Set it via environment or in .env file."
    exit 1
fi

echo "========================================"
echo " Qwen3.5-122B-A10B-NVFP4 Model Download"
echo "========================================"
echo "Repository: ${MODEL_REPO}"
echo "Destination: ${MODEL_DIR}"
echo "Estimated size: ~78GB"
echo ""

# Check if model already exists
if [ -d "${MODEL_DIR}" ] && [ -f "${MODEL_DIR}/config.json" ]; then
    echo "Model directory already exists with config.json."
    echo "To re-download, remove the directory first:"
    echo "  rm -rf ${MODEL_DIR}"
    exit 0
fi

# Check disk space
AVAIL_GB=$(df --output=avail -BG "${PROJECT_DIR}" | tail -1 | tr -d ' G')
echo "Available disk space: ${AVAIL_GB}GB"
if [ "${AVAIL_GB}" -lt 100 ]; then
    echo "WARNING: Less than 100GB available. Download requires ~78GB + overhead."
    read -p "Continue? (y/N): " confirm
    [ "${confirm}" = "y" ] || exit 1
fi

# Create model directory
mkdir -p "${MODEL_DIR}"

echo ""
echo "Starting download via Docker container..."
echo "(huggingface-cli supports resume if interrupted)"
echo ""

docker run --rm \
    -v "${PROJECT_DIR}/models:/models" \
    -e HF_TOKEN="${HF_TOKEN}" \
    -e HF_HUB_ENABLE_HF_TRANSFER=1 \
    nvcr.io/nvidia/pytorch:26.01-py3 \
    python3 -c "
import subprocess, sys
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'huggingface_hub', 'hf_transfer'])
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='${MODEL_REPO}',
    local_dir='/models/txn545_Qwen3.5-122B-A10B-NVFP4',
    local_dir_use_symlinks=False,
)
print('Download complete.')
"

echo ""
echo "========================================"
echo " Download Complete"
echo "========================================"
echo ""
du -sh "${MODEL_DIR}"
echo ""
echo "To build the Docker image:"
echo "  cd ${PROJECT_DIR}"
echo "  docker compose -f docker-compose.qwen122b.yml --env-file .env.qwen122b build"
