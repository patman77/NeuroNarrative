from pathlib import Path

from fastapi import UploadFile


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

    async with upload as uploaded_file:
        content = await uploaded_file.read()
    target.write_bytes(content)
    return target
