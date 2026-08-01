"""BE (Blitzentladung) and LPA_slow.

The defining property of a BE in the manual is *not* size — "die Größe spielt keine Rolle" — but
that the needle does not come back on its own: "Die Nadel geht nicht von selbst wieder zurück zum
Messpunkt, sondern bleibt rechts davon liegen, daher ist ein Knopfdruck nötig." That is a
non-recovering response, i.e. a phasic fall accompanied by a persistent step in the tonic level.

That test is only computable because L1 separates tonic from deflection, and it is what
distinguishes a BE from a large ordinary `A`, which recovers.
"""

from __future__ import annotations

import numpy as np

from ..conditioning import LP_DEVICE_STEP
from ..primitives import Primitives
from ..schema import Phenomenon, PhenomenonKind

# "Schneller Ladungsabfall" — fast. Beyond this the manual would call it a creeping LPA instead.
#
# UNVALIDATED. The manual does not quantify "schnell", so this is a proxy, and it is the single
# most consequential free parameter in the detector. Falls >= 0.05 LP passing the recovery test,
# by rise-time cutoff, across the three real sessions:
#
#     cutoff:      3.0s   4.0s   5.0s   6.0s
#     28 min:        27     37     46     49
#     24 min:         7      8     13     13
#     54 min:        13     25     32     34
#
# The design proposed 3.0 s, which turns out to cut the population at its median — in the 54-minute session the
# median rise time is 3.62 s — so it was discarding as many candidates as it kept. 5.0 s is the
# upper edge of the standard SCR rise-time range (1-5 s) and is where the count plateaus in all
# three sessions, which is weak evidence that it lands past the real population rather than
# inside it. It is *not* validated against labels; that needs the evaluation set from stage 6.
BE_MAX_RISE_TIME_SEC = 5.0
# The needle stayed put: at most this fraction of the excursion came back within the recovery
# window. Above it, the level returned and this was a transient, not a discharge.
BE_MAX_RECOVERY_FRACTION = 0.3
# The device's own smallest displayable unit. Nothing below it would have been readable as a BE.
BE_MIN_AMPLITUDE_LP = LP_DEVICE_STEP

# LPA_slow: a creeping decline rather than a snap.
LPA_MIN_DURATION_SEC = 20.0
LPA_MIN_DROP_A = 1.0
# Tolerate brief flat or slightly rising patches inside an otherwise monotone decline.
LPA_MERGE_GAP_SEC = 5.0


def detect_blitzentladungen(
    primitives: Primitives, a_unit_lp: float
) -> tuple[list[Phenomenon], set[int]]:
    """Return the BEs and the peak indices they claim, so `A` detection can skip them."""
    phenomena: list[Phenomenon] = []
    claimed: set[int] = set()

    for deflection in primitives.deflections:
        if deflection.amplitude_lp >= 0:
            continue
        if abs(deflection.amplitude_lp) < BE_MIN_AMPLITUDE_LP:
            continue
        if deflection.rise_time_sec > BE_MAX_RISE_TIME_SEC:
            continue
        if deflection.recovery_fraction > BE_MAX_RECOVERY_FRACTION:
            continue
        # The level must actually have moved down and stayed there.
        if deflection.tonic_step_lp >= 0:
            continue

        claimed.add(deflection.peak_idx)
        phenomena.append(
            Phenomenon(
                kind=PhenomenonKind.BLITZENTLADUNG,
                t_start=deflection.onset_time,
                t_end=deflection.peak_time,
                amplitude_lp=deflection.tonic_step_lp,
                # In A-units so ranking compares like with like. The manual is explicit that a
                # BE in LP and an A in scale divisions are not comparable without the
                # sensitivity calibration, so this is indicative until stage 4.
                amplitude_a=abs(deflection.tonic_step_lp) / a_unit_lp if a_unit_lp > 0 else None,
                detector="discharge",
                evidence={
                    "excursion_lp": deflection.amplitude_lp,
                    "rise_time_sec": deflection.rise_time_sec,
                    "recovery_fraction": deflection.recovery_fraction,
                },
            )
        )

    return phenomena, claimed


def detect_slow_discharges(primitives: Primitives, a_unit_lp: float) -> list[Phenomenon]:
    """Sustained tonic decline: the needle creeping right over tens of seconds."""
    time_sec = primitives.time_sec
    tonic = primitives.tonic
    if time_sec.size < 3:
        return []

    falling = primitives.dtonic < 0
    merge_samples = (
        max(1, int(LPA_MERGE_GAP_SEC * primitives.sampling_rate_hz))
        if primitives.sampling_rate_hz > 0
        else 1
    )

    phenomena: list[Phenomenon] = []
    start: int | None = None
    gap = 0

    for idx in range(falling.size):
        if falling[idx]:
            if start is None:
                start = idx
            gap = 0
            continue

        if start is None:
            continue
        gap += 1
        if gap < merge_samples:
            continue

        end = idx - gap
        phenomenon = _slow_discharge(time_sec, tonic, start, end, a_unit_lp)
        if phenomenon is not None:
            phenomena.append(phenomenon)
        start = None
        gap = 0

    if start is not None:
        phenomenon = _slow_discharge(time_sec, tonic, start, falling.size - 1, a_unit_lp)
        if phenomenon is not None:
            phenomena.append(phenomenon)

    return phenomena


def _slow_discharge(
    time_sec: np.ndarray, tonic: np.ndarray, start: int, end: int, a_unit_lp: float
) -> Phenomenon | None:
    if end <= start:
        return None
    duration = float(time_sec[end] - time_sec[start])
    if duration < LPA_MIN_DURATION_SEC:
        return None

    drop = float(tonic[end] - tonic[start])
    magnitude_a = abs(drop) / a_unit_lp if a_unit_lp > 0 else 0.0
    if magnitude_a < LPA_MIN_DROP_A:
        return None

    return Phenomenon(
        kind=PhenomenonKind.LPA_SLOW,
        t_start=float(time_sec[start]),
        t_end=float(time_sec[end]),
        amplitude_lp=drop,
        amplitude_a=magnitude_a,
        detector="discharge",
        evidence={"duration_sec": duration, "rate_lp_per_min": drop / (duration / 60.0)},
    )
