# ネットワーク・接続情報

## IPアドレス

| インターフェース | IP | 用途 |
|---|---|---|
| {{WIFI_INTERFACE}} (WiFi) | {{LAN_IP}} | LAN内アクセス |
| tailscale0 | {{VPN_IP}} | VPN経由のリモートアクセス |

## SSH接続

- **ホスト名:** {{HOSTNAME}}.local（mDNSが不安定な場合はIP直指定を推奨）
- **ユーザー:** {{USERNAME}}
- **ポート:** 22
- **認証鍵:** {{AUTH_KEY_DESCRIPTION}}

### クライアント側の設定

- **秘密鍵:** `{{SSH_KEY_PATH}}`
- **接続コマンド:** `ssh {{SSH_ALIAS}}`
- **VS Code:** Remote SSH で `{{SSH_ALIAS}}` を指定

### トラブルシュート

**"ssh: connect to host {{HOSTNAME}}.local port 22: Undefined error: 0"**
- 原因: mDNS (.local) の名前解決の一時的な遅延
- 対処: 再試行、またはIPアドレス直指定（{{LAN_IP}}）で回避

## リモート端末からサービスへのアクセス

リモート端末からDGX Sparkのサービスに接続する際のエンドポイント:

| サービス | LAN | VPN |
|---|---|---|
| SGLang (LLM) | `http://{{LAN_IP}}:{{SGLANG_PORT}}/v1` | `http://{{VPN_IP}}:{{SGLANG_PORT}}/v1` |
| Ollama | `http://{{LAN_IP}}:{{OLLAMA_PORT}}/v1` | `http://{{VPN_IP}}:{{OLLAMA_PORT}}/v1` |

## Docker ネットワーク

DGX Spark上のDockerコンテナ間は `llm-network` で接続する。

| コンテナ内エンドポイント | 対象 |
|---|---|
| `http://sglang-llm:{{SGLANG_PORT}}/v1` | SGLang |
| `http://host.docker.internal:{{OLLAMA_PORT}}/v1` | Ollama（ホスト上のsystemdサービス） |
