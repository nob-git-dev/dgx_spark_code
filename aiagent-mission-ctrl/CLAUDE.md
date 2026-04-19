# GX10 MCP Server

## プロジェクト概要
GX10のインフラ管理をMCPプロトコルで公開するサーバー。
設計書: `~/projects/docs/designs/mcp-server.md`

## Agent Kanban System
看板方式ベースのエージェント間協調システム。
設計書: `~/projects/docs/designs/agent-kanban.md`
設定: `kanban.yml`（ボード・リソース・ルール定義）

### アーキテクチャ
- `lib/kanban_store.py` — Redis操作、カードライフサイクル、リソース管理、ルールエンジン
- `tools/kanban.py` — MCPツール10個（card/claim/done/board/reserve/release/resources/andon/signal/watch）
- `hooks/check_board.py` — Claude Code PreToolUse hook（未読通知）
- `docker-compose.yml` — Redis コンテナ（llm-network 参加）

### 依存サービス
- Redis 7（`docker compose up -d` で起動）
- 環境変数 `REDIS_URL` でRedis接続先を変更可能（デフォルト: `redis://localhost:6379`）

### エージェント識別
- 現状: ツール呼び出し時に `agent` パラメータとして明示的に渡す（TODO: FastMCPセッションメタデータから自動取得）
- エージェント名: `gx10-claude`, `mac-claude`, `nanoclaw`

## 実行方式
- ホストOS上で `uv run server.py` で直接実行（Docker不使用）
- systemd ユーザーサービスとして常駐
- 外部依存は `fastmcp`, `redis`, `pyyaml`。他は全て subprocess

## 開発ルール
- `lib/` に共通処理、`tools/` にツール定義を分離
- subprocess の実行は `lib/subprocess_utils.py` の `run()` を使う
- 部分障害は `collect_with_fallback()` で吸収し、`[unavailable: 理由]` を返す
- ツール全体をエラーにしない（Graceful Degradation）
- kanban.yml の変更でドメインを切り替える。コードは変えない（Mechanism, not Policy）
