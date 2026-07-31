from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = Field(default="ok")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summarizer_enabled: bool = Field(default=False)
    summarizer_status: str = Field(default="", description="Why summaries are or are not available")
    gpu_available: bool = Field(default=False)
    cpu: str = Field(default="", description="Detected CPU topology")
    asr_threads: int = Field(default=0, description="Threads transcription will use")


class SignalMetadata(BaseModel):
    sampling_rate_hz: float
    duration_sec: float


class SummarizedEvent(BaseModel):
    event_id: str
    time_sec: float
    rule: str
    delta_kohm: float | None = None
    delta_z: float | None = None
    summary: str | None = None
    transcript_excerpt: str | None = None
    score: float | None = None


class AnalysisRequest(BaseModel):
    csv_path: str = Field(..., description="Temporary path to uploaded GSR CSV")
    wav_path: str = Field(..., description="Temporary path to uploaded WAV audio")
    ruleset_name: str = Field(default="default")
    pre_event_window_sec: float = Field(default=5.0)
    post_event_window_sec: float = Field(default=7.0)


class TranscriptWord(BaseModel):
    text: str
    start: float | None = None
    end: float | None = None


class AnalysisResponse(BaseModel):
    events: list[SummarizedEvent]
    gsr_metadata: SignalMetadata
    audio_metadata: SignalMetadata
    transcript: list[TranscriptWord] = []


class UploadResponse(BaseModel):
    csv_path: str
    wav_path: str


class AnalysisJobCreated(BaseModel):
    job_id: str


class AnalysisJobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    stage: str = ""
    progress: float = 0.0
    result: AnalysisResponse | None = None
    error: str | None = None
