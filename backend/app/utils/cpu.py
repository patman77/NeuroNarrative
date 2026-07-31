"""CPU topology detection and thread budgeting for CPU-bound work (ASR).

Transcription saturates every core by default, which makes the machine unusable while an
analysis runs. This module works out how much compute is actually available — honouring
heterogeneous cores, CPU affinity and container quotas — and leaves headroom for the UI.
"""

from __future__ import annotations

import logging
import math
import os
import platform
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CpuTopology:
    """What the machine actually offers this process."""

    logical: int
    performance: int | None = None  # None when the platform reports no P/E split
    efficiency: int | None = None
    quota: float | None = None  # container CPU limit, in cores
    source: str = "unknown"

    @property
    def budget(self) -> int:
        """Cores worth scheduling compute on.

        On heterogeneous CPUs (Apple silicon, Intel P/E) only the performance cores are
        counted: efficiency cores add little throughput to this workload and dragging the
        thread pool across both core types tends to make it slower, not faster.
        """
        base = self.performance if self.performance else self.logical
        if self.quota is not None:
            base = min(base, max(1, int(self.quota)))
        return max(1, base)

    def describe(self) -> str:
        parts = [f"{self.logical} logical"]
        if self.performance is not None and self.efficiency is not None:
            parts.append(f"{self.performance}P+{self.efficiency}E")
        if self.quota is not None:
            parts.append(f"quota {self.quota:.2f} cores")
        return ", ".join(parts) + f" (via {self.source})"


def _sysctl_int(name: str) -> int | None:
    """Read an integer sysctl without shelling out (PATH is unreliable when frozen)."""
    import ctypes
    import ctypes.util

    try:
        libc_path = ctypes.util.find_library("c")
        libc = ctypes.CDLL(libc_path) if libc_path else ctypes.CDLL("libc.dylib")
        value = ctypes.c_int64(0)
        size = ctypes.c_size_t(ctypes.sizeof(value))
        rc = libc.sysctlbyname(
            name.encode(), ctypes.byref(value), ctypes.byref(size), None, ctypes.c_size_t(0)
        )
        if rc != 0:
            return None
        return int(value.value) or None
    except Exception:  # pragma: no cover - platform specific
        return None


def _cgroup_quota() -> float | None:
    """Container CPU limit in cores, or None when unconstrained."""
    v2 = Path("/sys/fs/cgroup/cpu.max")
    try:
        if v2.exists():
            raw = v2.read_text().split()
            if len(raw) == 2 and raw[0] != "max":
                quota, period = float(raw[0]), float(raw[1])
                if period > 0:
                    return quota / period
            return None

        quota_file = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        period_file = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if quota_file.exists() and period_file.exists():
            quota = float(quota_file.read_text().strip())
            period = float(period_file.read_text().strip())
            if quota > 0 and period > 0:
                return quota / period
    except (OSError, ValueError):  # pragma: no cover - unusual cgroup layouts
        return None
    return None


def detect_cpu() -> CpuTopology:
    """Best-effort view of the CPUs available to this process."""
    logical = os.cpu_count() or 1

    # Affinity can be narrower than the machine (taskset, cpuset, some schedulers).
    if hasattr(os, "sched_getaffinity"):
        try:
            logical = len(os.sched_getaffinity(0)) or logical
        except OSError:  # pragma: no cover - not supported everywhere
            pass

    if platform.system() == "Darwin":
        performance = _sysctl_int("hw.perflevel0.logicalcpu")
        efficiency = _sysctl_int("hw.perflevel1.logicalcpu")
        if performance:
            return CpuTopology(
                logical=logical,
                performance=performance,
                efficiency=efficiency or 0,
                quota=None,
                source="sysctl hw.perflevel*",
            )
        return CpuTopology(logical=logical, source="os.cpu_count")

    return CpuTopology(logical=logical, quota=_cgroup_quota(), source="affinity/cgroup")


def _headroom(budget: int) -> int:
    """Cores deliberately left free so the UI stays responsive during analysis."""
    if budget <= 2:
        return 0
    if budget <= 4:
        return 1
    return 2


def asr_thread_count(override: int = 0, topology: CpuTopology | None = None) -> int:
    """Threads to hand the ASR model.

    Two limits apply, and the smaller wins:

    * responsiveness — keep `_headroom` cores free so the UI does not stall;
    * throughput — oversubscribing int8 GEMM makes transcription *slower*, not faster.

    The second is not intuition. Measured on an M1 Pro (8P+2E), transcribing 3 minutes of
    speech: 4 threads 29 s, 6 threads 32 s, 8 threads 51 s, 10 threads 70 s. Half the
    compute budget is both the fastest and the gentlest setting, so that is the default.

    `override` > 0 (NEURONARRATIVE_ASR_THREADS) wins outright, for anyone who wants to
    hand over every core or pin it to one.
    """
    topology = topology or detect_cpu()
    budget = topology.budget

    if override > 0:
        return max(1, min(override, topology.logical))

    responsive = budget - _headroom(budget)
    efficient = math.ceil(budget / 2)
    return max(1, min(responsive, efficient))
