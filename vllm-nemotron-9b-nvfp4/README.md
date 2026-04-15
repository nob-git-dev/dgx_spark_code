# Nemotron-9B-v2-Japanese NVFP4 on vLLM

[nvidia/NVIDIA-Nemotron-Nano-9B-v2-Japanese](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2-Japanese) を NVFP4 量子化して vLLM でサーブする構成。
DGX Spark（GB10 Grace Blackwell / ARM64）向け。

## 概要

- **元モデル:** BF16（18GB）→ **NVFP4 量子化後:** 6.3GB（約65%削減）
- **量子化手法:** ModelOpt PTQ（選択的精度: Mamba+MLP→NVFP4、Attention+Conv1d→BF16維持）
- **vLLM イメージ:** 標準 `nvcr.io/nvidia/vllm:26.01-py3`（カスタムビルド不要）
- **Blackwell NVFP4:** ~427.3 TFLOPS（FP8 比 約2倍の理論スループット）

## ベンチマーク結果: NVFP4 vs オリジナル (BF16)

> DGX Spark (GB10 Grace Blackwell / ARM64 / 128GB統合メモリ) 上で vLLM 0.13.0 (nvcr.io/nvidia/vllm:26.01-py3) を使用。
> 全テスト `temperature=0`、推論モード無効 (`enable_thinking=false`)、各速度テスト3回実行の平均値。

### 速度性能

| 指標 | NVFP4 | BF16 (オリジナル) | 改善率 |
|------|------:|------------------:|-------:|
| **スループット (tok/s)** | **30.4** | 13.0 | **2.3x 高速** |
| **初回トークン到達時間 (TTFT)** | **0.046s** | 0.100s | **2.2x 高速** |
| **GPU メモリ使用率** | **20%** | 90% | **4.5x 効率的** |
| **モデルサイズ** | **6.3 GB** | 18 GB | **65% 削減** |

NVFP4 量子化により **生成速度 2.3倍、GPU メモリ 4.5倍効率化** を達成。
モデルサイズが 1/3 未満のため、他の GPU サービス（VLM、Whisper 等）との同時稼働も容易です。

<details>
<summary>速度テスト詳細（3回実行の平均 ± 標準偏差）</summary>

| テスト内容 | NVFP4 (tok/s) | BF16 (tok/s) | NVFP4 TTFT | BF16 TTFT |
|-----------|---------------:|-------------:|-----------:|----------:|
| 論理的推論 (短文) | 30.4 ± 0.0 | 13.1 ± 0.1 | 0.046s | 0.100s |
| 日本語概念説明 (中文) | 30.4 ± 0.0 | 13.0 ± 0.1 | 0.047s | 0.104s |
| 歴史知識 (長文) | 30.5 ± 0.0 | 13.1 ± 0.0 | 0.046s | 0.102s |

</details>

### 品質比較（15問 × 5カテゴリ）

5カテゴリ（日本語表現・推論/論理・知識/事実・要約・コード生成）にわたる15問で品質を評価。
**NVFP4 はオリジナル BF16 と同等の品質を維持しています。**

| カテゴリ | テスト内容 | 結果 |
|----------|-----------|------|
| 日本語表現 | 文体使い分け、文章改善、日本語概念説明 | 同等 — 丁寧語・口語・文語すべて適切に表現 |
| 推論・論理 | 順序推論、数学的推論 (64%)、パターン認識 (42) | 同等 — 全問正解 |
| 知識・事実 | 憲法の三大原則、光合成、第二次世界大戦の転換点 | 同等 — 正確な知識を提供 |
| 要約 | 文章要約、データ分析、技術概念説明 | 同等 — ほぼ同一の要約出力 |
| コード生成 | Python、jq、SQL | 同等 — 正しいコードを生成 |

<details>
<summary>品質テスト例: 数学的推論（両モデル正答）</summary>

**問題:** ある学校で、全生徒の60%が女子です。女子の80%と男子の40%がクラブ活動に参加しています。全生徒のうち、クラブ活動に参加している生徒の割合は何%ですか？

**NVFP4 の回答（抜粋）:**
> - 女子の人数 = 60人、男子の人数 = 40人
> - クラブ参加: 女子 60 × 0.8 = 48人、男子 40 × 0.4 = 16人
> - **全生徒のうち、クラブ活動に参加している生徒の割合は 64% です。** ✅

**BF16 の回答（抜粋）:**
> - 60% × 80% = 48%（女子の参加率）
> - 40% × 40% = 16%（男子の参加率）
> - **48% + 16% = 64%** ✅

</details>

<details>
<summary>品質テスト例: コード生成（jq コマンド — 両モデル同一出力）</summary>

**問題:** JSON データから年齢が30以上の人の名前をリストで返す jq コマンドを書いてください。

**NVFP4 / BF16 共通の回答:**
```bash
jq -r '.people[] | select(.age >= 30) | .name'
```
```
鈴木
佐藤
```

</details>

<details>
<summary>品質テスト例: SQL クエリ生成（両モデル同一出力）</summary>

**問題:** 部署ごとの平均給与が50万円以上の部署名と平均給与を取得する SQL クエリ

**NVFP4 / BF16 共通の回答:**
```sql
SELECT department, AVG(salary) AS average_salary
FROM employees
GROUP BY department
HAVING AVG(salary) >= 500000;
```

</details>

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

## ライセンス

| 対象 | ライセンス |
|---|---|
| 本リポジトリのコード（Dockerfile・スクリプト等） | MIT |
| vLLM | [Apache License 2.0](https://github.com/vllm-project/vllm/blob/main/LICENSE) |
| **Nemotron-Nano-9B-v2-Japanese モデル** | **[NVIDIA Open Model License](https://developer.download.nvidia.com/licenses/nvidia-open-model-license-agreement-june-2024.pdf)** |
| NVIDIA ModelOpt | [NVIDIA Proprietary License](https://github.com/NVIDIA/TensorRT-Model-Optimizer/blob/main/LICENSE) |

> ⚠️ **Nemotron モデルのライセンスに注意**
>
> `nvidia/NVIDIA-Nemotron-Nano-9B-v2-Japanese` は **NVIDIA Open Model License** の適用を受けます。
> このライセンスは商用利用を許可していますが、モデルを利用するサービスにおいて
> エンドユーザーへの一定の制限（同ライセンスの条件遵守）を課す条件があります。
> 商用利用前に必ず[ライセンス全文](https://developer.download.nvidia.com/licenses/nvidia-open-model-license-agreement-june-2024.pdf)を確認してください。
