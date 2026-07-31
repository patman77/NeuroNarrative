"""In-process job store for long-running analyses.

A 54-minute recording takes minutes to transcribe, which no HTTP request survives: the
webview enforces its own request timeout regardless of what the client sets. So /analyze
starts a job and returns immediately, and the UI polls for stage and progress.

The store is deliberately in-process and non-persistent — this is a single-user local app,
and a restart legitimately discards in-flight work.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

JobState = Literal["queued", "running", "done", "error"]

MAX_JOBS = 32
JOB_TTL_SEC = 3600.0


@dataclass
class Job:
    job_id: str
    status: JobState = "queued"
    stage: str = "queued"
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobStore:
    """Thread-safe: progress callbacks arrive from the worker thread."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(job_id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.job_id] = job
            self._prune_locked()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: JobState | None = None,
        stage: str | None = None,
        progress: float | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if status is not None:
                job.status = status
            if stage is not None:
                job.stage = stage
            if progress is not None:
                job.progress = max(0.0, min(1.0, progress))
            job.updated_at = time.time()

    def finish(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "done"
            job.stage = "done"
            job.progress = 1.0
            job.result = result
            job.updated_at = time.time()

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "error"
            job.stage = "error"
            job.error = error
            job.updated_at = time.time()

    def _prune_locked(self) -> None:
        """Drop finished jobs that are old, then oldest-first if still over the cap."""
        now = time.time()
        stale = [
            jid
            for jid, job in self._jobs.items()
            if job.status in ("done", "error") and now - job.updated_at > JOB_TTL_SEC
        ]
        for jid in stale:
            del self._jobs[jid]

        if len(self._jobs) > MAX_JOBS:
            ordered = sorted(self._jobs.items(), key=lambda kv: kv[1].updated_at)
            for jid, job in ordered[: len(self._jobs) - MAX_JOBS]:
                if job.status in ("done", "error"):
                    del self._jobs[jid]


store = JobStore()
