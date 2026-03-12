#!/usr/bin/env bash
# テキストチャットのテスト
# 使い方:
#   ./scripts/test-chat.sh          # Nemotron（日本語チャット用、ポート8001）
#   ./scripts/test-chat.sh ocr      # Qwen3-VL（OCR用、ポート8000）

if [ "${1}" = "ocr" ]; then
  PORT=${OCR_PORT:-8000}
  MODEL=${OCR_MODEL:-Qwen/Qwen3-VL-8B-Instruct}
  LABEL="OCR用 (vllm-ocr)"
else
  PORT=${CHAT_PORT:-8001}
  MODEL=${CHAT_MODEL:-NVIDIA-Nemotron-Nano-9B-v2-Japanese-NVFP4}
  LABEL="チャット用 (vllm-chat)"
fi

echo "=== チャットテスト: ${LABEL} ==="
curl -sf "http://localhost:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"${MODEL}\",
    \"messages\": [{\"role\": \"user\", \"content\": \"日本語で自己紹介してください。\"}],
    \"max_tokens\": 256,
    \"temperature\": 0.7
  }" | python3 -m json.tool
