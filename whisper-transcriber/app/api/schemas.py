"""REST API のリクエスト/レスポンスモデル"""

from pydantic import BaseModel, Field

from app.utils.formats import OutputFormat


class TranscribeParams(BaseModel):
    """文字起こしパラメータ"""

    language: str = Field(default="ja", description="言語コード (ja/en/auto)")
    model: str = Field(default="large-v3-turbo", description="Whisperモデル名")
    format: OutputFormat = Field(default="srt", description="出力フォーマット")
    beam_size: int = Field(default=5, ge=1, le=10, description="ビームサーチ幅")
    vad_filter: bool = Field(default=True, description="VADフィルタ有効化")
    word_timestamps: bool = Field(default=True, description="単語レベルタイムスタンプ")


class SegmentResponse(BaseModel):
    id: int
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    """文字起こし結果"""

    language: str
    language_probability: float
    duration: float
    processing_time: float
    model: str
    segments: list[SegmentResponse]
    formatted_output: str
    output_format: str
