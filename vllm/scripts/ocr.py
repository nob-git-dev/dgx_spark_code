#!/usr/bin/env python3
"""vLLM OCRテストスクリプト - 画像ファイルパスを引数として渡す"""
import sys
import base64
import json
import urllib.request
import os

def main():
    if len(sys.argv) < 2:
        print("使い方: python3 scripts/ocr.py <画像ファイルパス>")
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.exists(image_path):
        print(f"❌ ファイルが見つかりません: {image_path}")
        sys.exit(1)

    port = os.environ.get("VLLM_PORT", "8000")
    model = os.environ.get("MODEL_NAME", "Qwen/Qwen3-VL-8B-Instruct")
    endpoint = f"http://localhost:{port}/v1/chat/completions"

    # MIMEタイプ判定
    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"

    # 画像をBase64エンコード（Pythonで直接処理）
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    print(f"=== OCR テスト: {image_path} ===")
    print(f"モデル: {model}")
    print(f"エンドポイント: {endpoint}")
    print()

    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": "この画像のテキストをすべて正確に書き起こしてください。レイアウト（段落・表・リスト）を可能な限り保持してください。"}
            ]
        }],
        "max_tokens": 4096,
        "temperature": 0
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    print("--- OCR 結果 ---")
    print(result["choices"][0]["message"]["content"])
    print()
    usage = result.get("usage", {})
    print(f"--- トークン使用量 ---")
    print(f"入力: {usage.get('prompt_tokens','N/A')} / 出力: {usage.get('completion_tokens','N/A')}")

if __name__ == "__main__":
    main()
