"""VAD windowing and timeline mapping.

MLX has no VAD of its own, so windows are cut here — and the word timings it returns are
relative to each window. Getting the offset wrong would silently misplace every transcript
excerpt against its event, so it is tested directly.
"""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("soundfile")
pytest.importorskip("scipy")

from app.services.asr import (  # noqa: E402
    ASR_SAMPLE_RATE,
    MAX_WINDOW_SEC,
    decode_for_asr,
    drop_hallucinated_tokens,
    speech_windows,
)
from app.services.transcript import TranscribedWord  # noqa: E402


def _speech_like(seconds: float, seed: int = 0) -> np.ndarray:
    """Amplitude-modulated tone: loud enough for the VAD to treat as voice."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, seconds, 1 / ASR_SAMPLE_RATE)
    carrier = 0.4 * np.sin(2 * np.pi * 150 * t)
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
    return (carrier * envelope + rng.normal(0, 0.01, len(t))).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * ASR_SAMPLE_RATE), dtype=np.float32)


# ---------------------------------------------------------------------------
# windowing
# ---------------------------------------------------------------------------

def test_disabled_vad_returns_one_whole_file_window():
    audio = _speech_like(5.0)
    assert speech_windows(audio, enabled=False) == [(0.0, pytest.approx(5.0, abs=0.01))]


def test_windows_stay_inside_the_recording():
    audio = np.concatenate([_silence(1.0), _speech_like(3.0), _silence(2.0)])
    total = len(audio) / ASR_SAMPLE_RATE

    for start, end in speech_windows(audio, enabled=True):
        assert 0.0 <= start < end <= total + 1e-6


def test_windows_never_exceed_the_model_context():
    """Long continuous speech must be split, or Whisper silently truncates."""
    audio = _speech_like(90.0)

    for start, end in speech_windows(audio, enabled=True):
        assert end - start <= MAX_WINDOW_SEC + 2 * 0.2 + 1e-6


def test_silence_only_audio_yields_no_windows():
    """Nothing to transcribe beats hallucinating over silence."""
    assert speech_windows(_silence(10.0), enabled=True) == []


def test_empty_audio_is_handled():
    assert speech_windows(np.zeros(0, dtype=np.float32), enabled=False) == [(0.0, 0.0)]


# ---------------------------------------------------------------------------
# timeline mapping (the offset MLX results need)
# ---------------------------------------------------------------------------

def test_window_offsets_reconstruct_original_times():
    """A word at 1.0 s inside a window starting at 42 s belongs at 43 s."""
    windows = [(0.0, 5.0), (42.0, 55.0)]
    word_times_in_window = [1.0, 3.5]

    absolute = [w + start for (start, _), w in zip(windows, word_times_in_window)]

    assert absolute == [1.0, 45.5]


def test_decode_matches_asr_sample_rate(tmp_path):
    sf = pytest.importorskip("soundfile")
    wav = tmp_path / "s.wav"
    sf.write(wav, _speech_like(1.0), ASR_SAMPLE_RATE)

    audio = decode_for_asr(wav)

    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert len(audio) == pytest.approx(ASR_SAMPLE_RATE, abs=10)


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------

def test_analysis_delegates_to_the_asr_module(monkeypatch, tmp_path):
    """Regression: analysis.py once lost its `transcribe` import.

    Every unit test still passed, because none of them exercised the path from analysis
    into the ASR module — the failure only appeared in the packaged app, where it was
    swallowed into an empty transcript.
    """
    import asyncio

    from app.core.config import Settings
    from app.services import analysis
    from app.services.transcript import TranscribedWord

    called = {}

    def fake_transcribe(wav_path, settings, progress=None):
        called["wav"] = wav_path
        if progress:
            progress("transcribing", 0.5)
        return [TranscribedWord(text="hallo", start=0.0, end=0.5, confidence=0.9)]

    monkeypatch.setattr(analysis, "transcribe", fake_transcribe)

    words = asyncio.run(
        analysis._transcribe_audio(tmp_path / "x.wav", Settings(), lambda s, f: None)
    )

    assert called["wav"] == tmp_path / "x.wav"
    assert [w.text for w in words] == ["hallo"]


def test_transcription_failure_yields_empty_transcript(monkeypatch, tmp_path):
    """A broken ASR backend must not sink the whole analysis."""
    import asyncio

    from app.core.config import Settings
    from app.services import analysis

    def boom(*_args, **_kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(analysis, "transcribe", boom)

    assert asyncio.run(analysis._transcribe_audio(tmp_path / "x.wav", Settings())) == []


# ---------------------------------------------------------------------------
# hallucination guard
# ---------------------------------------------------------------------------

def _words(n, start=0.0, end=30.0):
    from app.services.transcript import TranscribedWord

    step = (end - start) / max(n, 1)
    return [
        TranscribedWord(text=f"w{i}", start=start + i * step, end=start + (i + 1) * step)
        for i in range(n)
    ]


def test_plausible_speech_rate_is_kept():
    from app.core.config import Settings
    from app.services.asr import _reject_implausible_rate

    # 75 words in 30 s = 2.5 words/s, normal German speech
    kept = _reject_implausible_rate(_words(75), 0.0, 30.0, Settings())
    assert len(kept) == 75


def test_hallucination_loop_is_discarded():
    """Regression: windows occasionally returned 237 words in 30 s (~8 words/s)."""
    from app.core.config import Settings
    from app.services.asr import _reject_implausible_rate

    assert _reject_implausible_rate(_words(237), 0.0, 30.0, Settings()) == []


def test_rate_guard_can_be_disabled():
    from app.core.config import Settings
    from app.services.asr import _reject_implausible_rate

    settings = Settings(asr_max_words_per_sec=0)
    assert len(_reject_implausible_rate(_words(237), 0.0, 30.0, settings)) == 237


def test_short_window_is_not_penalised():
    """A couple of words in a 1 s window is fine, not a loop."""
    from app.core.config import Settings
    from app.services.asr import _reject_implausible_rate

    assert len(_reject_implausible_rate(_words(3, 0.0, 1.0), 0.0, 1.0, Settings())) == 3


# ---------------------------------------------------------------------------
# Hallucinated-token filtering
# ---------------------------------------------------------------------------

def _tokens(*texts: str) -> list[TranscribedWord]:
    return [TranscribedWord(text=t, start=float(i), end=float(i) + 0.5) for i, t in enumerate(texts)]


def _german_filler(count: int = 120) -> list[TranscribedWord]:
    """Enough real text to establish a dominant script (the filter needs 200 letters)."""
    return _tokens(*(["Sitzung", "beginnt", "gleich"] * count))


def test_drop_hallucinated_tokens_removes_foreign_scripts():
    """Whisper emits Georgian/Sinhala runs over silence in an otherwise German recording."""
    words = _german_filler() + _tokens("ლლლლლლლლ", "වවවවවවවව", "සිවිිිිිිි")
    kept = drop_hallucinated_tokens(words)
    assert [w.text for w in kept] == [w.text for w in _german_filler()]


def test_drop_hallucinated_tokens_removes_ipa_glyphs():
    """`ʔ` and `ʕ` claim the Latin script — one is even lowercase — but are not words."""
    words = _german_filler() + _tokens("ʔ", "ʕ", "ʕʕʔʔʔʔʔʔ")
    assert [w.text for w in drop_hallucinated_tokens(words)] == [w.text for w in _german_filler()]


def test_drop_hallucinated_tokens_keeps_numbers_and_umlauts():
    """Spoken meter readings are real content and carry no script of their own."""
    extras = _tokens("5,9", "2.5mm", "43", "Übung", "heißt", "café", "...")
    kept = drop_hallucinated_tokens(_german_filler() + extras)
    assert [w.text for w in kept[-len(extras):]] == [w.text for w in extras]


def test_drop_hallucinated_tokens_passes_short_transcripts_through():
    """Under 200 letters there is no reliable dominant script, so nothing is dropped."""
    words = _tokens("Hallo", "ლლლლ")
    assert drop_hallucinated_tokens(words) == words


def test_drop_hallucinated_tokens_leaves_uncased_scripts_alone():
    """A Japanese transcript yields no cased dominant script; passing it through beats mangling it."""
    words = _tokens(*(["日本語", "です", "ね"] * 100))
    assert drop_hallucinated_tokens(words) == words
