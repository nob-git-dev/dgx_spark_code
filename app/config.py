"""アプリケーション設定 (環境変数から読み込み)"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- モデル設定 ---
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_language: str = "ja"

    # --- パス ---
    model_cache_dir: str = "/app/models"
    data_dir: str = "/app/data"

    # --- サーバー ---
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    gradio_port: int = 7860

    # --- 文字起こしデフォルト ---
    default_output_format: str = "srt"
    beam_size: int = 5
    vad_filter: bool = True
    word_timestamps: bool = True

    # --- Blackwell互換 ---
    disable_blackwell_patch: bool = False

    model_config = {"env_prefix": ""}


settings = Settings()
