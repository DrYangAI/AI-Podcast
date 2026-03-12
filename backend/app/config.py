"""Application configuration loaded from config.yaml and environment variables."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


def load_yaml_config(path: str = "config.yaml") -> dict[str, Any]:
    """Load YAML configuration file."""
    config_path = Path(path)
    if not config_path.exists():
        config_path = Path("config.example.yaml")
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_yaml = load_yaml_config()


class DatabaseSettings(BaseSettings):
    url: str = _yaml.get("database", {}).get("url", "sqlite+aiosqlite:///./data/db/ai_podcast.db")
    echo: bool = _yaml.get("database", {}).get("echo", False)


class StorageSettings(BaseSettings):
    base_dir: str = _yaml.get("storage", {}).get("base_dir", "./data")
    output_dir: str = _yaml.get("storage", {}).get("output_dir", "./data/output")
    temp_dir: str = _yaml.get("storage", {}).get("temp_dir", "./data/temp")
    assets_dir: str = _yaml.get("storage", {}).get("assets_dir", "./data/assets")
    max_temp_age_hours: int = _yaml.get("storage", {}).get("max_temp_age_hours", 24)


class VideoQualitySettings(BaseSettings):
    crf: int = 23
    preset: str = "medium"
    codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    fps: int = 30


class ASRSettings(BaseSettings):
    model_config = {"protected_namespaces": ()}

    enabled: bool = True
    model_size: str = "medium"
    device: str = "auto"
    compute_type: str = "int8"


class SubtitleSettings(BaseSettings):
    enabled: bool = True
    font_family: str = "Noto Sans CJK SC"
    font_size: int = 24
    font_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 2
    position: str = "bottom"
    max_chars_per_line: int = 20
    max_lines: int = 1
    margin_bottom: int = 50


class OutputSettings(BaseSettings):
    default_aspect_ratio: str = "16:9"
    default_template: str = "slideshow"
    default_format: str = "mp4"
    naming_rule: str = "{date}_{topic}_{aspect_ratio}"
    video_quality: VideoQualitySettings = VideoQualitySettings(
        **_yaml.get("output", {}).get("video_quality", {})
    )


class ContentSettings(BaseSettings):
    default_language: str = "zh-CN"
    article_min_words: int = 300
    article_max_words: int = 1500
    article_default_style: str = "science_popularization"
    segments_min: int = 3
    segments_max: int = 15
    split_method: str = "paragraph"
    script_default_style: str = "conversational"


class TTSSettings(BaseSettings):
    icl_max_chars: int = 500       # ICL 声音复刻模式每段最大字符数
    standard_max_chars: int = 2000  # 标准 TTS 每段最大字符数


class TaskSettings(BaseSettings):
    max_concurrent: int = 3
    retry_attempts: int = 2
    retry_delay_seconds: int = 5
    task_timeout_seconds: int = 300


class PromptSettings(BaseSettings):
    article_system: str = ""
    article_user: str = ""
    script_system: str = ""
    script_user: str = ""
    image_prompt_system: str = ""
    image_prompt_user: str = ""


class Settings(BaseSettings):
    """Main application settings."""

    app_name: str = _yaml.get("app", {}).get("name", "AI Podcast")
    app_version: str = _yaml.get("app", {}).get("version", "1.0.0")
    debug: bool = _yaml.get("app", {}).get("debug", False)
    host: str = _yaml.get("app", {}).get("host", "0.0.0.0")
    port: int = _yaml.get("app", {}).get("port", 8000)
    log_level: str = _yaml.get("app", {}).get("log_level", "info")
    cors_origins: list[str] = Field(
        default=_yaml.get("app", {}).get("cors_origins", ["http://localhost:5173"])
    )

    database: DatabaseSettings = DatabaseSettings()
    storage: StorageSettings = StorageSettings()
    output: OutputSettings = OutputSettings(
        **{k: v for k, v in _yaml.get("output", {}).items() if k != "video_quality"}
    )
    asr: ASRSettings = ASRSettings(**_yaml.get("asr", {}))
    subtitles: SubtitleSettings = SubtitleSettings(**_yaml.get("subtitles", {}))
    content: ContentSettings = ContentSettings()
    tts: TTSSettings = TTSSettings(**_yaml.get("tts", {}))
    tasks: TaskSettings = TaskSettings(**_yaml.get("tasks", {}))
    prompts: PromptSettings = PromptSettings(**_yaml.get("prompts", {}))

    # API Keys from environment variables
    # ---- 国际模型 ----
    openai_api_key: str = Field(default="", alias="AI_PODCAST_OPENAI_API_KEY")
    claude_api_key: str = Field(default="", alias="AI_PODCAST_CLAUDE_API_KEY")
    elevenlabs_api_key: str = Field(default="", alias="AI_PODCAST_ELEVENLABS_API_KEY")

    # ---- 国产文本/图片/视频模型 ----
    deepseek_api_key: str = Field(default="", alias="AI_PODCAST_DEEPSEEK_API_KEY")
    doubao_api_key: str = Field(default="", alias="AI_PODCAST_DOUBAO_API_KEY")
    qwen_api_key: str = Field(default="", alias="AI_PODCAST_QWEN_API_KEY")
    zhipu_api_key: str = Field(default="", alias="AI_PODCAST_ZHIPU_API_KEY")
    minimax_api_key: str = Field(default="", alias="AI_PODCAST_MINIMAX_API_KEY")
    wenxin_api_key: str = Field(default="", alias="AI_PODCAST_WENXIN_API_KEY")
    moonshot_api_key: str = Field(default="", alias="AI_PODCAST_MOONSHOT_API_KEY")
    stepfun_api_key: str = Field(default="", alias="AI_PODCAST_STEPFUN_API_KEY")
    siliconflow_api_key: str = Field(default="", alias="AI_PODCAST_SILICONFLOW_API_KEY")

    # ---- 讯飞语音合成 ----
    xunfei_app_id: str = Field(default="", alias="AI_PODCAST_XUNFEI_APP_ID")
    xunfei_api_key: str = Field(default="", alias="AI_PODCAST_XUNFEI_API_KEY")
    xunfei_api_secret: str = Field(default="", alias="AI_PODCAST_XUNFEI_API_SECRET")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "populate_by_name": True}


def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
