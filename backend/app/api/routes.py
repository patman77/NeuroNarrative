import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..core.config import Settings, get_settings
from ..services.analysis import run_analysis
from ..services.jobs import store
from ..services.labels import Label, LabelStore, missed_id, training_rows
from ..services.phenomena.evaluate import evaluate
from ..services.storage import prune_old_uploads, save_temp_upload
from ..utils.cpu import asr_thread_count, detect_cpu
from ..utils.hardware import gpu_is_available
from .schemas import (
    EvaluateRequest,
    LabelListResponse,
    LabelRequest,
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


# ---------------------------------------------------------------------------
# Labels
#
# The hinge for everything past stage 4 of docs/phenomena-detection-design.md: there is no
# ground truth for this corpus, so precision and recall are unmeasurable until the operator
# marks some. Labels key on the content-derived `Phenomenon.id` and survive re-analysis.
# ---------------------------------------------------------------------------


def _label_store(settings: Settings = Depends(get_settings)) -> LabelStore:
    return LabelStore(settings.label_dir)


@router.get("/labels/{recording_id}", response_model=LabelListResponse)
async def list_labels(
    recording_id: str, store: LabelStore = Depends(_label_store)
) -> LabelListResponse:
    return LabelListResponse(
        recording_id=recording_id,
        labels=[label.as_dict() for label in store.load(recording_id)],
        summary=store.summary(recording_id),
    )


@router.put("/labels/{recording_id}", response_model=LabelListResponse)
async def upsert_label(
    recording_id: str,
    payload: LabelRequest,
    store: LabelStore = Depends(_label_store),
) -> LabelListResponse:
    if payload.verdict in ("reclassified", "missed") and not payload.kind:
        raise HTTPException(status_code=400, detail=f"{payload.verdict} needs a kind")
    if payload.verdict == "missed" and payload.t_start is None:
        raise HTTPException(status_code=400, detail="a missed phenomenon needs t_start")

    phenomenon_id = payload.phenomenon_id
    if payload.verdict == "missed" and not phenomenon_id:
        # No detection to key on, so derive a stable id from the time and kind instead.
        phenomenon_id = missed_id(payload.t_start or 0.0, payload.kind or "A")
    if not phenomenon_id:
        raise HTTPException(status_code=400, detail="phenomenon_id is required")

    label = Label(
        phenomenon_id=phenomenon_id,
        verdict=payload.verdict,
        kind=payload.kind,
        t_start=payload.t_start,
        note=payload.note,
    )
    labels = store.upsert(recording_id, label)
    return LabelListResponse(
        recording_id=recording_id,
        labels=[l.as_dict() for l in labels],
        summary=store.summary(recording_id),
    )


@router.delete("/labels/{recording_id}/{phenomenon_id}", response_model=LabelListResponse)
async def delete_label(
    recording_id: str, phenomenon_id: str, store: LabelStore = Depends(_label_store)
) -> LabelListResponse:
    labels = store.delete(recording_id, phenomenon_id)
    return LabelListResponse(
        recording_id=recording_id,
        labels=[l.as_dict() for l in labels],
        summary=store.summary(recording_id),
    )


@router.post("/labels/{recording_id}/evaluate", response_model=dict)
async def evaluate_labels(
    recording_id: str,
    payload: EvaluateRequest,
    store: LabelStore = Depends(_label_store),
) -> dict:
    """Precision and recall per kind, from whatever labels exist so far.

    The detections are posted back rather than recomputed: re-running detection here would
    re-read the recording for no benefit, and the client already has the exact result its
    labels were made against.
    """
    labels = store.load(recording_id)
    scores = evaluate(payload.phenomena, labels, tolerance_sec=payload.tolerance_sec)
    return {
        "evaluation": scores.as_dict(),
        "training_rows": training_rows(labels, payload.phenomena),
    }
