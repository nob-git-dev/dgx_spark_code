# 開発ポリシー・制約

DGX Spark上で開発を行う際（またはリモートからDGX Sparkを利用するアプリを作る際）に従うべきルール。

## ホストOSクリーンポリシー（最重要）

ホストOSへのソフトウェアインストールを最小限に保つ。

- **pip install 禁止** — `pip install`, `sudo pip install`, グローバルconda は一切使用しない
- **apt/dnf** — git, curl, docker, htop, drivers等のシステム管理ツールのみ許可
- **Python環境の優先順位:**
  1. **Docker（最優先）** — アプリ・サービス・スクリプトは `docker compose` でコンテナ化
  2. **uv（最終手段）** — ホスト上での直接実行が避けられない場合のみ
     - CLIツール: `uv tool install`
     - スクリプト実行: `uv run`

## ARM64必須

- **アーキテクチャ:** aarch64 — x86バイナリは動作しない
- Dockerイメージは **`linux/arm64`** 対応を必ず確認する
- ARM64非対応のツールやバイナリを提案しない

## Docker運用ルール

- インフラ（DB, Webサーバー, 各種サービス）は必ず `docker compose` でコンテナ化
- LLM接続が必要なプロジェクトは `llm-network`（external）に参加させる:
  ```yaml
  networks:
    llm-network:
      external: true
  ```
- プロジェクト内にLLMを内包しない — 共有SGLangサービスにAPI接続する

## LLM接続の設計原則

- **Dockerコンテナ内から:**
  - SGLang: `http://sglang-llm:{{SGLANG_PORT}}/v1`
  - Ollama: `http://host.docker.internal:{{OLLAMA_PORT}}/v1`
- **ホストから:** `http://localhost:{{SGLANG_PORT}}/v1` / `http://localhost:{{OLLAMA_PORT}}/v1`
- **リモート端末から:** IPアドレスを使用（`services.md` 参照）
- SGLangが起動していない場合は `~/projects/sglang/` で `docker compose up -d` を先に実行

## メモリ安全設計

DGX Sparkの128GB統合メモリは CPU/GPU で共有される。大型モデルのロード時にOOMでフリーズするリスクがある。

- 大型モデル（80GB超）には `num_ctx` を制限して KVキャッシュの膨張を防ぐ
- モデル重み + KVキャッシュ + OS/カーネル の合計が 120GB を超えないようにする
- 複数モデルの同時ロードに注意（Ollamaは自動アンロードするが、リクエスト次第で同時ロードされる）

## ソフトウェア設計原則

- UI層・ロジック層・データ層を分離する
- バックエンドは常にAPIとして設計する（WebUI・エージェント・CLIが同じAPIを使える）
- 設定値・APIキー・パスは外部ファイル（.env / config.yaml）に分離する
- 1ファイルの肥大化を避ける（目安: 300行超で分割検討）

## 新プロジェクト開始時の手順

1. ディレクトリ構造を提示してユーザーの確認を得る
2. README.md を生成する
3. docker-compose.yml を作成してから実装を始める
