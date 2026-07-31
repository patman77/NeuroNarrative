"""Unit tests for _load_gsr and _infer_sampling_rate in app.services.analysis."""
from __future__ import annotations

import pytest

pytest.importorskip("pandas")
pytest.importorskip("fastapi")

import pandas as pd  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.services.analysis import _infer_sampling_rate, _load_gsr  # noqa: E402


# ---------------------------------------------------------------------------
# _load_gsr
# ---------------------------------------------------------------------------

def test_load_gsr_valid(tmp_path):
    """Valid CSV with Time and resistance columns returns correct DataFrame."""
    csv = tmp_path / "gsr.csv"
    csv.write_text("Time,resistance\n0,10.5\n100,11.0\n200,10.8\n")

    df = _load_gsr(csv)

    assert list(df.columns) == ["time_sec", "resistance_kohm"]
    assert len(df) == 3
    # Time values are in milliseconds (max=200 > 1000 is False here, so kept as-is)
    assert df["time_sec"].iloc[0] == pytest.approx(0.0)
    assert df["resistance_kohm"].iloc[1] == pytest.approx(11.0)


def test_load_gsr_missing_resistance_column(tmp_path):
    """CSV without a resistance column raises HTTPException(400)."""
    csv = tmp_path / "bad.csv"
    csv.write_text("Time,voltage\n0,3.3\n100,3.4\n")

    with pytest.raises(HTTPException) as exc_info:
        _load_gsr(csv)
    assert exc_info.value.status_code == 400


def test_load_gsr_time_in_milliseconds(tmp_path):
    """When time column max > 1000 (ms), time_sec should be divided by 1000."""
    rows = "\n".join(f"{i * 100},{10 + i * 0.1}" for i in range(20))
    csv = tmp_path / "ms.csv"
    csv.write_text(f"Time,resistance\n{rows}\n")

    df = _load_gsr(csv)

    # max raw time = 19 * 100 = 1900 ms → divided by 1000 → 1.9 s
    assert df["time_sec"].max() == pytest.approx(1.9)
    assert df["time_sec"].min() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _decode_for_asr
# ---------------------------------------------------------------------------

def test_decode_for_asr_downmixes_and_resamples(tmp_path):
    """Stereo 44.1 kHz input becomes mono float32 at the 16 kHz the ASR model wants."""
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")

    from app.services.asr import ASR_SAMPLE_RATE, decode_for_asr

    rate = 44_100
    t = np.arange(0, 2, 1 / rate)
    stereo = np.stack([0.3 * np.sin(2 * np.pi * 220 * t), 0.3 * np.sin(2 * np.pi * 440 * t)], axis=1)
    wav = tmp_path / "stereo.wav"
    sf.write(wav, stereo, rate)

    audio = decode_for_asr(wav)

    assert audio.ndim == 1
    assert audio.dtype == np.float32
    assert audio.flags["C_CONTIGUOUS"]
    assert audio.shape[0] == pytest.approx(2 * ASR_SAMPLE_RATE, abs=10)


def test_decode_for_asr_passes_through_16k_mono(tmp_path):
    """Already-conformant audio is returned without resampling."""
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")

    from app.services.asr import ASR_SAMPLE_RATE, decode_for_asr

    t = np.arange(0, 1, 1 / ASR_SAMPLE_RATE)
    wav = tmp_path / "mono.wav"
    sf.write(wav, 0.2 * np.sin(2 * np.pi * 440 * t), ASR_SAMPLE_RATE)

    audio = decode_for_asr(wav)

    assert audio.shape[0] == ASR_SAMPLE_RATE
    assert audio.dtype == np.float32


# ---------------------------------------------------------------------------
# _infer_sampling_rate
# ---------------------------------------------------------------------------

def test_infer_sampling_rate_regular_10hz():
    """Regular 10 Hz signal (0.1 s intervals) → returns ~10.0."""
    times = [i * 0.1 for i in range(50)]
    df = pd.DataFrame({"time_sec": times})
    rate = _infer_sampling_rate(df)
    assert rate == pytest.approx(10.0, rel=0.01)


def test_infer_sampling_rate_single_row():
    """Single-row DataFrame → returns 0.0 (no intervals to compute)."""
    df = pd.DataFrame({"time_sec": [0.0]})
    rate = _infer_sampling_rate(df)
    assert rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Time unit detection
# ---------------------------------------------------------------------------

def test_long_recording_in_seconds_is_not_treated_as_milliseconds(tmp_path):
    """Regression: a 30-min recording logged in seconds was compressed to 1.8 s.

    The old rule divided by 1000 whenever max(time) > 1000, so any session longer than
    ~16.7 minutes silently lost its real duration.
    """
    rows = "\n".join(f"{i * 0.02:.2f},{3.0 + i * 1e-5}" for i in range(90_000))
    csv = tmp_path / "long.csv"
    csv.write_text(f"Time,resistance\n{rows}\n")

    df = _load_gsr(csv)

    assert df["time_sec"].max() == pytest.approx(1799.98, abs=0.1)


def test_milliseconds_still_detected_by_step_size(tmp_path):
    """A 100 ms step means milliseconds, even when the total is small."""
    rows = "\n".join(f"{i * 100},{10 + i * 0.1}" for i in range(50))
    csv = tmp_path / "ms.csv"
    csv.write_text(f"Time,resistance\n{rows}\n")

    df = _load_gsr(csv)

    assert df["time_sec"].max() == pytest.approx(4.9)


def test_millisecond_column_name_is_honoured(tmp_path):
    """An explicit unit in the header wins over the step heuristic."""
    rows = "\n".join(f"{i * 0.5},{10 + i}" for i in range(10))
    csv = tmp_path / "named.csv"
    csv.write_text(f"time_ms,resistance\n{rows}\n")

    df = _load_gsr(csv)

    assert df["time_sec"].max() == pytest.approx(0.0045)


# ---------------------------------------------------------------------------
# Summary context window
# ---------------------------------------------------------------------------

def test_context_widens_when_the_exact_window_is_empty():
    """A silent 12 s window around an event still gets the nearest speech as context.

    This is what "No summary available" actually meant on a real recording: 1589 words
    spread over 54 minutes, so 17 of 23 events had an empty pre/post window.
    """
    from app.services.analysis import _context_words
    from app.services.transcript import TranscribedWord

    words = [TranscribedWord(text=f"w{i}", start=100.0 + i, end=100.5 + i) for i in range(8)]
    settings = Settings(summary_context_sec=45.0, summary_min_words=4)

    # Event 30 s after the speech: outside the 5/7 s window, inside the 45 s fallback.
    assert _context_words(words, 135.0, 5.0, 7.0, settings) == words
    # Nothing within the fallback radius either — stays empty rather than inventing context.
    assert _context_words(words, 400.0, 5.0, 7.0, settings) == []


def test_context_prefers_the_narrow_window_when_it_suffices():
    """Dense passages must not be widened; the tight window is the more precise context."""
    from app.services.analysis import _context_words
    from app.services.transcript import TranscribedWord

    near = [TranscribedWord(text=f"n{i}", start=100.0 + i * 0.5, end=100.4 + i * 0.5) for i in range(8)]
    far = [TranscribedWord(text="far", start=130.0, end=130.5)]
    settings = Settings(summary_context_sec=45.0, summary_min_words=4)

    assert _context_words(near + far, 101.0, 5.0, 7.0, settings) == near


def test_context_fallback_can_be_disabled():
    from app.services.analysis import _context_words
    from app.services.transcript import TranscribedWord

    words = [TranscribedWord(text="w", start=100.0, end=100.5)]
    settings = Settings(summary_context_sec=0.0)
    assert _context_words(words, 135.0, 5.0, 7.0, settings) == []

# ---------------------------------------------------------------------------
# Protocol-cue fallback (guided-recall session phrases)
# ---------------------------------------------------------------------------

def _speech(text: str, start: float, step: float = 0.6):
    from app.services.transcript import TranscribedWord

    return [
        TranscribedWord(text=tok, start=start + i * step, end=start + (i + 1) * step)
        for i, tok in enumerate(text.split())
    ]


def test_context_falls_back_to_the_protocol_exercise():
    """An event in a long silence still gets the exercise it sits in as context.

    The opener "Ruf dir ein Erlebnis zurück" and the closing "Danke" bound the exercise;
    the 45 s radius holds nothing, so the whole exercise becomes the excerpt.
    """
    from app.services.analysis import _context_words

    content = (
        _speech("Ruf dir ein Erlebnis zurück als du ausgesperrt warst", 100.0)
        + _speech("Ich stand vor der Tür ohne Schlüssel", 160.0)
    )
    words = content + _speech("Danke", 400.0)
    settings = Settings(summary_context_sec=45.0, summary_min_words=4)

    # Event at 300 s: >45 s from any speech, but inside the ruf-zurück…Danke exercise.
    # The closing "Danke" is a cue, not content, and stays out of the excerpt.
    selected = _context_words(words, 300.0, 5.0, 7.0, settings)
    assert selected == content


def test_context_prefers_the_subsection_cue():
    """"Beschreibe" opens a subchapter; an event inside it gets that scope, not the whole exercise."""
    from app.services.analysis import _context_words

    exercise = _speech("Ruf dir ein Erlebnis zurück", 100.0)
    detail = _speech("Beschreibe was du an der Tür gesehen hast genau", 200.0)
    closing = _speech("Danke", 500.0)
    settings = Settings(summary_context_sec=45.0, summary_min_words=4)

    # Event at 260 s: silence around it, inside the Beschreibe subsection.
    assert _context_words(exercise + detail + closing, 260.0, 5.0, 7.0, settings) == detail


def test_context_without_cues_keeps_the_widened_window():
    """Recordings that don't follow the protocol behave exactly as before."""
    from app.services.analysis import _context_words

    words = _speech("nur normale Sprache ohne besondere Hinweise", 100.0)
    settings = Settings(summary_context_sec=45.0, summary_min_words=4)
    assert _context_words(words, 400.0, 5.0, 7.0, settings) == []


def test_session_markers_match_ascii_umlaut_spelling_and_all_cues():
    from app.services.transcript import find_session_markers

    words = (
        _speech("ruf zurueck", 10.0)
        + _speech("was siehst du noch", 20.0)
        + _speech("was ist am deutlichsten", 30.0)
        + _speech("Danke,", 40.0)
    )
    kinds = [(m.kind, m.time) for m in find_session_markers(words)]
    assert kinds == [("begin", 10.0), ("section", 20.0), ("section", 30.0), ("end", 40.0)]


def test_ruf_alone_is_not_an_opener():
    """"ruf" without a nearby "zurück" (e.g. "ruf mich an") must not start an exercise."""
    from app.services.transcript import find_session_markers

    words = _speech("ruf mich später bitte einfach nochmal kurz an", 10.0)
    assert find_session_markers(words) == []
