"""コア文字起こしエンジン — faster-whisper (CTranslate2) をラップする"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from faster_whisper import WhisperModel

from app.config import settings
from app.patches.blackwell_compat import apply_blackwell_patch

logger = logging.getLogger(__name__)


@dataclass
class WordInfo:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    words: list[WordInfo] = field(default_factory=list)


@dataclass
class TranscriptionResult:
    segments: list[Segment]
    language: str
    language_probability: float
    duration: float
    processing_time: float
    model_name: str


# シングルトンでモデルを保持（リクエストごとにロードしない）
_model_cache: dict[str, WhisperModel] = {}


def get_model(
    model_name: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
) -> WhisperModel:
    """Whisper モデルをロード（キャッシュ済みならそれを返す）。

    初回呼び出し時にモデルのダウンロードが発生する（large-v3-turbo: ~1.5GB）。
    """
    model_name = model_name or settings.whisper_model
    device = device or settings.whisper_device
    compute_type = compute_type or settings.whisper_compute_type

    cache_key = f"{model_name}:{device}:{compute_type}"

    if cache_key not in _model_cache:
        # Blackwell GPU の場合、互換パッチを適用
        apply_blackwell_patch()

        logger.info(
            "モデルをロード中: %s (device=%s, compute_type=%s)",
            model_name,
            device,
            compute_type,
        )
        start = time.time()

        _model_cache[cache_key] = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=settings.model_cache_dir,
        )

        elapsed = time.time() - start
        logger.info("モデルロード完了: %.1f秒", elapsed)

    return _model_cache[cache_key]


def transcribe(
    audio_path: str | Path,
    *,
    model_name: str | None = None,
    language: str | None = None,
    beam_size: int | None = None,
    vad_filter: bool | None = None,
    word_timestamps: bool | None = None,
) -> TranscriptionResult:
    """音声/動画ファイルを文字起こしする。

    Args:
        audio_path: 入力ファイルのパス（FFmpeg がサポートする全形式に対応）
        model_name: Whisper モデル名 (例: "large-v3-turbo")
        language: 言語コード (例: "ja", "en", None=自動検出)
        beam_size: ビームサーチ幅（大きいほど精度が上がるが遅くなる）
        vad_filter: VAD フィルタ（無音区間を除去して精度と速度を向上）
        word_timestamps: 単語レベルのタイムスタンプを生成するか

    Returns:
        TranscriptionResult: 文字起こし結果
    """
    audio_path = str(audio_path)
    language = language or settings.whisper_language
    beam_size = beam_size if beam_size is not None else settings.beam_size
    vad_filter = vad_filter if vad_filter is not None else settings.vad_filter
    word_timestamps = (
        word_timestamps if word_timestamps is not None else settings.word_timestamps
    )

    # "auto" は None に変換（faster-whisper が自動検出する）
    if language == "auto":
        language = None

    model = get_model(model_name)
    used_model_name = model_name or settings.whisper_model

    logger.info("文字起こし開始: %s (language=%s)", audio_path, language or "auto")
    start_time = time.time()

    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
        word_timestamps=word_timestamps,
    )

    segments = []
    for i, seg in enumerate(segments_iter):
        words = []
        if seg.words:
            words = [
                WordInfo(
                    word=w.word,
                    start=w.start,
                    end=w.end,
                    probability=w.probability,
                )
                for w in seg.words
            ]

        segments.append(
            Segment(
                id=i,
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                words=words,
            )
        )

    processing_time = time.time() - start_time
    logger.info(
        "文字起こし完了: %.1f秒 (検出言語=%s, 確率=%.1f%%)",
        processing_time,
        info.language,
        info.language_probability * 100,
    )

    return TranscriptionResult(
        segments=segments,
        language=info.language,
        language_probability=info.language_probability,
        duration=info.duration,
        processing_time=processing_time,
        model_name=used_model_name,
    )
