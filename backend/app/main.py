from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.routes import router as api_router
from .core.config import Settings, get_settings
from .services.summary import probe_summarizer
from .utils.hardware import gpu_is_available

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_summarizer(settings)

    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    _mount_frontend(app, settings)
    return app


def _configure_summarizer(settings: Settings) -> None:
    """Decide whether summaries can actually be produced, and say why not.

    The old check asked only "is there a CUDA GPU?", which is false on every Apple silicon
    Mac — so summaries were disabled even with Ollama running on Metal. What actually
    matters is whether Ollama answers and has a usable model, so that is what we test.
    """
    if not settings.summarizer_enabled:
        settings.summarizer_status = "disabled by configuration"
        return

    if settings.require_gpu_for_summarizer and not gpu_is_available():
        settings.summarizer_enabled = False
        settings.summarizer_status = "no GPU detected"
        logger.warning("No GPU detected; disabling summarisation.")
        return

    available, model, status = probe_summarizer(settings)
    settings.summarizer_status = status
    settings.resolved_ollama_model = model
    if not available:
        settings.summarizer_enabled = False
        logger.warning("Summarisation unavailable: %s", status)
    else:
        logger.info("Summarisation enabled: %s", status)


class SpaStaticFiles(StaticFiles):
    """StaticFiles that serves index.html for unknown paths.

    `html=True` alone only handles directory indexes, so a client-side route would 404.
    API routes are registered before this mount, so they still win.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the built SPA from the API process when NEURONARRATIVE_FRONTEND_DIST is set.

    Desktop builds have no Vite dev server, so the backend serves the assets itself.
    Same-origin also means the proxy and CORS config stop mattering there.
    """
    dist = settings.frontend_dist
    if dist is None:
        return
    if not (dist / "index.html").exists():
        logger.warning("frontend_dist=%s has no index.html; not serving the SPA.", dist)
        return

    app.mount("/", SpaStaticFiles(directory=dist, html=True), name="frontend")
    logger.info("Serving frontend from %s", dist)


app = create_app()
