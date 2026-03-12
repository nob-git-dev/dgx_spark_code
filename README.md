# DGX Spark Code

NVIDIA DGX Spark (Grace Blackwell GPU) 上で動作するAI関連プロジェクトのコレクション。
すべてDockerコンテナとして動作し、ARM64 (aarch64) ネイティブで構成されています。

## プロジェクト一覧

| プロジェクト | 説明 | 技術スタック |
|-------------|------|-------------|
| [**vllm-nemotron-9b-nvfp4**](./vllm-nemotron-9b-nvfp4/) | Nemotron-9B-v2-Japanese の NVFP4 量子化 + vLLM サーブ構成。ModelOpt PTQ による選択的精度量子化（BF16 18GB → NVFP4 6.3GB） | vLLM, ModelOpt, NVFP4 |
| [**vllm-qwen122b-nvfp4**](./vllm-qwen122b-nvfp4/) | Qwen3.5-122B-A10B NVFP4 の vLLM カスタムビルド。FlashInfer SM121 コンパイル + パッチ適用 | vLLM (custom), FlashInfer, NVFP4 |
| [**local-agent**](./local-agent/) | ReActパターンのエージェンティックAIチャットシステム。Web検索・ファイル操作・サンドボックス実行・RAGの6ツールを搭載 | FastAPI, Ollama, ChromaDB, Docker SDK, Vanilla JS |
| [**whisper-transcriber**](./whisper-transcriber/) | GPU高速推論による音声・動画文字起こしツール。REST API / Web UI / CLI の3インターフェース | FastAPI, faster-whisper (CTranslate2), Gradio |

## 共通の前提環境

- Docker + Docker Compose
- NVIDIA GPU + NVIDIA Container Toolkit
- ARM64 (aarch64) アーキテクチャ

各プロジェクトの詳細なセットアップ手順は、各サブディレクトリのREADMEを参照してください。

## ライセンス

MIT
