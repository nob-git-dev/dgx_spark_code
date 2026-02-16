"""文字起こし結果の出力フォーマッタ

対応フォーマット: txt, srt, vtt, json, tsv
"""

import json
from typing import Literal

from app.transcriber import TranscriptionResult

OutputFormat = Literal["txt", "srt", "vtt", "json", "tsv"]

SUPPORTED_FORMATS: list[OutputFormat] = ["txt", "srt", "vtt", "json", "tsv"]


def format_result(result: TranscriptionResult, fmt: OutputFormat) -> str:
    """TranscriptionResult を指定フォーマットの文字列に変換する。"""
    formatters = {
        "txt": _format_txt,
        "srt": _format_srt,
        "vtt": _format_vtt,
        "json": _format_json,
        "tsv": _format_tsv,
    }
    formatter = formatters.get(fmt)
    if formatter is None:
        raise ValueError(f"未対応のフォーマット: {fmt} (対応: {SUPPORTED_FORMATS})")
    return formatter(result)


def get_file_extension(fmt: OutputFormat) -> str:
    """フォーマットに対応するファイル拡張子を返す。"""
    return f".{fmt}"


def _format_timestamp_srt(seconds: float) -> str:
    """SRT 形式のタイムスタンプ: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    """VTT 形式のタイムスタンプ: HH:MM:SS.mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _format_txt(result: TranscriptionResult) -> str:
    """プレーンテキスト — セグメントを改行で結合"""
    return "\n".join(seg.text for seg in result.segments) + "\n"


def _format_srt(result: TranscriptionResult) -> str:
    """SubRip 字幕形式"""
    lines = []
    for i, seg in enumerate(result.segments, start=1):
        lines.append(str(i))
        lines.append(
            f"{_format_timestamp_srt(seg.start)} --> {_format_timestamp_srt(seg.end)}"
        )
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)


def _format_vtt(result: TranscriptionResult) -> str:
    """WebVTT 字幕形式"""
    lines = ["WEBVTT", ""]
    for seg in result.segments:
        lines.append(
            f"{_format_timestamp_vtt(seg.start)} --> {_format_timestamp_vtt(seg.end)}"
        )
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)


def _format_json(result: TranscriptionResult) -> str:
    """JSON 形式 — 全メタデータ含む"""
    data = {
        "language": result.language,
        "language_probability": result.language_probability,
        "duration": result.duration,
        "processing_time": result.processing_time,
        "model": result.model_name,
        "segments": [
            {
                "id": seg.id,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "words": [
                    {
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability,
                    }
                    for w in seg.words
                ],
            }
            for seg in result.segments
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _format_tsv(result: TranscriptionResult) -> str:
    """TSV (タブ区切り) 形式"""
    lines = ["start\tend\ttext"]
    for seg in result.segments:
        start_ms = int(seg.start * 1000)
        end_ms = int(seg.end * 1000)
        lines.append(f"{start_ms}\t{end_ms}\t{seg.text}")
    return "\n".join(lines) + "\n"
