"""Desktop launcher: runs the API and shows the UI in a native window.

This is the entrypoint PyInstaller freezes. It differs from `uvicorn app.main:app` in
ways that only matter when there is no terminal:

* it binds an ephemeral port, because 8000 is often taken;
* it serves the built SPA itself, so there is no dev server, proxy or CORS involved;
* it logs to a file, because nobody is watching stdout;
* it opens a pywebview window (system WKWebView on macOS) rather than a browser tab.

Display modes:

* default                        – native window; falls back to the browser if pywebview
                                   is unavailable
* NEURONARRATIVE_BROWSER=1       – force the system browser
* NEURONARRATIVE_NO_BROWSER=1    – headless; serve only, open nothing (used by the smoke test)
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from platformdirs import user_log_path, user_state_path

APP_DIRNAME = "neuronarrative"
HEALTH_TIMEOUT_SEC = 60.0
# Must match info_plist bundle_identifier in packaging/neuronarrative.spec.
BUNDLE_ID = "dev.neuronarrative.app"

logger = logging.getLogger("neuronarrative.desktop")


def _bundle_root() -> Path:
    """Directory holding bundled data files, frozen or not."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:  # PyInstaller
        return Path(meipass)
    # Running from a checkout: backend/app/desktop.py -> repo root
    return Path(__file__).resolve().parents[2]


def _resolve_frontend_dist(root: Path) -> Path | None:
    for candidate in (root / "frontend_dist", root / "frontend" / "dist"):
        if (candidate / "index.html").exists():
            return candidate
    return None


def _resolve_bundled_model_dir(root: Path) -> Path | None:
    """Return the bundled model cache if this build shipped one."""
    candidate = root / "asr_models"
    # huggingface_hub layout: models--Systran--faster-whisper-<size>
    if candidate.is_dir() and any(candidate.glob("models--*")):
        return candidate
    return None


def _configure_logging() -> Path:
    log_dir = user_log_path(APP_DIRNAME, ensure_exists=True)
    log_file = log_dir / "neuronarrative.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stderr)],
    )
    return log_file


def _reserve_port() -> tuple[socket.socket, int]:
    """Bind an ephemeral port and keep the socket, so nothing can race us for it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.set_inheritable(True)
    return sock, sock.getsockname()[1]


def _state_file() -> Path:
    return user_state_path(APP_DIRNAME, ensure_exists=True) / "instance.port"


def _existing_instance_url() -> str | None:
    """If a previous instance is still serving, return its URL.

    The state file can outlive the process: quitting via the window closes the app
    through AppKit, which does not unwind our `finally`. So the file is never trusted on
    its own — always health-probe it, and clear it when the probe fails.
    """
    state = _state_file()
    if not state.exists():
        return None
    try:
        port = int(state.read_text().strip())
    except (ValueError, OSError):
        state.unlink(missing_ok=True)
        return None

    import httpx

    url = f"http://127.0.0.1:{port}"
    try:
        if httpx.get(f"{url}/api/health", timeout=2.0).status_code == 200:
            return url
    except httpx.HTTPError:
        pass

    logger.info("Clearing stale instance file for port %d", port)
    state.unlink(missing_ok=True)
    return None


def _activate_running_app() -> bool:
    """Focus the already-running instance's window instead of opening a browser."""
    if sys.platform != "darwin":
        return False
    try:
        from AppKit import NSRunningApplication

        running = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
        if not running:
            return False
        running[0].activateWithOptions_(1 << 1)  # NSApplicationActivateIgnoringOtherApps
        return True
    except Exception as exc:  # pragma: no cover - platform specific
        logger.debug("Could not activate the running app: %s", exc)
        return False


def _wait_for_health(url: str) -> bool:
    """Block until the API answers, so the window never loads a connection error."""
    import time

    import httpx

    deadline = time.monotonic() + HEALTH_TIMEOUT_SEC
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/api/health", timeout=2.0).status_code == 200:
                logger.info("Backend ready at %s", url)
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    logger.error("Backend did not become healthy within %.0fs", HEALTH_TIMEOUT_SEC)
    return False


def _show_window(url: str) -> bool:
    """Open the UI in a native window. Blocks until closed.

    Returns False if pywebview is unavailable, so the caller can fall back to a browser.
    On macOS the GUI event loop must own the main thread, which is why the HTTP server
    runs on a worker thread and this is called from main().
    """
    try:
        import webview
    except ImportError:
        logger.warning("pywebview not installed; falling back to the system browser.")
        return False

    try:
        webview.create_window(
            "NeuroNarrative",
            url,
            width=1440,
            height=940,
            min_size=(1024, 700),
            text_select=True,
        )
        webview.start()
        return True
    except Exception as exc:  # pragma: no cover - platform/GUI specific
        logger.warning("Could not open a native window (%s); falling back to browser.", exc)
        return False


def main() -> int:
    # MUST be first. In a PyInstaller bundle a child process spawned by any library
    # re-executes this binary from the top; without freeze_support each one would start a
    # whole new app, hit the single-instance guard and pop open a browser window. That is
    # exactly what happened when transcription spawned workers.
    multiprocessing.freeze_support()

    log_file = _configure_logging()
    root = _bundle_root()

    existing = _existing_instance_url()
    if existing:
        logger.info("An instance is already running at %s.", existing)
        if os.environ.get("NEURONARRATIVE_NO_BROWSER") == "1":
            return 0
        # Bring the running app's own window forward. Opening a browser instead would be
        # a second, confusing copy of the same session.
        if not _activate_running_app():
            logger.info("Could not focus the running window; opening %s instead.", existing)
            webbrowser.open(existing)
        return 0

    # Configure the app through the environment before importing it: Settings is
    # lru_cached on first access, so this has to happen first.
    dist = _resolve_frontend_dist(root)
    if dist is not None:
        os.environ.setdefault("NEURONARRATIVE_FRONTEND_DIST", str(dist))
    else:
        logger.warning("No built frontend found under %s; serving the API only.", root)

    bundled_model = _resolve_bundled_model_dir(root)
    if bundled_model is not None:
        os.environ.setdefault("NEURONARRATIVE_ASR_MODEL_DIR", str(bundled_model))
        # MLX resolves models through huggingface_hub, which reads this at import time —
        # hence setting it before app.main (and therefore any hub import) is pulled in.
        os.environ.setdefault("HF_HUB_CACHE", str(bundled_model))
        logger.info("Using bundled ASR model cache at %s", bundled_model)

    sock, port = _reserve_port()
    url = f"http://127.0.0.1:{port}"
    _state_file().write_text(str(port), encoding="utf-8")

    logger.info("NeuroNarrative starting on %s (logs: %s)", url, log_file)
    print(f"NeuroNarrative running at {url}", flush=True)

    import uvicorn

    # Absolute import, not relative: when frozen this module runs as __main__, so it has
    # no parent package. Import (not create_app()) to reuse the module-level app.
    from app.main import app as fastapi_app

    server = uvicorn.Server(uvicorn.Config(fastapi_app, log_config=None))

    try:
        if os.environ.get("NEURONARRATIVE_NO_BROWSER") == "1":
            # Headless: serve on the main thread and open nothing.
            server.run(sockets=[sock])
            return 0

        # The GUI needs the main thread (a hard requirement on macOS), so the server
        # goes to a worker.
        server_thread = threading.Thread(
            target=server.run, kwargs={"sockets": [sock]}, name="uvicorn", daemon=True
        )
        server_thread.start()

        if not _wait_for_health(url):
            return 1

        windowed = os.environ.get("NEURONARRATIVE_BROWSER") != "1" and _show_window(url)
        if not windowed:
            webbrowser.open(url)
            server_thread.join()  # browser mode: stay up until killed

        # The window closed — shut the server down rather than orphaning it.
        logger.info("Window closed; shutting down.")
        server.should_exit = True
        server_thread.join(timeout=10)
    finally:
        try:
            _state_file().unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best effort
            pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
