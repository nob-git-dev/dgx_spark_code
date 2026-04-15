#!/bin/bash
# entrypoint.sh — mineru-api コンテナ起動スクリプト
# ADR-3: モデルダウンロードは起動時のみ（ボリュームマウント時は2回目以降スキップ）
set -e

# Pro 2604 モデルが未存在の場合のみダウンロード
MODEL_DIR="/root/.cache/huggingface/hub/models--opendatalab--MinerU2.5-Pro-2604-1.2B"
if [ ! -d "$MODEL_DIR" ]; then
    echo "[entrypoint] Pro-2604 model not found. Downloading all models..."
    # mineru-models-download は VLM モデルの ID 指定オプションを持たないため
    # まず全モデルをダウンロードし、その後 Python で Pro-2604 を追加取得する
    mineru-models-download -s huggingface -m all

    # Pro-2604 モデルを huggingface_hub で直接ダウンロード
    echo "[entrypoint] Downloading Pro-2604 model via huggingface_hub..."
    python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='opendatalab/MinerU2.5-Pro-2604-1.2B',
    repo_type='model',
    local_dir=None  # デフォルトキャッシュ（/root/.cache/huggingface）に保存
)
print('[entrypoint] Pro-2604 download completed.')
"
    echo "[entrypoint] Model download completed."
else
    echo "[entrypoint] Model already exists, skipping download."
fi

# mineru.json を設定（Pro 2604 モデルパスを指定）
python3 -c "
import json, os, glob

cfg_path = '/root/mineru.json'
cfg = {}
if os.path.exists(cfg_path):
    with open(cfg_path) as f:
        cfg = json.load(f)

# vlm パスを Pro 2604 に設定
# snapshots 以下の最新コミットハッシュを動的に解決
model_base = '/root/.cache/huggingface/hub/models--opendatalab--MinerU2.5-Pro-2604-1.2B'
snapshot_dirs = glob.glob(os.path.join(model_base, 'snapshots', '*'))
if snapshot_dirs:
    vlm_path = sorted(snapshot_dirs)[-1]
else:
    # ダウンロード前またはパス未解決の場合はモデルID文字列を設定
    vlm_path = 'opendatalab/MinerU2.5-Pro-2604-1.2B'

cfg.setdefault('models-dir', {})['vlm'] = vlm_path
with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2)
print('[entrypoint] mineru.json updated, vlm:', vlm_path)
"

export MINERU_MODEL_SOURCE=local
echo "[entrypoint] Starting mineru-api on 0.0.0.0:8091..."
exec mineru-api --host 0.0.0.0 --port 8091
