"""L1 primitives: the substrate every phenomenon detector is a predicate over.

Two components carry different halves of the vocabulary and must not be collapsed into one
threshold (`docs/phenomena-detection-design.md` §3):

- **tonic** — the slowly varying charge level. `LP`, `LPA`, `LPD`, `LPB` and the zones are
  statements about this.
- **deflections** — excursions riding on it. `A`, `T`, `BE` are statements about these.

Sign convention: amplitudes stay in **signed LP**, so a fall — release, in the method's reading —
is *negative*. The design notes that negating to conductance-like polarity is what lets the EDA
literature apply directly; that only matters when we adopt a published decomposition (cvxEDA /
Benedek-Kaernbach), which is deliberately deferred. The simple filter split below needs no such
flip, and reporting signed LP keeps the output in the units the operator reads.

Deviation from the design worth knowing about: §2.3 proposes resampling to a fixed 20 Hz. Real
exports are 50 Hz and filtering 161k samples costs milliseconds, so resampling would add index
mapping for no measured benefit. `MAX_ANALYSIS_RATE_HZ` decimates only if a much faster source
ever turns up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, sosfiltfilt

logger = logging.getLogger(__name__)

# Boundary between "level" and "deflection". GSR phasic responses live above ~0.05 Hz.
TONIC_CUTOFF_HZ = 0.05
# Sample-noise smoothing before extremum finding. 0.5 s is well below the ~1-4 s rise time of a
# real response, so it cannot blur one away.
SMOOTHING_SEC = 0.5
# Decimate only if a source is far faster than anything we have seen (real exports are 50 Hz).
MAX_ANALYSIS_RATE_HZ = 100.0


@dataclass(frozen=True)
class Deflection:
    """One excursion: a local extremum and the opposite extremum that preceded it."""

    onset_idx: int
    peak_idx: int
    onset_time: float
    peak_time: float
    amplitude_lp: float
    """Signed. Negative = a fall = the needle moving right = release."""
    rise_time_sec: float
    recovery_fraction: float
    """How much of the excursion had returned `RECOVERY_WINDOW_SEC` after the peak. 1.0 = fully
    recovered (an ordinary transient), 0.0 = the level stayed where it went (a discharge)."""
    tonic_step_lp: float
    """Change in the *tonic* level across the deflection. This is what distinguishes a
    Blitzentladung from a large ordinary Ausschlag."""


@dataclass(frozen=True)
class Primitives:
    time_sec: np.ndarray
    lp: np.ndarray
    lp_smooth: np.ndarray
    tonic: np.ndarray
    phasic: np.ndarray
    dtonic: np.ndarray
    sampling_rate_hz: float
    noise_lp: float
    """Robust per-sample noise scale (MAD of the first difference). Every amplitude threshold is
    expressed as a multiple of this or in A-units, never as a bare LP constant."""
    deflections: list[Deflection]


RECOVERY_WINDOW_SEC = 10.0
# A leg that has not advanced for this long is over, even without a reversal. Longer than a
# response's rise and settle, shorter than the quiet between two separate discharges.
LEG_STALL_SEC = 15.0


def _estimate_rate(time_sec: np.ndarray) -> float:
    if time_sec.size < 2:
        return 0.0
    steps = np.diff(time_sec)
    steps = steps[steps > 0]
    if steps.size == 0:
        return 0.0
    return float(1.0 / np.median(steps))


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or values.size < window:
        return values.copy()
    kernel = np.ones(window) / window
    # 'same' would taper the ends towards zero; pad with the edge values instead so the start and
    # end of a recording are not read as huge excursions.
    padded = np.pad(values, (window // 2, window - 1 - window // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _lowpass(values: np.ndarray, rate: float, cutoff_hz: float) -> np.ndarray:
    """Zero-phase low-pass, degrading to a wide moving average when the signal is too short.

    `sosfiltfilt` needs roughly 3x its padding length in samples; a 20-second test signal at
    0.05 Hz does not have it, and raising an error there would make the detectors untestable on
    short inputs.
    """
    if rate <= 0 or values.size < 32:
        return _moving_average(values, max(1, values.size // 4))

    nyquist = rate / 2.0
    normalised = cutoff_hz / nyquist
    if not 0 < normalised < 1:
        return _moving_average(values, max(1, values.size // 4))

    sos = butter(2, normalised, btype="low", output="sos")
    padlen = 3 * (sos.shape[0] * 2)
    if values.size <= padlen:
        return _moving_average(values, max(1, values.size // 4))
    try:
        return sosfiltfilt(sos, values, padlen=padlen)
    except ValueError:  # pragma: no cover - guarded by the size checks above
        logger.warning("Low-pass fell back to a moving average (n=%d, rate=%.2f)", values.size, rate)
        return _moving_average(values, max(1, values.size // 4))


def _noise_scale(values: np.ndarray) -> float:
    """MAD of the first difference: the per-sample noise floor, robust to real excursions."""
    steps = np.diff(values)
    if steps.size == 0:
        return 0.0
    mad = float(np.median(np.abs(steps - np.median(steps))))
    # 1.4826 converts MAD to a standard-deviation-equivalent for Gaussian noise.
    return mad * 1.4826


def _monotone_legs(
    values: np.ndarray, reversal_lp: float, stall_samples: int = 0
) -> list[tuple[int, int]]:
    """Segment the signal into monotone legs, closing one only on a reversal of `reversal_lp`.

    This replaced a `find_peaks` extremum-pairing scheme that could not represent the single most
    important phenomenon in the catalogue. A Blitzentladung is by definition a fall that *stays
    down* — "die Nadel geht nicht von selbst wieder zurück" — and a monotone step has no local
    minimum at all, so peak finding only ever caught the ones where noise happened to produce a
    dip. Hysteresis segmentation has no such blind spot: a leg ends when the signal reverses, or
    when the recording does.
    """
    n = values.size
    if n < 2 or reversal_lp <= 0:
        return []

    legs: list[tuple[int, int]] = []
    direction = 0
    anchor = 0
    extreme = 0
    stalled_since = 0

    for idx in range(1, n):
        value = values[idx]
        if direction == 0:
            # Uncommitted: the anchor stays at the start of the recording until the signal has
            # moved far enough in one direction to call it a leg. Tracking a running extreme here
            # instead is what an earlier version did, and it deadlocked — the extreme followed the
            # very fall it was supposed to detect, so the reversal test could never fire.
            if value >= values[anchor] + reversal_lp:
                direction, extreme, stalled_since = 1, idx, idx
            elif value <= values[anchor] - reversal_lp:
                direction, extreme, stalled_since = -1, idx, idx
        elif direction == 1:
            if value >= values[extreme]:
                extreme, stalled_since = idx, idx
            elif values[extreme] - value >= reversal_lp:
                legs.append((anchor, extreme))
                direction, anchor, extreme, stalled_since = -1, extreme, idx, idx
            elif stall_samples and idx - stalled_since >= stall_samples:
                legs.append((anchor, extreme))
                direction, anchor, stalled_since = 0, extreme, idx
        else:
            if value <= values[extreme]:
                extreme, stalled_since = idx, idx
            elif value - values[extreme] >= reversal_lp:
                legs.append((anchor, extreme))
                direction, anchor, extreme, stalled_since = 1, extreme, idx, idx
            elif stall_samples and idx - stalled_since >= stall_samples:
                legs.append((anchor, extreme))
                direction, anchor, stalled_since = 0, extreme, idx

    if direction != 0 and extreme > anchor:
        legs.append((anchor, extreme))
    return legs


ONSET_TRIM_FRACTION = 0.02


def _trim_onset(values: np.ndarray, anchor: int, extreme: int) -> int:
    """Move the onset forward to where the signal actually left its starting level.

    A leg runs from the previous turning point, which may be minutes of quiet before anything
    happens. Reporting that as the onset would make `rise_time_sec` the age of the recording
    rather than the speed of the response — and rise time is the Blitzentladung criterion, so
    getting this wrong silently disables BE detection entirely.
    """
    amplitude = values[extreme] - values[anchor]
    if amplitude == 0 or extreme <= anchor:
        return anchor

    threshold = values[anchor] + ONSET_TRIM_FRACTION * amplitude
    segment = values[anchor : extreme + 1]
    # Last sample still within the trim band, i.e. the moment before departure.
    still_flat = segment >= threshold if amplitude < 0 else segment <= threshold
    found = np.nonzero(still_flat)[0]
    if found.size == 0:
        return anchor
    refined = anchor + int(found[-1])
    return refined if refined < extreme else anchor


def _trim_peak(values: np.ndarray, onset: int, extreme: int) -> int:
    """Move the peak back to where the signal first reached its settled level.

    Needed for the same reason as `_trim_onset`, at the other end. A leg's extreme is a *running*
    extreme, so across a long flat plateau it lands wherever the lowest noise sample happens to
    be — on a synthetic step it drifted 46 seconds past the actual settle, which inflates the rise
    time by the length of the plateau.
    """
    amplitude = values[extreme] - values[onset]
    if amplitude == 0 or extreme <= onset:
        return extreme

    threshold = values[onset] + (1.0 - ONSET_TRIM_FRACTION) * amplitude
    segment = values[onset : extreme + 1]
    arrived = segment <= threshold if amplitude < 0 else segment >= threshold
    found = np.nonzero(arrived)[0]
    if found.size == 0:
        return extreme
    refined = onset + int(found[0])
    return refined if refined > onset else extreme


def _extract_deflections(
    time_sec: np.ndarray,
    lp_smooth: np.ndarray,
    tonic: np.ndarray,
    rate: float,
    prominence_lp: float,
) -> list[Deflection]:
    """One `Deflection` per monotone leg, in both directions.

    Rises are kept here even though no current detector emits them: `LPD` reads them, and the
    session-state work in a later stage needs "LP rauf = SP mauert" as a first-class observation.
    """
    if lp_smooth.size < 3 or prominence_lp <= 0:
        return []

    recovery_samples = max(1, int(RECOVERY_WINDOW_SEC * rate)) if rate > 0 else 1
    last = lp_smooth.size - 1
    deflections: list[Deflection] = []

    stall_samples = int(LEG_STALL_SEC * rate) if rate > 0 else 0
    for anchor_idx, extreme_idx in _monotone_legs(lp_smooth, prominence_lp, stall_samples):
        onset_idx = _trim_onset(lp_smooth, anchor_idx, extreme_idx)
        peak_idx = _trim_peak(lp_smooth, onset_idx, extreme_idx)
        amplitude = float(lp_smooth[peak_idx] - lp_smooth[onset_idx])
        if amplitude == 0:
            continue
        after_idx = min(peak_idx + recovery_samples, last)
        # How far back towards the onset level the signal came within the recovery window.
        recovered = float(lp_smooth[after_idx] - lp_smooth[peak_idx])
        fraction = recovered / -amplitude
        deflections.append(
            Deflection(
                onset_idx=onset_idx,
                peak_idx=peak_idx,
                onset_time=float(time_sec[onset_idx]),
                peak_time=float(time_sec[peak_idx]),
                amplitude_lp=amplitude,
                rise_time_sec=float(time_sec[peak_idx] - time_sec[onset_idx]),
                recovery_fraction=float(np.clip(fraction, -1.0, 2.0)),
                tonic_step_lp=float(tonic[after_idx] - tonic[onset_idx]),
            )
        )

    return deflections


def compute_primitives(
    time_sec: np.ndarray,
    lp: np.ndarray,
    prominence_noise_multiple: float = 6.0,
    min_prominence_lp: float = 0.004,
) -> Primitives:
    """Decompose a conditioned LP channel into the primitives the L2 detectors consume.

    `prominence_noise_multiple` and `min_prominence_lp` together set the smallest excursion that
    counts as an extremum at all. The floor matters because a very clean recording drives the
    noise-derived threshold towards zero, at which point every sample is a peak.
    """
    time_sec = np.asarray(time_sec, dtype=float)
    lp = np.asarray(lp, dtype=float)
    if time_sec.size != lp.size:
        raise ValueError("time and lp must be the same length")

    rate = _estimate_rate(time_sec)
    if rate > MAX_ANALYSIS_RATE_HZ:
        step = int(round(rate / MAX_ANALYSIS_RATE_HZ))
        logger.info("Decimating %.1f Hz input by %d for analysis", rate, step)
        time_sec = time_sec[::step]
        lp = lp[::step]
        rate = _estimate_rate(time_sec)

    smoothing_window = max(1, int(round(SMOOTHING_SEC * rate))) if rate > 0 else 1
    lp_smooth = _moving_average(lp, smoothing_window)
    tonic = _lowpass(lp, rate, TONIC_CUTOFF_HZ)
    phasic = lp - tonic
    dtonic = np.gradient(tonic, time_sec) if time_sec.size > 1 else np.zeros_like(tonic)

    noise_lp = _noise_scale(lp)
    prominence = max(prominence_noise_multiple * noise_lp, min_prominence_lp)

    return Primitives(
        time_sec=time_sec,
        lp=lp,
        lp_smooth=lp_smooth,
        tonic=tonic,
        phasic=phasic,
        dtonic=dtonic,
        sampling_rate_hz=rate,
        noise_lp=noise_lp,
        deflections=_extract_deflections(time_sec, lp_smooth, tonic, rate, prominence),
    )
