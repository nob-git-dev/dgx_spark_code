"""Gradio Web UI — ファイルアップロードによる文字起こし"""

import logging
import tempfile
from pathlib import Path

import gradio as gr

from app import transcriber
from app.config import settings
from app.utils.formats import SUPPORTED_FORMATS, format_result

logger = logging.getLogger(__name__)

_FILE_SEPARATOR = "=" * 60

LANGUAGE_CHOICES = [
    ("日本語", "ja"),
    ("英語", "en"),
    ("自動検出", "auto"),
    ("中国語", "zh"),
    ("韓国語", "ko"),
    ("フランス語", "fr"),
    ("ドイツ語", "de"),
    ("スペイン語", "es"),
]

MODEL_CHOICES = [
    ("large-v3-turbo (推奨: 高速・高精度)", "large-v3-turbo"),
    ("large-v3 (最高精度)", "large-v3"),
    ("medium", "medium"),
    ("small", "small"),
    ("base", "base"),
    ("tiny (テスト用)", "tiny"),
]

FORMAT_CHOICES = [
    ("SRT (字幕)", "srt"),
    ("VTT (Web字幕)", "vtt"),
    ("テキスト", "txt"),
    ("JSON (詳細)", "json"),
    ("TSV (タブ区切り)", "tsv"),
]


def _transcribe_ui(
    file_paths: list[str] | None,
    language: str,
    model_name: str,
    output_format: str,
    beam_size: int,
    vad_filter: bool,
    word_timestamps: bool,
    progress: gr.Progress = gr.Progress(),
) -> tuple[str, str, list[str] | None]:
    """Gradio UI から呼ばれる文字起こし関数（複数ファイル対応）。

    Returns:
        (フォーマット済みテキスト, メタ情報, ダウンロード用ファイルパスのリスト)
    """
    if not file_paths:
        return "ファイルをアップロードしてください。", "", None

    all_formatted: list[str] = []
    all_meta: list[str] = []
    download_paths: list[str] = []
    total = len(file_paths)

    for idx, file_path in enumerate(file_paths, start=1):
        filename = Path(file_path).name
        progress((idx - 1) / total, desc=f"処理中: {filename} ({idx}/{total})")

        try:
            result = transcriber.transcribe(
                file_path,
                model_name=model_name,
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
                word_timestamps=word_timestamps,
            )

            formatted = format_result(result, output_format)

            meta = (
                f"検出言語: {result.language} ({result.language_probability:.1%})\n"
                f"音声長: {result.duration:.1f}秒\n"
                f"処理時間: {result.processing_time:.1f}秒\n"
                f"速度: {result.duration / result.processing_time:.1f}x リアルタイム\n"
                f"モデル: {result.model_name}\n"
                f"セグメント数: {len(result.segments)}"
            )

            # ダウンロード用ファイルを生成
            stem = Path(file_path).stem
            ext = f".{output_format}"
            download_path = tempfile.mktemp(prefix=f"{stem}_", suffix=ext)
            Path(download_path).write_text(formatted, encoding="utf-8")
            download_paths.append(download_path)

            if total > 1:
                header = f"{_FILE_SEPARATOR}\n{filename}\n{_FILE_SEPARATOR}"
                all_formatted.append(f"{header}\n{formatted}")
                all_meta.append(f"[{filename}]\n{meta}")
            else:
                all_formatted.append(formatted)
                all_meta.append(meta)

        except Exception as e:
            logger.exception("Web UI 文字起こしエラー (%s): %s", filename, e)
            if total > 1:
                all_formatted.append(
                    f"{_FILE_SEPARATOR}\n{filename}\n{_FILE_SEPARATOR}\nエラー: {e}"
                )
                all_meta.append(f"[{filename}]\nエラー: {e}")
            else:
                all_formatted.append(f"エラー: {e}")
                all_meta.append(f"エラー: {e}")

    progress(1.0, desc="完了")
    return (
        "\n\n".join(all_formatted),
        "\n\n".join(all_meta),
        download_paths if download_paths else None,
    )


def create_gradio_app() -> gr.Blocks:
    """Gradio アプリケーションを構築して返す。"""

    with gr.Blocks(
        title="Whisper Transcriber",
        theme=gr.themes.Soft(),
    ) as app:
        gr.Markdown("# Whisper Transcriber")
        gr.Markdown(
            "音声・動画ファイルをアップロードして、高精度な文字起こしを実行します。\n"
            "対応形式: MP4, MP3, WAV, M4A, WebM, MKV, OGG 等"
        )

        with gr.Row():
            with gr.Column(scale=1):
                file_input = gr.File(
                    label="音声/動画ファイル（MP4, MP3, WAV, M4A, MKV, WebM 等）",
                    file_types=[
                        ".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac",
                        ".aac", ".wma",
                        ".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv",
                        ".flv", ".ts",
                    ],
                    type="filepath",
                    file_count="multiple",
                )

                with gr.Accordion("設定", open=False):
                    language = gr.Dropdown(
                        choices=LANGUAGE_CHOICES,
                        value="ja",
                        label="言語",
                    )
                    model_name = gr.Dropdown(
                        choices=MODEL_CHOICES,
                        value=settings.whisper_model,
                        label="モデル",
                    )
                    output_format = gr.Dropdown(
                        choices=FORMAT_CHOICES,
                        value=settings.default_output_format,
                        label="出力フォーマット",
                    )
                    beam_size = gr.Slider(
                        minimum=1,
                        maximum=10,
                        value=settings.beam_size,
                        step=1,
                        label="ビームサーチ幅",
                        info="大きいほど精度が上がるが処理が遅くなる",
                    )
                    vad_filter = gr.Checkbox(
                        value=settings.vad_filter,
                        label="VADフィルタ",
                        info="無音区間を除去して精度と速度を向上",
                    )
                    word_timestamps = gr.Checkbox(
                        value=settings.word_timestamps,
                        label="単語タイムスタンプ",
                        info="単語レベルのタイミング情報を生成",
                    )

                transcribe_btn = gr.Button("文字起こし開始", variant="primary", size="lg")

            with gr.Column(scale=2):
                output_text = gr.Textbox(
                    label="文字起こし結果",
                    lines=20,
                    max_lines=50,
                )
                meta_text = gr.Textbox(
                    label="メタ情報",
                    lines=6,
                    interactive=False,
                )
                download_file = gr.File(label="ダウンロード", file_count="multiple")

        transcribe_btn.click(
            fn=_transcribe_ui,
            inputs=[
                file_input,
                language,
                model_name,
                output_format,
                beam_size,
                vad_filter,
                word_timestamps,
            ],
            outputs=[output_text, meta_text, download_file],
        )

    return app
