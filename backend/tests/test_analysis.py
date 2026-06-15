"""Unit tests for _load_gsr and _infer_sampling_rate in app.services.analysis."""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi import HTTPException

from app.services.analysis import _infer_sampling_rate, _load_gsr


# ---------------------------------------------------------------------------
# _load_gsr
# ---------------------------------------------------------------------------

def test_load_gsr_valid(tmp_path):
    """Valid CSV with Time and resistance columns returns correct DataFrame."""
    csv = tmp_path / "gsr.csv"
    csv.write_text("Time,resistance\n0,10.5\n100,11.0\n200,10.8\n")

    df = _load_gsr(csv)

    assert list(df.columns) == ["time_sec", "resistance_kohm"]
    assert len(df) == 3
    # Time values are in milliseconds (max=200 > 1000 is False here, so kept as-is)
    assert df["time_sec"].iloc[0] == pytest.approx(0.0)
    assert df["resistance_kohm"].iloc[1] == pytest.approx(11.0)


def test_load_gsr_missing_resistance_column(tmp_path):
    """CSV without a resistance column raises HTTPException(400)."""
    csv = tmp_path / "bad.csv"
    csv.write_text("Time,voltage\n0,3.3\n100,3.4\n")

    with pytest.raises(HTTPException) as exc_info:
        _load_gsr(csv)
    assert exc_info.value.status_code == 400


def test_load_gsr_time_in_milliseconds(tmp_path):
    """When time column max > 1000 (ms), time_sec should be divided by 1000."""
    rows = "\n".join(f"{i * 100},{10 + i * 0.1}" for i in range(20))
    csv = tmp_path / "ms.csv"
    csv.write_text(f"Time,resistance\n{rows}\n")

    df = _load_gsr(csv)

    # max raw time = 19 * 100 = 1900 ms → divided by 1000 → 1.9 s
    assert df["time_sec"].max() == pytest.approx(1.9)
    assert df["time_sec"].min() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _infer_sampling_rate
# ---------------------------------------------------------------------------

def test_infer_sampling_rate_regular_10hz():
    """Regular 10 Hz signal (0.1 s intervals) → returns ~10.0."""
    times = [i * 0.1 for i in range(50)]
    df = pd.DataFrame({"time_sec": times})
    rate = _infer_sampling_rate(df)
    assert rate == pytest.approx(10.0, rel=0.01)


def test_infer_sampling_rate_single_row():
    """Single-row DataFrame → returns 0.0 (no intervals to compute)."""
    df = pd.DataFrame({"time_sec": [0.0]})
    rate = _infer_sampling_rate(df)
    assert rate == pytest.approx(0.0)
