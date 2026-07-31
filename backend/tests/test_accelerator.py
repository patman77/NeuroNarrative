"""Backend autodetection across hardware we cannot all test on directly.

The selection logic is pure given the three probes, so the probes are patched to simulate
Apple silicon, NVIDIA machines, Intel Macs and GPU-less Windows.
"""
from __future__ import annotations

import pytest

from app.utils import accelerator as acc


@pytest.fixture()
def probes(monkeypatch):
    """Patch the hardware probes; defaults to a plain CPU machine."""

    state = {"mlx": False, "cuda": 0, "apple": False}
    monkeypatch.setattr(acc, "mlx_is_usable", lambda: state["mlx"])
    monkeypatch.setattr(acc, "cuda_device_count", lambda: state["cuda"])
    monkeypatch.setattr(acc, "is_apple_silicon", lambda: state["apple"])
    # detect_accelerator is cached in production (it must not re-probe Metal while
    # transcription runs), so each test needs a clean slate.
    acc.detect_accelerator.cache_clear()
    yield state
    acc.detect_accelerator.cache_clear()


# ---------------------------------------------------------------------------
# auto
# ---------------------------------------------------------------------------

def test_apple_silicon_with_mlx_uses_the_gpu(probes):
    probes.update(mlx=True, apple=True)
    a = acc.detect_accelerator("auto")
    assert (a.backend, a.device) == ("mlx", "gpu")
    assert a.uses_gpu


def test_nvidia_machine_uses_cuda(probes):
    probes.update(cuda=1)
    a = acc.detect_accelerator("auto")
    assert (a.backend, a.device, a.compute_type) == ("faster-whisper", "cuda", "float16")
    assert a.uses_gpu


def test_apple_silicon_without_mlx_falls_back_to_cpu(probes):
    """M-series Mac where the optional MLX extra was not installed."""
    probes.update(apple=True)
    a = acc.detect_accelerator("auto")
    assert (a.backend, a.device, a.compute_type) == ("faster-whisper", "cpu", "int8")
    assert not a.uses_gpu
    assert "MLX" in a.reason


def test_intel_mac_or_windows_without_gpu_uses_cpu(probes):
    a = acc.detect_accelerator("auto")
    assert (a.backend, a.device, a.compute_type) == ("faster-whisper", "cpu", "int8")


def test_mlx_wins_over_cuda_when_both_somehow_report(probes):
    probes.update(mlx=True, apple=True, cuda=1)
    assert acc.detect_accelerator("auto").backend == "mlx"


# ---------------------------------------------------------------------------
# explicit preference, including impossible ones
# ---------------------------------------------------------------------------

def test_forcing_cpu_is_honoured(probes):
    probes.update(mlx=True, apple=True)
    a = acc.detect_accelerator("cpu")
    assert (a.backend, a.device) == ("faster-whisper", "cpu")


def test_forcing_mlx_without_mlx_degrades_instead_of_raising(probes):
    a = acc.detect_accelerator("mlx")
    assert (a.backend, a.device) == ("faster-whisper", "cpu")
    assert "unavailable" in a.reason


def test_forcing_cuda_without_a_device_degrades(probes):
    a = acc.detect_accelerator("cuda")
    assert a.device == "cpu"
    assert "unavailable" in a.reason


def test_unknown_preference_is_treated_as_auto(probes):
    probes.update(cuda=2)
    assert acc.detect_accelerator("nonsense").device == "cuda"


# ---------------------------------------------------------------------------
# model naming
# ---------------------------------------------------------------------------

def test_model_names_map_per_backend():
    assert acc.resolve_model("small", "faster-whisper") == "small"
    assert acc.resolve_model("small", "mlx") == "mlx-community/whisper-small-mlx"
    assert acc.resolve_model("large-v3-turbo", "mlx").startswith("mlx-community/")


def test_unknown_model_passes_through():
    """Custom paths and hub repos must survive the mapping."""
    assert acc.resolve_model("/models/custom", "mlx") == "/models/custom"
    assert acc.resolve_model("org/repo", "faster-whisper") == "org/repo"


def test_every_alias_covers_both_backends():
    for name, (ct2, mlx) in acc.MODEL_ALIASES.items():
        assert ct2 and mlx, name
        assert mlx.startswith("mlx-community/"), name


# ---------------------------------------------------------------------------
# live probes must never raise
# ---------------------------------------------------------------------------

def test_real_detection_returns_a_usable_choice():
    a = acc.detect_accelerator("auto")
    assert a.backend in ("mlx", "faster-whisper")
    assert a.device in ("gpu", "cuda", "cpu")
    assert a.describe()


def test_probes_are_safe_to_call():
    assert isinstance(acc.mlx_is_usable(), bool)
    assert acc.cuda_device_count() >= 0
    assert isinstance(acc.is_apple_silicon(), bool)
