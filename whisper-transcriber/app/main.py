"""FastAPI エントリポイント — REST API + Gradio Web UI"""

import logging

import gradio as gr
from fastapi import FastAPI

from app.api.router import router as api_router
from app.config import settings
from app.webui.gradio_app import create_gradio_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Whisper Transcriber",
    description="音声・動画ファイルの文字起こし API (powered by faster-whisper)",
    version="1.0.0",
)

# REST API を /api/v1 以下にマウント
app.include_router(api_router, prefix="/api/v1", tags=["transcription"])


@app.get("/health")
async def health():
    """ヘルスチェック"""
    return {
        "status": "ok",
        "model": settings.whisper_model,
        "device": settings.whisper_device,
        "language": settings.whisper_language,
    }


# Gradio Web UI を /ui にマウント
gradio_app = create_gradio_app()
app = gr.mount_gradio_app(app, gradio_app, path="/ui")

logger.info(
    "Whisper Transcriber 起動: model=%s, device=%s",
    settings.whisper_model,
    settings.whisper_device,
)
