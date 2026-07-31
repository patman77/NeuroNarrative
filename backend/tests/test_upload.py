"""Endpoint tests for /api/upload.

These cover the route end-to-end because a Starlette API change once broke uploads
(`async with upload` stopped working on UploadFile) with nothing to catch it.
"""
from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path, summarizer_enabled=False
    )
    with TestClient(app) as test_client:
        yield test_client


def _files():
    return {
        "gsr": ("gsr.csv", b"Time,resistance\n0,10.5\n100,11.0\n", "text/csv"),
        "audio": ("audio.wav", b"RIFF....WAVE", "audio/wav"),
    }


def test_upload_stages_both_files(client, tmp_path):
    response = client.post("/api/upload", files=_files())

    assert response.status_code == 200
    body = response.json()
    for key in ("csv_path", "wav_path"):
        staged = tmp_path / (body[key].rsplit("/", 1)[-1])
        assert staged.exists(), f"{key} was not written"
    assert (tmp_path / "gsr.csv").read_bytes().startswith(b"Time,resistance")


def test_upload_deduplicates_repeat_filenames(client, tmp_path):
    first = client.post("/api/upload", files=_files()).json()
    second = client.post("/api/upload", files=_files()).json()

    assert first["csv_path"] != second["csv_path"]
    assert (tmp_path / "gsr-1.csv").exists()


def test_upload_rejects_non_csv_gsr(client):
    files = _files()
    files["gsr"] = ("gsr.txt", b"nope", "text/plain")

    response = client.post("/api/upload", files=files)

    assert response.status_code == 400
    assert "CSV" in response.json()["detail"]


def test_upload_accepts_wav_by_extension_when_mime_is_blank(client):
    files = _files()
    files["audio"] = ("audio.wav", b"RIFF....WAVE", "")

    assert client.post("/api/upload", files=files).status_code == 200


def test_analyze_rejects_unstaged_path(client):
    response = client.post(
        "/api/analyze",
        json={"csv_path": "/etc/passwd", "wav_path": "/etc/hosts"},
    )

    assert response.status_code == 400


def test_analyze_returns_a_job_immediately(client, tmp_path):
    """The request must not block on the analysis; it returns a job to poll."""
    staged = client.post("/api/upload", files=_files()).json()

    response = client.post(
        "/api/analyze",
        json={
            "csv_path": staged["csv_path"],
            "wav_path": staged["wav_path"],
            "ruleset_name": "default",
        },
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]

    status = client.get(f"/api/analyze/{job_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["job_id"] == job_id
    assert body["status"] in {"queued", "running", "done", "error"}


def test_status_of_unknown_job_is_404(client):
    assert client.get("/api/analyze/does-not-exist").status_code == 404


def test_failing_analysis_is_reported_on_the_job(client):
    """A broken input must surface as job error, not as an unhandled exception."""
    staged = client.post("/api/upload", files=_files()).json()

    job_id = client.post(
        "/api/analyze",
        json={"csv_path": staged["csv_path"], "wav_path": staged["wav_path"]},
    ).json()["job_id"]

    # The stub WAV is not decodable, so the job must end in "error" rather than hanging.
    for _ in range(100):
        body = client.get(f"/api/analyze/{job_id}").json()
        if body["status"] in {"done", "error"}:
            break
        time.sleep(0.05)

    assert body["status"] == "error"
    assert body["error"]
