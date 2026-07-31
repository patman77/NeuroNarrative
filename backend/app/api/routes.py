import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..core.config import Settings, get_settings
from ..services.analysis import run_analysis
from ..services.jobs import store
from ..services.storage import prune_old_uploads, save_temp_upload
from ..utils.cpu import asr_thread_count, detect_cpu
from ..utils.hardware import gpu_is_available
from .schemas import (
    AnalysisJobCreated,
    AnalysisJobStatus,
    AnalysisRequest,
    AnalysisResponse,
    HealthResponse,
    UploadResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_staged_path(raw: str, settings: Settings) -> Path:
    """Confine an /analyze path argument to the upload directory.

    The client hands back paths it received from /upload, so anything outside the
    staging directory is either a stale path or an attempt to read arbitrary files.
    """
    upload_dir = settings.upload_dir.resolve()
    candidate = Path(raw).resolve()
    if not candidate.is_relative_to(upload_dir):
        raise HTTPException(status_code=400, detail="Path is outside the upload directory")
    return candidate


@router.get("/health", response_model=HealthResponse)
async def healthcheck(settings: Settings = Depends(get_settings)) -> HealthResponse:
    topology = detect_cpu()
    return HealthResponse(
        summarizer_enabled=settings.summarizer_enabled,
        summarizer_status=settings.summarizer_status,
        gpu_available=gpu_is_available(),
        cpu=topology.describe(),
        asr_threads=asr_thread_count(override=settings.asr_threads, topology=topology),
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_recording(
    gsr: UploadFile = File(..., description="CSV export of GSR readings"),
    audio: UploadFile = File(..., description="WAV recording aligned with GSR"),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    if gsr.content_type not in {"text/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=400, detail="GSR file must be CSV")
    ALLOWED_WAV_TYPES = {"audio/wav", "audio/x-wav", "audio/vnd.wave", "audio/wave", ""}
    wav_name = audio.filename or ""
    if audio.content_type not in ALLOWED_WAV_TYPES and not wav_name.lower().endswith(".wav"):
        raise HTTPException(status_code=400, detail="Audio file must be WAV")

    upload_dir = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    prune_old_uploads(upload_dir, settings.upload_retention_hours)

    csv_path = await save_temp_upload(upload_dir, gsr)
    wav_path = await save_temp_upload(upload_dir, audio)

    return UploadResponse(csv_path=str(csv_path), wav_path=str(wav_path))


@router.post("/analyze", response_model=AnalysisJobCreated, status_code=202)
async def analyze_recording(
    payload: AnalysisRequest,
    settings: Settings = Depends(get_settings),
) -> AnalysisJobCreated:
    """Start an analysis and return immediately.

    Transcribing a long recording takes minutes, which no single HTTP request survives —
    the webview enforces its own request timeout. Poll `GET /analyze/{job_id}` instead.
    """
    csv_path = _resolve_staged_path(payload.csv_path, settings)
    wav_path = _resolve_staged_path(payload.wav_path, settings)
    if not csv_path.exists() or not wav_path.exists():
        raise HTTPException(status_code=404, detail="Uploaded files not found; please upload again")

    validated = payload.model_copy(update={"csv_path": str(csv_path), "wav_path": str(wav_path)})
    job = store.create()

    async def _run() -> None:
        store.update(job.job_id, status="running", stage="starting")
        try:
            result = await run_analysis(
                validated,
                settings=settings,
                progress=lambda stage, fraction: store.update(
                    job.job_id, stage=stage, progress=fraction
                ),
            )
            store.finish(job.job_id, result)
        except HTTPException as exc:
            store.fail(job.job_id, str(exc.detail))
        except Exception as exc:  # noqa: BLE001 - surface anything to the client
            logger.exception("Analysis job %s failed", job.job_id)
            store.fail(job.job_id, f"{type(exc).__name__}: {exc}")

    asyncio.create_task(_run())
    return AnalysisJobCreated(job_id=job.job_id)


@router.get("/analyze/{job_id}", response_model=AnalysisJobStatus)
async def analysis_status(job_id: str) -> AnalysisJobStatus:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired analysis job")

    return AnalysisJobStatus(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        result=AnalysisResponse(**job.result) if job.result else None,
        error=job.error,
    )


@router.post("/summaries/test", response_model=dict)
async def summarize_text(
    text: str,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    from ..services.summary import summarize_with_local_llm

    summary = await summarize_with_local_llm(text=text, settings=settings)
    return JSONResponse(content={"summary": summary, "id": uuid.uuid4().hex})
