"""L1/L2 phenomenon detection.

The strategy is injection-and-recovery: build an LP signal containing phenomena at known times
with known magnitudes, and check the detector finds those and not others. It is the only ground
truth available until the labelling path in stage 5 exists.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.phenomena.detectors.deflection import calibrate_a_unit
from app.services.phenomena.detectors.discharge import (
    BE_MAX_RECOVERY_FRACTION,
    BE_MAX_RISE_TIME_SEC,
)
from app.services.phenomena.fusion import charge_rank, detect_phenomena
from app.services.phenomena.primitives import compute_primitives
from app.services.phenomena.schema import Phenomenon, PhenomenonKind

RATE = 50.0


def _timeline(duration_sec: float) -> np.ndarray:
    return np.arange(0.0, duration_sec, 1.0 / RATE)


def _quiet(duration_sec: float, level: float = 3.0, noise: float = 2e-4) -> tuple[np.ndarray, np.ndarray]:
    t = _timeline(duration_sec)
    rng = np.random.default_rng(20260801)
    return t, np.full(t.size, level) + rng.normal(0.0, noise, t.size)


def _add_transient(lp: np.ndarray, t: np.ndarray, at: float, depth: float, rise: float = 2.0) -> None:
    """A fall that recovers — an ordinary Ausschlag."""
    fall = (t >= at) & (t < at + rise)
    lp[fall] -= depth * (t[fall] - at) / rise
    recover = (t >= at + rise) & (t < at + rise + 8.0)
    lp[recover] -= depth * (1.0 - (t[recover] - at - rise) / 8.0)


def _add_discharge(lp: np.ndarray, t: np.ndarray, at: float, depth: float, rise: float = 2.0) -> None:
    """A fall that does NOT recover — a Blitzentladung."""
    fall = (t >= at) & (t < at + rise)
    lp[fall] -= depth * (t[fall] - at) / rise
    lp[t >= at + rise] -= depth


def _kinds(phenomena: list[Phenomenon], kind: PhenomenonKind) -> list[Phenomenon]:
    return [p for p in phenomena if p.kind == kind]


def _near(phenomena: list[Phenomenon], when: float, tolerance: float = 4.0) -> list[Phenomenon]:
    return [p for p in phenomena if abs(p.t_end - when) <= tolerance]


# --- primitives ------------------------------------------------------------------------------


def test_tonic_and_phasic_split_a_step_from_its_transients():
    t, lp = _quiet(400.0)
    lp[t >= 200.0] -= 0.5  # a level change
    _add_transient(lp, t, 60.0, 0.15)  # a transient riding on it

    primitives = compute_primitives(t, lp)

    # The tonic follows the level change...
    assert primitives.tonic[int(50 * 150)] > primitives.tonic[int(50 * 250)]
    # ...and the transient shows up in the phasic residual, not the tonic.
    window = slice(int(50 * 58), int(50 * 72))
    assert np.abs(primitives.phasic[window]).max() > 0.05


def test_noise_scale_is_robust_to_real_excursions():
    """A handful of genuine deflections must not inflate the noise floor."""
    t, lp = _quiet(300.0, noise=3e-4)
    quiet_scale = compute_primitives(t, lp).noise_lp

    for at in (50.0, 120.0, 200.0):
        _add_discharge(lp, t, at, 0.3)

    assert compute_primitives(t, lp).noise_lp == pytest.approx(quiet_scale, rel=0.5)


def test_a_flat_signal_yields_no_deflections():
    t = _timeline(200.0)
    primitives = compute_primitives(t, np.full(t.size, 3.0))

    assert primitives.deflections == []


# --- A and T ---------------------------------------------------------------------------------


def test_an_injected_transient_is_found_as_a_fall():
    t, lp = _quiet(200.0)
    _add_transient(lp, t, 100.0, 0.30)

    result = detect_phenomena(t, lp)
    found = _near(result.phenomena, 102.0)

    assert found, "the injected deflection was not detected"
    assert min(p.amplitude_lp for p in found) < -0.15


def test_rises_are_not_reported_as_events():
    """The method reads a rise as defence, not as something to take up."""
    t, lp = _quiet(200.0)
    lp[(t >= 100.0) & (t < 104.0)] += 0.3
    lp[t >= 104.0] += 0.3

    result = detect_phenomena(t, lp)

    assert all(p.amplitude_lp is None or p.amplitude_lp <= 0 for p in result.phenomena)


def test_small_deflections_are_ticken_and_large_ones_are_ausschlaege():
    t, lp = _quiet(600.0)
    for i in range(12):  # populate the amplitude distribution so the A-unit is stable
        _add_transient(lp, t, 40.0 + i * 40.0, 0.20)
    _add_transient(lp, t, 540.0, 0.02)  # far below the others

    result = detect_phenomena(t, lp)

    assert _kinds(result.phenomena, PhenomenonKind.AUSSCHLAG)
    tiny = _near(_kinds(result.phenomena, PhenomenonKind.TICKEN), 542.0)
    assert tiny, "a deflection well under 0.5 A should be reported as a Ticken"


def test_the_a_unit_is_always_flagged_uncalibrated():
    """Until the Dosendruck ritual is detected (stage 4), "3A" is an estimate, not a reading."""
    t, lp = _quiet(600.0)
    for i in range(30):
        _add_transient(lp, t, 20.0 + i * 19.0, 0.2)

    _, calibrated = calibrate_a_unit(compute_primitives(t, lp).deflections)
    assert calibrated is False
    assert detect_phenomena(t, lp).metrics.a_unit_calibrated is False


# --- BE --------------------------------------------------------------------------------------


def test_a_non_recovering_fall_is_a_blitzentladung():
    t, lp = _quiet(300.0)
    _add_discharge(lp, t, 150.0, 0.30, rise=2.0)

    result = detect_phenomena(t, lp)
    blitz = _near(_kinds(result.phenomena, PhenomenonKind.BLITZENTLADUNG), 152.0)

    assert blitz, "a fast fall that does not come back is the manual's definition of a BE"
    assert blitz[0].amplitude_lp < 0


def test_a_recovering_fall_of_the_same_size_is_not_a_blitzentladung():
    """Size is explicitly not what makes a BE — non-recovery is."""
    t, lp = _quiet(300.0)
    _add_transient(lp, t, 150.0, 0.30, rise=2.0)

    result = detect_phenomena(t, lp)

    assert not _near(_kinds(result.phenomena, PhenomenonKind.BLITZENTLADUNG), 152.0)


def test_a_blitzentladung_is_not_double_reported_as_an_ausschlag():
    t, lp = _quiet(300.0)
    _add_discharge(lp, t, 150.0, 0.30)

    result = detect_phenomena(t, lp)
    at_event = _near(result.phenomena, 152.0, tolerance=2.0)

    assert len(_kinds(at_event, PhenomenonKind.BLITZENTLADUNG)) == 1
    assert not _kinds(at_event, PhenomenonKind.AUSSCHLAG)


def test_a_slow_fall_is_not_a_blitzentladung():
    """A creeping decline is an LPA, not a Blitzentladung, however far it goes."""
    t, lp = _quiet(400.0)
    _add_discharge(lp, t, 100.0, 0.4, rise=BE_MAX_RISE_TIME_SEC * 4)

    result = detect_phenomena(t, lp)

    assert not _kinds(result.phenomena, PhenomenonKind.BLITZENTLADUNG)


# --- LPA, LPD, LPB ---------------------------------------------------------------------------


def test_a_sustained_decline_is_reported_as_a_slow_discharge():
    t, lp = _quiet(400.0)
    ramp = (t >= 100.0) & (t < 200.0)
    lp[ramp] -= 0.4 * (t[ramp] - 100.0) / 100.0
    lp[t >= 200.0] -= 0.4

    result = detect_phenomena(t, lp)
    slow = _kinds(result.phenomena, PhenomenonKind.LPA_SLOW)

    assert slow
    assert any(p.t_start < 150.0 < p.t_end for p in slow)


def test_lpb_is_the_span_of_the_level():
    t, lp = _quiet(400.0)
    lp[t >= 200.0] -= 0.8

    metrics = detect_phenomena(t, lp).metrics

    assert metrics.lpb == pytest.approx(0.8, abs=0.1)


def test_lpd_is_higher_for_a_busy_level_than_a_drifting_one():
    """Total variation, not spread: the same range travelled repeatedly means more dynamic."""
    t, quiet = _quiet(600.0)
    drifting = quiet.copy()
    drifting += np.linspace(0.0, 0.6, t.size)

    busy = quiet.copy()
    busy += 0.3 * np.sin(2 * np.pi * t / 60.0)

    assert detect_phenomena(t, busy).metrics.lpd_mean > detect_phenomena(t, drifting).metrics.lpd_mean


def test_metrics_survive_a_signal_too_short_to_filter():
    t, lp = _quiet(5.0)

    result = detect_phenomena(t, lp)

    assert result.metrics.lpb >= 0.0


# --- identity and ranking --------------------------------------------------------------------


def test_ids_are_stable_across_reparses_and_unique_within_a_session():
    t, lp = _quiet(400.0)
    for at in (60.0, 150.0, 260.0):
        _add_discharge(lp, t, at, 0.25)

    first = detect_phenomena(t, lp).phenomena
    second = detect_phenomena(t.copy(), lp.copy()).phenomena

    assert [p.id for p in first] == [p.id for p in second]
    assert len({p.id for p in first}) == len(first)


def test_ids_survive_a_sub_sample_timing_shift():
    """A re-parse that nudges a detection by a few milliseconds must not orphan its label."""
    base = Phenomenon(kind=PhenomenonKind.BLITZENTLADUNG, t_start=100.001, t_end=102.0, amplitude_lp=-0.30001)
    nudged = Phenomenon(kind=PhenomenonKind.BLITZENTLADUNG, t_start=100.004, t_end=102.0, amplitude_lp=-0.30002)

    assert base.id == nudged.id


def test_ranking_puts_the_largest_discharge_first():
    """"Größte Ladung zuerst" — the rule the whole method leans on."""
    t, lp = _quiet(500.0)
    _add_discharge(lp, t, 100.0, 0.08)
    _add_discharge(lp, t, 300.0, 0.45)

    ranked = sorted(detect_phenomena(t, lp).phenomena, key=charge_rank, reverse=True)

    assert ranked[0].t_start > 250.0


def test_detection_is_bounded_on_a_long_recording():
    """A 60-minute 50 Hz session must stay fast; the old changepoint path once froze the machine."""
    import time as _time

    t = _timeline(3600.0)
    rng = np.random.default_rng(7)
    lp = 3.0 + np.cumsum(rng.normal(0.0, 2e-4, t.size))

    started = _time.perf_counter()
    result = detect_phenomena(t, lp)
    elapsed = _time.perf_counter() - started

    assert elapsed < 15.0, f"took {elapsed:.1f}s for a 1-hour recording"
    assert result.metrics.lpb > 0
