# Nemotron-9B-v2-Japanese NVFP4 on vLLM

[nvidia/NVIDIA-Nemotron-Nano-9B-v2-Japanese](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2-Japanese) を NVFP4 量子化して vLLM でサーブする構成。
DGX Spark（GB10 Grace Blackwell / ARM64）向け。

## 概要

- **元モデル:** BF16（18GB）→ **NVFP4 量子化後:** 6.3GB（約65%削減）
- **量子化手法:** ModelOpt PTQ（選択的精度: Mamba+MLP→NVFP4、Attention+Conv1d→BF16維持）
- **vLLM イメージ:** 標準 `nvcr.io/nvidia/vllm:26.01-py3`（カスタムビルド不要）
- **Blackwell NVFP4:** ~427.3 TFLOPS（FP8 比 約2倍の理論スループット）

## セットアップ

### 1. NVFP4 量子化の実行

公式に日本語版の NVFP4 チェックポイントが公開されていないため、自前で量子化する必要がある。

```bash
cp .env.example .env
# HF_TOKEN を設定（モデルダウンロードに必要な場合）

docker compose -f docker-compose.quantize.yml run --rm quantize
# → models/nemotron-9b-v2-japanese-nvfp4/ に出力（約60分）
```

### 2. サービス起動

```bash
docker compose up -d
./scripts/health-check.sh
```

### 3. 動作確認

```bash
./scripts/test-chat.sh
```

## 量子化の選択的精度戦略

[英語版 NVFP4 モデル](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2-NVFP4) の `hf_quant_config.json` を再現。

| レイヤー種別 | 精度 | 理由 |
|------------|------|------|
| Mamba 層 (27層) in_proj/out_proj | NVFP4 | 主要な計算層 |
| MLP 層 (25層) up_proj/down_proj | NVFP4 | 主要な計算層 |
| Attention 層 (4層) | BF16 維持 | 精度感度が高い |
| Conv1d (Mamba内) | BF16 維持 | 精度感度が高い |
| 先頭/末尾 2層 | BF16 維持 | エッジ精度の保護 |

## 他プロジェクトからの接続

```yaml
# docker-compose.yml
services:
  your-app:
    environment:
      - LLM_BASE_URL=http://vllm-chat:8000/v1
    networks:
      - llm-network

networks:
  llm-network:
    external: true
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://vllm-chat:8000/v1",  # Docker内から
    # base_url="http://localhost:8001/v1",  # ホストから
    api_key="dummy"
)
```

## ディレクトリ構成

```
vllm-nemotron-9b-nvfp4/
├── docker-compose.yml            # vLLM サービス定義
├── docker-compose.quantize.yml   # 量子化コンテナ
├── .env.example                  # 設定テンプレート
├── quantize/
│   ├── Dockerfile                # ModelOpt 量子化環境（ARM64対応）
│   └── quantize_nemotron.py      # NVFP4 量子化スクリプト
├── plugins/
│   ├── nemotron_nano_v2_reasoning_parser.py
│   └── nemotron_toolcall_parser_streaming.py
├── scripts/
│   ├── health-check.sh
│   └── test-chat.sh
└── models/                       # (gitignore) 量子化済みモデル出力先
```
