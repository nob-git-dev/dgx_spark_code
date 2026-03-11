#!/usr/bin/env bash
# vLLM サービスの起動状態と動作中モデルを確認

OCR_PORT=${OCR_PORT:-8000}
CHAT_PORT=${CHAT_PORT:-8001}

check_service() {
  local name="$1"
  local port="$2"
  echo "--- ${name} (ポート ${port}) ---"
  response=$(curl -sf "http://localhost:${port}/v1/models")
  if [ $? -ne 0 ]; then
    echo "❌ 未起動またはロード中"
  else
    echo "✅ 起動済み"
    echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('data', []):
    print(f\"  モデル: {m['id']}\")
" 2>/dev/null || echo "$response"
  fi
  echo ""
}

echo "=== vLLM ヘルスチェック ==="
echo ""
check_service "vllm-ocr  (OCR・画像認識用)" "$OCR_PORT"
check_service "vllm-chat (日本語チャット用)" "$CHAT_PORT"
echo "ログ確認: docker compose logs -f vllm-ocr"
echo "          docker compose logs -f vllm-chat"
