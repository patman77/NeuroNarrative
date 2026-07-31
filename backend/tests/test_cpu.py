"""Unit tests for CPU topology detection and the ASR thread budget."""
from __future__ import annotations

import pytest

from app.utils.cpu import CpuTopology, asr_thread_count, detect_cpu


# ---------------------------------------------------------------------------
# budget: which cores count as compute
# ---------------------------------------------------------------------------

def test_budget_prefers_performance_cores():
    """Apple silicon: efficiency cores are not counted as compute."""
    topo = CpuTopology(logical=10, performance=8, efficiency=2)
    assert topo.budget == 8


def test_budget_falls_back_to_logical_when_homogeneous():
    assert CpuTopology(logical=16).budget == 16


def test_budget_respects_container_quota():
    """A 2-core cgroup limit wins over 16 visible cores."""
    assert CpuTopology(logical=16, quota=2.0).budget == 2


def test_budget_never_drops_below_one():
    assert CpuTopology(logical=1, quota=0.25).budget == 1


# ---------------------------------------------------------------------------
# headroom policy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "topology,expected",
    [
        (CpuTopology(logical=10, performance=8, efficiency=2), 4),  # M1 Pro
        (CpuTopology(logical=8), 4),
        (CpuTopology(logical=4), 2),
        (CpuTopology(logical=2), 1),
        (CpuTopology(logical=1), 1),
        (CpuTopology(logical=16), 8),
        (CpuTopology(logical=16, quota=2.0), 1),  # small container
    ],
)
def test_thread_count_is_half_the_budget(topology, expected):
    """Half the compute budget: fastest measured setting and leaves the machine usable."""
    assert asr_thread_count(topology=topology) == expected


def test_thread_count_never_exceeds_responsive_limit():
    """Headroom still binds when halving would allow more."""
    for cores in range(1, 65):
        topo = CpuTopology(logical=cores)
        threads = asr_thread_count(topology=topo)
        assert 1 <= threads <= cores
        if cores > 4:
            assert threads <= cores - 2


def test_override_wins():
    topo = CpuTopology(logical=10, performance=8, efficiency=2)
    assert asr_thread_count(override=1, topology=topo) == 1
    assert asr_thread_count(override=4, topology=topo) == 4


def test_override_is_capped_at_logical_cores():
    topo = CpuTopology(logical=10, performance=8, efficiency=2)
    assert asr_thread_count(override=64, topology=topo) == 10


def test_override_of_zero_means_auto():
    topo = CpuTopology(logical=8)
    assert asr_thread_count(override=0, topology=topo) == asr_thread_count(topology=topo)


# ---------------------------------------------------------------------------
# live detection
# ---------------------------------------------------------------------------

def test_detect_cpu_returns_something_sane():
    topo = detect_cpu()
    assert topo.logical >= 1
    assert topo.budget >= 1
    assert topo.budget <= topo.logical
    assert 1 <= asr_thread_count(topology=topo) <= topo.logical
    assert topo.describe()
