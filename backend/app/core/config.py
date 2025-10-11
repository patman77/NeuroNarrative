from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEURONARRATIVE_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    app_name: str = Field(default="NeuroNarrative API")
    api_prefix: str = Field(default="/api")
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    max_event_duration: float = Field(default=30.0, description="Maximum window length in seconds around detected events")
    ollama_url: str = Field(default="http://127.0.0.1:11434/api/generate", description="Local LLM endpoint")
    ollama_model: str = Field(default="qwen2.5:7b-instruct-q4_K_M")
    summarizer_enabled: bool = Field(default=True)
    require_gpu_for_summarizer: bool = Field(
        default=True,
        description="Disable summarisation automatically when no GPU is available",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
