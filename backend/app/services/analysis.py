from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import soundfile as sf
from fastapi import HTTPException

from ..api.schemas import AnalysisRequest
from ..core.config import Settings
from .events import detect_events
from .summary import summarize_with_local_llm
from .transcript import TranscribedWord, align_transcript


@dataclass
class SignalMetadata:
    sampling_rate_hz: float
    duration_sec: float

    def model_dump(self) -> dict[str, float]:
        return {
            "sampling_rate_hz": self.sampling_rate_hz,
            "duration_sec": self.duration_sec,
        }


async def run_analysis(payload: AnalysisRequest, settings: Settings) -> dict[str, Any]:
    csv_path = Path(payload.csv_path)
    wav_path = Path(payload.wav_path)

    gsr_df = _load_gsr(csv_path)
    gsr_metadata = SignalMetadata(
        sampling_rate_hz=_infer_sampling_rate(gsr_df),
        duration_sec=float(gsr_df["time_sec"].iloc[-1] - gsr_df["time_sec"].iloc[0]),
    )

    audio_metadata = _load_audio_metadata(wav_path)

    events = detect_events(
        timestamps=gsr_df["time_sec"].to_numpy(),
        readings=gsr_df["resistance_kohm"].to_numpy(),
        ruleset=payload.ruleset_name,
    )

    words = await _transcribe_audio(wav_path)

    event_payloads = await _summaries_for_events(
        events=events,
        timestamps=gsr_df["time_sec"].to_numpy(),
        readings=gsr_df["resistance_kohm"].to_numpy(),
        words=words,
        pre_window=payload.pre_event_window_sec,
        post_window=payload.post_event_window_sec,
        settings=settings,
    )

    return {
        "events": event_payloads,
        "gsr_metadata": gsr_metadata.model_dump(),
        "audio_metadata": audio_metadata.model_dump(),
    }


async def _transcribe_audio(wav_path: Path) -> list[TranscribedWord]:
    # Placeholder for integration with Whisper or other ASR.
    # Returns an empty transcript for now so the rest of the pipeline can be tested.
    return []


async def _summaries_for_events(
    events: list[dict[str, Any]],
    timestamps: np.ndarray,
    readings: np.ndarray,
    words: list[TranscribedWord],
    pre_window: float,
    post_window: float,
    settings: Settings,
) -> list[dict[str, Any]]:
    async def process_event(event: dict[str, Any]) -> dict[str, Any]:
        event_time = event["time_sec"]
        excerpt, summary = "", None
        window_words = align_transcript(words, event_time, pre_window, post_window)
        if window_words:
            excerpt = " ".join(w.text for w in window_words)
            if settings.summarizer_enabled:
                summary = await summarize_with_local_llm(excerpt, settings=settings)
        return {
            "event_id": event.get("event_id", uuid.uuid4().hex),
            "time_sec": event_time,
            "rule": event.get("rule", "unknown"),
            "delta_kohm": event.get("delta_kohm"),
            "delta_z": event.get("delta_z"),
            "transcript_excerpt": excerpt or None,
            "summary": summary if summary and summary.upper() != "NONE" else None,
            "score": event.get("score"),
        }

    return await asyncio.gather(*[process_event(evt) for evt in events])


def _load_gsr(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    time_column = next((c for c in df.columns if "time" in c.lower()), None)
    resistance_column = next((c for c in df.columns if "resistance" in c.lower()), None)
    if not time_column or not resistance_column:
        raise HTTPException(status_code=400, detail="CSV must contain Time and Resistance columns")

    df = df.rename(columns={time_column: "time", resistance_column: "resistance"})
    df["time_sec"] = df["time"].astype(float) / (1000 if df["time"].max() > 1000 else 1)
    df["resistance_kohm"] = df["resistance"].astype(float)
    df = df.sort_values("time_sec").reset_index(drop=True)
    return df[["time_sec", "resistance_kohm"]]


def _load_audio_metadata(path: Path) -> SignalMetadata:
    data, rate = sf.read(path)
    duration = len(data) / rate
    return SignalMetadata(sampling_rate_hz=float(rate), duration_sec=float(duration))


def _infer_sampling_rate(df: pd.DataFrame) -> float:
    diffs = df["time_sec"].diff().dropna()
    if diffs.empty:
        return 0.0
    avg_interval = diffs.mean()
    if avg_interval == 0:
        return 0.0
    return float(1 / avg_interval)
