# DGX Spark Code

> 全体ポートフォリオ: [AI Agent Engineering Portfolio](https://github.com/nob-git-dev/ai-agent-portfolio)

NVIDIA DGX Spark (Grace Blackwell GPU) 上で動作するAI関連プロジェクトのコレクション。
すべてDockerコンテナとして動作し、ARM64 (aarch64) ネイティブで構成されています。

## Portfolio Snapshot

このリポジトリは、DGX Spark / Grace Blackwell / ARM64 環境で、
**ローカル LLM 推論・量子化・音声認識・マルチエージェント管制**を実装・検証するための実機向けプロジェクト集です。

| 観点 | 内容 |
|---|---|
| **Problem** | DGX Spark のような新しい AI ワークステーション環境では、ARM64、Blackwell、CUDA、vLLM、NVFP4、統合メモリなどの制約により、既存手順がそのまま動かない。 |
| **Built** | NVFP4 量子化済み LLM serving、vLLM custom build、ReAct 型ローカルエージェント、Whisper 文字起こし API / UI / CLI、マルチ Claude エージェント管制 API、DGX アップデート事前確認スキル。 |
| **Technical Focus** | vLLM / ModelOpt / NVFP4、Docker / Docker Compose、FastAPI / WebSocket / Redis、ARM64 Linux、GPU memory-aware service design、local-first AI infrastructure。 |
| **Evidence** | Nemotron 9B NVFP4 の BF16 比 2.3 倍高速・GPU メモリ効率 4.5 倍改善、aiagent-mission-ctrl の 29 エンドポイント、read-only / sudo なし / 副作用ゼロを機械検証する dgx-update-check。 |
| **Maturity** | DGX Spark 実機での検証・運用を前提とした個人 AI インフラ実装群。 |

## プロジェクト一覧

| プロジェクト | 説明 | 技術スタック |
|-------------|------|-------------|
| [**vllm-nemotron-9b-nvfp4**](./vllm-nemotron-9b-nvfp4/) | Nemotron-9B-v2-Japanese の NVFP4 量子化 + vLLM サーブ構成。ModelOpt PTQ による選択的精度量子化（BF16 18GB → NVFP4 6.3GB） | vLLM, ModelOpt, NVFP4 |
| [**vllm-qwen122b-nvfp4**](./vllm-qwen122b-nvfp4/) | Qwen3.5-122B-A10B NVFP4 の vLLM カスタムビルド。FlashInfer SM121 コンパイル + パッチ適用 | vLLM (custom), FlashInfer, NVFP4 |
| [**local-agent**](./local-agent/) | ReActパターンのエージェンティックAIチャットシステム。Web検索・ファイル操作・サンドボックス実行・RAGの6ツールを搭載 | FastAPI, Ollama, ChromaDB, Docker SDK, Vanilla JS |
| [**whisper-transcriber**](./whisper-transcriber/) | GPU高速推論による音声・動画文字起こしツール。REST API / Web UI / CLI の3インターフェース | FastAPI, faster-whisper (CTranslate2), Gradio |
| [**env-docs**](./env-docs/) | DGX Sparkの環境情報を構造化管理するテンプレート。Claude Codeのスラッシュコマンドで自然言語から自動同期 | Markdown, Claude Code |
| [**aiagent-mission-ctrl**](./aiagent-mission-ctrl/) | マルチ Claude エージェント管制システム。アクティビティ宣言・Kanban・インフラ監視・作業記録（Git 自動コミット）を REST API + WebSocket で提供。29 エンドポイント | FastAPI, Redis, WebSocket, Claude Code |
| [**claude-sdlc-skills**](./claude-sdlc-skills/) | Claude Code に SDLC（仕様→設計→TDD→レビュー→デプロイ）の規律を強制するスキル・エージェント・フックのセット。破壊的操作（DROP/TRUNCATE、WHERE 句なし DELETE、rm -rf /、main への force push、sudo）を物理ブロック | Claude Code (Skills / Subagents / PreToolUse Hooks), Bash, jq |
| [**dgx-update-check**](./dgx-update-check/) | DGX Spark のシステムアップデートを、ブラウザ・ダッシュボードのボタンを押す **前に**「何が来ているか」を **副作用ゼロ・read-only** で覗き見るスキル。`nvidia-spark-ota-check` で DGX OTA 世代、`apt-get -s full-upgrade` で Ubuntu 標準 apt 更新を取得し、リリースノートと CVE をネット調査して提示。`apt update` も .deb DL もサービス操作も行わない（allowlist で構造的に担保） | Claude Code Skill, Bash, Python (stdlib), jq |

## 共通の前提環境

- Docker + Docker Compose
- NVIDIA GPU + NVIDIA Container Toolkit
- ARM64 (aarch64) アーキテクチャ

各プロジェクトの詳細なセットアップ手順は、各サブディレクトリのREADMEを参照してください。

## ライセンス

各プロジェクトのライセンスは独立しています。詳細は各ディレクトリの `README.md` を参照してください。

| プロジェクト | コードのライセンス | 注意事項 |
|---|---|---|
| **claude-sdlc-skills** | [CC BY-NC-SA 4.0](./claude-sdlc-skills/LICENSE)（非商用）/ 商用は要申請 | 詳細: [LICENSE-COMMERCIAL.md](./claude-sdlc-skills/LICENSE-COMMERCIAL.md) |
| **dgx-update-check** | [CC BY-NC-SA 4.0](./dgx-update-check/LICENSE)（非商用）/ 商用は要申請 | — |
| **mineru-api** | MIT | MinerU 本体は Apache 2.0、モデルは各モデルカードのライセンスに従う |
| **vllm-nemotron-9b-nvfp4** | MIT | **Nemotron モデルは NVIDIA Open Model License**（要確認） |
| **vllm-qwen122b-nvfp4** | MIT（ただし Apache 2.0 コードの改変を含む） | vLLM パッチは Apache 2.0、Qwen3.5 モデルは Qwen License |
| **whisper-transcriber** | MIT | 依存ライブラリは MIT / Apache 2.0 |
| **local-agent** | MIT | 依存ライブラリは MIT / Apache 2.0 |
| **aiagent-mission-ctrl** | MIT | FastAPI は MIT、Redis は BSD |
| **env-docs** | MIT | — |
