import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..core.config import Settings, get_settings
from ..services.analysis import run_analysis
from ..services.storage import save_temp_upload
from .schemas import (
    AnalysisRequest,
    AnalysisResponse,
    HealthResponse,
    UploadResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse()


@router.post("/upload", response_model=UploadResponse)
async def upload_recording(
    gsr: UploadFile = File(..., description="CSV export of GSR readings"),
    audio: UploadFile = File(..., description="WAV recording aligned with GSR"),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    if gsr.content_type not in {"text/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=400, detail="GSR file must be CSV")
    if audio.content_type not in {"audio/wav", "audio/x-wav", "audio/vnd.wave"}:
        raise HTTPException(status_code=400, detail="Audio file must be WAV")

    upload_dir = Path("/tmp/neuronarrative")
    upload_dir.mkdir(parents=True, exist_ok=True)

    csv_path = await save_temp_upload(upload_dir, gsr)
    wav_path = await save_temp_upload(upload_dir, audio)

    return UploadResponse(csv_path=str(csv_path), wav_path=str(wav_path))


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_recording(
    payload: AnalysisRequest,
    settings: Settings = Depends(get_settings),
) -> AnalysisResponse:
    if not Path(payload.csv_path).exists() or not Path(payload.wav_path).exists():
        raise HTTPException(status_code=404, detail="Uploaded files not found; please upload again")

    result = await run_analysis(payload, settings=settings)
    return AnalysisResponse(**result)


@router.post("/summaries/test", response_model=dict)
async def summarize_text(
    text: str,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    from ..services.summary import summarize_with_local_llm

    summary = await summarize_with_local_llm(text=text, settings=settings)
    return JSONResponse(content={"summary": summary, "id": uuid.uuid4().hex})
