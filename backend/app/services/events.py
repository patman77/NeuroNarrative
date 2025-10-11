from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import ruptures as rpt


@dataclass
class EventRule:
    name: str
    derivative_z: float = 2.5
    min_gap_sec: float = 5.0
    changepoint_penalty: float = 8.0


DEFAULT_RULESET = {
    "default": EventRule(name="default"),
    "sensitive": EventRule(name="sensitive", derivative_z=1.8, min_gap_sec=3.0, changepoint_penalty=6.0),
    "strict": EventRule(name="strict", derivative_z=3.2, min_gap_sec=7.5, changepoint_penalty=10.0),
}


def detect_events(timestamps: np.ndarray, readings: np.ndarray, ruleset: str = "default") -> list[dict[str, Any]]:
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
            delta_kohm = float(readings[idx] - baseline)
            delta_z = float(zscores[idx]) if len(zscores) > idx else None
            events.append(
                {
                    "event_id": f"evt-{idx}",
                    "time_sec": float(timestamps[idx]),
                    "rule": rule.name,
                    "delta_kohm": delta_kohm,
                    "delta_z": delta_z,
                    "score": float(abs(delta_z or 0) + abs(delta_kohm)),
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
    if len(signal) < 10:
        return []
    algo = rpt.Pelt(model="rbf").fit(signal)
    bkps = algo.predict(pen=penalty)
    # Convert breakpoints (segment end indices) into candidate indices
    return [max(0, idx - 1) for idx in bkps if idx > 0]


def _zscore(arr: np.ndarray) -> np.ndarray:
    if arr.size == 0:
        return np.array([])
    mean = np.mean(arr)
    std = np.std(arr)
    if std == 0:
        return np.zeros_like(arr)
    return (arr - mean) / std
