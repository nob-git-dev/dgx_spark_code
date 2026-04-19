# aiagent-mission-ctrl

REST API + WebSocket による **マルチ Claude エージェント管制システム**。

複数の Claude Code エージェントが同一サーバー上で協調して動くための基盤。
アクティビティ宣言・看板（Kanban）・コンテキスト共有・インフラ監視・作業記録を一手に担う。

---

## 機能一覧

| カテゴリ | エンドポイント数 | 主な機能 |
|----------|---------------|---------|
| **インフラ参照** | 6 | 環境情報・サービス状態・GPU 監視・プロジェクトコンテキスト |
| **エージェント協調** | 2 | アクティビティ宣言・他エージェント状況確認 |
| **作業記録** | 4 | ジャーナル・意思決定（ADR）・課題報告（Git 自動コミット）|
| **ライブ操作** | 4 | サービス起動停止・ログ取得・エンドポイント疎通確認 |
| **履歴参照** | 2 | ジャーナル検索・ADR 一覧 |
| **Kanban** | 10 | カードライフサイクル・リソース管理・アンドン・イベント |
| **WebSocket** | 1 | リアルタイム通知（エージェント間イベント配信）|

合計 **29 エンドポイント**。すべて curl / Bash から直接呼び出せる。

---

## 前提条件

### Python / uv

```bash
# uv がなければインストール
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Docker（Redis 用）

```bash
docker compose up -d
```

### docs リポジトリ

`write_journal` / `write_decision` 等の write 系操作は `~/projects/docs/` に Git コミットする。
このリポジトリが存在しない場合、write 系操作はすべて失敗する。

```bash
mkdir -p ~/projects/docs/{journal,decisions,contracts}
cd ~/projects/docs
git init && git commit --allow-empty -m "init: docs repository"
```

---

## Quick Start

```bash
# 1. Redis を起動（Kanban・アクティビティ管理に必要）
docker compose up -d

# 2. サーバー起動
uv run uvicorn server:app --host 0.0.0.0 --port 9100

# 3. 動作確認
curl http://localhost:9100/health
# → {"status":"ok","redis":"connected"}
```

## systemd サービスとして常駐

```bash
# サービスファイルをコピーしてディレクトリ名を合わせる
cp gx10-mcp.service ~/.config/systemd/user/aiagent-mission-ctrl.service

# サービスファイル内の "gx10-mcp" を "aiagent-mission-ctrl" に置換
sed -i 's|gx10-mcp|aiagent-mission-ctrl|g' ~/.config/systemd/user/aiagent-mission-ctrl.service

systemctl --user daemon-reload
systemctl --user enable --now aiagent-mission-ctrl
```

---

## エンドポイント早見表

```
GET  /health                   ヘルスチェック
GET  /environment              環境サマリー (?verbose=true で全文)
GET  /contract                 API 仕様書 (?name=xxx で個別取得)
GET  /service-status           コンテナ・メモリ・ディスク状態
GET  /gpu-status               GPU 詳細メトリクス
GET  /project-context          指定プロジェクトの CLAUDE.md (?name=xxx)
GET  /doc                      docs リポジトリ内任意ファイル (?path=xxx)

POST /activity                 作業宣言（30 分で自動期限切れ）
GET  /activity                 他エージェントの作業状況一覧

POST /recording/journal        作業記録（Git 自動コミット）
POST /recording/decision       意思決定記録・ADR（Git 自動コミット）
POST /recording/contract       API 仕様書更新（Git 自動コミット）
POST /recording/issue          問題報告（Git 自動コミット）

GET  /logs                     コンテナログ (?service=xxx&lines=30)
GET  /check-endpoint           疎通確認 (?url=xxx)
POST /service/start            サービス起動（メモリ・競合チェック付き）
POST /service/stop             サービス停止（graceful）

GET  /journal                  ジャーナル検索 (?topic=xxx&limit=10)
GET  /decisions                ADR 一覧

POST /kanban/card              カード作成
POST /kanban/claim             カード取得
POST /kanban/done              カード完了
GET  /kanban/board             ボード表示
POST /kanban/reserve           リソース予約
POST /kanban/release           リソース解放
GET  /kanban/resources         リソース状況
POST /kanban/andon             アンドン（停止信号）
POST /kanban/signal            イベント送信
GET  /kanban/watch             イベント監視 (?channel=xxx&timeout=30)

WS   /ws                       WebSocket（リアルタイム通知）
```

---

## アーキテクチャ

```
Claude Code エージェント（curl / Bash）
        │
        ▼
FastAPI REST API（port 9100）
        │
        ├── routers/environment.py   — インフラ参照
        ├── routers/coordination.py  — アクティビティ管理
        ├── routers/recording.py     — 作業記録
        ├── routers/live.py          — ライブ操作
        ├── routers/history.py       — 履歴参照
        ├── routers/kanban.py        — Kanban
        └── ws/manager.py            — WebSocket + Redis pub/sub
                │
                ▼
            Redis（kanban-redis、llm-network 参加）
```

- **実行環境:** ホスト OS 上で `uv run uvicorn` で直接実行（Docker 不使用）
  - 理由: subprocess で docker / systemd を操作するため、コンテナ内からは制御できない
- **Graceful Degradation:** Redis 未接続時も環境参照・記録・ライブ操作は正常動作
- **Git 自動コミット:** write 系操作は `lib/git.py` 経由で docs リポジトリに自動コミット

---

## Kanban 設定

`kanban.yml` を編集してボード・リソース・レーン・ルールを定義する。
コードを変えずに設定のみでドメインを切り替えられる（Mechanism, not Policy）。

---

## 前提環境

- Python 3.12+ / [uv](https://docs.astral.sh/uv/)
- Docker（Redis 用）
- ARM64 (aarch64) — NVIDIA DGX Spark / ASUS Ascent GX10 を想定
- systemd（常駐サービスとして使う場合）

---

## Claude Code 連携セットアップ

サーバーを起動しただけでは Claude は自動では使ってくれない。
以下の2ステップで Claude Code と繋ぐ。

### 1. フック設定（~/.claude/settings.json）

`~/.claude/settings.json` の `"hooks"` に以下を追記する。
**パスは自分のインストールディレクトリに合わせて変更すること。**

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup",
      "hooks": [{
        "type": "command",
        "command": "python3 /path/to/aiagent-mission-ctrl/hooks/session_start.py",
        "timeout": 5
      }]
    }],
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": "python3 /path/to/aiagent-mission-ctrl/hooks/activity_guard.py",
          "timeout": 3
        }]
      },
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "uv --project /path/to/aiagent-mission-ctrl run python3 /path/to/aiagent-mission-ctrl/hooks/check_board.py your-agent-name",
          "timeout": 3
        }]
      }
    ],
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python3 /path/to/aiagent-mission-ctrl/hooks/stop_guard.py",
        "timeout": 5
      }]
    }]
  }
}
```

> **注意:** `check_board.py` のみ `redis-py` が必要なため `uv --project` 経由で実行する。
> 他の3フックは Python 標準ライブラリのみで動作するため `python3` 直接実行でよい。

### 2. CLAUDE.md への追記

プロジェクトまたはグローバルの `CLAUDE.md` に以下を追記する。
これがないと Claude は自発的に `set_activity` や `write_journal` を呼ばない。

```markdown
## aiagent-mission-ctrl 連携フロー

aiagent-mission-ctrl サーバー（:9100）が接続されている場合、以下のフローに従う。

1. `GET /activity` で他エージェントの作業状況を確認する
2. コード変更前に `POST /activity` で作業を宣言する
3. 重要な判断は `POST /recording/decision` で記録する
4. 作業完了時に `POST /recording/journal` で経緯を記録する

# curl 例
curl -s http://localhost:9100/activity
curl -s -X POST http://localhost:9100/activity \
  -H "Content-Type: application/json" \
  -d '{"agent": "your-agent-name", "description": "作業内容"}'
curl -s -X POST http://localhost:9100/recording/journal \
  -H "Content-Type: application/json" \
  -d '{"agent": "your-agent-name", "title": "タイトル", "content": "内容"}'
```

---

## セキュリティ注意

このサーバーは認証機構を持たない。**ローカル LAN 内専用**として使うこと。
外部ネットワークに公開する場合は、別途リバースプロキシで認証を追加すること。

---

## ライセンス

MIT
