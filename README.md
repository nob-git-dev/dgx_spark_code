# DGX Spark Code

NVIDIA DGX Spark (Grace Blackwell GPU) 上で動作するAI関連プロジェクトのコレクション。
すべてDockerコンテナとして動作し、ARM64 (aarch64) ネイティブで構成されています。

## プロジェクト一覧

| プロジェクト | 説明 | 技術スタック |
|-------------|------|-------------|
| [**vllm**](./vllm/) | vLLM推論サーバー構成。Nemotron-9B-v2-Japanese NVFP4量子化、Qwen3.5-122B NVFP4カスタムビルド、Qwen3-VL-8B OCRサービスを含む | vLLM, ModelOpt, FlashInfer, Docker Compose |
| [**local-agent**](./local-agent/) | ReActパターンのエージェンティックAIチャットシステム。Web検索・ファイル操作・サンドボックス実行・RAGの6ツールを搭載 | FastAPI, Ollama, ChromaDB, Docker SDK, Vanilla JS |
| [**whisper-transcriber**](./whisper-transcriber/) | GPU高速推論による音声・動画文字起こしツール。REST API / Web UI / CLI の3インターフェース | FastAPI, faster-whisper (CTranslate2), Gradio |

## 共通の前提環境

- Docker + Docker Compose
- NVIDIA GPU + NVIDIA Container Toolkit
- ARM64 (aarch64) アーキテクチャ

各プロジェクトの詳細なセットアップ手順は、各サブディレクトリのREADMEを参照してください。

## ライセンス

MIT
