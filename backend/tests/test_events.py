"""Unit tests for detect_events in app.services.events."""
from __future__ import annotations

import resource
import time

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


# ---------------------------------------------------------------------------
# Scaling guard
# ---------------------------------------------------------------------------

def test_long_recording_stays_bounded():
    """A realistic long recording must not blow up time or memory.

    Regression test for a hang that consumed 32 GB: the rbf changepoint cost builds an
    n x n Gram matrix, so a half-hour recording at 50 Hz (90k samples) needed ~64 GB.
    `_changepoint_candidates` now decimates to CHANGEPOINT_MAX_SAMPLES first.
    """
    from app.services.events import CHANGEPOINT_MAX_SAMPLES

    n = 90_000  # 30 min at 50 Hz
    hz = 50.0
    ts = _make_timestamps(n, hz=hz)
    rng = np.random.default_rng(0)
    readings = 3.0 + np.cumsum(rng.normal(0, 0.01, n))
    readings[40_000:40_500] += 2.0  # one clear excursion

    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.monotonic()
    events = detect_events(ts, readings, ruleset="default")
    elapsed = time.monotonic() - started
    rss_growth = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss_before

    assert elapsed < 30, f"detection took {elapsed:.1f}s on {n} samples"
    # ru_maxrss is bytes on macOS, kilobytes on Linux; 1 GB either way is a generous cap
    # that the quadratic implementation blew through immediately.
    limit = 1_000_000_000 if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 1e7 else 1_000_000
    assert rss_growth < limit, f"detection grew RSS by {rss_growth}"
    assert isinstance(events, list)
    assert CHANGEPOINT_MAX_SAMPLES <= 5000


def test_changepoint_indices_stay_in_range():
    """Decimation must map indices back inside the original signal."""
    from app.services.events import _changepoint_candidates

    n = 20_000
    rng = np.random.default_rng(1)
    signal = 3.0 + np.cumsum(rng.normal(0, 0.01, n))
    signal[12_000:] += 1.5

    candidates = _changepoint_candidates(signal, penalty=8.0)

    assert candidates, "expected at least one changepoint"
    assert all(0 <= c < n for c in candidates), f"index out of range: {candidates}"
