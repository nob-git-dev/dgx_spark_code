# aiagent-mission-ctrl

## プロジェクト概要

マルチ Claude エージェント管制システム。
REST API + WebSocket で複数の Claude Code エージェントの協調動作を支援する。

- **ポート:** 9100
- **実行:** ホスト OS 上で `uv run uvicorn server:app`（Docker 不使用）
- **常駐:** systemd ユーザーサービス（`gx10-mcp.service`）

## アーキテクチャ

```
server.py                  — FastAPI アプリファクトリ（lifespan / ルーター登録 / WebSocket）
routers/
  environment.py           — GET: /environment, /contract, /service-status, /gpu-status, /project-context, /doc
  coordination.py          — GET/POST: /activity（Redis専用・未接続時503）
  recording.py             — POST: /recording/journal, /decision, /contract, /issue（Git自動コミット）
  live.py                  — GET/POST: /logs, /check-endpoint, /service/start, /service/stop
  history.py               — GET: /journal, /decisions
  kanban.py                — /kanban/* 10エンドポイント
  context.py               — /context/* エージェント間コンテキスト共有
ws/
  manager.py               — WebSocket接続管理・Redis pub/sub・ブロードキャスト
lib/                       — ビジネスロジック（変更禁止）
  config.py                — 定数（MCP_PORT, DOCS_DIR, PROJECTS_DIR など）
  kanban_store.py          — Redis操作・カードライフサイクル・ルールエンジン
  git.py                   — Git自動コミット（write系操作が使用）
  docker.py / nvidia.py / services.py / systemd.py / subprocess_utils.py
hooks/
  session_start.py         — PostStart hook: サーバー疎通確認・アクティビティ表示
  activity_guard.py        — PreToolUse hook: 他エージェント作業中の警告
  check_board.py           — PreToolUse hook: Kanban未読通知
  stop_guard.py            — Stop hook: write_journal 促し
tests/                     — pytest + pytest-asyncio（31件）
```

## 依存サービス

- **Redis 7**（`docker compose up -d` で起動）— Kanban・アクティビティ管理に必須
  - 環境変数 `REDIS_URL` で接続先変更可（デフォルト: `redis://localhost:6379`）
- **docs リポジトリ**（`~/projects/docs/`）— write系操作のGitコミット先

## 開発ルール

- `lib/` のビジネスロジックは変更しない。ルーターは `lib/` を呼び出すだけ
- subprocess 実行は `lib/subprocess_utils.py` の `run()` を使う
- 部分障害は `collect_with_fallback()` で吸収し `[unavailable: 理由]` を返す（Graceful Degradation）
- Redis 未接続時: Kanban・activity は 503、それ以外は正常動作
- `kanban.yml` の変更でドメインを切り替える。コードは変えない（Mechanism, not Policy）
- 新しいエンドポイントは `routers/` に追加し `server.py` でルーター登録する
- テストは `tests/` に追加し `uv run pytest tests/ -q` で実行する

## テスト実行

```bash
# Redis を起動してからテスト
docker compose up -d
uv run pytest tests/ -q
```

## エージェント識別

- `agent` パラメータで明示的に渡す（例: `"gx10-claude"`, `"mac-claude"`）
- WebSocket: `ws://localhost:9100/ws?agent=gx10-claude` で接続
