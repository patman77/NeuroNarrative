"""Runtime detection helpers for GPU availability."""

from __future__ import annotations

import os
from pathlib import Path

from .accelerator import is_apple_silicon


def cuda_gpu_is_available() -> bool:
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


def gpu_is_available() -> bool:
    """True if *any* usable GPU is present — CUDA or Apple's integrated Metal GPU.

    This gates local LLM summarisation. It used to test for CUDA only, so every Apple
    silicon Mac reported "no GPU" and disabled summaries — even with Ollama running
    happily on Metal right next to it.
    """
    return cuda_gpu_is_available() or is_apple_silicon()
