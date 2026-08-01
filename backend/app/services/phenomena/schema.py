"""The phenomenon record and its stable identity.

One `Phenomenon` replaces the untyped event dict. The important design constraint is the **id**:
it is derived from the content, not from a sample index. The old `evt-{idx}` changed whenever the
parse changed, which makes it impossible to persist a human label against a detection — and
labelling is the critical path for everything downstream (`docs/phenomena-detection-design.md`
§7, §9).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PhenomenonKind(str, Enum):
    """The MindWalking vocabulary. See `docs/mindwalking-domain.md` §2."""

    AUSSCHLAG = "A"
    """A fall of the needle: something became available. Magnitude in A-units."""

    TICKEN = "T"
    """The smallest deflection. Noted, but below the manual's 0.5 A reliability floor."""

    BLITZENTLADUNG = "BE"
    """A fast fall that does *not* come back — the standing charge dropped, not just a transient.
    The manual's marker of an important single statement."""

    LPA_SLOW = "LPA_slow"
    """A slow discharge: the needle creeps right over tens of seconds rather than snapping."""

    # Reserved for later stages, listed so the enum is the single source of truth for the UI.
    KEIN_AUSSCHLAG = "X"
    """An instruction that produced no deflection. Needs the transcript to exist at all."""

    KVZ = "KVZ"
    """Kommunikationsverzögerung: the signal moves while nothing is said."""

    SCHMUTZIGE_NADEL = "SN"
    FREIE_NADEL = "FN"
    KOERPERBEWEGUNG = "KB"


@dataclass(frozen=True)
class Phenomenon:
    kind: PhenomenonKind
    t_start: float
    t_end: float
    amplitude_lp: float | None = None
    """Signed, in LP. **Falls are negative**, matching the physics (resistance drops) rather than
    the method's spoken convention where a fall is "positive" news."""
    amplitude_a: float | None = None
    """Magnitude in calibrated A-units, or None when the A-unit is not calibrated."""
    confidence: float = 1.0
    stimulus_locked: bool | None = None
    """None until transcript alignment exists (stage 3)."""
    utterance_id: str | None = None
    detector: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Content-derived and stable across re-parses.

        Rounded before hashing so that a re-parse which shifts a detection by a sample, or
        changes an amplitude in the fourth decimal, still yields the same id.
        """
        amplitude = 0.0 if self.amplitude_lp is None else self.amplitude_lp
        payload = f"{self.kind.value}|{self.t_start:.2f}|{amplitude:.4f}"
        return f"{self.kind.value.lower()}-{hashlib.sha1(payload.encode()).hexdigest()[:10]}"

    @property
    def is_fall(self) -> bool:
        return self.amplitude_lp is not None and self.amplitude_lp < 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "amplitude_lp": self.amplitude_lp,
            "amplitude_a": self.amplitude_a,
            "confidence": self.confidence,
            "stimulus_locked": self.stimulus_locked,
            "utterance_id": self.utterance_id,
            "detector": self.detector,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class SessionMetrics:
    """Session-level readings the SL would otherwise note by hand."""

    lpb: float
    """Ladungspegelbereich: max - min tonic LP across the session."""
    lp_min: float
    lp_max: float
    lpd_mean: float
    """Mean Ladungspegeldynamik in A-units per minute."""
    lpd_track: list[tuple[float, float]]
    """(time_sec, LPD) samples, decimated for display."""
    a_unit_lp: float
    a_unit_calibrated: bool
    """False means the A-unit is a fallback, so `amplitude_a` is indicative only and "3A" must
    not be printed as if it were the device's own reading (`docs/...-design.md` §4)."""
    counts: dict[str, int] = field(default_factory=dict)
    zone_min: str | None = None
    zone_max: str | None = None
    """Charge zone names, or None when no solo offset was supplied — naming a zone without it
    would report an entire solo session as Kampfzone."""
    level_description: str = ""
    unmasked_duration_sec: float = 0.0
    """Coverage denominator: artefact spans do not count as quiet session."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "lpb": self.lpb,
            "lp_min": self.lp_min,
            "lp_max": self.lp_max,
            "lpd_mean": self.lpd_mean,
            "lpd_track": [{"time_sec": t, "lpd": v} for t, v in self.lpd_track],
            "a_unit_lp": self.a_unit_lp,
            "a_unit_calibrated": self.a_unit_calibrated,
            "counts": self.counts,
            "zone_min": self.zone_min,
            "zone_max": self.zone_max,
            "level_description": self.level_description,
            "unmasked_duration_sec": self.unmasked_duration_sec,
        }
