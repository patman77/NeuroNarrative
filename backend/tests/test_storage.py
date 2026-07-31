"""Unit tests for upload staging: pruning and path confinement."""
from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException  # noqa: E402

from app.api.routes import _resolve_staged_path  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.services.storage import prune_old_uploads  # noqa: E402


# ---------------------------------------------------------------------------
# prune_old_uploads
# ---------------------------------------------------------------------------

def _age(path, hours: float) -> None:
    """Backdate a file's mtime by `hours`."""
    past = time.time() - hours * 3600
    import os

    os.utime(path, (past, past))


def test_prune_removes_only_stale_files(tmp_path):
    fresh = tmp_path / "fresh.csv"
    stale = tmp_path / "stale.csv"
    fresh.write_text("a")
    stale.write_text("b")
    _age(stale, 48)

    removed = prune_old_uploads(tmp_path, retention_hours=24)

    assert removed == 1
    assert fresh.exists()
    assert not stale.exists()


def test_prune_disabled_when_retention_is_zero(tmp_path):
    stale = tmp_path / "stale.csv"
    stale.write_text("b")
    _age(stale, 999)

    assert prune_old_uploads(tmp_path, retention_hours=0) == 0
    assert stale.exists()


def test_prune_ignores_missing_directory(tmp_path):
    assert prune_old_uploads(tmp_path / "nope", retention_hours=24) == 0


def test_prune_leaves_subdirectories_alone(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    _age(nested, 48)

    assert prune_old_uploads(tmp_path, retention_hours=24) == 0
    assert nested.is_dir()


# ---------------------------------------------------------------------------
# _resolve_staged_path
# ---------------------------------------------------------------------------

def test_resolve_accepts_path_inside_upload_dir(tmp_path):
    settings = Settings(upload_dir=tmp_path)
    staged = tmp_path / "session.csv"
    staged.write_text("x")

    assert _resolve_staged_path(str(staged), settings) == staged.resolve()


def test_resolve_rejects_path_outside_upload_dir(tmp_path):
    settings = Settings(upload_dir=tmp_path / "uploads")

    with pytest.raises(HTTPException) as exc_info:
        _resolve_staged_path("/etc/passwd", settings)
    assert exc_info.value.status_code == 400


def test_resolve_rejects_traversal_escape(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    settings = Settings(upload_dir=upload_dir)

    with pytest.raises(HTTPException) as exc_info:
        _resolve_staged_path(str(upload_dir / ".." / "secret.csv"), settings)
    assert exc_info.value.status_code == 400
