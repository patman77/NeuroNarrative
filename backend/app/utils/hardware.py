"""Runtime detection helpers for GPU availability."""

from __future__ import annotations

import os
from pathlib import Path


def gpu_is_available() -> bool:
    """Return True if a CUDA-capable GPU is exposed to the container."""
    # Environment variables provided by Docker/NVIDIA runtimes
    visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES") or os.environ.get(
        "NVIDIA_VISIBLE_DEVICES"
    )
    if visible_devices and visible_devices.lower() not in {"", "void", "none"}:
        if any(part.strip() not in {"", "none", "void"} for part in visible_devices.split(",")):
            return True

    # Device files mounted by the NVIDIA container toolkit
    dev_path = Path("/dev")
    if dev_path.exists():
        gpu_devices = [
            entry
            for entry in dev_path.glob("nvidia*")
            if entry.name not in {"nvidiactl", "nvidia-uvm", "nvidia-uvm-tools", "nvidia-modeset"}
        ]
        if gpu_devices:
            return True

    return False
