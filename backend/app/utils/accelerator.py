"""Pick the fastest available transcription backend for this machine.

Three hardware situations, detected at runtime rather than configured:

* Apple silicon (M1-M5)  -> MLX on the Metal GPU. Roughly 4.6x faster than CPU int8 on an
  M1 Pro, and slightly more accurate because it runs float16 rather than int8.
* NVIDIA GPU             -> CTranslate2 on CUDA (Windows/Linux; the macOS wheel has no CUDA).
* Everything else        -> CTranslate2 on CPU, including Intel Macs and GPU-less Windows.

Every probe is defensive: a missing package or an unusable driver must degrade to CPU, never
raise, because this runs on machines we cannot test.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

logger = logging.getLogger(__name__)

Backend = Literal["mlx", "faster-whisper"]

# Logical model name -> (faster-whisper name, MLX hub repo).
MODEL_ALIASES: dict[str, tuple[str, str]] = {
    "tiny": ("tiny", "mlx-community/whisper-tiny-mlx"),
    "base": ("base", "mlx-community/whisper-base-mlx"),
    "small": ("small", "mlx-community/whisper-small-mlx"),
    "medium": ("medium", "mlx-community/whisper-medium-mlx"),
    "large-v3": ("large-v3", "mlx-community/whisper-large-v3-mlx"),
    "large-v3-turbo": ("large-v3-turbo", "mlx-community/whisper-large-v3-turbo"),
}


@dataclass(frozen=True)
class Accelerator:
    backend: Backend
    device: str  # "gpu" (Metal), "cuda", "cpu"
    compute_type: str  # CTranslate2 only; empty for MLX
    reason: str

    @property
    def uses_gpu(self) -> bool:
        return self.device in ("gpu", "cuda")

    def describe(self) -> str:
        return f"{self.backend} on {self.device} ({self.reason})"


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64")


def mlx_is_usable() -> bool:
    """True only if MLX imports *and* Metal is actually available."""
    if not is_apple_silicon():
        return False
    try:
        import mlx.core as mx

        if hasattr(mx, "metal") and not mx.metal.is_available():
            return False
        import mlx_whisper  # noqa: F401

        return True
    except Exception as exc:  # pragma: no cover - depends on the host
        logger.debug("MLX unavailable: %s", exc)
        return False


def cuda_device_count() -> int:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception as exc:  # pragma: no cover - depends on the host
        logger.debug("CUDA probe failed: %s", exc)
        return 0


@lru_cache(maxsize=8)
def detect_accelerator(preference: str = "auto") -> Accelerator:
    """Resolve the backend. `preference` may force "mlx", "cuda" or "cpu".

    Cached deliberately: the probes touch Metal, and `/api/health` calls this on the HTTP
    thread. Re-probing while transcription runs on a worker thread means touching MLX from
    two threads at once, which crashes the process. Hardware does not change at runtime.
    """
    preference = (preference or "auto").lower()

    if preference == "mlx":
        if mlx_is_usable():
            return Accelerator("mlx", "gpu", "", "forced by configuration")
        logger.warning("MLX requested but unavailable; falling back to CPU.")
        return Accelerator("faster-whisper", "cpu", "int8", "MLX requested but unavailable")

    if preference == "cuda":
        if cuda_device_count() > 0:
            return Accelerator("faster-whisper", "cuda", "float16", "forced by configuration")
        logger.warning("CUDA requested but no device found; falling back to CPU.")
        return Accelerator("faster-whisper", "cpu", "int8", "CUDA requested but unavailable")

    if preference == "cpu":
        return Accelerator("faster-whisper", "cpu", "int8", "forced by configuration")

    # auto
    if mlx_is_usable():
        return Accelerator("mlx", "gpu", "", "Apple silicon with Metal")
    if cuda_device_count() > 0:
        return Accelerator("faster-whisper", "cuda", "float16", "CUDA device present")
    if is_apple_silicon():
        return Accelerator("faster-whisper", "cpu", "int8", "Apple silicon without MLX installed")
    return Accelerator("faster-whisper", "cpu", "int8", "no GPU acceleration available")


def resolve_model(logical_name: str, backend: Backend) -> str:
    """Translate a logical model name into what the chosen backend expects."""
    alias = MODEL_ALIASES.get(logical_name)
    if alias is None:
        # Unknown name: pass it through so custom paths and hub repos still work.
        return logical_name
    return alias[1] if backend == "mlx" else alias[0]
