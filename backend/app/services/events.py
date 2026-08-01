from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import ruptures as rpt

from .phenomena.conditioning import (
    LP_DEVICE_STEP,
    NOMINAL_LN_R_INTERCEPT,
    NOMINAL_LN_R_SLOPE,
)


def _lp_delta_to_kohm(lp: float, baseline_lp: float) -> float:
    """Legacy `delta_kohm` field, derived from LP rather than measured independently."""
    to_kohm = lambda value: float(np.exp(NOMINAL_LN_R_SLOPE * value + NOMINAL_LN_R_INTERCEPT))
    return to_kohm(lp) - to_kohm(baseline_lp)


@dataclass
class EventRule:
    name: str
    derivative_z: float = 2.5
    min_gap_sec: float = 5.0
    changepoint_penalty: float = 8.0


# Upper bound on the samples handed to the changepoint detector. The rbf cost is O(n^2)
# in memory, so this caps it at roughly 2000^2 * 8 B = 32 MB regardless of recording length.
CHANGEPOINT_MAX_SAMPLES = 2000

DEFAULT_RULESET = {
    "default": EventRule(name="default"),
    "sensitive": EventRule(name="sensitive", derivative_z=1.8, min_gap_sec=3.0, changepoint_penalty=6.0),
    "strict": EventRule(name="strict", derivative_z=3.2, min_gap_sec=7.5, changepoint_penalty=10.0),
}


def detect_events(timestamps: np.ndarray, readings: np.ndarray, ruleset: str = "default") -> list[dict[str, Any]]:
    """Detect events in a charge-level (LP) signal.

    `readings` is LP — log resistance, the scale the MindWalking method is defined on — not kOhm.
    The derivative rule is z-scored and so survives the change of units unharmed, but the reported
    magnitudes do not: `delta_lp` is the meaningful one and is comparable across a session and
    between sessions. `delta_kohm` is retained for the existing API contract and is derived from
    LP, so it inherits LP's session-position dependence and should not be thresholded on.
    """
    if len(readings) == 0:
        return []
    rule = DEFAULT_RULESET.get(ruleset, DEFAULT_RULESET["default"])
    sampling_rate = _estimate_rate(timestamps)
    drz = _zscore(np.gradient(readings) * sampling_rate)

    candidate_idx = set(np.where(drz >= rule.derivative_z)[0].tolist())
    candidate_idx.update(_changepoint_candidates(readings, penalty=rule.changepoint_penalty))

    # enforce min gap
    sorted_idx = sorted(candidate_idx)
    keep: list[int] = []
    last_time = -1e9
    for idx in sorted_idx:
        t = timestamps[idx]
        if t - last_time >= rule.min_gap_sec:
            keep.append(idx)
            last_time = t

    events: list[dict[str, Any]] = []
    if len(readings) > 0:
        zscores = _zscore(readings)
        baseline = float(np.median(readings))
        for idx in keep:
            delta_lp = float(readings[idx] - baseline)
            delta_z = float(zscores[idx]) if len(zscores) > idx else None
            events.append(
                {
                    "event_id": f"evt-{idx}",
                    "time_sec": float(timestamps[idx]),
                    "rule": rule.name,
                    "delta_lp": delta_lp,
                    "delta_kohm": _lp_delta_to_kohm(readings[idx], baseline),
                    "delta_z": delta_z,
                    # Magnitudes in LP are ~0.05-2 while z-scores run to several units, so the
                    # old `|z| + |delta|` sum would be all z. Scale the LP term by the device's
                    # own smallest unit so both terms are in comparable "how many steps" units.
                    "score": float(abs(delta_z or 0) + abs(delta_lp) / LP_DEVICE_STEP),
                }
            )
    return events


def _estimate_rate(timestamps: np.ndarray) -> float:
    if len(timestamps) < 2:
        return 0.0
    intervals = np.diff(timestamps)
    valid = intervals[intervals > 0]
    if len(valid) == 0:
        return 0.0
    return float(1 / np.mean(valid))


def _changepoint_candidates(signal: np.ndarray, penalty: float) -> list[int]:
    """Changepoint indices, computed on a length-bounded view of the signal.

    The rbf cost builds an n x n Gram matrix, so memory and time grow with the square of
    the sample count: ~2.6 GB at 10k samples, ~64 GB at 90k. A real half-hour recording
    would exhaust the machine (it did). Detection therefore runs on at most
    CHANGEPOINT_MAX_SAMPLES evenly spaced samples and the results are mapped back to
    original indices.

    GSR is a slow signal, so decimating for changepoint purposes costs little resolution;
    the derivative rule still runs at full rate and supplies precise timing.
    """
    n = len(signal)
    if n < 10:
        return []

    if n > CHANGEPOINT_MAX_SAMPLES:
        positions = np.linspace(0, n - 1, CHANGEPOINT_MAX_SAMPLES).round().astype(int)
        reduced = signal[positions]
    else:
        positions = np.arange(n)
        reduced = signal

    algo = rpt.Pelt(model="rbf").fit(reduced)
    bkps = algo.predict(pen=penalty)
    # Breakpoints are segment end indices into `reduced`; map them back to the original.
    return [int(positions[min(idx - 1, len(positions) - 1)]) for idx in bkps if idx > 0]


def _zscore(arr: np.ndarray) -> np.ndarray:
    if arr.size == 0:
        return np.array([])
    mean = np.mean(arr)
    std = np.std(arr)
    if std == 0:
        return np.zeros_like(arr)
    return (arr - mean) / std
