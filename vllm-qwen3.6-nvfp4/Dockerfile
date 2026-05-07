# syntax=docker/dockerfile:1.6
#
# vLLM + Qwen3.6-35B-A3B-NVFP4 on NVIDIA DGX Spark (GB10, SM121)
#
# Self-contained multi-stage build:
#   1. flashinfer-builder : Compile FlashInfer from upstream for SM121
#   2. runner             : vLLM 0.20.x nightly + cu130 / aarch64
#
# Usage:
#   docker buildx build -t vllm-node --load .
#
# Build args (override with --build-arg):
#   VLLM_VERSION        - vLLM nightly wheel specifier
#   FLASHINFER_REF      - FlashInfer git ref (branch/tag/SHA)
#   CUTLASS_REF         - CUTLASS git ref
#   TRANSFORMERS_VER    - transformers version
#   BUILD_JOBS          - parallel build jobs (default: 16)
# =========================================================================

ARG BUILD_JOBS=16

# =========================================================================
# STAGE 1: FlashInfer Builder (SM121 / GB10 Blackwell 専用)
# =========================================================================
FROM nvcr.io/nvidia/pytorch:26.04-py3 AS flashinfer-builder

ARG BUILD_JOBS
ENV MAX_JOBS=${BUILD_JOBS}
ENV CMAKE_BUILD_PARALLEL_LEVEL=${BUILD_JOBS}
ENV NINJAFLAGS="-j${BUILD_JOBS}"
ENV MAKEFLAGS="-j${BUILD_JOBS}"

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV UV_CACHE_DIR=/root/.cache/uv
ENV UV_SYSTEM_PYTHON=1
ENV UV_BREAK_SYSTEM_PACKAGES=1
ENV UV_LINK_MODE=copy

# SM121 = NVIDIA Blackwell (GB10 / DGX Spark)
ARG TORCH_CUDA_ARCH_LIST="12.1a"
ARG FLASHINFER_CUDA_ARCH_LIST="12.1a"
ENV TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST}
ENV FLASHINFER_CUDA_ARCH_LIST=${FLASHINFER_CUDA_ARCH_LIST}

# Build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl vim ninja-build git ccache && \
    rm -rf /var/lib/apt/lists/* && \
    pip install uv && pip uninstall -y flash-attn

ENV PATH=/usr/lib/ccache:$PATH
ENV CCACHE_DIR=/root/.ccache
ENV CCACHE_MAXSIZE=50G
ENV CCACHE_COMPRESS=1
ENV CMAKE_CXX_COMPILER_LAUNCHER=ccache
ENV CMAKE_CUDA_COMPILER_LAUNCHER=ccache

# FlashInfer build dependencies
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv pip install nvidia-nvshmem-cu13 "apache-tvm-ffi<0.2"

# ---- Clone FlashInfer (upstream) ----
ARG FLASHINFER_REF=main
ARG FLASHINFER_REPO=https://github.com/flashinfer-ai/flashinfer.git

RUN --mount=type=cache,id=git-flashinfer,target=/git-cache/flashinfer \
    if [ -d /git-cache/flashinfer/.git ]; then \
        cp -a /git-cache/flashinfer /workspace/flashinfer && \
        cd /workspace/flashinfer && \
        git fetch origin && git fetch origin --tags; \
    else \
        git clone ${FLASHINFER_REPO} /workspace/flashinfer && \
        cp -a /workspace/flashinfer /git-cache/flashinfer; \
    fi && \
    cd /workspace/flashinfer && \
    (git checkout --detach origin/${FLASHINFER_REF} 2>/dev/null || git checkout ${FLASHINFER_REF})

RUN cd /workspace/flashinfer && \
    git submodule update --init 3rdparty/spdlog

# ---- Clone CUTLASS (upstream) ----
ARG CUTLASS_REF=main
ARG CUTLASS_REPO=https://github.com/NVIDIA/cutlass.git

RUN --mount=type=cache,id=git-cutlass,target=/git-cache/cutlass \
    cd /workspace/flashinfer && \
    rm -rf 3rdparty/cutlass && \
    if [ -d /git-cache/cutlass/.git ]; then \
        cp -a /git-cache/cutlass 3rdparty/cutlass && \
        cd 3rdparty/cutlass && \
        git fetch origin && git fetch origin --tags; \
    else \
        git clone ${CUTLASS_REPO} 3rdparty/cutlass && \
        cp -a 3rdparty/cutlass/. /git-cache/cutlass/; \
    fi && \
    cd /workspace/flashinfer/3rdparty/cutlass && \
    (git checkout --detach origin/${CUTLASS_REF} 2>/dev/null || git checkout ${CUTLASS_REF})

# ---- Optional: FlashInfer cubin cache patch ----
COPY patches/flashinfer_cache.patch /workspace/flashinfer/
RUN cd /workspace/flashinfer && \
    (patch -p1 --dry-run < flashinfer_cache.patch &>/dev/null && \
     patch -p1 < flashinfer_cache.patch || \
     echo "FlashInfer cache patch not applicable, skipping.")

# ---- Build FlashInfer wheels ----
WORKDIR /workspace/flashinfer

RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    --mount=type=cache,id=ccache,target=/root/.ccache \
    sed -i -e 's/license = "Apache-2.0"/license = { text = "Apache-2.0" }/' \
           -e '/license-files/d' pyproject.toml && \
    uv build --no-build-isolation --wheel . --out-dir=/workspace/wheels -v

RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    --mount=type=cache,id=ccache,target=/root/.ccache \
    cd flashinfer-cubin && \
    uv build --no-build-isolation --wheel . --out-dir=/workspace/wheels -v

RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    --mount=type=cache,id=ccache,target=/root/.ccache \
    cd flashinfer-jit-cache && \
    uv build --no-build-isolation --wheel . --out-dir=/workspace/wheels -v


# =========================================================================
# STAGE 2: Runner
# =========================================================================
FROM nvcr.io/nvidia/pytorch:26.04-py3 AS runner

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV UV_CACHE_DIR=/root/.cache/uv
ENV UV_SYSTEM_PYTHON=1
ENV UV_BREAK_SYSTEM_PACKAGES=1
ENV UV_LINK_MODE=copy
ENV VLLM_BASE_DIR=/workspace/vllm

# Bypass NVIDIA driver version check (host: 580.x, container expects 590.48+)
ENV NVIDIA_DISABLE_REQUIRE=1
ENV CUDA_DRIVER_VERSION=""

ARG TORCH_CUDA_ARCH_LIST="12.1a"
ARG FLASHINFER_CUDA_ARCH_LIST="12.1a"
ENV TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST}
ENV FLASHINFER_CUDA_ARCH_LIST=${FLASHINFER_CUDA_ARCH_LIST}
ENV TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas

# Minimal runtime packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl vim git libxcb1 && \
    rm -rf /var/lib/apt/lists/* && \
    pip install uv && pip uninstall -y flash-attn

WORKDIR ${VLLM_BASE_DIR}

# Tiktoken encodings (offline)
RUN mkdir -p tiktoken_encodings && \
    wget -O tiktoken_encodings/o200k_base.tiktoken \
      "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken" && \
    wget -O tiktoken_encodings/cl100k_base.tiktoken \
      "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
ENV TIKTOKEN_ENCODINGS_BASE=${VLLM_BASE_DIR}/tiktoken_encodings

# ---- Install FlashInfer wheels from builder stage ----
RUN --mount=type=bind,from=flashinfer-builder,source=/workspace/wheels,target=/mount/wheels \
    --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv pip install /mount/wheels/*.whl

# ---- Install vLLM (PyPI stable release / aarch64) ----
# --no-deps to protect NVIDIA custom PyTorch and custom FlashInfer from overwrite
# v0.20.1: official stable release (2026-05-04), aarch64 wheel available on PyPI
ARG VLLM_VERSION="vllm==0.20.1"
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    pip install "${VLLM_VERSION}" \
      --no-deps --quiet

# ---- vLLM dependencies (auto-resolved, excluding NVIDIA base) ----
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    DEPS=$(pip show vllm | grep "^Requires:" | sed 's/^Requires: //' | tr ',' '\n' | \
      sed 's/^ *//' | \
      grep -v -E '^(flashinfer|torch$|torchaudio|torchvision|numpy|setuptools|regex|pillow|six|filelock|requests|tqdm|pyyaml|typing.extensions|tokenizers|sentencepiece|protobuf|psutil|nvidia-cutlass)' | \
      tr '\n' ' ') && \
    echo "Installing vLLM deps: $DEPS" && \
    pip install $DEPS uvloop uvicorn httptools --quiet

# ---- Additional runtime dependencies ----
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv pip install \
      ray[default] \
      fastsafetensors \
      nvidia-nvshmem-cu13

# ---- Transformers (Qwen3.6 MoE / compressed-tensors 対応) ----
ARG TRANSFORMERS_VER=5.3.0
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv pip install \
      transformers==${TRANSFORMERS_VER} \
      compressed-tensors \
      --upgrade --no-deps --system && \
    uv pip install huggingface-hub --upgrade --no-deps --system

# ---- fastsafetensors natural-sort patch (multi-node weight loading) ----
COPY patches/fastsafetensors_natural_sort.patch /tmp/
RUN cd / && \
    (patch -p1 --dry-run < /tmp/fastsafetensors_natural_sort.patch &>/dev/null && \
     patch -p1 < /tmp/fastsafetensors_natural_sort.patch && \
     echo "Applied fastsafetensors natural-sort patch." || \
     echo "Patch not applicable (may already be fixed upstream), skipping.")

# Remove incompatible triton-kernels if present
RUN uv pip uninstall triton-kernels 2>/dev/null || true

# ---- Fix: vLLM split_module tuple_return version check bug ----
# PyTorch 2.11.x (26.03-py3) does NOT trigger the tuple_return path, but patch kept for safety
# but split_module doesn't support it yet in older nightly builds.
# Use runtime introspection instead of version string comparison.
# NOTE: Uses heredoc (python3 -) to avoid Dockerfile multi-line RUN parse errors.
RUN python3 - <<'PYEOF'
f = '/usr/local/lib/python3.12/dist-packages/vllm/compilation/backends.py'
import os
if not os.path.exists(f):
    print('split_module tuple_return patch: file not found, skipping')
else:
    txt = open(f).read()
    old = 'has_tuple_return = is_torch_equal_or_newer("2.12.0.dev")'
    new = ('import inspect as _sm_insp; has_tuple_return = "tuple_return" in '
           '_sm_insp.signature(__import__("torch").fx.passes.split_module.split_module).parameters')
    if old in txt:
        open(f, 'w').write(txt.replace(old, new))
        print('split_module tuple_return patch: applied')
    else:
        print('split_module tuple_return patch: not needed (may be fixed upstream)')
PYEOF

# ---- Fix: vLLM register_opaque_type 'hoist' arg not present in PyTorch 2.11 ----
# PyTorch 2.12 added 'hoist' kwarg to register_opaque_type(); 2.11 raises TypeError.
# Patch: wrap the call in try/except to fall back gracefully on older PyTorch.
RUN python3 - <<'PYEOF'
f = '/usr/local/lib/python3.12/dist-packages/vllm/utils/torch_utils.py'
import os
if not os.path.exists(f):
    print('register_opaque_type hoist patch: file not found, skipping')
else:
    txt = open(f).read()
    old = 'register_opaque_type(LayerName, typ="value", hoist=True)'
    new = ('try:\n        register_opaque_type(LayerName, typ="value", hoist=True)\n'
           '    except TypeError:\n        register_opaque_type(LayerName, typ="value")')
    if old in txt:
        open(f, 'w').write(txt.replace(old, new))
        print('register_opaque_type hoist patch: applied')
    else:
        print('register_opaque_type hoist patch: not needed (may be fixed upstream)')
PYEOF

EXPOSE 8000
