"""Calibration: the A-unit and the solo offset.

Without these, every absolute claim the system makes is wrong, so the rule here is that an
uncalibrated quantity is *labelled* uncalibrated rather than quietly printed as if it were the
device's own reading (`docs/phenomena-detection-design.md` §4).

Two quantities, neither recoverable from the CSV alone:

- **The A-unit.** Defined by a physical ritual: set sensitivity so a firm squeeze of the
  electrode (`Dosendruck`) drops the needle a third of the scale = `3A`. We cannot see the squeeze
  in the file, so the operator can pass it in; otherwise a robust fallback stands in.
- **The solo offset.** A single-hand electrode reads high. The manual has the solist measure LP
  two-handed, then solo, and carry the difference ("Dif. 0,8") for the session. Our whole real
  corpus sits at LP 4.4-6.0, which naively reads as an hour in the Kampfzone; it is the electrode.
"""

from __future__ import annotations

from dataclasses import dataclass

# Zone boundaries, on the *corrected* charge level. mw-Kurs, "Die vier Ladungszonen".
ZONE_BOUNDS = (
    (1.0, 2.0, "Opferzone"),
    (2.0, 3.0, "Normalzone"),
    (3.0, 3.5, "Alarmzone"),
    (3.5, 6.5, "Kampfzone"),
)


@dataclass(frozen=True)
class Calibration:
    a_unit_lp: float
    a_unit_calibrated: bool
    lp_offset: float | None
    """Subtracted from LP before any zone is named. None means the operator did not supply it."""

    @property
    def zones_available(self) -> bool:
        return self.lp_offset is not None

    def corrected_lp(self, lp: float) -> float | None:
        if self.lp_offset is None:
            return None
        return lp - self.lp_offset

    def zone(self, lp: float) -> str | None:
        """Name the charge zone, or None when it cannot be named honestly.

        Emitting "Kampfzone" for an entire solo session — which is what happens without the
        offset — would be a confident, systematic, wrong answer. Silence is better.
        """
        corrected = self.corrected_lp(lp)
        if corrected is None:
            return None
        for low, high, name in ZONE_BOUNDS:
            if low <= corrected < high:
                return name
        return "Kampfzone" if corrected >= ZONE_BOUNDS[-1][1] else "Opferzone"

    def as_dict(self) -> dict:
        return {
            "a_unit_lp": self.a_unit_lp,
            "a_unit_calibrated": self.a_unit_calibrated,
            "lp_offset": self.lp_offset,
            "zones_available": self.zones_available,
        }


def relative_band(lp: float, lp_min: float, lp_max: float) -> str:
    """Language for level that does not pretend to know the absolute zone.

    Used whenever `lp_offset` is absent: says where in *this session's* range a reading sits,
    which is true regardless of the electrode.
    """
    span = lp_max - lp_min
    if span <= 0:
        return "flat"
    position = (lp - lp_min) / span
    if position < 0.25:
        return "lower quarter of this session"
    if position < 0.5:
        return "below this session's midpoint"
    if position < 0.75:
        return "above this session's midpoint"
    return "upper quarter of this session"
