# Local Agent

Ollama上の大規模言語モデル（LLM）を活用した、完全ローカル動作のエージェンティックAIチャットシステム。
ReActパターンによる自律的なツール呼び出しと、リアルタイムSSEストリーミングによるWeb UIを提供します。

## アーキテクチャ

```
Browser (any device on the network)
    │  http://<host>:8090
    ▼
┌─────────────────────────────────────────────┐
│  backend (FastAPI) :8090                    │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐ │
│  │ ReAct    │→ │ Tool      │→ │ LLM      │ │
│  │ Agent    │  │ Registry  │  │ Client   │ │
│  │ Loop     │← │           │← │ (httpx)  │ │
│  └──────────┘  └───────────┘  └──────────┘ │
│       │          │  │  │  │        │        │
│       │     ┌────┘  │  │  └───┐   │        │
│       │     ▼       ▼  ▼      ▼   │        │
│       │  web     file  shell  rag  │        │
│       │  search  ops  (Docker     │        │
│       │  (DDG)        SDK)  (Chroma)        │
└───────┼─────────────────────────────────────┘
        │                    │           │
   Ollama API          Sandbox       ChromaDB
   :11434            Container       (internal)
   (LLM)             (ephemeral)
```

## 機能

### ReActエージェント
- LLMが自律的に「思考 → ツール選択 → 実行 → 結果分析」のループを繰り返す
- 最大10イテレーションまでの多段推論に対応
- 各ステップ（thinking / tool_call / tool_result / answer）をSSEでリアルタイム配信

### 利用可能なツール（6種類）

| ツール | 説明 |
|--------|------|
| 🔍 `web_search` | DuckDuckGoによるWeb検索（API鍵不要） |
| 📄 `read_file` | ワークスペース内のファイル読み取り |
| ✏️ `write_file` | ワークスペースへのファイル書き込み |
| 📁 `list_files` | ディレクトリ一覧の取得 |
| 💻 `execute_command` | Dockerサンドボックスでの安全なコマンド実行 |
| 📚 `search_documents` | アップロードされた文書のベクトル検索（RAG） |

### コマンド実行のサンドボックス
- Docker SDKで一時コンテナを動的に生成・破棄
- ネットワーク無効化（`network_disabled: true`）
- メモリ制限（デフォルト256MB）
- タイムアウト制御（デフォルト30秒）

### RAG（検索拡張生成）
- テキストファイルをアップロードしてChromaDBにベクトルインデックス
- Ollamaの埋め込みモデルでセマンティック検索
- チャンク分割（1000文字、200文字オーバーラップ）

## セットアップ

### 前提条件
- Docker + Docker Compose
- [Ollama](https://ollama.ai/) がホスト上で稼働していること
- Ollamaに利用したいモデルがインストール済みであること

### 手順

```bash
# 1. .envを作成（WORKSPACE_HOST_PATHを実環境のパスに設定）
cp .env.example .env
vi .env

# 2. サンドボックスイメージをビルド
docker compose build sandbox

# 3. 起動
docker compose up --build -d

# 4. ログ確認
docker compose logs -f backend
```

### .env 設定項目

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `OLLAMA_MODEL` | 使用するOllamaモデル名 | `gpt-oss-120b-128k` |
| `EMBEDDING_MODEL` | 埋め込み用モデル名 | `nemotron-3-nano` |
| `AGENT_PORT` | Web UIのポート番号 | `8090` |
| `WORKSPACE_HOST_PATH` | ホスト上のworkspaceディレクトリの絶対パス | （必須） |
| `LOG_LEVEL` | ログレベル | `INFO` |

> **Note**: `OLLAMA_MODEL` と `EMBEDDING_MODEL` は、Ollamaにインストールされている任意のモデルに変更可能です。

## アクセス

- **ローカル**: http://localhost:8090
- **ネットワーク上の他マシン**: http://\<ホストのIPアドレス\>:8090

## 技術スタック

| コンポーネント | 技術 | 選定理由 |
|----------------|------|----------|
| Backend | FastAPI + httpx | 非同期処理、SSEサポート |
| Agent Pattern | ReAct（自作） | 外部依存なし、学習・カスタマイズ容易 |
| LLM接続 | Ollama OpenAI互換API | ツール呼び出しがOpenAI形式で利用可能 |
| Web検索 | duckduckgo-search | API鍵不要、軽量 |
| Vector DB | ChromaDB | 軽量、HTTP API対応 |
| Sandbox | Docker SDK | ネットワーク分離・リソース制限付き |
| Frontend | Vanilla JS + SSE | フレームワーク不要、軽量 |
| Streaming | SSE (Server-Sent Events) | POST経由のリアルタイム配信 |

## プロジェクト構成

```
local-agent/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── app/
│       ├── main.py              # FastAPIエントリ + 静的ファイル配信
│       ├── config.py            # pydantic_settings
│       ├── agents/
│       │   ├── react.py         # ReActループ（SSEストリーム）
│       │   └── schemas.py       # AgentStep, ToolCall等
│       ├── tools/
│       │   ├── registry.py      # ツール登録・ディスパッチ
│       │   ├── web_search.py    # DuckDuckGo検索
│       │   ├── file_ops.py      # ファイル操作（パストラバーサル防止）
│       │   ├── shell.py         # Dockerサンドボックス実行
│       │   └── rag.py           # ChromaDBベクトル検索
│       ├── llm/
│       │   └── client.py        # Ollama非同期クライアント
│       ├── memory/
│       │   └── conversation.py  # 会話履歴（インメモリ）
│       └── api/
│           └── routes.py        # REST + SSEエンドポイント
├── frontend/
│   ├── index.html
│   ├── css/                     # Apple HIG風デザインシステム
│   └── js/
│       ├── app.js               # メインエントリ
│       ├── api-client.js        # fetch + ReadableStream SSE
│       ├── store/state.js       # Observableステートストア
│       └── components/          # UI部品
├── sandbox/
│   └── Dockerfile               # サンドボックス用最小イメージ
└── data/
    ├── workspace/               # エージェントのファイル操作領域
    ├── chroma/                  # ChromaDB永続化
    └── uploads/                 # RAGアップロードファイル
```

## API エンドポイント

| Method | Path | 説明 |
|--------|------|------|
| POST | `/api/v1/chat` | メッセージ送信（SSEストリーム応答） |
| GET | `/api/v1/conversations` | 会話一覧取得 |
| GET | `/api/v1/conversations/:id` | 会話詳細取得 |
| DELETE | `/api/v1/conversations/:id` | 会話削除 |
| POST | `/api/v1/upload` | RAG用ドキュメントアップロード |
| GET | `/health` | ヘルスチェック |

## SSEイベント形式

`POST /api/v1/chat` が返すSSEストリームのイベント：

```
data: {"type": "conversation_id", "conversation_id": "uuid"}
data: {"type": "thinking", "reasoning": "LLMの推論過程"}
data: {"type": "tool_call", "tool_call": {"id": "...", "name": "web_search", "arguments": {...}}}
data: {"type": "tool_result", "tool_result": {"tool_call_id": "...", "content": "..."}}
data: {"type": "answer", "content": "最終回答（Markdown）"}
data: {"type": "done"}
```

## ライセンス

MIT
