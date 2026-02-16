# Whisper Transcriber

NVIDIA GPU (Blackwell / Hopper / Ada Lovelace) 対応の音声・動画文字起こしツール。
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) をベースに、Docker コンテナ上で REST API / Web UI / CLI の3つのインターフェースを提供します。

## 主な特徴

- **高速推論** — CTranslate2 による最適化で、リアルタイムの数倍速で文字起こし
- **Blackwell GPU 対応** — SM_121 (GB10等) を Hopper 互換で動作させるパッチを内蔵
- **3つのインターフェース** — REST API、Gradio Web UI、ホスト側 CLI ラッパー
- **複数ファイル一括処理** — Web UI から複数ファイルをまとめてアップロード可能
- **多言語対応** — 日本語・英語をはじめ、Whisper がサポートする全言語に対応
- **複数出力形式** — SRT / VTT / TXT / JSON / TSV
- **Docker 完結** — ホスト側に Python や FFmpeg のインストール不要

## 動作環境

- Docker + NVIDIA Container Toolkit
- NVIDIA GPU (CUDA 対応)

## クイックスタート

```bash
# 1. リポジトリをクローン
git clone https://github.com/nob-git-dev/dgx_spark_code.git
cd dgx_spark_code

# 2. 環境変数を設定
cp .env.example .env

# 3. ビルド & 起動
docker compose up -d

# 4. アクセス
#   Web UI:   http://localhost:7860/ui
#   REST API: http://localhost:8080/api/v1/transcribe
#   ヘルス:   http://localhost:8080/health
```

## CLI の使い方

ホスト側から直接ファイルを指定して文字起こしできます。

```bash
./transcribe recording.mp4
./transcribe meeting.wav --format txt --language en
./transcribe interview.m4a --model large-v3 --stdout
```

## REST API

```bash
curl -X POST http://localhost:8080/api/v1/transcribe \
  -F "file=@recording.mp4" \
  -F "language=ja" \
  -F "format=srt"
```

## 利用可能なモデル

| モデル | サイズ | 説明 |
|--------|--------|------|
| `tiny` | ~75MB | 最小・最速（テスト用） |
| `base` | ~145MB | 基本モデル |
| `small` | ~488MB | 小型モデル |
| `medium` | ~1.5GB | 中型モデル |
| `large-v3-turbo` | ~1.6GB | **高速・高精度（デフォルト）** |
| `large-v3` | ~3.1GB | 最高精度 |

## プロジェクト構成

```
├── app/
│   ├── main.py              # FastAPI エントリポイント
│   ├── config.py             # 環境変数ベースの設定
│   ├── transcriber.py        # コア文字起こしエンジン
│   ├── api/                  # REST API (FastAPI)
│   ├── webui/                # Web UI (Gradio)
│   ├── cli/                  # コンテナ内 CLI
│   ├── patches/              # Blackwell 互換パッチ
│   └── utils/                # 出力フォーマッタ、メディアユーティリティ
├── compose.yaml              # Docker Compose 定義
├── Dockerfile                # マルチステージビルド (CTranslate2 ソースビルド含む)
├── transcribe                # ホスト側 CLI ラッパー
├── data/                     # 入出力データ
└── models/                   # モデルキャッシュ（自動ダウンロード）
```

## ライセンス

MIT
