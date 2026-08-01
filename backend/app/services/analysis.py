from __future__ import annotations

import asyncio
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import soundfile as sf
from fastapi import HTTPException

from ..api.schemas import AnalysisRequest
from ..core.config import Settings
from .asr import transcribe
from .events import detect_events
from .phenomena.conditioning import ChannelResolution, ChannelResolutionError, conditioned_frame
from .phenomena.fusion import detect_phenomena
from .summary import summarize_with_local_llm
from .protocol import parse_session, segment_turns
from .transcript import TranscribedWord, align_transcript, protocol_segment

logger = logging.getLogger(__name__)


@dataclass
class SignalMetadata:
    sampling_rate_hz: float
    duration_sec: float

    def model_dump(self) -> dict[str, float]:
        return {
            "sampling_rate_hz": self.sampling_rate_hz,
            "duration_sec": self.duration_sec,
        }


ProgressFn = Callable[[str, float], None]


def _noop_progress(stage: str, fraction: float) -> None:
    """Default when nobody is watching (direct calls, tests)."""


async def run_analysis(
    payload: AnalysisRequest,
    settings: Settings,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    report = progress or _noop_progress
    csv_path = Path(payload.csv_path)
    wav_path = Path(payload.wav_path)

    # Parsing and detection are CPU-bound; off the event loop so the API stays responsive
    # (health checks included) while a long recording is processed.
    report("parsing", 0.02)
    gsr_df, channel_resolution = await asyncio.to_thread(_load_gsr, csv_path)
    gsr_metadata = SignalMetadata(
        sampling_rate_hz=_infer_sampling_rate(gsr_df),
        duration_sec=float(gsr_df["time_sec"].iloc[-1] - gsr_df["time_sec"].iloc[0]),
    )

    audio_metadata = await asyncio.to_thread(_load_audio_metadata, wav_path)

    logger.info(
        "Analysing %d GSR samples (%.1f s) with ruleset %r",
        len(gsr_df),
        gsr_metadata.duration_sec,
        payload.ruleset_name,
    )
    report("detecting", 0.08)
    # Detection runs on LP (log resistance), not kOhm: the same physiological event produces
    # ~15x the kOhm delta at LP 5.5 that it does at LP 2.5, so kOhm thresholds are not
    # comparable within a session. See docs/mindwalking-domain.md §4.
    events = await asyncio.to_thread(
        detect_events,
        gsr_df["time_sec"].to_numpy(),
        gsr_df["lp"].to_numpy(),
        payload.ruleset_name,
    )
    logger.info("Detected %d events", len(events))

    report("transcribing", 0.15)
    words = await _transcribe_audio(wav_path, settings=settings, progress=report)

    # The MindWalking phenomenon catalogue, run *after* transcription so the cross-modal layer
    # has utterances to lock against. The Eiserne Regeln make timing relative to speech
    # constitutive, so this ordering is not incidental.
    utterances = segment_turns(words)
    session_tree = parse_session(utterances, gsr_metadata.duration_sec)
    phenomena = await asyncio.to_thread(
        detect_phenomena,
        gsr_df["time_sec"].to_numpy(),
        gsr_df["lp"].to_numpy(),
        payload.lp_offset,
        payload.a_unit_lp,
        utterances,
    )

    report("summarising", 0.92)
    event_payloads = await _summaries_for_events(
        events=events,
        timestamps=gsr_df["time_sec"].to_numpy(),
        readings=gsr_df["lp"].to_numpy(),
        words=words,
        pre_window=payload.pre_event_window_sec,
        post_window=payload.post_event_window_sec,
        settings=settings,
    )

    return {
        "events": event_payloads,
        "phenomena": phenomena.as_dict()["phenomena"],
        "session_metrics": phenomena.as_dict()["metrics"],
        "calibration": phenomena.as_dict()["calibration"],
        "artefacts": phenomena.as_dict()["artefacts"],
        "protocol": [segment.as_dict() for segment in session_tree],
        "channel": {
            "strategy": channel_resolution.strategy,
            "resolution_lp": channel_resolution.resolution_lp,
            "quantised": channel_resolution.quantised,
            "source_columns": channel_resolution.source_columns,
            "notes": channel_resolution.notes,
        },
        "gsr_metadata": gsr_metadata.model_dump(),
        "audio_metadata": audio_metadata.model_dump(),
        "transcript": [
            {"text": w.text, "start": w.start, "end": w.end}
            for w in words
        ],
    }


# One dedicated thread for all transcription. `asyncio.to_thread` would hand the work to an
# arbitrary pool thread, so consecutive analyses could drive the GPU from different threads;
# Metal does not appreciate that. A single worker also serialises concurrent analyses, which
# is what you want with one GPU anyway.
_ASR_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")


async def _transcribe_audio(
    wav_path: Path, settings: Settings, progress: ProgressFn | None = None
) -> list[TranscribedWord]:
    """Transcribe off the event loop, degrading to an empty transcript on any failure."""
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _ASR_EXECUTOR, partial(transcribe, wav_path, settings, progress)
        )
    except ImportError:
        logger.info("No ASR backend installed; returning an empty transcript.")
        return []
    except Exception as exc:
        # Log and continue — transcription failure should not block event detection
        logger.warning("Transcription failed: %s", exc)
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
        window_words = _context_words(words, event_time, pre_window, post_window, settings)
        if window_words:
            excerpt = " ".join(w.text for w in window_words)
            if settings.summarizer_enabled:
                summary = await summarize_with_local_llm(
                    excerpt, settings=settings, resolved_model=settings.resolved_ollama_model
                )
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


def _context_words(
    words: list[TranscribedWord],
    event_time: float,
    pre_window: float,
    post_window: float,
    settings: Settings,
) -> list[TranscribedWord]:
    """Words around an event, widening the search when the exact window is near-empty.

    The configured window (5 s before, 7 s after) assumes someone is talking continuously.
    Real sessions are mostly silent: a 54-minute recording held 1589 words, so 17 of 23
    events had fewer than the handful of words a summary needs and the UI just said "no
    summary available". Widening to `summary_context_sec` picks up the nearest utterance,
    which is the only context that exists. The narrow window still wins whenever it has
    enough on its own, so dense passages are unaffected.

    When even the widened window is too sparse, the last resort is the session protocol
    itself: the facilitator's cue phrases ("ruf … zurück" / "Beschreibe" / "Danke", see
    `protocol_segment`) bound the exercise the event belongs to, and everything said in
    that exercise is the context there is.
    """
    selected = align_transcript(words, event_time, pre_window, post_window)
    radius = settings.summary_context_sec
    if len(selected) >= settings.summary_min_words or radius <= max(pre_window, post_window):
        return selected
    widened = align_transcript(words, event_time, radius, radius)
    if len(widened) >= settings.summary_min_words:
        return widened
    segment = protocol_segment(words, event_time, settings.summary_min_words)
    return segment if segment is not None else widened


def _load_gsr(path: Path) -> tuple[pd.DataFrame, ChannelResolution]:
    """Parse a GSR export into the canonical `time_sec` / `lp` / `resistance_kohm` frame.

    Channel selection lives in `phenomena.conditioning` so the preview and the analysis cannot
    resolve the same file to different columns — which they did, the frontend plotting the
    quantised `Baseline` while this analysed `Resistance(kOhm)`.
    """
    try:
        frame, resolution = conditioned_frame(pd.read_csv(path))
    except ChannelResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for note in resolution.notes:
        logger.info("GSR conditioning: %s", note)
    return frame, resolution


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
