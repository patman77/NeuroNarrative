import logging
import time
from pathlib import Path

from fastapi import UploadFile

logger = logging.getLogger(__name__)


def prune_old_uploads(directory: Path, retention_hours: float) -> int:
    """Delete staged uploads older than `retention_hours`. Returns the count removed.

    Uploads are only needed between /upload and the /analyze call that follows it, but
    nothing else ever cleans them up — without this the cache grows without bound.
    """
    if retention_hours <= 0 or not directory.exists():
        return 0

    cutoff = time.time() - retention_hours * 3600
    removed = 0
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError as exc:  # pragma: no cover - filesystem race
            logger.warning("Could not prune %s: %s", entry, exc)
    if removed:
        logger.info("Pruned %d stale upload(s) from %s", removed, directory)
    return removed


async def save_temp_upload(directory: Path, upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "upload.bin").suffix
    target = directory / f"{upload.filename or 'upload'}"
    if target.exists():
        stem = Path(upload.filename or "upload").stem
        counter = 1
        while True:
            candidate = directory / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                target = candidate
                break
            counter += 1

    # Note: UploadFile is not an async context manager in current Starlette versions.
    try:
        content = await upload.read()
    finally:
        await upload.close()
    target.write_bytes(content)
    return target
