# Qwen3.5-122B-A10B NVFP4 on vLLM (Custom Build)

[Qwen3.5-122B-A10B](https://huggingface.co/Qwen/Qwen3.5-122B-A10B) の NVFP4 量子化モデルを vLLM でサーブするためのカスタムビルド構成。
DGX Spark（GB10 Grace Blackwell / SM121 / ARM64）向け。

## 概要

- **カスタム Dockerfile:** FlashInfer SM121 コンパイル + vLLM nightly + パッチ適用
- **NVFP4 MoE:** CUTLASS MoE FP4 バックエンド（SM121 対応）
- **122B MoE モデル:** 128GB 統合メモリで動作（GPU Memory Util 0.9）

## カスタムビルドが必要な理由

標準の vLLM イメージでは Qwen3.5-122B MoE + NVFP4 + SM121 (Blackwell) の組み合わせに
未対応のため、以下のパッチを適用したカスタムビルドを使用。

### 適用パッチ

| パッチ | 内容 |
|-------|------|
| `fastsafetensors_natural_sort.patch` | safetensors のシャード読み込み順序修正 |
| `flashinfer_cache.patch` | FlashInfer autotuner キャッシュパス修正 |
| `qwen3_5_moe_rope_fix.py` | Qwen3.5 MoE RoPE 修正 |

## セットアップ

```bash
# 1. カスタムイメージのビルド（初回のみ、約30分）
docker compose build

# 2. 環境変数ファイルを作成
cp .env.example .env
# MODEL_HOST_PATH を実際のモデルパスに変更

# 3. 起動
docker compose up -d
```

## ディレクトリ構成

```
vllm-qwen122b-nvfp4/
├── Dockerfile                # カスタム vLLM ビルド（FlashInfer SM121 + パッチ）
├── docker-compose.yml        # サービス定義
├── .env.example              # 設定テンプレート
├── patches/
│   ├── fastsafetensors_natural_sort.patch
│   ├── flashinfer_cache.patch
│   └── qwen3_5_moe_rope_fix.py
├── qwen3_5_vl_moe.py        # Qwen3.5 MoE モデル定義
└── scripts/
    ├── download-qwen122b.sh  # モデルダウンロード
    └── test-qwen122b.sh      # テスト
```
