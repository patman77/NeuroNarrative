from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services.phenomena.conditioning import (
    LP_DEVICE_STEP,
    NOMINAL_LN_R_INTERCEPT,
    NOMINAL_LN_R_SLOPE,
    ChannelResolutionError,
    conditioned_frame,
    resolve_lp,
)

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "mindwalker_export.csv"


def _lp_to_resistance(lp: float) -> float:
    return math.exp(NOMINAL_LN_R_SLOPE * lp + NOMINAL_LN_R_INTERCEPT)


# --- the golden fixture, shared with the frontend parser test -------------------------------


def test_real_export_resolves_via_the_raw_adc_channel():
    resolution = resolve_lp(pd.read_csv(FIXTURE))

    assert resolution.strategy == "data+baseline"
    assert resolution.source_columns["data"] == "Data(16 bit)"
    # ~1e-4 LP, i.e. the ADC channel rather than the 0.05 Baseline staircase.
    assert resolution.resolution_lp < 0.001
    assert not resolution.quantised


def test_real_export_lp_tracks_the_baseline_staircase():
    """LP must agree with the device's own charge level to within its quantisation."""
    df = pd.read_csv(FIXTURE)
    resolution = resolve_lp(df)

    assert np.max(np.abs(resolution.lp - df["Baseline"].to_numpy())) < LP_DEVICE_STEP


def test_real_export_recovers_detail_the_baseline_column_discards():
    """The first five samples sit in one Baseline step but are five distinct charge levels.

    This is the defect the whole stage exists to fix: plotting `Baseline` shows a flat staircase
    tread here, because the column cannot represent movement finer than 0.05 LP.
    """
    df = pd.read_csv(FIXTURE)
    resolution = resolve_lp(df)

    assert df["Baseline"].to_numpy()[:5].tolist() == [6.0] * 5
    assert len(np.unique(np.round(resolution.lp[:5], 5))) > 1


def test_real_export_reports_measured_resistance_not_a_reconstruction():
    """The nominal calibration is ~0.3 LP off on any individual device, so prefer the column."""
    df = pd.read_csv(FIXTURE)
    frame, _ = conditioned_frame(df)

    assert frame["resistance_kohm"].iloc[0] == pytest.approx(213.3044)


def test_milliseconds_are_detected_from_the_column_name():
    frame, _ = conditioned_frame(pd.read_csv(FIXTURE))

    assert frame["time_sec"].iloc[0] == pytest.approx(0.0)
    assert frame["time_sec"].iloc[1] == pytest.approx(0.02)


# --- resolution order ------------------------------------------------------------------------


def test_resistance_with_baseline_fits_this_recordings_own_constants():
    lp = np.linspace(2.0, 4.0, 40)
    df = pd.DataFrame(
        {
            "time": np.arange(40) * 0.1,
            "Baseline": np.round(lp / LP_DEVICE_STEP) * LP_DEVICE_STEP,
            "Resistance(kOhm)": np.exp(1.2 * lp - 0.5),
        }
    )

    resolution = resolve_lp(df)

    assert resolution.strategy == "resistance+baseline"
    # Recovered LP must follow the recording's own 1.2/-0.5 calibration, not the nominal one.
    assert np.max(np.abs(resolution.lp - lp)) < 0.05


def test_resistance_alone_falls_back_to_the_nominal_calibration():
    lp = np.linspace(2.0, 4.0, 20)
    df = pd.DataFrame({"time": np.arange(20) * 0.1, "resistance": [_lp_to_resistance(v) for v in lp]})

    resolution = resolve_lp(df)

    assert resolution.strategy == "resistance-nominal"
    assert np.max(np.abs(resolution.lp - lp)) < 1e-6
    assert any("nominal" in note for note in resolution.notes)


def test_conductance_is_reciprocated_to_resistance():
    lp = np.linspace(2.0, 4.0, 20)
    resistance_kohm = np.array([_lp_to_resistance(v) for v in lp])
    df = pd.DataFrame({"time": np.arange(20) * 0.1, "Conductance(uS)": 1.0e3 / resistance_kohm})

    resolution = resolve_lp(df)

    assert np.max(np.abs(resolution.lp - lp)) < 1e-6


def test_baseline_alone_is_used_but_flagged_as_quantised():
    df = pd.DataFrame({"time": np.arange(20) * 0.1, "Baseline": np.repeat([3.0, 3.05, 3.1, 3.15], 5)})

    resolution = resolve_lp(df)

    assert resolution.strategy == "baseline"
    assert resolution.quantised
    assert any("quantised" in note for note in resolution.notes)


def test_a_generic_data_column_does_not_hijack_resolution():
    """A `data` column only means the ADC channel when a Baseline sits beside it to anchor it."""
    lp = np.linspace(2.0, 4.0, 20)
    df = pd.DataFrame(
        {
            "time": np.arange(20) * 0.1,
            "data": np.random.default_rng(0).normal(size=20),
            "resistance": [_lp_to_resistance(v) for v in lp],
        }
    )

    resolution = resolve_lp(df)

    assert resolution.strategy == "resistance-nominal"


def test_an_unrelated_data_column_beside_a_baseline_is_rejected_not_trusted():
    """If `data` does not fit the Baseline, say so and fall through rather than inventing LP."""
    df = pd.DataFrame(
        {
            "time": np.arange(20) * 0.1,
            "data": np.random.default_rng(1).normal(size=20),
            "Baseline": np.repeat([3.0, 3.05, 3.1, 3.15], 5),
            "resistance": [_lp_to_resistance(v) for v in np.linspace(3.0, 3.15, 20)],
        }
    )

    resolution = resolve_lp(df)

    assert resolution.strategy != "data+baseline"
    assert any("not the raw charge channel" in note for note in resolution.notes)


# --- failure modes ---------------------------------------------------------------------------


def test_missing_time_column_is_rejected():
    with pytest.raises(ChannelResolutionError, match="time"):
        resolve_lp(pd.DataFrame({"resistance": [1.0, 2.0]}))


def test_missing_charge_channel_is_rejected():
    with pytest.raises(ChannelResolutionError, match="charge channel"):
        resolve_lp(pd.DataFrame({"time": [0.0, 0.1], "temperature": [20.0, 21.0]}))


def test_seconds_are_left_alone():
    df = pd.DataFrame({"time": np.arange(20) * 0.1, "resistance": np.full(20, 5.0)})

    frame, _ = conditioned_frame(df)

    assert frame["time_sec"].iloc[-1] == pytest.approx(1.9)


def test_long_recording_in_seconds_is_not_read_as_milliseconds():
    """A 30-minute session logged in seconds must stay 30 minutes (the old max-based bug)."""
    seconds = np.arange(0, 1800, 0.1)
    df = pd.DataFrame({"time": seconds, "resistance": np.full(seconds.size, 5.0)})

    frame, _ = conditioned_frame(df)

    assert frame["time_sec"].iloc[-1] == pytest.approx(1799.9)


def test_rows_with_unparseable_values_are_dropped():
    df = pd.DataFrame({"time": [0.0, 0.1, 0.2], "resistance": [5.0, float("nan"), 5.2]})

    frame, _ = conditioned_frame(df)

    assert len(frame) == 2
