from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = Field(default="ok")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


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


class AnalysisResponse(BaseModel):
    events: list[SummarizedEvent]
    gsr_metadata: SignalMetadata
    audio_metadata: SignalMetadata


class UploadResponse(BaseModel):
    csv_path: str
    wav_path: str
