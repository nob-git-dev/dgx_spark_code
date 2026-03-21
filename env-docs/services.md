# 公開サービス一覧

DGX Spark上で稼働する（または起動可能な）サービスとその接続情報。

## LLM推論

### SGLang（メイン推論基盤）

- **プロジェクト:** `~/projects/sglang/`
- **コンテナ名:** `sglang-llm`
- **イメージ:** `lmsysorg/sglang:spark`
- **モデル:** {{SGLANG_MODEL}}（表示名: {{SGLANG_SERVED_NAME}}）
- **ポート:** {{SGLANG_PORT}}
- **プロトコル:** OpenAI互換 API
- **Docker内から:** `http://sglang-llm:{{SGLANG_PORT}}/v1`（llm-network経由）
- **ホストから:** `http://localhost:{{SGLANG_PORT}}/v1`
- **LAN/VPNから:** `http://{{LAN_IP}}:{{SGLANG_PORT}}/v1` / `http://{{VPN_IP}}:{{SGLANG_PORT}}/v1`
- **Docker Network:** llm-network（external）
- **状態:** 常時起動ではない（必要時に `docker compose up -d`）
- **備考:** `--mem-fraction-static 0.75`、RadixAttention KVキャッシュ再利用

### Ollama（サブモデル・実験用）

- **実行形態:** ホストOS上の systemd サービス
- **ポート:** {{OLLAMA_PORT}}
- **プロトコル:** Ollama API（OpenAI互換エンドポイントあり）
- **Docker内から:** `http://host.docker.internal:{{OLLAMA_PORT}}/v1`
- **ホストから:** `http://localhost:{{OLLAMA_PORT}}/v1`
- **LAN/VPNから:** `http://{{LAN_IP}}:{{OLLAMA_PORT}}/v1` / `http://{{VPN_IP}}:{{OLLAMA_PORT}}/v1`
- **状態:** 常時稼働
- **用途:** 新モデルの試用、軽量タスク、マルチエージェントのサブエージェント
- **API共通デフォルト:** num_predict=-1（無制限、自然停止まで生成）。明示的に小さい値を指定すると途中で切れるので注意
- **導入済みモデル:**
  - `{{MODEL_1}}` — パラメータ数, 量子化, サイズ, ctx: コンテキスト長
  - `{{MODEL_2}}` — パラメータ数, 量子化, サイズ, ctx: コンテキスト長
  <!-- モデルを追加したらここに追記 -->

## アプリケーション

<!-- 自分のアプリケーションをここに追加 -->
<!--
### アプリ名

- **プロジェクト:** `~/projects/{{APP_NAME}}/`
- **コンテナ:** {{CONTAINER_NAME}}
- **ポート:** {{APP_PORT}}
- **Docker Network:** llm-network経由でSGLang/Ollama接続
- **状態:** 常時稼働 / 必要時に起動
-->

## インフラ

### SSH

- **ポート:** 22
- **詳細:** `network.md` を参照

### Tailscale

- **サービス:** tailscaled.service
- **IP:** {{VPN_IP}}
- **用途:** リモートからのVPN接続

### Docker

- **バージョン:** {{DOCKER_VERSION}} / Compose {{COMPOSE_VERSION}}
- **共有ネットワーク:** `llm-network`（LLMサービスへの接続用）
- **新規プロジェクトでの接続方法:**
  ```yaml
  networks:
    llm-network:
      external: true
  ```

## 停止済み・未使用

<!-- 使わなくなったサービスはここに移動 -->
