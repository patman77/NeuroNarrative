"""Hand-made phenomenon labels — the thing everything downstream is blocked on.

There is no ground truth for this corpus. Nothing in `docs/phenomena-detection-design.md`
past stage 4 can be built or even measured without it: no precision, no recall, no
BE-vs-KB classifier, no evaluation of any threshold. §7 lists three ways to get labels and
this is the cheapest — make the app the annotation tool, since the operator is already
looking at the trace with the audio aligned.

Design constraints that matter:

- **Labels outlive detections.** They key on the content-derived `Phenomenon.id`, which is
  stable across re-parses, so re-running an analysis does not orphan a verdict.
- **Labels are user data, not cache.** They live under `user_data_path`, not the upload cache
  that gets pruned after 24 hours.
- **A missed phenomenon is a label too.** Detection recall cannot be measured from confirmations
  alone; the operator must be able to mark something the detector never proposed.
- **Never lose a label to a write error.** Writes go through a temporary file and an atomic
  rename, because a truncated JSON file would silently destroy hours of annotation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

Verdict = Literal["confirmed", "rejected", "reclassified", "missed"]

# One lock for the whole store. Annotation is a human-speed activity, so contention is
# irrelevant, and per-file locking would be more code for no benefit.
_LOCK = threading.Lock()

SCHEMA_VERSION = 1


def recording_id(csv_path: Path) -> str:
    """Content hash of the GSR export.

    Content rather than filename: the same recording gets copied, renamed and re-staged into
    the upload cache under a fresh name every time it is analysed, and a label set that did not
    survive that would be useless.
    """
    digest = hashlib.sha256()
    with open(csv_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


@dataclass
class Label:
    phenomenon_id: str
    """The detection this verdict is about. For `missed`, a synthetic id derived from the time."""
    verdict: Verdict
    kind: str | None = None
    """What it actually is. Required for `reclassified` and `missed`, ignored otherwise."""
    t_start: float | None = None
    """Only for `missed`, where there is no detection to take a time from."""
    note: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def missed_id(t_start: float, kind: str) -> str:
    """Stable id for a phenomenon the detector never proposed."""
    return f"missed-{kind.lower()}-{t_start:.2f}"


class LabelStore:
    """One JSON file per recording, under `settings.label_dir`."""

    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, recording: str) -> Path:
        # The id is a hex digest, so it cannot escape the directory, but be explicit anyway.
        safe = "".join(c for c in recording if c.isalnum())[:64]
        if not safe:
            raise ValueError("invalid recording id")
        return self.directory / f"{safe}.json"

    def load(self, recording: str) -> list[Label]:
        path = self._path(recording)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read labels for %s: %s", recording, exc)
            return []
        return [Label(**entry) for entry in payload.get("labels", [])]

    def save(self, recording: str, labels: list[Label]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(recording)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "recording_id": recording,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "labels": [label.as_dict() for label in labels],
        }
        # Atomic replace: a partial write here would destroy the annotation work outright.
        handle = tempfile.NamedTemporaryFile(
            "w", dir=self.directory, delete=False, encoding="utf-8", suffix=".tmp"
        )
        try:
            with handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise

    def upsert(self, recording: str, label: Label) -> list[Label]:
        with _LOCK:
            labels = [l for l in self.load(recording) if l.phenomenon_id != label.phenomenon_id]
            labels.append(label)
            labels.sort(key=lambda l: (l.t_start if l.t_start is not None else 0.0, l.phenomenon_id))
            self.save(recording, labels)
            return labels

    def delete(self, recording: str, phenomenon_id: str) -> list[Label]:
        with _LOCK:
            labels = [l for l in self.load(recording) if l.phenomenon_id != phenomenon_id]
            self.save(recording, labels)
            return labels

    def summary(self, recording: str) -> dict[str, Any]:
        labels = self.load(recording)
        counts: dict[str, int] = {}
        for label in labels:
            counts[label.verdict] = counts.get(label.verdict, 0) + 1
        return {"recording_id": recording, "total": len(labels), "by_verdict": counts}


def training_rows(labels: list[Label], phenomena: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join verdicts onto detections, flattening `evidence` into feature columns.

    This is the export that a classifier is eventually trained on (design §7). `missed` labels
    carry no detection, so they appear with `detected=False` — they are the recall half of the
    picture and dropping them would make any measured recall meaningless.
    """
    by_id = {p["id"]: p for p in phenomena}
    rows: list[dict[str, Any]] = []

    for label in labels:
        detection = by_id.get(label.phenomenon_id)
        row: dict[str, Any] = {
            "phenomenon_id": label.phenomenon_id,
            "verdict": label.verdict,
            "true_kind": label.kind or (detection or {}).get("kind"),
            "detected": detection is not None,
            "note": label.note,
        }
        if detection is not None:
            row.update(
                {
                    "predicted_kind": detection["kind"],
                    "t_start": detection["t_start"],
                    "t_end": detection["t_end"],
                    "amplitude_lp": detection.get("amplitude_lp"),
                    "amplitude_a": detection.get("amplitude_a"),
                    "confidence": detection.get("confidence"),
                    "stimulus_locked": detection.get("stimulus_locked"),
                    "detector": detection.get("detector"),
                }
            )
            for key, value in (detection.get("evidence") or {}).items():
                if isinstance(value, (int, float, bool)) or value is None:
                    row[f"evidence_{key}"] = value
        else:
            row["t_start"] = label.t_start
        rows.append(row)

    return rows
