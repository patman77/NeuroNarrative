"""Session-level readings: LPB and LPD.

These are not point events, so they are not `Phenomenon` records. `LPB` is one number; `LPD` is a
track, because the manual ties it proportionally to the partner's interest in whatever is being
worked ("heißes Thema = viel LPD") and a single session mean would throw that away.

Charge **zones** are deliberately absent. They need the solo-electrode offset, which cannot be
recovered from the file — our whole real corpus reads as an hour in the Kampfzone without it.
Stage 4. See `docs/phenomena-detection-design.md` §4.
"""

from __future__ import annotations

import numpy as np

# Window over which "is something going on" is a meaningful question.
LPD_WINDOW_SEC = 120.0
# Cap on returned track points, so a 54-minute session does not ship 160k samples to the UI.
LPD_TRACK_POINTS = 200


def lpb(tonic: np.ndarray) -> tuple[float, float, float]:
    """Ladungspegelbereich: `(range, min, max)` of the tonic level."""
    if tonic.size == 0:
        return 0.0, 0.0, 0.0
    low = float(np.min(tonic))
    high = float(np.max(tonic))
    return high - low, low, high


def lpd_track(
    time_sec: np.ndarray, tonic: np.ndarray, a_unit_lp: float, sampling_rate_hz: float
) -> tuple[list[tuple[float, float]], float]:
    """Ladungspegeldynamik: total variation of the tonic level per minute, in A-units.

    Total variation rather than variance: the manual's reading is "geht der LP fleißig rauf und
    runter", which is about distance travelled, not spread. A level that drifts once from 3 to 5
    has a large variance but little dynamic; one that oscillates between 3 and 4 twenty times has
    the same spread and a great deal of it.
    """
    if time_sec.size < 2 or sampling_rate_hz <= 0 or a_unit_lp <= 0:
        return [], 0.0

    window = max(2, int(LPD_WINDOW_SEC * sampling_rate_hz))
    if window >= time_sec.size:
        window = time_sec.size

    # Cumulative absolute movement lets any window's total variation be read off in O(1).
    travel = np.concatenate([[0.0], np.cumsum(np.abs(np.diff(tonic)))])

    step = max(1, (time_sec.size - window) // LPD_TRACK_POINTS or 1)
    points: list[tuple[float, float]] = []
    for start in range(0, max(1, time_sec.size - window + 1), step):
        end = start + window - 1
        span_min = float(time_sec[end] - time_sec[start]) / 60.0
        if span_min <= 0:
            continue
        variation_a = float(travel[end] - travel[start]) / a_unit_lp
        points.append((float(time_sec[start + window // 2]), variation_a / span_min))

    mean = float(np.mean([value for _, value in points])) if points else 0.0
    return points, mean
