"""FFmpeg メディアユーティリティ

音声・動画ファイルの情報取得とフォーマット判定を行う。
FFmpeg はコンテナ内にインストールされている前提。
"""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# faster-whisper が直接処理できる拡張子
# （FFmpeg を経由せずデコード可能）
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".flv", ".ts"}
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


@dataclass
class MediaInfo:
    """メディアファイルの情報"""

    path: str
    duration: float  # 秒
    has_audio: bool
    has_video: bool
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    format_name: str


def is_supported(path: str | Path) -> bool:
    """ファイルが対応フォーマットかどうかを拡張子で判定する。"""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def get_media_info(path: str | Path) -> MediaInfo:
    """ffprobe を使用してメディアファイルの情報を取得する。

    副作用: なし（読み取り専用の ffprobe コマンドを実行）
    """
    path = str(path)

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError("ffprobe が見つかりません。FFmpeg がインストールされていることを確認してください。")

    if result.returncode != 0:
        raise ValueError(f"メディア情報の取得に失敗: {result.stderr.strip()}")

    probe = json.loads(result.stdout)
    streams = probe.get("streams", [])
    fmt = probe.get("format", {})

    audio_stream = next((s for s in streams if s["codec_type"] == "audio"), None)
    video_stream = next((s for s in streams if s["codec_type"] == "video"), None)

    return MediaInfo(
        path=path,
        duration=float(fmt.get("duration", 0)),
        has_audio=audio_stream is not None,
        has_video=video_stream is not None,
        audio_codec=audio_stream["codec_name"] if audio_stream else None,
        sample_rate=int(audio_stream["sample_rate"]) if audio_stream and "sample_rate" in audio_stream else None,
        channels=int(audio_stream["channels"]) if audio_stream and "channels" in audio_stream else None,
        format_name=fmt.get("format_name", "unknown"),
    )


def validate_input(path: str | Path) -> Path:
    """入力ファイルの存在とフォーマットを検証する。

    Returns:
        検証済みのPath

    Raises:
        FileNotFoundError: ファイルが存在しない
        ValueError: 未対応のフォーマットまたは音声トラックがない
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")

    if not path.is_file():
        raise ValueError(f"ディレクトリは指定できません: {path}")

    info = get_media_info(path)

    if not info.has_audio:
        raise ValueError(f"音声トラックが見つかりません: {path}")

    logger.info(
        "入力ファイル: %s (%.1f秒, codec=%s, %dHz)",
        path.name,
        info.duration,
        info.audio_codec,
        info.sample_rate or 0,
    )

    return path
