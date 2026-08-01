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
    lp_offset: float | None = Field(
        default=None,
        description=(
            "Solo-electrode offset in LP, subtracted before naming a charge zone. The solo "
            "procedure has you measure it at every session start ('Dif.'). Without it no zone "
            "is named at all, because a single-hand electrode reads an entire session as "
            "Kampfzone."
        ),
    )
    a_unit_lp: float | None = Field(
        default=None,
        description=(
            "Size of one scale division (1A) in LP, from the Dosendruck calibration. Without it "
            "a fallback scale is used and every A-magnitude is flagged uncalibrated."
        ),
    )


class TranscriptWord(BaseModel):
    text: str
    start: float | None = None
    end: float | None = None


class Phenomenon(BaseModel):
    id: str
    kind: str
    t_start: float
    t_end: float
    amplitude_lp: float | None = None
    amplitude_a: float | None = None
    confidence: float = 1.0
    stimulus_locked: bool | None = None
    utterance_id: str | None = None
    detector: str = ""
    evidence: dict = Field(default_factory=dict)


class AnalysisResponse(BaseModel):
    recording_id: str = ""
    events: list[SummarizedEvent]
    phenomena: list[Phenomenon] = Field(default_factory=list)
    session_metrics: dict = Field(default_factory=dict)
    calibration: dict = Field(default_factory=dict)
    artefacts: dict = Field(default_factory=dict)
    protocol: list[dict] = Field(default_factory=list)
    channel: dict = Field(default_factory=dict)
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


class LabelRequest(BaseModel):
    phenomenon_id: str = Field(default="", description="Empty only for a 'missed' verdict")
    verdict: Literal["confirmed", "rejected", "reclassified", "missed"]
    kind: str | None = Field(default=None, description="Required for 'reclassified' and 'missed'")
    t_start: float | None = Field(default=None, description="Required for 'missed'")
    note: str = ""


class LabelListResponse(BaseModel):
    recording_id: str
    labels: list[dict] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class EvaluateRequest(BaseModel):
    phenomena: list[dict] = Field(default_factory=list)
    tolerance_sec: float = Field(
        default=2.0,
        description="Onset match window. The SCR literature uses ±1 s; ±2 s allows for ASR "
        "timing slop and the 0.5 s smoothing window.",
    )
