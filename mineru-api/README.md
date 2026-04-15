# MinerU 2.5 Pro on DGX Spark / GX10

[MinerU](https://github.com/opendatalab/MinerU) 2.5 Pro を **NVIDIA DGX Spark / ASUS Ascent GX10**（GB10 Blackwell、ARM64）で動かすための Docker 構成例です。

## 背景 — なぜ transformers バックエンドか

MinerU のデフォルト VLM バックエンドは vllm ですが、vllm の ptxas は GB10 の compute capability `sm_121a`（Blackwell Ultra）に対応していないためクラッシュします。

本構成では `mineru-vl-utils[transformers]` を使い **vllm を完全に排除**することで、sm_121a 環境での動作を実現しています。

```
# vllm を使った場合（動かない）
RuntimeError: CUDA error: no kernel image is available for execution on the device
# → ptxas が sm_121a を認識できない

# transformers バックエンド（本構成）
→ 正常起動・推論可能
```

## 動作確認環境

| 項目 | 内容 |
|---|---|
| ハードウェア | ASUS Ascent GX10 / NVIDIA DGX Spark |
| GPU | GB10（Grace Blackwell、sm_121a） |
| アーキテクチャ | ARM64 (aarch64) |
| ベースイメージ | `nvcr.io/nvidia/pytorch:25.04-py3` |
| MinerU | `mineru[pipeline]>=3.0.0` + `mineru-vl-utils[transformers]>=0.2.3` |
| VLM モデル | `opendatalab/MinerU2.5-Pro-2604-1.2B`（Qwen2-VL 1.2B fine-tune） |

## ファイル構成

```
mineru-api/
├── Dockerfile          # NVIDIA PyTorch 25.04-py3 ベース、transformers バックエンド
├── entrypoint.sh       # 起動時モデルダウンロード + mineru.json 設定
├── docker-compose.yml  # GPU・ヘルスチェック・ボリューム設定
├── tests/
│   ├── test_api.py     # 受け入れテスト（pytest）
│   └── run_tests.sh    # テスト実行スクリプト
└── SPEC.md             # 設計仕様書・アーキテクチャ決定記録（ADR）
```

## 使い方

### 前提条件

- NVIDIA Container Toolkit インストール済み
- Docker / Docker Compose インストール済み
- `llm-network` Docker ネットワークが存在すること（なければ作成）

```bash
docker network create llm-network
```

### 起動

```bash
cd mineru-api
docker compose up -d
```

初回起動時はモデル（約 10GB）を自動ダウンロードします。`models/` ディレクトリにキャッシュされるため、2回目以降はスキップされます。

### ヘルスチェック

```bash
curl http://localhost:8091/health
# → {"status": "healthy"}
```

### PDF 解析

```bash
curl -X POST http://localhost:8091/file_parse \
  -F "files=@your_document.pdf"
```

レスポンス例：

```json
{
  "status": "completed",
  "results": {
    "your_document.pdf": {
      "md_content": "# タイトル\n\n本文テキスト..."
    }
  }
}
```

### テスト実行

```bash
cd mineru-api
bash tests/run_tests.sh
```

## アーキテクチャ上の決定事項（ADR）

詳細は [SPEC.md](./SPEC.md) を参照してください。

| ADR | 決定内容 |
|---|---|
| ADR-1 | ベースイメージを `nvcr.io/nvidia/pytorch:25.04-py3` に変更（vllm イメージは sm_121a 非対応） |
| ADR-2 | `mineru[pipeline]` + `mineru-vl-utils[transformers]` で vllm 依存を排除 |
| ADR-3 | モデルダウンロードをビルド時でなく起動時に行う（ボリュームキャッシュ利用） |
| ADR-4 | `PIP_CONSTRAINT=""` で NVIDIA コンテナの pip 制約を一時解除してインストール |

## ネットワーク構成

`docker-compose.yml` は `llm-network`（external）に参加する設定になっています。
他のサービスと同じ Docker ネットワークで通信する構成を想定していますが、
スタンドアロンで使う場合は `networks:` セクションを削除してください。

## ライセンス

本リポジトリのコード（Dockerfile、entrypoint.sh 等）は MIT License です。

### 使用している OSS

- [MinerU](https://github.com/opendatalab/MinerU) — Apache License 2.0
- [NVIDIA PyTorch Container](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/pytorch) — NVIDIA Deep Learning Container License
- VLM モデル [MinerU2.5-Pro-2604-1.2B](https://huggingface.co/opendatalab/MinerU2.5-Pro-2604-1.2B) — 各モデルカードのライセンスに従う
