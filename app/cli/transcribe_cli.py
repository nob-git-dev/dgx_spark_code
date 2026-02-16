"""コンテナ内 CLI — ファイルを指定して文字起こしを実行する

Usage (コンテナ内):
    python -m app.cli.transcribe_cli /tmp/input/meeting.mp4 --format srt --language ja
"""

import argparse
import logging
import sys
from pathlib import Path

from app import transcriber
from app.utils.formats import SUPPORTED_FORMATS, format_result, get_file_extension
from app.utils.media import validate_input

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Whisper Transcriber CLI — 音声/動画ファイルの文字起こし",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  python -m app.cli.transcribe_cli input.mp4\n"
            "  python -m app.cli.transcribe_cli input.wav -l en -f txt\n"
            "  python -m app.cli.transcribe_cli input.mp3 --model large-v3 -o result.srt\n"
        ),
    )
    parser.add_argument("input", help="音声/動画ファイルのパス")
    parser.add_argument(
        "-l", "--language",
        default="ja",
        help="言語コード (ja/en/auto) [デフォルト: ja]",
    )
    parser.add_argument(
        "-m", "--model",
        default="large-v3-turbo",
        help="Whisperモデル名 [デフォルト: large-v3-turbo]",
    )
    parser.add_argument(
        "-f", "--format",
        default="srt",
        choices=SUPPORTED_FORMATS,
        help="出力フォーマット [デフォルト: srt]",
    )
    parser.add_argument(
        "-o", "--output",
        help="出力ファイルパス [デフォルト: 入力ファイル名 + 拡張子]",
    )
    parser.add_argument(
        "--output-dir",
        default="/app/data/output",
        help="出力ディレクトリ [デフォルト: /app/data/output]",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=5,
        help="ビームサーチ幅 [デフォルト: 5]",
    )
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="VADフィルタを無効化",
    )
    parser.add_argument(
        "--word-timestamps",
        action="store_true",
        default=True,
        help="単語レベルタイムスタンプ [デフォルト: 有効]",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="結果を標準出力に出力（ファイル保存しない）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        # 入力ファイル検証
        input_path = validate_input(args.input)

        # 文字起こし実行
        result = transcriber.transcribe(
            input_path,
            model_name=args.model,
            language=args.language,
            beam_size=args.beam_size,
            vad_filter=not args.no_vad,
            word_timestamps=args.word_timestamps,
        )

        # フォーマット
        formatted = format_result(result, args.format)

        # 出力
        if args.stdout:
            print(formatted, end="")
        else:
            if args.output:
                output_path = Path(args.output)
            else:
                ext = get_file_extension(args.format)
                output_path = Path(args.output_dir) / (input_path.stem + ext)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(formatted, encoding="utf-8")
            logger.info("出力: %s", output_path)

        # メタ情報を stderr に出力
        print(
            f"\n--- 完了 ---\n"
            f"検出言語: {result.language} ({result.language_probability:.1%})\n"
            f"音声長: {result.duration:.1f}秒\n"
            f"処理時間: {result.processing_time:.1f}秒\n"
            f"速度: {result.duration / result.processing_time:.1f}x リアルタイム\n"
            f"モデル: {result.model_name}",
            file=sys.stderr,
        )

        return 0

    except (FileNotFoundError, ValueError) as e:
        logger.error("%s", e)
        return 1
    except KeyboardInterrupt:
        logger.info("中断されました")
        return 130
    except Exception as e:
        logger.exception("予期しないエラー: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
