# Whisper Transcriber — インストール手順書

このドキュメントは、NVIDIA Grace Blackwell (GB10) 搭載マシン上で Whisper 文字起こし環境を構築する手順をまとめたものです。
ARM64 + Blackwell GPU という特殊な組み合わせで発生する問題と、その回避策を含んでいます。

---

## 前提条件

以下がホスト OS に導入済みであること。

| ソフトウェア | 確認コマンド | 備考 |
|---|---|---|
| Docker Engine | `docker --version` | 20.10 以上 |
| Docker Compose V2 | `docker compose version` | V2 プラグイン形式 |
| NVIDIA ドライバ | `nvidia-smi` | GPU が認識されていること |
| NVIDIA Container Toolkit | `dpkg -l nvidia-container-toolkit` | コンテナから GPU を使うために必要 |

NVIDIA Container Toolkit が未導入の場合は、[公式手順](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) に従ってインストールしてください。

---

## 手順

### 1. プロジェクトの配置

リポジトリをクローン、またはファイル一式をサーバー上に配置します。

```bash
cd ~/projects/whisper-transcriber
```

ディレクトリ構成は以下の通りです。

```
whisper-transcriber/
├── Dockerfile          ← Docker イメージ定義
├── compose.yaml        ← Docker Compose 定義
├── .env                ← 環境変数（モデル・言語の設定）
├── .env.example        ← 環境変数のテンプレート
├── transcribe          ← ホスト側 CLI ラッパースクリプト
├── app/                ← Python アプリケーション本体
│   ├── main.py
│   ├── config.py
│   ├── transcriber.py
│   ├── patches/
│   │   └── blackwell_compat.py
│   ├── api/
│   ├── webui/
│   ├── cli/
│   └── utils/
├── data/
│   ├── input/          ← 入力ファイル置き場
│   └── output/         ← 文字起こし結果の出力先
└── models/             ← Whisper モデルのキャッシュ（自動ダウンロード）
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、必要に応じて編集します。

```bash
cp .env.example .env
```

通常はデフォルト値のままで問題ありません。

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `WHISPER_MODEL` | `large-v3-turbo` | 使用するモデル（後述） |
| `WHISPER_LANGUAGE` | `ja` | デフォルト言語 |
| `WHISPER_DEVICE` | `cuda` | 推論デバイス |
| `WHISPER_COMPUTE_TYPE` | `float16` | 計算精度 |

### 3. Docker イメージのビルド

```bash
docker compose build
```

**所要時間: 約 30〜60 分（初回のみ）**

内部で CTranslate2 という推論エンジンを C++ ソースからコンパイルしています。
これは ARM64 + CUDA の公式ビルド済みパッケージが存在しないためです。
2 回目以降は Docker のレイヤーキャッシュが効くため、アプリケーションコードの変更だけなら数秒で完了します。

> **ビルドが失敗する場合**
> よくあるエラーとその対処法を [トラブルシューティング](#トラブルシューティング) にまとめています。

### 4. 起動

```bash
docker compose up -d
```

初回起動時に Whisper モデルが Hugging Face から自動ダウンロードされます。
`large-v3-turbo` は約 1.6GB、`large-v3` は約 3.1GB です。
ダウンロードされたモデルは `./models/` に保存され、次回以降は再ダウンロード不要です。

### 5. 動作確認

```bash
# ヘルスチェック — {"status":"ok"} と返れば成功
curl http://localhost:8080/health
```

**初回の文字起こし実行時の注意:**
最初の 1 回だけ、CUDA ドライバが PTX（中間コード）を GPU 向けにコンパイルする処理が走ります。
そのため、初回のみ数秒〜十数秒の追加遅延が発生します。
2 回目以降はドライバがコンパイル結果をキャッシュするため、この遅延はなくなります。

---

## 使い方

3 つのインターフェースが利用できます。

### Web UI（ブラウザ）

ブラウザで以下を開きます。

```
http://<サーバーのIP>:8080/ui/
```

ファイルをドラッグ＆ドロップし、「文字起こし開始」を押すだけです。
対応形式: MP4, MP3, WAV, M4A, MKV, WebM, OGG, FLAC, AVI, MOV 等

### CLI（コマンドライン）

```bash
# 基本
./transcribe ~/Downloads/会議録音.mp4

# オプション指定
./transcribe recording.wav --format txt --language en --model large-v3

# 結果を標準出力に（ファイル保存しない）
./transcribe interview.m4a --stdout --format txt
```

出力は `./data/output/` に保存されます。

### REST API

```bash
curl -X POST http://localhost:8080/api/v1/transcribe \
  -F "file=@音声ファイル.mp4" \
  -F "language=ja" \
  -F "format=srt"
```

API の詳細:

| エンドポイント | 説明 |
|---|---|
| `POST /api/v1/transcribe` | ファイルを送信して文字起こし（JSON レスポンス） |
| `POST /api/v1/transcribe/download` | ファイルを送信して結果をファイルとしてダウンロード |
| `GET /api/v1/models` | 利用可能なモデル一覧 |
| `GET /api/v1/formats` | 対応する出力フォーマット一覧 |
| `GET /health` | ヘルスチェック |

---

## モデルの選択

| モデル名 | サイズ | 速度 | 精度 | 推奨用途 |
|---|---|---|---|---|
| `large-v3-turbo` | 1.6GB | 速い | 高い | **日常的な文字起こし（推奨）** |
| `large-v3` | 3.1GB | 遅い | 最高 | 最高精度が必要な場合 |
| `medium` | 1.5GB | 速い | 中程度 | リソース節約時 |
| `tiny` | 75MB | 最速 | 低い | テスト用 |

デフォルトは `large-v3-turbo` です。`.env` の `WHISPER_MODEL` で変更できます。
Web UI や CLI からも都度モデルを選択できます。

---

## 運用コマンド

```bash
# 停止
docker compose down

# ログ確認（リアルタイム）
docker compose logs -f whisper

# 再起動
docker compose restart

# イメージの再ビルド（アプリケーションコード変更時）
docker compose build

# 完全リセット（イメージ削除 + 再ビルド）
docker compose down && docker compose build --no-cache
```

---

## Dockerfile の設計について

この Dockerfile は ARM64 + Blackwell という環境のために、いくつかの特殊な対応を含んでいます。
他の環境に移植する場合や、ビルドエラーに遭遇した場合のために、設計意図を記録しておきます。

### なぜ CTranslate2 をソースからビルドするのか

推論エンジン CTranslate2 の公式 pip パッケージ（ホイール）は、ARM64 版に CUDA サポートが含まれていません。
x86_64 版には CUDA 対応ホイールが存在しますが、ARM64 ではソースからのビルドが必須です。

### sed による CMakeLists.txt のパッチ

```dockerfile
RUN sed -i 's/cuda_select_nvcc_arch_flags(ARCH_FLAGS ${CUDA_ARCH_LIST})/set(ARCH_FLAGS "-gencode=arch=compute_90,code=compute_90")/' CMakeLists.txt
```

CMake に同梱されている `select_compute_arch.cmake` は、CMake 3.28 でも 4.2 でも SM 89 (Ada Lovelace) / SM 90 (Hopper) のアーキテクチャ名を認識しません。
そのため、CTranslate2 の CMakeLists.txt を直接パッチして、NVCC に渡す gencode フラグを固定しています。

### なぜ `code=compute_90` なのか（`code=sm_90` ではなく）

これは最も重要なポイントです。

| フラグ | 出力形式 | Blackwell で動くか |
|---|---|---|
| `code=sm_90` | SASS（Hopper 専用の機械語） | **動かない** |
| `code=compute_90` | PTX（CUDA の中間言語） | **動く** |

`sm_90` は Hopper GPU でしか実行できない固定バイナリを生成します。
`compute_90` は PTX という中間表現を埋め込み、実行時に CUDA ドライバが対象 GPU（Blackwell）向けに JIT コンパイルします。

`code=sm_90` を使うと、ビルドやモデルロードは成功するように見えますが、
**実際の音声データを処理する段階で `cudaErrorNoKernelImageForDevice` エラーが発生します。**
テスト時に無音ファイルを使うと VAD が全区間を除去してしまい、GPU カーネルが実行されないため、このエラーを見逃す可能性があります。

### `-DOPENMP_RUNTIME=COMP` の理由

CTranslate2 のデフォルトは Intel OpenMP (`libiomp5`) ですが、これは x86 専用です。
ARM64 では GCC 標準の OpenMP ランタイム (`libgomp`) を使う必要があるため、`COMP` を指定しています。

### `-DCMAKE_INSTALL_PREFIX=/usr/local` の理由

CTranslate2 の Python バインディング（`setup.py bdist_wheel`）は、C++ ライブラリのヘッダファイルをシステム標準パスから探します。
カスタムパス（例: `/opt/ctranslate2/install`）にインストールすると、ヘッダが見つからずビルドが失敗します。

---

## トラブルシューティング

### ビルド時のエラー

#### `Intel OpenMP runtime libiomp5 not found`

```
CMake Error: Intel OpenMP runtime libiomp5 not found
```

Dockerfile の cmake オプションに `-DOPENMP_RUNTIME=COMP` が含まれていることを確認してください。
ARM64 では Intel OpenMP は利用できません。

#### `Unknown CUDA Architecture Name 89/90`

```
CMake Error: Unknown CUDA Architecture Name 90 in CUDA_SELECT_NVCC_ARCH_FLAGS
```

`sed` による CMakeLists.txt パッチが正しく適用されていません。
Dockerfile 内の `sed` コマンドで、置換対象の関数名が `ARCH_FLAGS`（`CUDA_NVCC_ARCH_FLAGS` ではない）であることを確認してください。
CTranslate2 のバージョンによって変数名が異なる可能性があります。最新のソースを確認してください:

```bash
grep 'cuda_select_nvcc_arch_flags' CMakeLists.txt
```

#### `No module named 'pybind11'`

```
ModuleNotFoundError: No module named 'pybind11'
```

Dockerfile の Python ホイールビルド行で `pybind11` がインストールされていることを確認してください:

```dockerfile
RUN pip install --break-system-packages wheel setuptools pybind11 && \
```

#### `fatal error: ctranslate2/models/whisper.h: No such file or directory`

cmake の `CMAKE_INSTALL_PREFIX` が `/usr/local` に設定されていることを確認してください。
カスタムパスを使うと、Python バインディングのビルド時にヘッダファイルが見つかりません。

### 実行時のエラー

#### `cudaErrorNoKernelImageForDevice`

```
parallel_for failed: cudaErrorNoKernelImageForDevice: no kernel image is available for execution on the device
```

gencode フラグが `code=sm_90` になっています。`code=compute_90` に変更して再ビルドしてください。
詳細は上記「なぜ `code=compute_90` なのか」を参照してください。

#### 初回実行が異常に遅い

初回は PTX → SASS の JIT コンパイルが走るため、数秒〜十数秒の遅延が発生します。
これは正常な動作で、2 回目以降はキャッシュされて高速になります。

#### `GPU device discovery failed: ... /sys/class/drm/card0/device/vendor`

```
[W:onnxruntime:Default, device_discovery.cc:211 DiscoverDevicesForPlatform] GPU device discovery failed
```

onnxruntime が GPU 情報の取得に失敗していますが、文字起こしには影響ありません。無視して構いません。

---

## ポート一覧

| ポート | 用途 |
|---|---|
| 8080 | REST API (FastAPI) + Web UI (`/ui/`) |
| 7860 | （現在未使用。Gradio 単体起動時に使用） |

他のサービスとの競合に注意してください（例: Ollama は 11434、Open WebUI は 3000）。

---

## ホスト OS への影響

この環境はホスト OS を一切汚しません。

- Python、FFmpeg、ライブラリ類は全てコンテナ内にインストールされます
- ホスト側に必要なのは Docker と NVIDIA Container Toolkit のみです
- モデルファイルは `./models/` にダウンロードされますが、不要になれば削除するだけです

---

## 参考リンク

- [faster-whisper (GitHub)](https://github.com/SYSTRAN/faster-whisper)
- [CTranslate2 (GitHub)](https://github.com/OpenNMT/CTranslate2)
- [CTranslate2 ARM64 CUDA の問題 (Issue #1306)](https://github.com/OpenNMT/CTranslate2/issues/1306)
- [whisperx-blackwell (Blackwell 互換パッチの参考実装)](https://github.com/Mekopa/whisperx-blackwell)
- [NVIDIA Container Toolkit インストールガイド](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
