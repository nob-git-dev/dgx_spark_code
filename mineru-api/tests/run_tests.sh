#!/bin/bash
# mineru-api 受け入れテスト実行スクリプト
# 使用方法: cd mineru-api && bash tests/run_tests.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== mineru-api 受け入れテスト ==="
echo "プロジェクト: $PROJECT_DIR"
echo "実行日時: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# pytest が使えるか確認
if ! command -v uv &> /dev/null; then
    echo "[ERROR] uv が見つかりません。'uv' をインストールしてください。"
    exit 1
fi

# コンテナが起動しているか確認
if ! docker ps --format '{{.Names}}' | grep -q '^mineru-api$'; then
    echo "[WARN] mineru-api コンテナが起動していません。"
    echo "  docker compose up -d を実行してから再試行してください。"
    echo ""
    echo "静的テストのみ実行します（TC-8, TC-9）..."
    cd "$PROJECT_DIR"
    uv run --with pytest --with requests pytest tests/test_api.py \
        -v \
        -k "test_llm_network_membership or test_model_volume_mount" \
        2>&1
    exit $?
fi

cd "$PROJECT_DIR"
echo "コンテナが起動中です。全テストを実行します..."
echo ""

uv run --with pytest --with requests pytest tests/test_api.py -v 2>&1
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "=== 全テスト PASS ==="
else
    echo "=== テスト失敗あり（exit code: $EXIT_CODE）==="
fi

exit $EXIT_CODE
