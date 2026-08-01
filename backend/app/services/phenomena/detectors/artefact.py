"""L0 artefact masking.

The manual is emphatic that a body movement must never be confused with a discharge: a `KB`
"verursacht häufig einen großen LPA, der aber keinesfalls mit einer BE verwechselt werden darf.
Daher im Protokoll unbedingt als KB ausweisen."

What this module masks is the mechanical, non-mental stuff that has no business reaching a
detector at all — electrode settling, rail excursions, cable faults. Discriminating a KB from a
genuine BE is a harder, learned problem and belongs in L3 (`docs/phenomena-detection-design.md`
§7); it is deliberately not attempted here.

Masked spans are first-class: no detector may report inside one, and coverage is reported against
*unmasked* duration so a bad recording cannot quietly look like a quiet one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# The device scale is 1.0-6.5. Within this much of either end the reading is pinned and the true
# resistance is unknown. The manual's cable-break anecdote is exactly this: "zeigt er auf 6,5,
# rast runter auf 0,95 und wieder hoch auf 6,5 - Kabelbruch!"
RAIL_MARGIN_LP = 0.1
LP_SCALE_MIN = 1.0
LP_SCALE_MAX = 6.5

# Movement is judged against the session's *own* distribution, not a fixed constant. A fixed
# 2.0 LP/s missed the clearest artefact in the corpus: Solo46 has a 0.37 LP down-and-up excursion
# at 1.57 LP/s eight seconds in, while the rest of that session never exceeds 0.067 LP/s. It is
# 23x the session's normal maximum rate and obviously mechanical, but under any threshold chosen
# to be safe across devices.
#
# median + 40*MAD of |dLP/dt| flags 0.02-0.23% of samples across the three real sessions, which
# is a plausible artefact rate.
#
# The floor is the safety catch, and it is deliberately set where nothing physiological can
# reach: LP is log resistance, so 1.0 LP/s is a 2.76x change in resistance *per second*. An
# earlier 0.15 LP/s floor was inside the real response range — a strong 0.3 LP deflection over
# two seconds sits exactly on it — and masked genuine deflections in the injection tests. On the
# current corpus the floor binds in all three sessions (their MAD-derived thresholds are
# 0.28-0.70 LP/s); the session-relative term exists for devices with a coarser noise scale.
MOVEMENT_MAD_MULTIPLE = 40.0
MOVEMENT_FLOOR_LP_PER_SEC = 1.0
IMPLAUSIBLE_RATE_LP_PER_SEC = 2.0

MOVEMENT_REASON = "body movement"

# The session has not started until the trace has been quiet for this long.
SETTLE_QUIET_SEC = 5.0
# Give up looking for that quiet window after this much of the recording, so a genuinely restless
# session is not masked wholesale.
SETTLE_MAX_SEC = 120.0
# Pad either side of a rail or rate artefact, since the recovery is as unphysiological as the
# excursion.
ARTEFACT_PAD_SEC = 2.0


@dataclass(frozen=True)
class ArtefactMask:
    mask: np.ndarray
    """True where the sample must not be used."""
    spans: list[tuple[float, float, str]] = field(default_factory=list)
    """(start_sec, end_sec, reason), for the report."""

    @property
    def masked_fraction(self) -> float:
        return float(self.mask.mean()) if self.mask.size else 0.0

    def unmasked_duration_sec(self, time_sec: np.ndarray) -> float:
        if time_sec.size < 2:
            return 0.0
        steps = np.diff(time_sec, prepend=time_sec[0])
        return float(steps[~self.mask].sum())

    def as_dict(self) -> dict:
        return {
            "masked_fraction": self.masked_fraction,
            "spans": [
                {"start_sec": start, "end_sec": end, "reason": reason}
                for start, end, reason in self.spans
            ],
        }


def _spans_from_mask(time_sec: np.ndarray, mask: np.ndarray, reason: str) -> list[tuple[float, float, str]]:
    if not mask.any():
        return []
    edges = np.diff(mask.astype(np.int8))
    starts = list(np.nonzero(edges == 1)[0] + 1)
    ends = list(np.nonzero(edges == -1)[0])
    if mask[0]:
        starts.insert(0, 0)
    if mask[-1]:
        ends.append(mask.size - 1)
    return [(float(time_sec[s]), float(time_sec[e]), reason) for s, e in zip(starts, ends)]


def _dilate(mask: np.ndarray, samples: int) -> np.ndarray:
    if samples <= 0 or not mask.any():
        return mask
    kernel = np.ones(2 * samples + 1, dtype=bool)
    return np.convolve(mask, kernel, mode="same") > 0


def compute_artefact_mask(time_sec: np.ndarray, lp: np.ndarray, noise_lp: float) -> ArtefactMask:
    """Mask electrode settling, rail excursions and impossibly fast movement."""
    n = lp.size
    mask = np.zeros(n, dtype=bool)
    spans: list[tuple[float, float, str]] = []
    if n < 3:
        return ArtefactMask(mask=mask, spans=spans)

    rate = 0.0
    steps = np.diff(time_sec)
    steps = steps[steps > 0]
    if steps.size:
        rate = float(1.0 / np.median(steps))
    pad_samples = int(ARTEFACT_PAD_SEC * rate) if rate > 0 else 0

    # --- rails -----------------------------------------------------------------------------
    railed = (lp >= LP_SCALE_MAX - RAIL_MARGIN_LP) | (lp <= LP_SCALE_MIN + RAIL_MARGIN_LP)
    if railed.any():
        railed = _dilate(railed, pad_samples)
        spans += _spans_from_mask(time_sec, railed & ~mask, "rail (electrode or cable fault)")
        mask |= railed

    # --- movement, judged against this session's own spread ---------------------------------
    slope = np.gradient(lp, time_sec)
    speed = np.abs(slope)
    median = float(np.median(speed))
    mad = float(np.median(np.abs(speed - median))) * 1.4826
    threshold = min(
        max(median + MOVEMENT_MAD_MULTIPLE * mad, MOVEMENT_FLOOR_LP_PER_SEC),
        IMPLAUSIBLE_RATE_LP_PER_SEC,
    )
    too_fast = speed > threshold
    if too_fast.any():
        too_fast = _dilate(too_fast, pad_samples)
        spans += _spans_from_mask(time_sec, too_fast & ~mask, MOVEMENT_REASON)
        mask |= too_fast

    # --- leading settle ---------------------------------------------------------------------
    settle_end = _settle_index(time_sec, slope, noise_lp, rate)
    if settle_end > 0:
        leading = np.zeros(n, dtype=bool)
        leading[:settle_end] = True
        spans += _spans_from_mask(time_sec, leading & ~mask, "electrode settling")
        mask |= leading

    spans.sort(key=lambda span: span[0])
    return ArtefactMask(mask=mask, spans=spans)


def _settle_index(time_sec: np.ndarray, slope: np.ndarray, noise_lp: float, rate: float) -> int:
    """First index after which the trace stays quiet for `SETTLE_QUIET_SEC`.

    Grabbing the electrodes produces the largest excursion in the whole session — on the
    reference recording the two biggest three-second falls both land inside the first ten
    seconds, and one of them ranked first by charge before this existed. It is a mechanical
    settling transient, not a discharge.
    """
    if rate <= 0 or noise_lp <= 0:
        return 0

    quiet_samples = int(SETTLE_QUIET_SEC * rate)
    limit = min(slope.size, int(SETTLE_MAX_SEC * rate))
    if quiet_samples < 2 or limit <= quiet_samples:
        return 0

    # A settled trace moves at roughly the noise floor per sample; allow a generous multiple so
    # only the grab transient is caught, not ordinary session activity.
    threshold = max(noise_lp * rate * 8.0, 0.01)
    quiet = np.abs(slope[:limit]) < threshold

    # Only a recording that *begins* disturbed has a settling transient to mask. Without this
    # guard the scan ran to the last disturbance anywhere in the first two minutes, so an
    # ordinary deflection at 100 s caused half the recording to be masked as "settling".
    if quiet[: min(quiet_samples, limit)].all():
        return 0

    run = 0
    for idx in range(limit):
        run = run + 1 if quiet[idx] else 0
        if run >= quiet_samples:
            return idx - quiet_samples + 1
    return 0
