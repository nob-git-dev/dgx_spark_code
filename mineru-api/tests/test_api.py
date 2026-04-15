"""
mineru-api 受け入れテスト
SPEC.md の受け入れ条件に対応する統合テスト群

前提条件:
  - コンテナが起動済みであること (docker compose up -d)
  - pytest と requests がインストールされていること (uv run pytest)

実行方法:
  cd mineru-api
  uv run pytest tests/test_api.py -v
"""

import json
import os
import subprocess
import time
import pytest
import requests

BASE_URL = os.environ.get("MINERU_API_URL", "http://localhost:8091")
CONTAINER_NAME = "mineru-api"
SAMPLE_PDF = os.path.join(os.path.dirname(__file__), "sample.pdf")
SAMPLE_PDF_WITH_FIGURE = os.path.join(os.path.dirname(__file__), "sample_with_figure.pdf")


# ============================================================
# TC-1: GET /health → {"status": "healthy"} (HTTP 200)
# ============================================================
def test_health_check():
    """受け入れ条件 1: GET /health に対して {"status": "healthy"} が返る（HTTP 200）"""
    resp = requests.get(f"{BASE_URL}/health", timeout=10)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("status") == "healthy", f"Expected status=healthy, got: {body}"


# ============================================================
# TC-2: POST /file_parse に PDF → Markdown + JSON (HTTP 200)
# ============================================================
def test_file_parse_returns_markdown_and_json():
    """受け入れ条件 2: POST /file_parse に PDF を送ると Markdown と JSON が返る（HTTP 200）"""
    assert os.path.exists(SAMPLE_PDF), f"Sample PDF not found: {SAMPLE_PDF}"
    with open(SAMPLE_PDF, "rb") as f:
        # mineru-api は files フィールドに配列形式でファイルを受け付ける
        resp = requests.post(
            f"{BASE_URL}/file_parse",
            files=[("files", ("sample.pdf", f, "application/pdf"))],
            timeout=120,
        )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    # status が completed であること
    assert body.get("status") == "completed", (
        f"Task status is not completed: {body.get('status')} | error: {body.get('error')}"
    )
    # results フィールドに md_content が含まれること
    # mineru-api v3 レスポンス形式: {"results": {"<filename>": {"md_content": "..."}}}
    results = body.get("results", {})
    has_markdown = any(
        "md_content" in file_result or "markdown" in file_result
        for file_result in results.values()
        if isinstance(file_result, dict)
    )
    assert has_markdown, (
        f"Response missing md_content in results: {list(body.keys())} | results: {results}"
    )


# ============================================================
# TC-3: 図表・表を含む PDF → VLM が図表領域を検出（smoke test）
# ============================================================
def test_file_parse_vlm_figure_detected():
    """受け入れ条件 3: 図表・表を含む PDF を送ると VLM によって図表領域が検出される"""
    # sample_with_figure.pdf がなければスキップ（CI で生成する場合は別途用意）
    if not os.path.exists(SAMPLE_PDF_WITH_FIGURE):
        pytest.skip(
            "sample_with_figure.pdf が存在しません。"
            "図表入りPDFを tests/sample_with_figure.pdf に配置して再実行してください。"
        )
    with open(SAMPLE_PDF_WITH_FIGURE, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/file_parse",
            files=[("files", ("sample_with_figure.pdf", f, "application/pdf"))],
            timeout=300,
        )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    # VLM が処理した証拠: content_list に figure または table が含まれる
    content_list = body.get("content_list", [])
    layout_result = body.get("layout_result", [])
    combined = content_list + layout_result
    types = [item.get("type", "") for item in combined if isinstance(item, dict)]
    assert any(t in ("figure", "table", "image") for t in types), (
        f"VLM が図表を検出しませんでした。検出タイプ一覧: {types}"
    )


# ============================================================
# TC-4: /root/mineru.json の vlm パスが Pro-2604 を指す
# ============================================================
def test_mineru_json_vlm_path():
    """受け入れ条件 4: /root/mineru.json の vlm パスが opendatalab/MinerU2.5-Pro-2604-1.2B を指す"""
    result = subprocess.run(
        ["docker", "exec", CONTAINER_NAME, "cat", "/root/mineru.json"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"docker exec failed: {result.stderr}"
    cfg = json.loads(result.stdout)
    vlm_path = (
        cfg.get("models-dir", {}).get("vlm")
        or cfg.get("vlm_model_path")
        or cfg.get("vlm")
    )
    assert vlm_path is not None, f"vlm パスが mineru.json に存在しません: {cfg}"
    assert "MinerU2.5-Pro-2604" in str(vlm_path), (
        f"vlm パスが Pro-2604 モデルを指していません: {vlm_path}"
    )


# ============================================================
# TC-5: sm_121a エラーがコンテナログに出ていないこと
# ============================================================
def test_no_sm121a_error():
    """受け入れ条件 5: hybrid-auto-engine で sm_121a エラーが発生しない"""
    result = subprocess.run(
        ["docker", "logs", CONTAINER_NAME, "--tail", "200"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    logs = result.stdout + result.stderr
    # sm_121a / sm_12 / sm_12xa 系のコンピュートケーパビリティエラーパターン
    error_patterns = [
        "sm_121a",
        "sm_121",
        "CUDA error",
        "no kernel image",
        "unrecognized compute capability",
    ]
    for pattern in error_patterns:
        assert pattern not in logs, (
            f"ログに GPU エラーパターン '{pattern}' が含まれています:\n"
            + "\n".join(
                line for line in logs.splitlines()
                if pattern.lower() in line.lower()
            )
        )


# ============================================================
# TC-6: 無効なファイル形式 → HTTP 422
# ============================================================
def test_file_parse_invalid_file():
    """受け入れ条件 6: 無効なファイル（PDF 以外）を送るとエラーレスポンスが返る（HTTP 400 または 422）"""
    fake_content = b"This is not a PDF file"
    resp = requests.post(
        f"{BASE_URL}/file_parse",
        files=[("files", ("fake.txt", fake_content, "text/plain"))],
        timeout=30,
    )
    # mineru-api は非対応ファイルに 400 を返す（FastAPI バリデーションエラーは 422）
    assert resp.status_code in (400, 422), (
        f"Expected 400 or 422, got {resp.status_code}: {resp.text}"
    )


# ============================================================
# TC-7: docker compose up 後に healthcheck が PASS (120s以内)
# ============================================================
def test_healthcheck_passes():
    """受け入れ条件 7: docker compose up 後に healthcheck が PASS する（start_period: 120s 以内）"""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"docker inspect failed: {result.stderr}"
    status = result.stdout.strip()
    assert status == "healthy", (
        f"healthcheck status が healthy ではありません: '{status}'"
    )


# ============================================================
# TC-8: コンテナが llm-network に参加している
# ============================================================
def test_llm_network_membership():
    """受け入れ条件 8: コンテナが llm-network に参加している"""
    result = subprocess.run(
        [
            "docker", "inspect",
            "--format", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}",
            CONTAINER_NAME,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"docker inspect failed: {result.stderr}"
    networks = result.stdout.strip().split()
    assert "llm-network" in networks, (
        f"コンテナが llm-network に参加していません。参加ネットワーク: {networks}"
    )


# ============================================================
# TC-9: モデルが ./models にボリュームマウントされている
# ============================================================
def test_model_volume_mount():
    """受け入れ条件 9: モデルファイルが ./models（ホスト）にボリュームマウントされ永続化されている"""
    result = subprocess.run(
        [
            "docker", "inspect",
            "--format",
            "{{range .Mounts}}{{.Source}} -> {{.Destination}}\n{{end}}",
            CONTAINER_NAME,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"docker inspect failed: {result.stderr}"
    mounts = result.stdout.strip()
    assert "/root/.cache/huggingface" in mounts, (
        f"ボリュームマウントに /root/.cache/huggingface が含まれていません:\n{mounts}"
    )
