"""Speech-to-text with automatic backend selection.

Two backends behind one function:

* MLX (Apple GPU) — fast and accurate, but has **no VAD option**, so silence is segmented
  here with Silero before transcribing. Without that it invents speech over quiet passages,
  which is exactly the "same phrase repeated 200 times" failure this app hit in the field.
* CTranslate2 / faster-whisper (CUDA or CPU) — has VAD built in, so it does its own.

Both return word timings on the *original* recording timeline; anything else would break
event alignment.
"""

from __future__ import annotations

import functools
import logging
import re
import unicodedata
from collections import Counter
from math import gcd
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from ..core.config import Settings
from ..utils.accelerator import Accelerator, detect_accelerator, resolve_model
from ..utils.cpu import asr_thread_count, detect_cpu
from .transcript import TranscribedWord

logger = logging.getLogger(__name__)

ASR_SAMPLE_RATE = 16_000
# Whisper's own window is 30 s; longer chunks are re-split internally anyway.
MAX_WINDOW_SEC = 30.0
# Keep a little audio either side of detected speech so word onsets are not clipped.
WINDOW_PAD_SEC = 0.2
# Below this frame level nothing can plausibly be speech; normal speech sits near -30 dBFS.
SILENCE_DBFS = -60.0
# Below this many letters the transcript is too short to say which script it is written in.
DOMINANT_SCRIPT_MIN_CHARS = 200

ProgressFn = Callable[[str, float], None]


def decode_for_asr(wav_path: Path) -> np.ndarray:
    """Read a WAV into the mono float32 @ 16 kHz that the ASR models expect.

    Decoding here rather than letting the ASR library shell out to ffmpeg keeps the
    ffmpeg CLI off the runtime dependency list, which matters for desktop bundles.
    """
    audio, rate = sf.read(wav_path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)  # downmix to mono
    if rate != ASR_SAMPLE_RATE:
        divisor = gcd(int(rate), ASR_SAMPLE_RATE)
        audio = resample_poly(audio, ASR_SAMPLE_RATE // divisor, int(rate) // divisor)
    return np.ascontiguousarray(audio, dtype=np.float32)


def detect_speech_regions(
    audio: np.ndarray,
    frame_sec: float = 0.03,
    hop_sec: float = 0.01,
    margin_db: float = 8.0,
    min_speech_sec: float = 0.20,
    min_gap_sec: float = 0.50,
) -> list[tuple[float, float]]:
    """Energy-based voice activity detection, in pure numpy.

    Deliberately *not* Silero: that runs on onnxruntime, and loading onnxruntime's OpenMP
    runtime in the same process as MLX segfaults the process (verified — the order decides
    whether it crashes, and `KMP_DUPLICATE_LIB_OK` does not help). A self-contained detector
    removes the conflict instead of gambling on import order.

    The bar here is lower than general-purpose VAD: it only has to skip long quiet stretches
    so the model is never asked to transcribe silence. Whisper copes with noise inside a
    window on its own.
    """
    if audio.size == 0:
        return []

    frame = max(1, int(frame_sec * ASR_SAMPLE_RATE))
    hop = max(1, int(hop_sec * ASR_SAMPLE_RATE))
    if audio.size < frame:
        return [(0.0, audio.size / ASR_SAMPLE_RATE)]

    # Frame energies in dB, via a strided view (no copy).
    count = 1 + (audio.size - frame) // hop
    frames = np.lib.stride_tricks.as_strided(
        audio, shape=(count, frame), strides=(audio.strides[0] * hop, audio.strides[0])
    )
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)

    # Noise floor from the quiet tail of the distribution, so the threshold adapts to the
    # recording rather than assuming a level.
    floor = float(np.percentile(db, 10))
    peak = float(np.percentile(db, 95))

    if peak < SILENCE_DBFS:
        # Nothing anywhere is loud enough to be speech (digital silence, dead channel).
        return []
    if peak - floor < 6.0:
        # Uniform level throughout: either all speech or steady noise. Treat as speech and
        # let the model decide, rather than discarding the recording.
        return [(0.0, audio.size / ASR_SAMPLE_RATE)]

    enter = floor + margin_db
    exit_ = floor + margin_db * 0.6  # hysteresis, so a brief dip does not split a word

    regions: list[tuple[float, float]] = []
    start_idx: int | None = None
    for i, level in enumerate(db):
        if start_idx is None:
            if level >= enter:
                start_idx = i
        elif level < exit_:
            regions.append((start_idx * hop / ASR_SAMPLE_RATE, (i * hop + frame) / ASR_SAMPLE_RATE))
            start_idx = None
    if start_idx is not None:
        regions.append((start_idx * hop / ASR_SAMPLE_RATE, audio.size / ASR_SAMPLE_RATE))

    # Bridge short gaps, then drop blips.
    merged: list[tuple[float, float]] = []
    for start, end in regions:
        if merged and start - merged[-1][1] <= min_gap_sec:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return [(s, e) for s, e in merged if e - s >= min_speech_sec]


def speech_windows(audio: np.ndarray, enabled: bool = True) -> list[tuple[float, float]]:
    """Group speech regions into transcription windows, in seconds.

    Returns a single whole-file window when VAD is disabled, so callers always have
    something to iterate.
    """
    total = len(audio) / ASR_SAMPLE_RATE
    if not enabled or total <= 0:
        return [(0.0, total)]

    try:
        regions = detect_speech_regions(audio)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("VAD failed (%s); transcribing the whole recording.", exc)
        return [(0.0, total)]

    if not regions:
        logger.info("No speech detected in %.1f s of audio.", total)
        return []

    windows: list[tuple[float, float]] = []
    start = end = None
    for r_start, r_end in regions:
        r_start = max(0.0, r_start - WINDOW_PAD_SEC)
        r_end = min(total, r_end + WINDOW_PAD_SEC)
        if start is None:
            start, end = r_start, r_end
            continue
        # Extend the current window while it stays within Whisper's context length.
        if r_end - start <= MAX_WINDOW_SEC:
            end = r_end
        else:
            windows.append((start, end))
            start, end = r_start, r_end
    if start is not None:
        windows.append((start, end))

    # A single region longer than the model context still has to be split.
    split: list[tuple[float, float]] = []
    for w_start, w_end in windows:
        while w_end - w_start > MAX_WINDOW_SEC:
            split.append((w_start, w_start + MAX_WINDOW_SEC))
            w_start += MAX_WINDOW_SEC
        split.append((w_start, w_end))

    kept = sum(e - s for s, e in split)
    logger.info(
        "VAD: %d speech window(s), %.1f s of %.1f s (%.0f%% skipped)",
        len(split),
        kept,
        total,
        100 * (1 - kept / total) if total else 0,
    )
    return split


def transcribe(
    wav_path: Path, settings: Settings, progress: ProgressFn | None = None
) -> list[TranscribedWord]:
    """Transcribe a WAV, choosing the backend that suits this machine."""
    accelerator = detect_accelerator(settings.asr_backend)
    model_name = resolve_model(settings.asr_model, accelerator.backend)
    logger.info(
        "Transcribing with %s, model %r (%s)",
        accelerator.describe(),
        model_name,
        settings.asr_model,
    )

    audio = decode_for_asr(wav_path)
    if accelerator.backend == "mlx":
        words = _transcribe_mlx(audio, model_name, settings, progress)
    else:
        words = _transcribe_ctranslate2(audio, model_name, settings, accelerator, progress)
    return drop_hallucinated_tokens(words)


# ---------------------------------------------------------------------------
# MLX (Apple GPU)
# ---------------------------------------------------------------------------

def _reject_implausible_rate(
    words: list[TranscribedWord], start: float, end: float, settings: Settings
) -> list[TranscribedWord]:
    """Drop a window whose word rate is physically impossible for speech.

    A hallucination loop shows up as hundreds of words in a 30 s window — measured at up to
    237, i.e. ~8 words/second, where German speech runs 2-3. Dropping the window loses
    nothing real: the content was invented.
    """
    limit = settings.asr_max_words_per_sec
    duration = max(end - start, 0.001)
    if limit <= 0 or not words:
        return words

    rate = len(words) / duration
    if rate <= limit:
        return words

    logger.warning(
        "Discarding window %.1f-%.1fs: %d words in %.1fs (%.1f words/s) is a hallucination loop",
        start,
        end,
        len(words),
        duration,
        rate,
    )
    return []


# Letters of a cased alphabet are named "<SCRIPT> SMALL/CAPITAL LETTER ...". The phonetic
# extensions are not: `ʔ` is LATIN LETTER GLOTTAL STOP and `ʕ` is LATIN LETTER PHARYNGEAL
# VOICED FRICATIVE — both claim the Latin script, one is even lowercase, and neither ever
# occurs in a German or English word. Whisper emits them over breath and room tone.
_CASED_LETTER_RE = re.compile(r"^(.+?) (?:SMALL|CAPITAL) LETTER ")


def _script_of(char: str) -> str | None:
    """Script of a cased alphabetic letter ("LATIN", "GREEK", ...), else None."""
    match = _CASED_LETTER_RE.match(unicodedata.name(char, ""))
    return match.group(1) if match else None


def drop_hallucinated_tokens(words: list[TranscribedWord]) -> list[TranscribedWord]:
    """Remove tokens that are not words of the language the recording is in.

    Quiet passages made Whisper emit runs like `ლლლლ…` (Georgian), `සිවිිිිි…` (Sinhala)
    and `ʕ ʔ ʔ` (IPA) in the middle of a German session. `_reject_implausible_rate` cannot
    see these — two tokens in a 30 s window is a perfectly plausible *rate* — yet they are
    what an event gets summarised from, so the summary came back empty.

    Rather than hard-code an alphabet, take the script the transcript is overwhelmingly
    written in and drop tokens carrying no letter of it. Numbers and punctuation have no
    script and are always kept: spoken meter readings ("5,9", "2.5mm") are real content.

    A transcript in an uncased script (CJK, Arabic, Hebrew) yields no dominant script and
    is passed through untouched rather than being mangled by a rule built for cased ones.
    """
    counts = Counter(script for word in words for script in map(_script_of, word.text) if script)
    if not counts:
        return words

    dominant, dominant_count = counts.most_common(1)[0]
    if dominant_count < DOMINANT_SCRIPT_MIN_CHARS:
        # Too little text to tell a foreign hallucination from a genuinely short recording.
        return words

    kept = [
        word
        for word in words
        if not any(char.isalpha() for char in word.text)
        or any(_script_of(char) == dominant for char in word.text)
    ]
    if len(kept) != len(words):
        logger.warning(
            "Dropped %d of %d tokens that are not %s words (hallucinations over silence)",
            len(words) - len(kept),
            len(words),
            dominant.title(),
        )
    return kept


def _prepare_mlx_model(model_repo: str, settings: Settings) -> str:
    """Resolve the model to a local directory and make loading it a one-off.

    `mlx_whisper.transcribe` reloads the model on *every* call — and this transcribes one
    window at a time, so a long recording reloaded ~500 MB of weights into GPU memory a
    hundred times over. That churn is slow and destabilises Metal. Memoising the loader
    keeps the model resident for the whole run.

    Resolving the repo to a local path also stops huggingface_hub spawning fetch workers,
    which drag `multiprocessing` into a Metal process.
    """
    import mlx_whisper.load_models as load_models

    if not hasattr(load_models.load_model, "cache_info"):
        load_models.load_model = functools.lru_cache(maxsize=1)(load_models.load_model)

    if Path(model_repo).is_dir():
        return model_repo

    try:
        from huggingface_hub import snapshot_download

        return snapshot_download(
            repo_id=model_repo, cache_dir=str(settings.asr_model_dir), max_workers=1
        )
    except Exception as exc:
        # Offline with no cached copy, or a private repo: let mlx_whisper try its own way.
        logger.debug("Could not pre-resolve %s (%s); passing the repo id through.", model_repo, exc)
        return model_repo


def _transcribe_mlx(
    audio: np.ndarray,
    model_repo: str,
    settings: Settings,
    progress: ProgressFn | None,
) -> list[TranscribedWord]:
    import mlx_whisper

    model_path = _prepare_mlx_model(model_repo, settings)
    windows = speech_windows(audio, enabled=settings.asr_vad)
    if not windows:
        return []

    span_start, span_end = 0.15, 0.90
    total_speech = sum(end - start for start, end in windows) or 1.0
    processed = 0.0
    words: list[TranscribedWord] = []

    for start, end in windows:
        chunk = audio[int(start * ASR_SAMPLE_RATE) : int(end * ASR_SAMPLE_RATE)]
        if chunk.size == 0:
            continue

        result = mlx_whisper.transcribe(
            chunk,
            path_or_hf_repo=model_path,
            word_timestamps=True,
            language=settings.asr_language,
            # Whisper otherwise feeds its own output back as context and latches onto a
            # phrase, repeating it for minutes.
            condition_on_previous_text=False,
            # A single temperature, not Whisper's fallback chain: the chain re-decodes hard
            # passages with random sampling, so the same recording produced anywhere from
            # 1576 to 3234 words across runs, with individual windows occasionally looping.
            temperature=settings.asr_temperature,
            verbose=None,
        )

        window_words = [
            TranscribedWord(
                text=str(word["word"]).strip(),
                # Shift back onto the original timeline; event alignment depends on it.
                start=float(word["start"]) + start,
                end=float(word["end"]) + start,
                confidence=float(word.get("probability", 1.0)),
            )
            for segment in result.get("segments", [])
            for word in segment.get("words", [])
        ]
        words.extend(_reject_implausible_rate(window_words, start, end, settings))

        processed += end - start
        if progress:
            progress("transcribing", span_start + (processed / total_speech) * (span_end - span_start))

    return words


# ---------------------------------------------------------------------------
# CTranslate2 (CUDA or CPU)
# ---------------------------------------------------------------------------

def _transcribe_ctranslate2(
    audio: np.ndarray,
    model_name: str,
    settings: Settings,
    accelerator: Accelerator,
    progress: ProgressFn | None,
) -> list[TranscribedWord]:
    from faster_whisper import WhisperModel

    topology = detect_cpu()
    threads = asr_thread_count(override=settings.asr_threads, topology=topology)
    logger.info("CPU threads: %d; %s", threads, topology.describe())

    model = WhisperModel(
        model_name,
        device=accelerator.device,
        compute_type=accelerator.compute_type,
        cpu_threads=threads,
        download_root=str(settings.asr_model_dir),
    )

    # `segments` is a generator — transcription only runs as it is consumed.
    segments, info = model.transcribe(
        audio,
        word_timestamps=True,
        language=settings.asr_language,
        vad_filter=settings.asr_vad,
        condition_on_previous_text=False,
        temperature=settings.asr_temperature,
    )

    total = float(getattr(info, "duration", 0.0)) or 0.0
    span_start, span_end = 0.15, 0.90

    words: list[TranscribedWord] = []
    for segment in segments:
        if progress and total > 0:
            done = min(1.0, float(segment.end) / total)
            progress("transcribing", span_start + done * (span_end - span_start))
        for word in segment.words or []:
            words.append(
                TranscribedWord(
                    text=word.word.strip(),
                    start=float(word.start),
                    end=float(word.end),
                    confidence=float(word.probability),
                )
            )
    return words
