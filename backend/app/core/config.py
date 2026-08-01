from functools import lru_cache
from pathlib import Path

from platformdirs import user_cache_path, user_data_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIRNAME = "neuronarrative"


def _default_label_dir() -> Path:
    """Labels are *user data*, not cache: they are hand-made and must survive a cache purge."""
    return user_data_path(APP_DIRNAME) / "labels"


def _default_upload_dir() -> Path:
    """Per-user cache location; works unchanged on macOS, Linux and Windows."""
    return user_cache_path(APP_DIRNAME) / "uploads"


def _default_model_dir() -> Path:
    return user_cache_path(APP_DIRNAME) / "models"


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

    label_dir: Path = Field(
        default_factory=_default_label_dir,
        description="Where hand-made phenomenon labels are stored, one JSON file per recording",
    )
    upload_dir: Path = Field(
        default_factory=_default_upload_dir,
        description="Where uploaded CSV/WAV pairs are staged between /upload and /analyze",
    )
    upload_retention_hours: float = Field(
        default=24.0,
        description="Uploads older than this are pruned on each new upload; 0 disables pruning",
    )
    asr_model: str = Field(
        default="small",
        description=(
            "faster-whisper model size. Measured on noisy German: tiny 16.7% WER, "
            "base 6.7%, small 3.3%. Use 'base' to trade accuracy for ~2.5x speed."
        ),
    )
    asr_backend: str = Field(
        default="auto",
        description=(
            "Transcription backend: 'auto' picks MLX on Apple silicon, CUDA on an NVIDIA "
            "machine, else CPU. Force with 'mlx', 'cuda' or 'cpu'."
        ),
    )
    asr_temperature: float = Field(
        default=0.0,
        description=(
            "Decoding temperature. 0 is greedy and deterministic. Whisper's default is a "
            "fallback chain (0.0-1.0) that re-decodes hard passages with random sampling, "
            "which makes output vary run to run and occasionally loop."
        ),
    )
    asr_max_words_per_sec: float = Field(
        default=6.0,
        description=(
            "Sanity limit. German speech runs 2-3 words/s; a window exceeding this is a "
            "hallucination loop, not speech, and is dropped. 0 disables the check."
        ),
    )
    asr_vad: bool = Field(
        default=True,
        description=(
            "Skip non-speech with voice activity detection. Speeds up recordings with "
            "pauses and stops the model hallucinating text over silence."
        ),
    )
    asr_language: str | None = Field(
        default=None,
        description="Force a language code (e.g. 'de'); None auto-detects per recording",
    )
    asr_threads: int = Field(
        default=0,
        description=(
            "CPU threads for transcription. 0 = auto: performance cores minus headroom, "
            "so the machine stays usable during an analysis."
        ),
    )
    asr_model_dir: Path = Field(
        default_factory=_default_model_dir,
        description="Download cache for ASR model weights",
    )
    frontend_dist: Path | None = Field(
        default=None,
        description="Optional path to the built frontend; when set it is served at / (desktop builds)",
    )

    summary_context_sec: float = Field(
        default=45.0,
        description=(
            "Fallback radius in seconds when the configured pre/post window holds too "
            "little speech to summarise. Sessions are mostly silent — a 54-minute "
            "recording carried 1589 words, so a 12 s window is empty for most events and "
            "the nearest utterance is the only context there is. 0 disables the fallback."
        ),
    )
    summary_min_words: int = Field(
        default=4,
        description="Excerpts shorter than this are not sent to the LLM; there is nothing to summarise.",
    )

    ollama_url: str = Field(default="http://127.0.0.1:11434/api/generate", description="Local LLM endpoint")
    ollama_model: str = Field(default="qwen2.5:7b-instruct-q4_K_M")
    summarizer_enabled: bool = Field(default=True)
    # Filled in at startup by _configure_summarizer; surfaced via /api/health so the UI can
    # explain *why* summaries are missing instead of just saying they are.
    summarizer_status: str = Field(default="not checked")
    resolved_ollama_model: str = Field(default="")

    require_gpu_for_summarizer: bool = Field(
        default=True,
        description="Disable summarisation automatically when no GPU is available",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
