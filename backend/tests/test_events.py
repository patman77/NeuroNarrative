"""Unit tests for detect_events in app.services.events."""
from __future__ import annotations

import pytest

pytest.importorskip("ruptures")
pytest.importorskip("scipy")

import numpy as np  # noqa: E402

from app.services.events import detect_events  # noqa: E402


def _make_timestamps(n: int, hz: float = 10.0) -> np.ndarray:
    """Create evenly-spaced timestamps at the given sample rate."""
    return np.arange(n, dtype=float) / hz


# ---------------------------------------------------------------------------
# Empty array
# ---------------------------------------------------------------------------

def test_detect_events_empty_array():
    ts = np.array([], dtype=float)
    readings = np.array([], dtype=float)
    events = detect_events(ts, readings)
    assert events == []


# ---------------------------------------------------------------------------
# Flat signal → few or no events
# ---------------------------------------------------------------------------

def test_detect_events_flat_signal():
    n = 100
    ts = _make_timestamps(n, hz=10.0)
    readings = np.full(n, 50.0)  # constant resistance
    events = detect_events(ts, readings)
    # A perfectly flat signal should produce at most 1 event (changepoint boundary)
    assert len(events) <= 1


# ---------------------------------------------------------------------------
# Sharp spike → at least one event near the spike
# ---------------------------------------------------------------------------

def test_detect_events_spike():
    n = 200
    ts = _make_timestamps(n, hz=10.0)
    readings = np.full(n, 50.0, dtype=float)
    spike_idx = 100
    readings[spike_idx] = 200.0  # large spike

    events = detect_events(ts, readings, ruleset="sensitive")
    assert len(events) >= 1

    # The event closest to the spike should be within 2 seconds
    spike_time = ts[spike_idx]
    closest = min(events, key=lambda e: abs(e["time_sec"] - spike_time))
    assert abs(closest["time_sec"] - spike_time) <= 2.0


# ---------------------------------------------------------------------------
# min_gap enforcement: two close spikes → only one kept
# ---------------------------------------------------------------------------

def test_detect_events_min_gap():
    """Two spikes separated by less than min_gap_sec should yield only one event."""
    n = 300
    hz = 10.0
    ts = _make_timestamps(n, hz=hz)
    readings = np.full(n, 50.0, dtype=float)

    # Default ruleset min_gap_sec = 5.0 s
    # Place spikes 2 s apart (< 5 s gap)
    spike_a = 100
    spike_b = 120  # 2 s later at 10 Hz
    readings[spike_a] = 300.0
    readings[spike_b] = 300.0

    events = detect_events(ts, readings, ruleset="default")

    # Count events in the window [spike_a - 1s, spike_b + 1s]
    t_start = ts[spike_a] - 1.0
    t_end = ts[spike_b] + 1.0
    events_in_window = [e for e in events if t_start <= e["time_sec"] <= t_end]
    assert len(events_in_window) <= 1
