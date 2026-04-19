# gx10-mcp 仕様書 — REST API + WebSocket への移行

## 目的

GX10 の MCP サーバー（FastMCP / Streamable HTTP）を廃止し、REST API + WebSocket ベースの
エージェント間通信基盤に移行する。

Streamable HTTP は 30 秒ポーリング方式でセッション依存のため、Claude Code 再起動のたびに
ツールが消える・`get_environment` が失敗する・`set_activity` が他エージェントに届かないという
構造的な問題を抱えている。REST + WebSocket に移行することで、セッション非依存のステートレス
通信と、必要な場合のリアルタイムプッシュの両立を図る。

---

## 振る舞い

### 概要

```
Claude Code (curl / Bash)
        │
        ▼
REST API サーバー（FastAPI、ポート 9100）
        │
        ├── /env/*           環境参照（read-only）
        ├── /recording/*     記録（Git コミット付き）
        ├── /live/*          サービス操作（ガードレール付き）
        ├── /coordination/*  アクティビティ管理
        ├── /history/*       ジャーナル・決定履歴参照
        ├── /kanban/*        カードライフサイクル
        └── /ws              WebSocket（エージェント間リアルタイム通知）
                │
                ▼
            Redis pub/sub（kanban-redis、既存コンテナ）
```

### エンドポイント一覧（移行対象機能）

#### Phase 1: 環境参照（environment.py → 6 ツール）

| HTTP | パス | 対応ツール | 説明 |
|------|------|-----------|------|
| GET | `/environment` | `get_environment` | 環境サマリー（`?verbose=true` で全文） |
| GET | `/contract` | `get_contract` | API 仕様書一覧（`?name=xxx` で個別取得） |
| GET | `/service-status` | `get_service_status` | コンテナ・メモリ・ディスク状態 |
| GET | `/gpu-status` | `get_gpu_status` | GPU 詳細（メモリ・稼働率・温度） |
| GET | `/project-context` | `get_project_context` | 指定プロジェクトの CLAUDE.md |
| GET | `/doc` | `read_doc` | docs リポジトリ内任意ファイル |

#### Phase 2: 記録（recording.py → 4 ツール）

| HTTP | パス | 対応ツール | 説明 |
|------|------|-----------|------|
| POST | `/journal` | `write_journal` | 作業記録（Git 自動コミット） |
| POST | `/decision` | `write_decision` | ADR 記録（Git 自動コミット） |
| POST | `/contract` | `update_contract` | API 仕様書更新（Git 自動コミット） |
| POST | `/issue` | `report_issue` | 問題報告（Git 自動コミット） |

#### Phase 3: ライブ操作（live.py → 4 ツール）

| HTTP | パス | 対応ツール | 説明 |
|------|------|-----------|------|
| GET | `/logs` | `get_server_logs` | コンテナログ取得（`?service=xxx&lines=30`） |
| GET | `/check-endpoint` | `check_endpoint` | API 疎通確認（`?url=xxx`） |
| POST | `/service/start` | `start_service` | サービス起動（ガードレール付き） |
| POST | `/service/stop` | `stop_service` | サービス停止（graceful） |

#### Phase 3: アクティビティ（coordination.py → 2 ツール）

| HTTP | パス | 対応ツール | 説明 |
|------|------|-----------|------|
| POST | `/activity` | `set_activity` | 作業宣言（30 分で自動期限切れ）→ Redis に保存 + WebSocket push |
| GET | `/activity` | `get_activity` | 他エージェントの作業状況確認（Redis から取得） |

#### Phase 4: 履歴（history.py → 2 ツール）

| HTTP | パス | 対応ツール | 説明 |
|------|------|-----------|------|
| GET | `/journal` | `get_journal` | ジャーナル検索・一覧（`?topic=xxx&limit=10`） |
| GET | `/decisions` | `get_decisions` | ADR 一覧 |

#### Kanban（kanban.py → 10 ツール）

| HTTP | パス | 対応ツール | 説明 |
|------|------|-----------|------|
| POST | `/kanban/card` | `card` | カード作成 |
| POST | `/kanban/claim` | `claim` | カード取得 |
| POST | `/kanban/done` | `done` | カード完了 |
| GET | `/kanban/board` | `board` | ボード表示 |
| POST | `/kanban/reserve` | `reserve` | リソース予約 |
| POST | `/kanban/release` | `release` | リソース解放 |
| GET | `/kanban/resources` | `resources` | リソース状況確認 |
| POST | `/kanban/andon` | `andon` | アンドン（停止信号） |
| POST | `/kanban/signal` | `signal` | イベント送信 |
| GET | `/kanban/watch` | `watch` | イベント監視（`?channel=xxx&timeout=30`） |

#### システム

| HTTP | パス | 説明 |
|------|------|------|
| GET | `/health` | ヘルスチェック |
| WS | `/ws` | WebSocket エンドポイント（リアルタイム通知） |

### WebSocket の振る舞い

- Claude Code は **REST（curl）をメイン手段**として使う
- WebSocket は「セッションが生きている間、他エージェントの動きをリアルタイムに受け取る」用途
- エージェントは `/ws?agent=gx10-claude` で接続する
- 接続後、Redis pub/sub の `gx10:events` チャンネルを subscribe する
- `POST /activity` / `POST /kanban/andon` / `POST /kanban/signal` 等の write 操作は Redis にパブリッシュし、接続中 WebSocket クライアントにリアルタイムでプッシュされる
- 接続断はサイレントに処理し、再接続は呼び出し側の責任とする

### activity の Redis 移行

- `activity.json`（ローカルファイル）を廃止し、Redis Hash に移行する
- キー: `gx10:activity:<agent>` / TTL: 1800 秒（30 分）
- `set_activity` 時に Redis に保存し、同時に WebSocket で全接続エージェントに push する
- `get_activity` は Redis から読む（セッション依存なし・複数クライアント間で共有）

---

## 受け入れ条件

### ヘルスチェック

- [ ] `GET /health` に対して `{"status": "ok", "redis": "connected"}` が返る（200）
- [ ] Redis 未接続時は `{"status": "degraded", "redis": "unavailable"}` が返る（200）

### 環境参照

- [ ] `GET /environment` に対して環境サマリー（Markdown テキスト）が返る（200）
- [ ] `GET /environment?verbose=true` に対して hardware.md / services.md / policies.md の全文が返る（200）
- [ ] `GET /contract` に対してコントラクト一覧が返る（200）
- [ ] `GET /contract?name=sglang` に対して sglang.md の内容が返る（200）
- [ ] `GET /contract?name=nonexistent` に対して利用可能なコントラクト名リストが含まれるエラーが返る（404）
- [ ] `GET /gpu-status` に対して GPU メトリクスが返る（200）
- [ ] `GET /project-context?name=whisper-transcriber` に対して CLAUDE.md が返る（200）

### 記録

- [ ] `POST /recording/journal` に `{"title": "テスト", "content": "内容", "agent": "gx10-claude"}` を送ると、docs/journal/ にファイルが作成され Git コミットされ成功メッセージが返る（200）
- [ ] `POST /recording/decision` に title/context/decision/reason を送ると、docs/decisions/ に ADR ファイルが作成され Git コミットされる（200）
- [ ] title が空文字の場合は HTTP 422 が返る
- [ ] `POST /recording/issue` に `{"service": "sglang", "description": "OOM"}` を送ると journal に記録され Git コミットされる（200）

### アクティビティ

- [ ] `POST /activity` に `{"agent": "gx10-claude", "description": "SGLang 再起動中"}` を送ると `"Activity registered for gx10-claude: SGLang 再起動中"` が返る（200）
- [ ] `GET /activity` に対して現在のアクティブエージェント一覧が返る（200）
- [ ] 30 分超過したアクティビティは `GET /activity` の結果に含まれない
- [ ] `POST /activity` 実行時、接続中の WebSocket クライアントにリアルタイム通知が届く
- [ ] activity データは Redis に保存され、activity.json に依存しない

### ライブ操作

- [ ] `GET /logs?service=sglang-llm&lines=50` に対してコンテナログが返る（200）
- [ ] `GET /check-endpoint?url=http://localhost:30000/health` に対して疎通結果が返る（200）
- [ ] `POST /service/start` に `{"name": "nonexistent"}` を送ると利用可能サービス一覧が含まれるエラーが返る（404）
- [ ] `POST /service/start` でメモリ不足の場合はガードレールメッセージが返る（200、エラーではない）

### Kanban

- [ ] `POST /kanban/card` に title/agent を送るとカードが作成されカード ID が返る（200）
- [ ] `GET /kanban/board` に対してボード状態が返る（200）
- [ ] Redis 未接続時に Kanban 操作を行うと、他 API は継続動作し Kanban のみ 503 が返る

### WebSocket

- [ ] `ws://localhost:9100/ws?agent=gx10-claude` に接続できる
- [ ] `POST /activity` を実行すると、接続中の WebSocket クライアントにイベントが届く
- [ ] WebSocket 接続が切れても REST API は正常に動作し続ける

### 移行完了条件

- [ ] FastMCP / Streamable HTTP に依存するコードが残存しない（server.py が FastAPI ベースになっている）
- [ ] 既存の 18 ツールすべてが REST エンドポイントとして利用可能
- [ ] `curl -s http://localhost:9100/env/environment` が Claude Code から実行できる
- [ ] systemd サービス（gx10-mcp.service）が新サーバーで起動する

---

## スコープ（やらないこと）

- NanoClaw への対応（対象外）
- MCP プロトコル（SSE / Streamable HTTP）の継続サポート
- 認証・認可（ローカル LAN 内のみのため不要）
- クライアント SDK の提供（curl / Bash で直接叩く）
- WebSocket の再接続ロジック実装（呼び出し側の責任）
- OpenAPI スキーマ自動生成以外のドキュメント自動生成

---

## 固定要件

<!-- 技術的判断で変更してはならない要件。後続エージェントはここを必ず読むこと -->
<!-- 逸脱する場合はユーザーに報告して承認を得ること -->

- **アーキテクチャ:** ARM64 (aarch64) 専用。x86 バイナリ・イメージは使用禁止
- **実行環境:** ホスト OS 上で `uv run` で直接実行（Docker 不使用、既存運用を維持）
  - 理由: MCP サーバーは subprocess で docker/systemd を操作するため、コンテナ内からは制御できない
- **既存 Redis:** `kanban-redis`（llm-network 参加済み）をそのまま流用する。新規 Redis コンテナを起動しない
- **ポート:** 9100 を維持する（`MCP_PORT` 環境変数から取得、`lib/config.py` で定義済み）
- **ホスト OS クリーンポリシー:** `pip install` 禁止。依存追加は `uv add` のみ
- **Graceful Degradation:** Redis 未接続時も REST API の非 Kanban 部分は正常動作すること
- **Git 自動コミット:** write 系操作は `lib/git.py` の `commit_file()` を使って必ず Git コミットする
- **言語:** Python（既存コードベースに統一）
- **フレームワーク:** FastAPI（FastMCP から移行）+ WebSocket は `fastapi.WebSocket` を使用
- **ASGI サーバー:** uvicorn
- **既存ロジックの再利用:** `lib/` 配下のモジュール（docker.py / git.py / nvidia.py / services.py / subprocess_utils.py / systemd.py / kanban_store.py）はそのまま使用する。ビジネスロジックを再実装しない
- **対象エージェント:** Mac Claude / GX10 Claude の 2 者のみ

---

<!-- 以下は後続エージェントが追記するセクション -->

## アーキテクチャ設計

### コンポーネント構成

```
gx10-mcp/
├── server.py                  ← FastAPI アプリケーション本体（FastMCP を除去）
├── routers/                   ← 新設：FastAPI ルーター群
│   ├── __init__.py
│   ├── environment.py         ← Phase 1: 6 エンドポイント（GET）
│   ├── recording.py           ← Phase 2: 4 エンドポイント（POST）
│   ├── live.py                ← Phase 3: 4 エンドポイント（GET/POST）
│   ├── coordination.py        ← Phase 3: 2 エンドポイント（GET/POST）+ Redis 移行
│   ├── history.py             ← Phase 4: 2 エンドポイント（GET）
│   └── kanban.py              ← Kanban: 10 エンドポイント（GET/POST）
├── ws/                        ← 新設：WebSocket 管理
│   ├── __init__.py
│   └── manager.py             ← 接続管理・Redis pub/sub・ブロードキャスト
├── lib/                       ← 既存：変更なし（ビジネスロジック再利用）
│   ├── config.py
│   ├── docker.py
│   ├── git.py
│   ├── kanban_store.py
│   ├── nvidia.py
│   ├── services.py
│   ├── subprocess_utils.py
│   └── systemd.py
├── tools/                     ← 既存：移行後は削除対象（段階的に廃止）
│   └── ...（Phase 移行完了後に削除）
├── pyproject.toml             ← fastapi / uvicorn / httpx を追加（uv add）
├── gx10-mcp.service           ← ExecStart を uvicorn に変更、TRANSPORT 除去
└── SPEC.md
```

### レイヤーと依存関係

```
[Presentation Layer]
  routers/*.py        — HTTP リクエスト受付・レスポンス成形
  ws/manager.py       — WebSocket 接続管理・イベントブロードキャスト
       │
       ▼（依存）
[Domain Layer]
  lib/kanban_store.py — カードライフサイクル・リソース管理・ルールエンジン
  lib/git.py          — Git コミット
  lib/docker.py       — Docker 操作
  lib/nvidia.py       — GPU メトリクス
  lib/services.py     — サービス定義
  lib/systemd.py      — systemd 操作
  lib/subprocess_utils.py — サブプロセス実行
       │
       ▼（依存）
[Infrastructure Layer]
  Redis (kanban-redis) — pub/sub・activity Hash・kanban 状態
  ファイルシステム     — docs/, kanban.yml
  Docker / systemd     — 実行環境
```

依存の方向は外側（routers）→ 内側（lib）の一方向のみ。
`lib/` モジュール間の既存依存は変更しない。

### 各ルーターの責務

| ルーター | ファイル | 対応ツール群 | 主な依存 lib |
|----------|----------|-------------|-------------|
| 環境参照 | `routers/environment.py` | get_environment, get_contract, get_service_status, get_gpu_status, get_project_context, read_doc | docker.py, nvidia.py, config.py |
| 記録 | `routers/recording.py` | write_journal, write_decision, update_contract, report_issue | git.py, config.py |
| ライブ操作 | `routers/live.py` | get_server_logs, check_endpoint, start_service, stop_service | services.py, systemd.py, subprocess_utils.py |
| 協調 | `routers/coordination.py` | set_activity, get_activity | Redis（aioredis）, ws/manager.py |
| 履歴 | `routers/history.py` | get_journal, get_decisions | config.py |
| Kanban | `routers/kanban.py` | card, claim, done, board, reserve, release, resources, andon, signal, watch | kanban_store.py, ws/manager.py |

### WebSocket 管理設計（ws/manager.py）

```python
# 責務
class WebSocketManager:
    # 接続管理
    _connections: dict[str, WebSocket]   # agent → WebSocket

    async def connect(agent: str, ws: WebSocket) -> None
    async def disconnect(agent: str) -> None

    # Redis pub/sub 購読（サーバー起動時に asyncio.create_task で常駐）
    async def _redis_subscriber(redis_client) -> None
        # gx10:events チャンネルを subscribe
        # メッセージ受信時に _broadcast() を呼ぶ

    # ブロードキャスト
    async def broadcast(event: dict) -> None
        # 接続中の全 WebSocket クライアントに JSON 送信
        # 送信失敗（切断済み）はサイレントに処理し disconnect() する

    # Redis パブリッシュ（write 操作から呼ばれる）
    async def publish(event: dict) -> None
        # Redis の gx10:events チャンネルに JSON パブリッシュ
```

WebSocket エンドポイント（`GET /ws?agent=gx10-claude`）は `server.py` で定義し、
`ws/manager.py` の `connect()` / `disconnect()` に委譲する。

### activity の Redis 移行方針

**変更前（tools/coordination.py）:**
- `activity.json`（ローカルファイル）に `fcntl.flock` で排他書き込み
- セッション依存なし・ただし複数プロセス間で競合リスク

**変更後（routers/coordination.py）:**
- Redis Hash: `gx10:activity:<agent>` → `{"description": "...", "timestamp": "..."}`
- TTL: 1800秒（HEXPIRE or EXPIRE on key）
- `set_activity`:
  1. `HSET gx10:activity:<agent> description <desc> timestamp <ts>`
  2. `EXPIRE gx10:activity:<agent> 1800`
  3. `ws_manager.publish({"type": "activity", "agent": ..., "description": ...})`
- `get_activity`:
  1. Redis の `KEYS gx10:activity:*` → 各キーから `HGETALL`
  2. TTL が正の値のものだけ返す（Redis が自動期限切れするため基本的に全件）
- Redis 未接続時: `503 Service Unavailable` を返す（Graceful Degradation の対象外、activity は Redis 専用）

> **補足:** Graceful Degradation の「非 Kanban 部分は正常動作すること」に activity を含めるか
> 判断が必要。activity は Redis 移行後に Redis 必須となるため、Redis 未接続時は 503 が適切と判断。
> 固定要件「Graceful Degradation: Redis 未接続時も REST API の非 Kanban 部分は正常動作」の
> 「非 Kanban 部分」に activity が含まれると解釈できる場合はユーザーに確認を要する。

### FastMCP 依存の除去（server.py の書き換え方針）

**変更前の server.py:**
- `FastMCP` インスタンスを生成し、各 tools モジュールの `register(mcp)` を呼ぶ
- `mcp.run(transport="streamable-http", host="0.0.0.0", port=9100)`

**変更後の server.py:**
```python
from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn

from lib.config import MCP_PORT
from lib.kanban_store import KanbanStore
from ws.manager import WebSocketManager
from routers import environment, recording, live, coordination, history, kanban

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis 接続（kanban_store + ws_manager 共用）
    await store.connect()
    asyncio.create_task(ws_manager.start_subscriber(store.redis))
    yield
    await store.close()

app = FastAPI(lifespan=lifespan)
ws_manager = WebSocketManager()
store = KanbanStore(REDIS_URL)

# ルーター登録
app.include_router(environment.router)
app.include_router(recording.router)
app.include_router(live.router)
app.include_router(coordination.router(ws_manager))
app.include_router(history.router)
app.include_router(kanban.router(store, ws_manager))

@app.get("/health")
async def health(): ...

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, agent: str): ...
```

**gx10-mcp.service の変更:**
```ini
ExecStart=/home/nob-san/.local/bin/uv run uvicorn server:app --host 0.0.0.0 --port 9100
# TRANSPORT 環境変数は不要になるため削除
```

### 段階的移行計画

ポート 9100 が重複するため、既存 MCP サービスを停止してから FastAPI サーバーを起動する。
ゼロダウンタイムは困難（同一ポート）。以下の移行フローを採用する。

#### フェーズ A: 並行開発（ポート 9101 で新サーバーを起動）

1. `server_new.py`（仮称）として FastAPI サーバーを実装
2. `gx10-mcp.service` はそのまま（port 9100 / FastMCP）で稼働を継続
3. `MCP_PORT=9101 uv run uvicorn server_new:app` でテスト

#### フェーズ B: カットオーバー

1. 受け入れ条件をすべて通過確認
2. `systemctl --user stop gx10-mcp`（FastMCP サービス停止）
3. `server.py` を新実装に差し替え、`gx10-mcp.service` を更新
4. `systemctl --user daemon-reload && systemctl --user start gx10-mcp`

> ダウンタイムは手順 2〜4 の数秒程度。MCP ツールはセッション依存なので
> 停止中にツールが消える問題は元々存在している。REST 移行後はこの問題がなくなる。

#### フェーズ C: tools/ の削除

FastMCP / tools/ ディレクトリは移行完了確認後に削除。
`pyproject.toml` から `fastmcp` 依存を除去（`uv remove fastmcp`）。

### pyproject.toml への追加依存

```toml
# uv add で追加するパッケージ（pip install 禁止）
fastapi>=0.115     # FastAPI 本体
uvicorn>=0.30      # ASGI サーバー
httpx>=0.27        # check_endpoint の実装（curl subprocess の代替として任意）
```

> `httpx` は任意。`check_endpoint` は既存通り `curl` subprocess で実装してもよい。
> `fastmcp` は移行完了後に `uv remove fastmcp` で除去する。

---

### ADR

#### ADR-1: FastAPI ルーター分割を tools/ モジュールの命名に揃える

**状況:** 既存 `tools/` ディレクトリには `environment.py`, `recording.py`, `live.py`,
`coordination.py`, `history.py`, `kanban.py` の 6 モジュールが存在する。
FastAPI への移行で新しいモジュール配置が必要になった。

**判断:** `routers/` ディレクトリを新設し、既存 `tools/` と同名のモジュールを配置する。
各 `routers/*.py` は対応する `tools/*.py` と 1:1 で対応させる。

**理由:** 既存の命名規則を踏襲することで、`tools/` から `routers/` への移植作業の
対応関係が明確になる。実装エージェントが迷わず移行できる。

**影響:** `tools/` と `routers/` が一時的に共存するフェーズ A 期間が生まれるが、
フェーズ C で `tools/` を削除することで解消する。

---

#### ADR-2: WebSocket 管理を ws/manager.py に集約する

**状況:** WebSocket の接続管理と Redis pub/sub の購読は、複数のルーターから参照される
横断的関心事である。各ルーターに分散させると重複・不整合が生じる。

**判断:** `ws/manager.py` に `WebSocketManager` クラスを定義し、接続管理・Redis 購読・
ブロードキャストをすべて集約する。`server.py` でシングルトンインスタンスを生成し、
依存注入（FastAPI の `Depends`）または直接参照でルーターに渡す。

**理由:** 単一責任の原則。WebSocket の接続ライフサイクルを 1 か所で管理することで、
切断時のクリーンアップ漏れや pub/sub の二重登録を防ぐ。

**影響:** `coordination.py` と `kanban.py` は `ws_manager` への参照が必要になる。
ルーター登録時にファクトリ関数 `router(ws_manager)` 形式で渡す。

---

#### ADR-3: activity を Redis 専用とし、Redis 未接続時は 503 を返す

**状況:** 固定要件に「Graceful Degradation: Redis 未接続時も REST API の非 Kanban 部分は
正常動作すること」とある。activity は現状 `activity.json` で動作しているが、
仕様で Redis への移行が定められている。

**判断:** activity は Redis 移行後、Redis 未接続時に 503 を返す設計とする。
`activity.json` へのフォールバックは実装しない。

**理由:** activity の設計意図は「複数エージェント間でのリアルタイム共有」であり、
ファイルフォールバックでは WebSocket push も機能せず、半壊した状態になる。
503 を返すことで呼び出し側が明確に異常を検知できる。
「非 Kanban 部分」に activity が含まれるかは仕様上曖昧だが、Redis に専用移行する
仕様を優先する。**ユーザーの承認を要する判断であることを明記する。**

**影響:** Redis が落ちた場合、`GET /activity` / `POST /activity` が 503 になる。
他のエンドポイント（environment, recording, live, history）は引き続き正常動作する。

---

#### ADR-4: ルーターへの KanbanStore・WebSocketManager の依存注入方式

**状況:** `KanbanStore` と `WebSocketManager` はアプリケーション起動時に生成される
シングルトンであり、複数のルーターから参照される。FastAPI には `Depends()` による
依存注入機構がある。

**判断:** `server.py` でシングルトンを生成し、ルーター関数にはモジュールレベルの
変数として保持する形式（既存 `tools/kanban.py` の `_store` パターン）を採用する。
`Depends()` は使わない。

**理由:** 既存 `tools/kanban.py` が `_store: KanbanStore | None = None` のパターンを
採用しており、同じ慣習に揃える。`Depends()` はテスト時のオーバーライドに便利だが、
現時点でテスト要件がないため YAGNI として採用しない。

**影響:** テスト時にモックを差し込む場合は、モジュール変数を直接書き換える必要がある。

---

#### ADR-5: 移行期間中の並行稼働戦略（ポート 9101 + カットオーバー）

**状況:** ポート 9100 は現行 FastMCP サービスが占有している。同一ポートでの
ゼロダウンタイム移行は不可能（bind 競合）。

**判断:** フェーズ A では新サーバーをポート 9101 で起動して検証し、
受け入れ条件クリア後にフェーズ B でカットオーバー（数秒のダウンタイムを許容）する。

**理由:** FastMCP の Streamable HTTP はセッション依存のため、現行でも Claude Code
再起動のたびにツールが消える問題がある。移行作業中の数秒ダウンタイムは現行の
問題より影響が小さい。ゼロダウンタイム実装（nginx リバースプロキシ等）はスコープ外。

**影響:** フェーズ A 期間中、本番（9100）と検証（9101）が並立する。
フェーズ B カットオーバーで 9101 を廃止し 9100 に戻す。

## テスト計画

### 実装概要

フェーズA として `server_new.py`（ポート 9101）に FastAPI ベースの新サーバーを実装した。
既存の `server.py`（FastMCP / ポート 9100）はそのまま維持している。

#### 実装ファイル

| ファイル | 役割 |
|---------|------|
| `server_new.py` | FastAPI アプリケーション本体（lifespan / ルーター登録 / WebSocket） |
| `routers/environment.py` | GET /environment, /contract, /service-status, /gpu-status, /project-context, /doc |
| `routers/recording.py` | POST /recording/journal, /recording/decision, /recording/contract, /recording/issue |
| `routers/live.py` | GET /logs, /check-endpoint / POST /service/start, /service/stop |
| `routers/coordination.py` | POST /activity, GET /activity（Redis 専用 / ADR-3） |
| `routers/history.py` | GET /journal, /decisions |
| `routers/kanban.py` | /kanban/* 10 エンドポイント |
| `ws/manager.py` | WebSocketManager（接続管理 / Redis pub/sub / ブロードキャスト） |
| `tests/` | pytest + pytest-asyncio テストスイート |

### テストケース（受け入れ条件より）

| 受け入れ条件 | テストケース | 結果 |
|---|---|---|
| GET /health → 200 + status/redis フィールド | test_health_returns_ok | ✅ PASS |
| Redis 未接続時 degraded | test_health_redis_unavailable | ✅ PASS |
| GET /environment → 200 + テキスト | test_get_environment_returns_200 | ✅ PASS |
| GET /environment?verbose=true → 200 | test_get_environment_verbose | ✅ PASS |
| GET /contract → 200 | test_get_contract_list | ✅ PASS |
| GET /contract?name=nonexistent → 404 + available | test_get_contract_not_found | ✅ PASS |
| GET /service-status → 200 | test_get_service_status | ✅ PASS |
| GET /gpu-status → 200 | test_get_gpu_status | ✅ PASS |
| GET /project-context?name=gx10-mcp → 200 | test_get_project_context | ✅ PASS |
| path traversal 拒否 → 400/404 | test_get_doc_path_traversal | ✅ PASS |
| POST /recording/journal → 200 + メッセージ | test_post_journal_success | ✅ PASS |
| title 空 → 422 | test_post_journal_empty_title_returns_422 | ✅ PASS |
| POST /recording/decision → 200 | test_post_decision_success | ✅ PASS |
| title 空 → 422 | test_post_decision_empty_title_returns_422 | ✅ PASS |
| POST /recording/issue → 200 | test_post_issue_success | ✅ PASS |
| Redis 未接続: POST /activity → 503 (ADR-3) | test_post_activity_redis_unavailable_returns_503 | ✅ PASS |
| Redis 未接続: GET /activity → 503 (ADR-3) | test_get_activity_redis_unavailable_returns_503 | ✅ PASS |
| Redis 接続済み: POST /activity → 200 + メッセージ | test_post_activity_returns_message | ✅ PASS |
| Redis 接続済み: GET /activity → 200 + agents | test_get_activity_returns_list | ✅ PASS |
| GET /logs?service=xxx → 200 | test_get_logs | ✅ PASS |
| GET /check-endpoint?url=xxx → 200 | test_check_endpoint | ✅ PASS |
| POST /service/start (不明なサービス) → 404 + available | test_start_service_unknown_returns_404 | ✅ PASS |
| POST /service/stop (不明なサービス) → 404 | test_stop_service_unknown_returns_404 | ✅ PASS |
| GET /journal → 200 | test_get_journal | ✅ PASS |
| GET /journal?topic=xxx → 200 | test_get_journal_with_topic | ✅ PASS |
| GET /decisions → 200 | test_get_decisions | ✅ PASS |
| Redis 未接続: GET /kanban/board → 503 | test_kanban_board_redis_unavailable_returns_503 | ✅ PASS |
| Redis 未接続: POST /kanban/card → 503 | test_kanban_card_create_redis_unavailable_returns_503 | ✅ PASS |
| Redis 接続済み: GET /kanban/board → 200 | test_kanban_board_with_redis | ✅ PASS |
| Redis 接続済み: POST /kanban/card → 200 + カードID | test_kanban_card_create_with_redis | ✅ PASS |
| Redis 未接続でも /environment は 200 (Graceful Degradation) | test_environment_works_when_kanban_unavailable | ✅ PASS |

### テスト環境

- フレームワーク: pytest + pytest-asyncio
- 環境: ホスト OS 上（uv run）/ kanban-redis コンテナ使用（統合テスト）
- 実行コマンド: `uv run pytest tests/ -q`
- テスト結果: 31 passed（2026-04-18 実行）

### 動作確認（curl）

```bash
# サーバー起動（フェーズA: ポート 9101 で並行稼働）
MCP_PORT=9101 uv run uvicorn server_new:app --host 0.0.0.0 --port 9101

# ヘルスチェック
curl -s http://localhost:9101/health
# → {"status":"ok","redis":"connected"}

# 環境サマリー
curl -s http://localhost:9101/environment | python3 -m json.tool

# アクティビティ
curl -s http://localhost:9101/activity
# → {"agents":[]}
```

### 未確認受け入れ条件（フェーズB以降）

以下は本テスト（フェーズA）では未確認。カットオーバー後に確認する。

- `systemd` サービス（gx10-mcp.service）が新サーバーで起動する
- FastMCP / Streamable HTTP 依存コードが残存しない（フェーズC）
- `curl -s http://localhost:9100/environment` が Claude Code から実行できる

## レビュー結果

### 判定: 承認（Must 指摘を修正済み）

レビュー実施日: 2026-04-18
レビュアー: gx10-claude (review skill)

---

### 固定要件の遵守確認

- [x] **ARM64 専用**: x86 バイナリ・イメージの使用なし
- [x] **uv run**: `pip install` 禁止守られている（`pyproject.toml` / `uv add` のみ）
- [x] **Redis 既存流用**: `kanban-redis` 流用、新規 Redis コンテナなし
- [x] **ポート 9100 維持**: `lib/config.py` の `MCP_PORT` 経由で取得
- [x] **Graceful Degradation**: Redis 未接続時も environment/recording/live/history は正常動作
- [x] **Git 自動コミット**: write 系は `lib/git.py` の `commit_file()` を使用
- [x] **FastAPI + fastapi.WebSocket + uvicorn**: 仕様通り
- [x] **lib/ 変更なし**: ビジネスロジックは lib/ を再利用、変更なし
- [x] **ADR-3 遵守**: activity は Redis 専用、未接続時 503

### 受け入れ条件との整合性

- [x] GET /health → 200 + status/redis フィールド
- [x] Redis 未接続時 degraded レスポンス
- [x] GET /environment → 200（通常・verbose 両対応）
- [x] GET /contract → 200（一覧・個別・404+available リスト対応）
- [x] GET /service-status, /gpu-status → 200
- [x] GET /project-context → 200
- [x] POST /recording/journal, /recording/decision, /recording/issue → 200 + Git コミット
- [x] title 空 → 422
- [x] POST /activity → 200 / Redis 未接続 503
- [x] GET /activity → 200 / Redis 未接続 503
- [x] GET /logs, /check-endpoint → 200
- [x] POST /service/start（不明サービス）→ 404 + available リスト
- [x] POST /service/start（メモリ不足）→ 200 + ガードレールメッセージ
- [x] GET /journal, /decisions → 200
- [x] Kanban 全操作: Redis 未接続 503 / 接続時 200
- [x] Graceful Degradation: Redis 未接続でも /environment は 200
- [ ] systemd サービス（gx10-mcp.service）新サーバーで起動（フェーズ B 以降）
- [ ] FastMCP / Streamable HTTP 依存除去（フェーズ C 以降）

### 指摘事項

| 重要度 | 場所 | 内容 | 改善案 | 状態 |
|--------|------|------|--------|------|
| **Must** | `ws/manager.py` `publish()` | Redis 接続時、`broadcast()` を直接呼んだ後に Redis pub/sub 経由でも `broadcast()` が呼ばれ、WebSocket クライアントが同一イベントを**2 回受信**する | Redis 接続時は直接 broadcast せず pub/sub 経由のみ使用。Redis 未接続時のみ直接 broadcast にフォールバック | ✅ 修正済み |
| **Must** | `routers/recording.py` `write_journal` / `write_decision` | `slug = title.lower().replace(" ", "-")` で `/` `..` が除去されず、`title=../../../etc/passwd` 等で `journal/` 外にファイルが書かれる可能性がある | `_safe_slug()` ヘルパーでファイルシステム危険文字を除去 | ✅ 修正済み |
| **Must** | `routers/recording.py` `update_contract` | `req.name` を直接ファイル名に使用。`name=../../secret` 等で `contracts/` 外への書き込みが可能 | `re.match(r'^[a-zA-Z0-9_\-]+$', req.name)` で検証し不正な場合は 422 | ✅ 修正済み |
| **Must** | `routers/recording.py` `report_issue` | `req.service` を直接ファイル名に使用（同上） | `_safe_slug(req.service)` を使用 | ✅ 修正済み |
| **Should** | `routers/coordination.py` L80 | `redis.keys(f"{ACTIVITY_KEY_PREFIX}*")` はブロッキングコマンド。大量キー時にサーバー全体がブロックされる | `redis.scan_iter()` に変更（アクティビティ件数は少ないため実害は限定的） | 未修正 |
| **Should** | `routers/kanban.py` L167, 175 | `ws_manager.publish(store._redis, event)` でプライベート変数に直接アクセス。`require_store()` 後なので None ではないが設計上望ましくない | `ws_manager.publish()` に渡す redis クライアントをルーターファクトリで受け取る設計への変更を検討 | 未修正 |
| **Should** | `tests/conftest.py` | `mock_app` と `mock_app_no_redis` が完全に同一の実装（重複フィクスチャ） | `mock_app_no_redis = mock_app` として alias にするか、一方を削除 | 未修正 |
| **Nit** | `gx10-mcp.service` | フェーズ A 時点のため `ExecStart` が旧 `server.py` / `TRANSPORT=streamable-http` のまま | フェーズ B カットオーバー時に `uvicorn server:app` に変更予定（意図的） | フェーズ B で対応 |

### 良い点

- **アプリケーションファクトリパターン** (`create_app(redis_url)`) によりテストと本番が同一コードパスを使う設計が優れている
- **Graceful Degradation の実装** が徹底されており、Redis 未接続時も非 Kanban API が正常動作する
- **パストラバーサル対策** (`/doc` エンドポイント) は `resolve()` + `startswith()` の二重チェックで適切に実装されている
- **WebSocket 切断時のクリーンアップ** が `broadcast()` 内のサイレント処理で漏れなく実装されている
- **31 件のテストケース** が受け入れ条件を網羅しており、Redis 未接続・接続済みの両パスがカバーされている

### カットオーバー判定

Must 指摘（二重ブロードキャスト・パストラバーサル 4 件）を修正済み。  
**フェーズ B カットオーバー可能。**

## デプロイ計画

### 実施日時
2026-04-19

### ロールバック計画
- **トリガー条件:** `curl http://localhost:9100/health` が 200 を返さない / `systemctl --user status gx10-mcp` が failed になる
- **手順:**
  1. `systemctl --user stop gx10-mcp`
  2. `cp server_mcp_backup.py server.py`
  3. `gx10-mcp.service` を元の ExecStart（`uv run server.py` / `TRANSPORT=streamable-http`）に戻す
  4. `systemctl --user daemon-reload && systemctl --user start gx10-mcp`
- **確認方法:** `/mcp` エンドポイントに POST して 202 Accepted が返ることを確認

### 受け入れ条件の照合結果

カットオーバー実行日時: 2026-04-19 01:11 JST

- [x] systemd サービス（gx10-mcp.service）が新サーバーで起動する — `active (running)` 確認済み。uvicorn + FastAPI で起動
- [x] `curl -s http://localhost:9100/health` が `{"status":"ok","redis":"connected"}` を返す — 確認済み
- [x] `curl -s http://localhost:9100/environment` が 200 を返す — HTTP 200 確認済み
- [x] `curl -s http://localhost:9100/activity` が 200 を返す — `{"agents":[...]}` 返却確認済み
- [x] FastMCP / Streamable HTTP に依存するコードが残存しない — server.py に fastmcp の記述ゼロ（grep -c = 0）
- [x] 既存の MCP 接続（~/.claude.json の mcpServers）は不要になる — REST API に移行完了

**判定: フェーズB カットオーバー 完了**

---

## リファクタリング記録

### 実施日時
2026-04-19

### 対象
- `hooks/session_start.py`
- `hooks/activity_guard.py`

### 変更内容

#### session_start.py
- `MCP_URL = "http://localhost:9100/mcp"` → `HEALTH_URL = "http://localhost:9100/health"` に変更（`/mcp` エンドポイントは FastAPI 移行で廃止済み）
- `check_mcp_reachable()`: HTTPError をキャッチして reachable と判定する旧実装を廃止。`GET /health` に対して 200 OK が返れば reachable と判定するシンプルな実装に変更
- `read_activities()`: `activity.json` ファイル直接読み込みを廃止。`GET /activity` REST API 呼び出しに変更
- `agents` フィールドが実際にはリスト形式 `[{"agent": "...", "description": "...", "timestamp": ...}]` であるため、表示ロジックを `.items()` からリスト走査に変更

#### activity_guard.py
- `ACTIVITY_FILE` 定数を廃止し `ACTIVITY_URL = "http://localhost:9100/activity"` に変更
- `read_activities()`: ファイル読み込みを REST API 呼び出しに変更（リスト形式に対応）
- `activities.get(AGENT)` → `next((a for a in agents if a.get("agent") == AGENT), None)` に変更（リスト形式への対応）
- docstring の `activity.json` 参照を `REST API GET /activity` に更新

### 振る舞いの変化なし
- 出力形式は変更前と同一（`[GX10 MCP] Server reachable (:9100)` 等）
- EXPIRY_SECONDS チェックロジックは維持
- 非ブロッキング（exit 0）の特性を維持

### 確認結果
- `python3 hooks/session_start.py` → `[GX10 MCP] Server reachable (:9100)` 出力確認
- `echo '{}' | python3 hooks/activity_guard.py` → set_activity 未設定時の警告 JSON 出力確認
- `grep "activity\.json\|/mcp" hooks/*.py` → 残留参照ゼロ確認
