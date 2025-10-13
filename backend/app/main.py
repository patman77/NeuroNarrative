from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router as api_router
from .core.config import get_settings
from .utils.hardware import gpu_is_available

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.summarizer_enabled and settings.require_gpu_for_summarizer:
        if not gpu_is_available():
            settings.summarizer_enabled = False
            logger.warning("GPU not detected; disabling summarisation service.")
        else:
            logger.info("GPU detected; summarisation service enabled.")

    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
