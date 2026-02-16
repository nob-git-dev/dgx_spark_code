"""REST API エンドポイント"""

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from app import transcriber
from app.api.schemas import TranscribeParams, TranscribeResponse, SegmentResponse
from app.config import settings
from app.utils.formats import SUPPORTED_FORMATS, format_result, get_file_extension
from app.utils.media import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_file(
    file: UploadFile = File(..., description="音声または動画ファイル"),
    language: str = Form(default="ja"),
    model: str = Form(default="large-v3-turbo"),
    format: str = Form(default="srt"),
    beam_size: int = Form(default=5),
    vad_filter: bool = Form(default=True),
    word_timestamps: bool = Form(default=True),
):
    """ファイルをアップロードして文字起こしを実行する。

    - 対応形式: mp4, mp3, wav, m4a, webm, mkv, ogg 等
    - FFmpeg がサポートする全メディア形式に対応
    """
    # パラメータ検証
    if format not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"未対応のフォーマット: {format} (対応: {SUPPORTED_FORMATS})",
        )

    # ファイル拡張子チェック
    suffix = Path(file.filename or "unknown").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"未対応のファイル形式: {suffix}",
        )

    # 一時ファイルに保存して処理
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        result = transcriber.transcribe(
            tmp_path,
            model_name=model,
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
        )

        formatted = format_result(result, format)

        return TranscribeResponse(
            language=result.language,
            language_probability=result.language_probability,
            duration=result.duration,
            processing_time=result.processing_time,
            model=result.model_name,
            segments=[
                SegmentResponse(id=s.id, start=s.start, end=s.end, text=s.text)
                for s in result.segments
            ],
            formatted_output=formatted,
            output_format=format,
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("文字起こし中にエラーが発生: %s", e)
        raise HTTPException(status_code=500, detail=f"文字起こしエラー: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/transcribe/download")
async def transcribe_and_download(
    file: UploadFile = File(...),
    language: str = Form(default="ja"),
    model: str = Form(default="large-v3-turbo"),
    format: str = Form(default="srt"),
    beam_size: int = Form(default=5),
    vad_filter: bool = Form(default=True),
    word_timestamps: bool = Form(default=True),
):
    """文字起こし結果をファイルとして直接ダウンロードする。"""
    if format not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=400, detail=f"未対応のフォーマット: {format}")

    suffix = Path(file.filename or "unknown").suffix.lower()

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        result = transcriber.transcribe(
            tmp_path,
            model_name=model,
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
        )

        formatted = format_result(result, format)
        ext = get_file_extension(format)
        filename = Path(file.filename or "output").stem + ext

        return PlainTextResponse(
            content=formatted,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as e:
        logger.exception("文字起こし中にエラーが発生: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/formats")
async def list_formats():
    """対応する出力フォーマット一覧を返す。"""
    return {
        "formats": SUPPORTED_FORMATS,
        "default": settings.default_output_format,
    }


@router.get("/models")
async def list_models():
    """利用可能なモデル一覧を返す。"""
    return {
        "models": [
            {"name": "tiny", "description": "最小・最速（テスト用）", "size": "~75MB"},
            {"name": "base", "description": "基本モデル", "size": "~145MB"},
            {"name": "small", "description": "小型モデル", "size": "~488MB"},
            {"name": "medium", "description": "中型モデル", "size": "~1.5GB"},
            {"name": "large-v3-turbo", "description": "高速・高精度（推奨）", "size": "~1.6GB"},
            {"name": "large-v3", "description": "最高精度", "size": "~3.1GB"},
        ],
        "default": settings.whisper_model,
    }
