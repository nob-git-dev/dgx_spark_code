# =============================================================================
# Whisper Transcriber — マルチステージ Dockerfile
#
# ステージ 1: CTranslate2 を ARM64 CUDA 対応でソースビルド
# ステージ 2: 軽量ランタイムイメージ
#
# Blackwell (SM_121) は Hopper (SM_90) バイナリ互換で動作するため、
# CUDA_ARCH_LIST に "89;90" を指定してビルドする。
# =============================================================================

# =============================================================================
# Stage 1: CTranslate2 ビルド
# =============================================================================
FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu24.04 AS ctranslate2-builder

ENV DEBIAN_FRONTEND=noninteractive

# ビルド依存パッケージをインストール
# - build-essential: C++ ビルドツール
# - python3-dev: Python C 拡張ビルド用ヘッダ
# - libopenblas-dev: CPU フォールバック用 BLAS ライブラリ
# ※ cmake は apt 版 (3.28) だと SM 89/90 を認識しないため pip で最新版を入れる
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    python3-dev \
    python3-pip \
    python3-venv \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

# CMake 最新版をインストール（SM 89/90 アーキテクチャ対応に必須）
RUN pip install --break-system-packages cmake

# CTranslate2 ソースを取得
RUN git clone --recursive https://github.com/OpenNMT/CTranslate2.git /opt/ctranslate2

WORKDIR /opt/ctranslate2

# CMake の select_compute_arch.cmake は SM 89/90 を認識しないため、
# cuda_select_nvcc_arch_flags() をパッチして直接 gencode フラグを設定する。
# code=compute_90 (SASS ではなく PTX) を埋め込むことで、CUDA ドライバが
# Blackwell (SM_121) 向けに JIT コンパイルできるようにする。
RUN sed -i 's/cuda_select_nvcc_arch_flags(ARCH_FLAGS ${CUDA_ARCH_LIST})/set(ARCH_FLAGS "-gencode=arch=compute_90,code=compute_90")/' CMakeLists.txt

# C++ ライブラリをビルド
# - WITH_CUDA=ON: CUDA GPU アクセラレーション有効
# - WITH_CUDNN=ON: cuDNN による高速化
# - CUDA_ARCH_LIST="90": Hopper (Blackwell バイナリ互換)
# - WITH_MKL=OFF: x86 専用の MKL は ARM64 では使用不可
# - OPENMP_RUNTIME=COMP: Intel libiomp5 は ARM64 非対応のため GCC libgomp を使用
# - WITH_OPENBLAS=ON: ARM64 対応の BLAS 実装
RUN mkdir build && cd build && \
    cmake .. \
      -DWITH_CUDA=ON \
      -DWITH_CUDNN=ON \
      -DCUDA_ARCH_LIST="90" \
      -DWITH_MKL=OFF \
      -DOPENMP_RUNTIME=COMP \
      -DWITH_OPENBLAS=ON \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
    && make -j$(nproc) \
    && make install \
    && ldconfig

# Python ホイールをビルド
# - pybind11: C++/Python バインディング生成に必須
RUN pip install --break-system-packages wheel setuptools pybind11 && \
    cd python && \
    python3 setup.py bdist_wheel


# =============================================================================
# Stage 2: ランタイム
# =============================================================================
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ランタイム依存パッケージをインストール
# - python3, python3-pip, python3-venv: Python 実行環境
# - ffmpeg: 音声/動画のデコード（MP4, MP3 等の処理に必須）
# - libopenblas0: CTranslate2 の CPU フォールバック用
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    libopenblas0 \
    && rm -rf /var/lib/apt/lists/*

# ビルド済み CTranslate2 ライブラリをコピー（/usr/local にインストール済み）
COPY --from=ctranslate2-builder /usr/local /usr/local
COPY --from=ctranslate2-builder /opt/ctranslate2/python/dist/*.whl /tmp/

# 共有ライブラリのキャッシュを更新（CTranslate2 の .so を認識させる）
RUN ldconfig

# Python 仮想環境を作成
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CTranslate2 ホイール + Python 依存パッケージをインストール
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
RUN pip install --no-cache-dir \
    faster-whisper \
    fastapi[standard] \
    "uvicorn[standard]" \
    gradio \
    python-multipart \
    pydantic-settings

# アプリケーションコードをコピー
WORKDIR /app
COPY app/ /app/app/

# データ・モデル用ディレクトリ（ボリュームマウントポイント）
RUN mkdir -p /app/data/input /app/data/output /app/models

# ポート公開
# 8080: FastAPI REST API
# 7860: Gradio Web UI
EXPOSE 8080 7860

# ヘルスチェック
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# FastAPI + Gradio を起動
# - host 0.0.0.0: コンテナ外からのアクセスを許可
# - port 8080: REST API ポート
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
