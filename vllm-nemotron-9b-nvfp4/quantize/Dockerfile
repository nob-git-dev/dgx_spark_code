# NVFP4 quantization environment for Nemotron-9B on DGX Spark (GB10/SM121)
#
# Usage:
#   docker compose -f docker-compose.quantize.yml run --rm quantize
#
FROM nvcr.io/nvidia/pytorch:26.01-py3

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1

ENV TORCH_CUDA_ARCH_LIST="12.1a"
ENV CUDA_HOME=/usr/local/cuda

# Mamba model dependencies (requires CUDA compilation for SM121/ARM64)
# Install from GitHub source to ensure CUDA kernels compile for aarch64
RUN pip install --no-build-isolation --no-cache-dir \
    "causal-conv1d @ git+https://github.com/Dao-AILab/causal-conv1d.git" \
    2>&1 | grep -E "(error|Error|nvcc|Building|Successfully|WARNING:)" | tail -20

# mamba-ssm: MAMBA_FORCE_BUILD=TRUE forces CUDA extension compilation
RUN MAMBA_FORCE_BUILD=TRUE \
    pip install --no-build-isolation --no-cache-dir \
    "mamba-ssm @ git+https://github.com/state-spaces/mamba.git" \
    2>&1 | tail -10

# Verify CUDA extensions were compiled for ARM64 (aarch64)
RUN python -c "import selective_scan_cuda; print('selective_scan_cuda OK')" && \
    python -c "import causal_conv1d_cuda; print('causal_conv1d_cuda OK')"

# ModelOpt + dependencies
RUN pip install --quiet \
    "nvidia-modelopt[hf]>=0.34" \
    "transformers>=4.45" \
    "accelerate" \
    "datasets" \
    "sentencepiece"

WORKDIR /workspace
COPY quantize_nemotron.py /workspace/quantize_nemotron.py

ENTRYPOINT ["python", "/workspace/quantize_nemotron.py"]
