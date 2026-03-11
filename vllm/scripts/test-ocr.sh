#!/usr/bin/env bash
# 画像OCRテスト（VLMモデル使用時）
# 使い方: ./scripts/test-ocr.sh <画像ファイルパス>

IMAGE_PATH="${1}"
PORT="${VLLM_PORT:-8000}"
MODEL="${MODEL_NAME:-Qwen/Qwen3-VL-8B-Instruct}"
ENDPOINT="http://localhost:${PORT}/v1/chat/completions"
TMP_JSON=$(mktemp /tmp/vllm-ocr-XXXXXX.json)

if [ -z "$IMAGE_PATH" ] || [ ! -f "$IMAGE_PATH" ]; then
  echo "使い方: $0 <画像ファイルパス>"
  exit 1
fi

MIME_TYPE="image/png"
case "${IMAGE_PATH##*.}" in
  jpg|jpeg) MIME_TYPE="image/jpeg" ;;
esac

BASE64_IMAGE=$(base64 -w 0 "$IMAGE_PATH")

echo "=== OCR テスト: $IMAGE_PATH ==="

# JSON を一時ファイルに書き出し（引数長制限を回避）
python3 -c "
import json, sys
payload = {
  'model': '${MODEL}',
  'messages': [{
    'role': 'user',
    'content': [
      {'type': 'image_url', 'image_url': {'url': 'data:${MIME_TYPE};base64,${BASE64_IMAGE}'}},
      {'type': 'text', 'text': 'この画像のテキストをすべて正確に書き起こしてください。レイアウト（段落・表・リスト）を可能な限り保持してください。'}
    ]
  }],
  'max_tokens': 4096,
  'temperature': 0
}
print(json.dumps(payload))
" > "$TMP_JSON"

curl -sf -X POST "$ENDPOINT" \
  -H "Content-Type: application/json" \
  --data "@${TMP_JSON}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data['choices'][0]['message']['content'])
print()
usage = data.get('usage', {})
print(f\"--- トークン使用量 ---\")
print(f\"入力: {usage.get('prompt_tokens','N/A')} / 出力: {usage.get('completion_tokens','N/A')}\")
"

rm -f "$TMP_JSON"
