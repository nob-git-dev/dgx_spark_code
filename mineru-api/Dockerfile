# MinerU 2.5 API Server for GX10 (ARM64 / NVIDIA GB10)
# ベースイメージ: nvcr.io/nvidia/pytorch:25.04-py3
# ARM64 / CUDA 13.0 / sm_121a (Blackwell) 対応
# ADR-1: vllm/vllm-openai:v0.11.2 は sm_121a 非対応のため切り替え
# ADR-2: mineru[core] (vllm依存) → mineru + mineru-vl-utils[transformers]

FROM nvcr.io/nvidia/pytorch:25.04-py3

# Install system dependencies for OpenCV and CJK fonts
RUN apt-get update && \
    apt-get install -y \
        fonts-noto-core \
        fonts-noto-cjk \
        fontconfig \
        libgl1 \
        curl && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install MinerU (transformers backend, no vllm dependency)
# ADR-2: vllm を排除し transformers エクストラのみ使用
# Note: nvcr.io/nvidia/pytorch:25.04-py3 は PIP_CONSTRAINT=/etc/pip/constraint.txt で
#       beautifulsoup4==4.13.3, pandas==2.2.3 等を pin している。
#       mineru>=3.0.0 はこれらの新しいバージョンを要求するため、
#       mineru インストール時のみ PIP_CONSTRAINT を無効化する。
#       ただしベースイメージの PyTorch 2.7 は NumPy 1.x でコンパイルされているため
#       numpy<2 を明示固定して上書きを防ぐ。
RUN PIP_CONSTRAINT="" pip install \
        'mineru[pipeline]>=3.0.0' \
        'mineru-vl-utils[transformers]>=0.2.3' \
        'numpy<2' \
    && pip cache purge

# Copy entrypoint script
# ADR-3: モデルダウンロードはビルド時でなく起動時に行う
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
