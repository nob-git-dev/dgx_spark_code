# vLLM - 共有LLM推論サービス

DGX Spark（GB10 Grace Blackwell / ARM64）向けの vLLM Docker サービス。
各プロジェクトの Docker から OpenAI 互換 API でアクセスする共有 LLM 基盤。

## 特徴

- ARM64 + Blackwell ネイティブ対応（NVIDIA 公式 DGX Spark プレイブック準拠）
- OpenAI 互換 API（既存コードをそのまま使える）
- `llm-network` 経由で他の Docker プロジェクトから接続可能
- モデルを `.env` で切り替えるだけで VLM / LLM を変更可能

## セットアップ

```bash
# 1. 環境変数ファイルを作成
cp .env.example .env
# 必要に応じて MODEL_NAME や GPU_MEMORY_UTIL を編集

# 2. 起動（初回はモデルのダウンロードで時間がかかります）
docker compose up -d

# 3. 起動確認
./scripts/health-check.sh
```

## テスト

```bash
# テキストチャット
./scripts/test-chat.sh

# OCR（VLMモデル使用時）
./scripts/test-ocr.sh /path/to/image.png
```

## 他のプロジェクトからの接続方法

### docker-compose.yml に追加する設定

```yaml
services:
  your-app:
    environment:
      - LLM_BASE_URL=http://vllm:8000/v1
    networks:
      - llm-network

networks:
  llm-network:
    external: true  # この1行で vLLM に接続できる
```

### Python コードからのアクセス

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://vllm:8000/v1",  # Docker内から
    # base_url="http://localhost:8000/v1",  # ホストから
    api_key="dummy"
)
```

## モデルの切り替え

`.env` の `MODEL_NAME` を変更して再起動するだけ：

```bash
# .env を編集
MODEL_NAME=Qwen/Qwen3-32B-Instruct

# 再起動
docker compose down && docker compose up -d
```

## 常時稼働への移行

`docker-compose.yml` の以下のコメントを外す：

```yaml
restart: unless-stopped
```

## ディレクトリ構造

```
vllm/
├── docker-compose.yml   # vLLM サービス定義
├── .env.example         # 設定テンプレート
├── .env                 # 実際の設定（git管理外）
└── scripts/
    ├── health-check.sh  # 起動確認
    ├── test-chat.sh     # チャットテスト
    └── test-ocr.sh      # OCRテスト
```
