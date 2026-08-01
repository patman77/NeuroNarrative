"""Score detections against hand-made labels.

This is the first thing in the project that can say whether the detector is any *good*, as
opposed to whether it is self-consistent. Everything reported up to now — 115 A, 34 BE, and so
on — is a count, not an accuracy.

Metric choices follow `docs/phenomena-detection-design.md` §10:

- **Per-kind precision/recall/F1**, because the kinds fail differently and a pooled number would
  hide a BE detector that has collapsed behind a large healthy `T` count.
- **Onset tolerance.** The SCR literature conventionally matches within ±1 s; ±2 s is defensible
  here given ASR timing slop and the 0.5 s smoothing window, so it is the default and explicit.
- **Recall needs `missed` labels.** Confirmations alone can only ever measure precision. A recall
  figure computed without them would be 1.0 by construction, which is why `has_recall_evidence`
  is reported alongside and the caller is expected to say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..labels import Label

DEFAULT_TOLERANCE_SEC = 2.0


@dataclass
class KindScore:
    kind: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float | None:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


@dataclass
class Evaluation:
    by_kind: dict[str, KindScore] = field(default_factory=dict)
    labelled: int = 0
    unlabelled: int = 0
    """Detections with no verdict either way. These are *not* counted as errors — an unreviewed
    detection is unknown, not wrong."""
    has_recall_evidence: bool = False
    tolerance_sec: float = DEFAULT_TOLERANCE_SEC

    def as_dict(self) -> dict[str, Any]:
        return {
            "by_kind": {k: v.as_dict() for k, v in sorted(self.by_kind.items())},
            "labelled": self.labelled,
            "unlabelled": self.unlabelled,
            "has_recall_evidence": self.has_recall_evidence,
            "tolerance_sec": self.tolerance_sec,
            "caveat": (
                "Recall is not measurable without 'missed' labels."
                if not self.has_recall_evidence
                else ""
            ),
        }


def evaluate(
    phenomena: list[dict[str, Any]],
    labels: list[Label],
    tolerance_sec: float = DEFAULT_TOLERANCE_SEC,
) -> Evaluation:
    """Precision and recall per phenomenon kind, from whatever labels exist so far."""
    result = Evaluation(tolerance_sec=tolerance_sec)
    by_id = {p["id"]: p for p in phenomena}
    verdicts = {label.phenomenon_id: label for label in labels}

    def score_for(kind: str) -> KindScore:
        return result.by_kind.setdefault(kind, KindScore(kind=kind))

    # Seed an entry for every kind that appears anywhere, so a kind scoring a clean zero is
    # reported as such rather than being absent from the result.
    for kind in {p["kind"] for p in phenomena} | {l.kind for l in labels if l.kind}:
        score_for(kind)

    for detection in phenomena:
        label = verdicts.get(detection["id"])
        if label is None:
            result.unlabelled += 1
            continue
        result.labelled += 1

        predicted = detection["kind"]
        if label.verdict == "confirmed":
            score_for(predicted).true_positives += 1
        elif label.verdict == "rejected":
            score_for(predicted).false_positives += 1
        elif label.verdict == "reclassified" and label.kind:
            # Wrong on both counts: a false positive for what was claimed, and a miss for what
            # it actually was.
            score_for(predicted).false_positives += 1
            score_for(label.kind).false_negatives += 1

    for label in labels:
        if label.verdict != "missed" or not label.kind:
            continue
        result.has_recall_evidence = True
        result.labelled += 1
        # Credit the detector if something of the right kind landed within tolerance after all;
        # the operator may have marked a miss the detector had actually caught under another id.
        if not _matched(by_id.values(), label, tolerance_sec):
            score_for(label.kind).false_negatives += 1

    return result


def _matched(phenomena: Any, label: Label, tolerance_sec: float) -> bool:
    if label.t_start is None:
        return False
    return any(
        p["kind"] == label.kind and abs(p["t_start"] - label.t_start) <= tolerance_sec
        for p in phenomena
    )
