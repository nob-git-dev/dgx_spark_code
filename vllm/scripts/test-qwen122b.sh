#!/usr/bin/env bash
# ---------------------------------------------------------------
# Test Qwen3.5-122B-A10B-NVFP4 inference via vLLM API
# ---------------------------------------------------------------
set -euo pipefail

API_URL="${1:-http://localhost:8000}"
MODEL_NAME="txn545_Qwen3.5-122B-A10B-NVFP4"

echo "========================================"
echo " Qwen3.5-122B-A10B-NVFP4 Inference Test"
echo "========================================"
echo "API URL: ${API_URL}"
echo ""

# 1. Health check
echo "--- Health Check ---"
if curl -sf "${API_URL}/health" > /dev/null 2>&1; then
    echo "OK: Service is healthy"
else
    echo "FAIL: Service is not responding at ${API_URL}/health"
    echo "Check if the container is running:"
    echo "  docker compose -f docker-compose.qwen122b.yml --env-file .env.qwen122b logs --tail=20"
    exit 1
fi
echo ""

# 2. Model list
echo "--- Model List ---"
curl -sf "${API_URL}/v1/models" | python3 -m json.tool
echo ""

# 3. Text inference test
echo "--- Text Inference Test ---"
echo "Prompt: 日本語で自己紹介してください。"
echo ""

START=$(date +%s%N)

RESPONSE=$(curl -sf "${API_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{
        \"model\": \"${MODEL_NAME}\",
        \"messages\": [{\"role\": \"user\", \"content\": \"日本語で自己紹介してください。\"}],
        \"max_tokens\": 256,
        \"temperature\": 0.7,
        \"extra_body\": {\"chat_template_kwargs\": {\"enable_thinking\": false}}
    }")

END=$(date +%s%N)
ELAPSED=$(( (END - START) / 1000000 ))

echo "Response:"
echo "${RESPONSE}" | python3 -c "
import sys, json
r = json.load(sys.stdin)
msg = r['choices'][0]['message']['content']
usage = r.get('usage', {})
print(msg)
print()
print(f'Tokens: prompt={usage.get(\"prompt_tokens\",\"?\")}, completion={usage.get(\"completion_tokens\",\"?\")}, total={usage.get(\"total_tokens\",\"?\")}')
"
echo "Wall time: ${ELAPSED}ms"
echo ""

echo "========================================"
echo " Test Complete"
echo "========================================"
