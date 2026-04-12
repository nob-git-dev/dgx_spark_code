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
| [**env-docs**](./env-docs/) | DGX Sparkの環境情報を構造化管理するテンプレート。Claude Codeのスラッシュコマンドで自然言語から自動同期 | Markdown, Claude Code |
| [**gx10-mcp**](./gx10-mcp/) | MCP Server + Agent Kanban System。トヨタ看板方式をAIエージェント間協調に適用。Redis-backed のカード管理・リソースプール・イベント駆動ルール | FastMCP, Redis, Claude Code |
| [**claude-sdlc-skills**](./claude-sdlc-skills/) | Claude Code に SDLC（仕様→設計→TDD→レビュー→デプロイ）の規律を強制するスキル・エージェント・フックのセット。破壊的操作（DROP/TRUNCATE、WHERE 句なし DELETE、rm -rf /、main への force push、sudo）を物理ブロック | Claude Code (Skills / Subagents / PreToolUse Hooks), Bash, jq |

## 共通の前提環境

- Docker + Docker Compose
- NVIDIA GPU + NVIDIA Container Toolkit
- ARM64 (aarch64) アーキテクチャ

各プロジェクトの詳細なセットアップ手順は、各サブディレクトリのREADMEを参照してください。

## ライセンス

MIT
