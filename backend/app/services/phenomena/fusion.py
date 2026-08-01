"""Run the L0 mask and the L2 detectors over a conditioned signal and assemble the result.

Ordering follows the method's own rule, **"Größte Ladung zuerst"** — pursue the largest discharge
first. The design notes this should ultimately rank *topic segments* by their total discharge
rather than individual deflections, which needs the BK3 parse tree; until that exists this ranks
the phenomena themselves, which is the same rule applied at a finer grain.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from .calibration import Calibration, relative_band
from .detectors.artefact import MOVEMENT_REASON, ArtefactMask, compute_artefact_mask
from .detectors.deflection import calibrate_a_unit, detect_deflection_phenomena
from .detectors.discharge import detect_blitzentladungen, detect_slow_discharges
from .detectors.level import lpb, lpd_track
from .detectors.stimulus import apply_stimulus_locking, detect_kein_ausschlag, detect_kvz
from ..protocol import Utterance
from .primitives import Primitives, compute_primitives
from .schema import Phenomenon, PhenomenonKind, SessionMetrics

logger = logging.getLogger(__name__)

# The manual explicitly makes a Ticken not worth taking up ("Ausschläge unter einem halben A
# greifen wir nicht auf. Zu unsicher!"), so it is deprioritised beyond its small size. No other
# kind is weighted: "größte Ladung zuerst" is a statement about charge, and inventing a
# multiplier for BE or LPA would be us ranking, not the method.
#
# Cross-kind comparison is in fact the exact question the manual says needs calibration — "was
# ist nun der größere LPA: eine BE von 0,3 oder 3A? Das kommt auf die Empfindlichkeit an!" — and
# our A-unit is a fallback unless the operator supplied one. Treat this order as indicative.
_KIND_WEIGHT = {PhenomenonKind.TICKEN: 0.25}


@dataclass(frozen=True)
class PhenomenaResult:
    phenomena: list[Phenomenon]
    metrics: SessionMetrics
    primitives: Primitives
    calibration: Calibration
    artefacts: ArtefactMask

    def as_dict(self) -> dict[str, Any]:
        return {
            "phenomena": [p.as_dict() for p in self.phenomena],
            "metrics": self.metrics.as_dict(),
            "calibration": self.calibration.as_dict(),
            "artefacts": self.artefacts.as_dict(),
        }


def charge_rank(phenomenon: Phenomenon) -> float:
    """ "Größte Ladung zuerst", in A-units where they exist and LP otherwise."""
    magnitude = phenomenon.amplitude_a
    if magnitude is None:
        magnitude = abs(phenomenon.amplitude_lp or 0.0)
    return _KIND_WEIGHT.get(phenomenon.kind, 1.0) * abs(magnitude)


def detect_phenomena(
    time_sec: np.ndarray,
    lp: np.ndarray,
    lp_offset: float | None = None,
    a_unit_lp: float | None = None,
    utterances: Sequence[Utterance] | None = None,
) -> PhenomenaResult:
    """L0 mask + L1 primitives + L2 detectors over one conditioned recording.

    `lp_offset` and `a_unit_lp` are the operator's own calibration numbers, both optional. Supply
    them and zones become nameable and A-magnitudes become real; omit them and the result says so
    rather than guessing.
    """
    started = time.perf_counter()
    primitives = compute_primitives(time_sec, lp)

    artefacts = compute_artefact_mask(primitives.time_sec, primitives.lp, primitives.noise_lp)

    if a_unit_lp is not None and a_unit_lp > 0:
        unit, calibrated = a_unit_lp, True
    else:
        unit, calibrated = calibrate_a_unit(_unmasked_deflections(primitives, artefacts))
    calibration = Calibration(a_unit_lp=unit, a_unit_calibrated=calibrated, lp_offset=lp_offset)

    blitz, claimed = detect_blitzentladungen(primitives, unit)
    deflections = detect_deflection_phenomena(primitives, unit, exclude_peak_indices=claimed)
    slow = detect_slow_discharges(primitives, unit)

    phenomena = [p for p in blitz + deflections + slow if not _overlaps_mask(p, primitives, artefacts)]
    phenomena += _body_movements(artefacts)

    # Cross-modal layer. Without a transcript everything simply stays `stimulus_locked=None`,
    # which is honest: we do not know, rather than "not locked".
    turns = list(utterances or [])
    if turns:
        phenomena = apply_stimulus_locking(phenomena, turns)
        phenomena += detect_kein_ausschlag(phenomena, turns)
        phenomena += detect_kvz(primitives, turns, unit)

    phenomena.sort(key=lambda p: p.t_start)

    span, low, high = lpb(primitives.tonic)
    track, lpd_mean = lpd_track(primitives.time_sec, primitives.tonic, unit, primitives.sampling_rate_hz)

    counts: dict[str, int] = {}
    for phenomenon in phenomena:
        counts[phenomenon.kind.value] = counts.get(phenomenon.kind.value, 0) + 1

    metrics = SessionMetrics(
        lpb=span,
        lp_min=low,
        lp_max=high,
        lpd_mean=lpd_mean,
        lpd_track=track,
        a_unit_lp=unit,
        a_unit_calibrated=calibrated,
        counts=counts,
        zone_min=calibration.zone(low),
        zone_max=calibration.zone(high),
        level_description=(
            f"LP {low:.2f}-{high:.2f}, uncalibrated ({relative_band(high, low, high)} at its highest)"
            if not calibration.zones_available
            else f"LP {low:.2f}-{high:.2f} raw, offset {lp_offset:+.2f}"
        ),
        unmasked_duration_sec=artefacts.unmasked_duration_sec(primitives.time_sec),
    )

    logger.info(
        "Detected %d phenomena in %.2f s (%s); LPB %.2f LP, A-unit %.4f LP (%s), %.1f%% masked",
        len(phenomena),
        time.perf_counter() - started,
        ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none",
        span,
        unit,
        "operator-supplied" if calibrated else "fallback",
        artefacts.masked_fraction * 100,
    )
    return PhenomenaResult(
        phenomena=phenomena,
        metrics=metrics,
        primitives=primitives,
        calibration=calibration,
        artefacts=artefacts,
    )


def _body_movements(artefacts: ArtefactMask) -> list[Phenomenon]:
    """Report movement spans as `KB` rather than leaving a silent gap.

    The manual requires it — a Körperbewegung must be marked in the protocol, not just excluded —
    and an operator reading "body movement at 0:09" is better served than one wondering why a
    visible excursion produced nothing.
    """
    return [
        Phenomenon(
            kind=PhenomenonKind.KOERPERBEWEGUNG,
            t_start=start,
            t_end=end,
            detector="artefact",
            confidence=0.6,
            evidence={"reason": reason},
        )
        for start, end, reason in artefacts.spans
        if reason == MOVEMENT_REASON
    ]


def _unmasked_deflections(primitives: Primitives, artefacts: ArtefactMask) -> list:
    """The A-unit must be estimated from real session activity, not from the electrode grab."""
    if not artefacts.mask.any():
        return primitives.deflections
    return [d for d in primitives.deflections if not artefacts.mask[d.onset_idx : d.peak_idx + 1].any()]


def _overlaps_mask(phenomenon: Phenomenon, primitives: Primitives, artefacts: ArtefactMask) -> bool:
    if not artefacts.mask.any():
        return False
    start, end = np.searchsorted(
        primitives.time_sec, [phenomenon.t_start, phenomenon.t_end], side="left"
    )
    end = max(end, start + 1)
    return bool(artefacts.mask[start:end].any())
