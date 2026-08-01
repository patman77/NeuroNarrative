"""A, T and the A-unit calibration they depend on.

The manual's own reliability floor is encoded here rather than invented: "Deswegen greifen wir
Ausschläge unter einem halben A nicht auf. Zu unsicher!" — so 0.5 A separates a `T` (noted, not
pursued) from an `A` (evidence you can build on).
"""

from __future__ import annotations

import numpy as np

from ..conditioning import LP_DEVICE_STEP
from ..primitives import Deflection, Primitives
from ..schema import Phenomenon, PhenomenonKind

# Below this fraction of an A-unit a deflection is a Ticken, not an Ausschlag.
TICKEN_THRESHOLD_A = 0.5
# A session needs at least this many deflections before its own amplitude distribution is a
# more trustworthy A-unit than the device's nominal smallest step.
MIN_DEFLECTIONS_FOR_SCALE = 20


def calibrate_a_unit(deflections: list[Deflection]) -> tuple[float, bool]:
    """Return `(a_unit_lp, calibrated)`.

    The A-unit is genuinely device- and session-specific: the manual defines it by a can-squeeze
    (`Dosendruck`) producing a third of the needle scale, which is a physical ritual we cannot
    recover from the CSV. Detecting that ritual is stage 4. Until then this is a *fallback*, and
    `calibrated` is always False so nothing downstream prints "3A" as if it were the device's own
    reading (`docs/phenomena-detection-design.md` §4).

    The fallback is the 75th percentile of fall amplitudes — a robust scale for "an ordinary
    deflection in this session" — or the device's nominal 0.05 LP step when the session is too
    sparse for that percentile to be stable.
    """
    falls = [abs(d.amplitude_lp) for d in deflections if d.amplitude_lp < 0]
    if len(falls) >= MIN_DEFLECTIONS_FOR_SCALE:
        scale = float(np.percentile(falls, 75))
        if scale > 0:
            return scale, False
    return LP_DEVICE_STEP, False


def detect_deflection_phenomena(
    primitives: Primitives,
    a_unit_lp: float,
    exclude_peak_indices: set[int] | None = None,
) -> list[Phenomenon]:
    """Classify falls as `A` or `T`.

    Rises are not emitted. The method reads a rise as resistance/defence rather than as an event
    to take up — "LP rauf = SP mauert oder schaut in die falsche Richtung" — and it is the tonic
    detectors (`LPD`, and later the session states) that account for them.

    `exclude_peak_indices` carries the deflections already claimed by the Blitzentladung detector,
    so a BE is not also reported as an ordinary A.
    """
    excluded = exclude_peak_indices or set()
    phenomena: list[Phenomenon] = []

    for deflection in primitives.deflections:
        if deflection.amplitude_lp >= 0 or deflection.peak_idx in excluded:
            continue

        magnitude_a = abs(deflection.amplitude_lp) / a_unit_lp if a_unit_lp > 0 else 0.0
        kind = PhenomenonKind.TICKEN if magnitude_a < TICKEN_THRESHOLD_A else PhenomenonKind.AUSSCHLAG

        phenomena.append(
            Phenomenon(
                kind=kind,
                t_start=deflection.onset_time,
                t_end=deflection.peak_time,
                amplitude_lp=deflection.amplitude_lp,
                amplitude_a=magnitude_a,
                detector="deflection",
                evidence={
                    "rise_time_sec": deflection.rise_time_sec,
                    "recovery_fraction": deflection.recovery_fraction,
                    "tonic_step_lp": deflection.tonic_step_lp,
                },
            )
        )

    return phenomena
