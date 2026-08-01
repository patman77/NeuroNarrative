"""The labelling path and the evaluation it unblocks."""

from __future__ import annotations

import json

import pytest

from app.services.labels import Label, LabelStore, missed_id, recording_id, training_rows
from app.services.phenomena.evaluate import evaluate


def detection(pid: str, kind: str, t_start: float, **extra) -> dict:
    return {
        "id": pid,
        "kind": kind,
        "t_start": t_start,
        "t_end": t_start + 2.0,
        "amplitude_lp": -0.2,
        "amplitude_a": 3.0,
        "confidence": 1.0,
        "stimulus_locked": True,
        "detector": "test",
        "evidence": {"rise_time_sec": 2.0, "recovery_fraction": 0.1, "text": "not a number"},
        **extra,
    }


# --- recording identity -----------------------------------------------------------------------


def test_recording_id_is_content_derived(tmp_path):
    """Labels must survive the file being copied and re-staged under a different name."""
    first = tmp_path / "session.csv"
    first.write_text("time,resistance\n0,5.0\n1,5.1\n")
    second = tmp_path / "renamed-after-restaging.csv"
    second.write_text(first.read_text())

    assert recording_id(first) == recording_id(second)


def test_different_recordings_get_different_ids(tmp_path):
    first = tmp_path / "a.csv"
    first.write_text("time,resistance\n0,5.0\n")
    second = tmp_path / "b.csv"
    second.write_text("time,resistance\n0,5.1\n")

    assert recording_id(first) != recording_id(second)


# --- the store --------------------------------------------------------------------------------


def test_a_label_round_trips(tmp_path):
    store = LabelStore(tmp_path)
    store.upsert("rec1", Label(phenomenon_id="be-abc", verdict="confirmed"))

    labels = store.load("rec1")

    assert len(labels) == 1
    assert labels[0].phenomenon_id == "be-abc"
    assert labels[0].verdict == "confirmed"


def test_relabelling_replaces_rather_than_duplicates(tmp_path):
    store = LabelStore(tmp_path)
    store.upsert("rec1", Label(phenomenon_id="be-abc", verdict="confirmed"))
    store.upsert("rec1", Label(phenomenon_id="be-abc", verdict="rejected"))

    labels = store.load("rec1")

    assert len(labels) == 1
    assert labels[0].verdict == "rejected"


def test_labels_are_isolated_per_recording(tmp_path):
    store = LabelStore(tmp_path)
    store.upsert("rec1", Label(phenomenon_id="a-1", verdict="confirmed"))
    store.upsert("rec2", Label(phenomenon_id="a-2", verdict="rejected"))

    assert [l.phenomenon_id for l in store.load("rec1")] == ["a-1"]
    assert [l.phenomenon_id for l in store.load("rec2")] == ["a-2"]


def test_deleting_leaves_the_rest(tmp_path):
    store = LabelStore(tmp_path)
    store.upsert("rec1", Label(phenomenon_id="a-1", verdict="confirmed"))
    store.upsert("rec1", Label(phenomenon_id="a-2", verdict="confirmed"))

    remaining = store.delete("rec1", "a-1")

    assert [l.phenomenon_id for l in remaining] == ["a-2"]


def test_a_corrupt_file_does_not_take_the_app_down(tmp_path):
    """Degrade to "no labels" rather than failing the whole analysis view."""
    store = LabelStore(tmp_path)
    store.upsert("rec1", Label(phenomenon_id="a-1", verdict="confirmed"))
    (tmp_path / "rec1.json").write_text("{ this is not json")

    assert store.load("rec1") == []


def test_writes_are_atomic(tmp_path):
    """A truncated write would destroy hours of annotation, so no partial files may remain."""
    store = LabelStore(tmp_path)
    store.upsert("rec1", Label(phenomenon_id="a-1", verdict="confirmed"))

    assert list(tmp_path.glob("*.tmp")) == []
    assert json.loads((tmp_path / "rec1.json").read_text())["labels"]


def test_summary_counts_by_verdict(tmp_path):
    store = LabelStore(tmp_path)
    store.upsert("rec1", Label(phenomenon_id="a-1", verdict="confirmed"))
    store.upsert("rec1", Label(phenomenon_id="a-2", verdict="confirmed"))
    store.upsert("rec1", Label(phenomenon_id="a-3", verdict="rejected"))

    assert store.summary("rec1")["by_verdict"] == {"confirmed": 2, "rejected": 1}


def test_missed_ids_are_stable():
    assert missed_id(123.456, "BE") == missed_id(123.456, "BE")
    assert missed_id(123.456, "BE") != missed_id(123.456, "A")


# --- evaluation -------------------------------------------------------------------------------


def test_confirmations_and_rejections_give_precision():
    phenomena = [detection("be-1", "BE", 10.0), detection("be-2", "BE", 20.0)]
    labels = [
        Label(phenomenon_id="be-1", verdict="confirmed"),
        Label(phenomenon_id="be-2", verdict="rejected"),
    ]

    result = evaluate(phenomena, labels)

    assert result.by_kind["BE"].precision == pytest.approx(0.5)


def test_recall_is_not_claimed_without_missed_labels():
    """Confirmations alone can only measure precision; a recall figure would be 1.0 by
    construction and meaningless."""
    phenomena = [detection("be-1", "BE", 10.0)]
    labels = [Label(phenomenon_id="be-1", verdict="confirmed")]

    result = evaluate(phenomena, labels)

    assert not result.has_recall_evidence
    assert "Recall is not measurable" in result.as_dict()["caveat"]


def test_a_missed_phenomenon_lowers_recall():
    phenomena = [detection("be-1", "BE", 10.0)]
    labels = [
        Label(phenomenon_id="be-1", verdict="confirmed"),
        Label(phenomenon_id="missed-be-500.00", verdict="missed", kind="BE", t_start=500.0),
    ]

    result = evaluate(phenomena, labels)

    assert result.has_recall_evidence
    assert result.by_kind["BE"].recall == pytest.approx(0.5)


def test_a_missed_label_the_detector_actually_caught_is_not_counted_against_it():
    """The operator may mark a miss that was detected under a different id."""
    phenomena = [detection("be-1", "BE", 100.0)]
    labels = [Label(phenomenon_id="missed-be-100.50", verdict="missed", kind="BE", t_start=100.5)]

    result = evaluate(phenomena, labels, tolerance_sec=2.0)

    assert result.by_kind["BE"].false_negatives == 0


def test_the_tolerance_window_is_respected():
    phenomena = [detection("be-1", "BE", 100.0)]
    labels = [Label(phenomenon_id="missed-be-110.00", verdict="missed", kind="BE", t_start=110.0)]

    result = evaluate(phenomena, labels, tolerance_sec=2.0)

    assert result.by_kind["BE"].false_negatives == 1


def test_reclassification_penalises_both_kinds():
    """A BE that was really a KB is a false positive for BE and a miss for KB."""
    phenomena = [detection("be-1", "BE", 10.0)]
    labels = [Label(phenomenon_id="be-1", verdict="reclassified", kind="KB")]

    result = evaluate(phenomena, labels)

    assert result.by_kind["BE"].false_positives == 1
    assert result.by_kind["KB"].false_negatives == 1


def test_unreviewed_detections_are_unknown_not_wrong():
    phenomena = [detection("be-1", "BE", 10.0), detection("be-2", "BE", 20.0)]
    labels = [Label(phenomenon_id="be-1", verdict="confirmed")]

    result = evaluate(phenomena, labels)

    assert result.unlabelled == 1
    assert result.by_kind["BE"].false_positives == 0


def test_kinds_are_scored_separately():
    """A pooled figure would hide a collapsed BE detector behind a healthy T count."""
    phenomena = [detection("be-1", "BE", 10.0), detection("t-1", "T", 20.0)]
    labels = [
        Label(phenomenon_id="be-1", verdict="rejected"),
        Label(phenomenon_id="t-1", verdict="confirmed"),
    ]

    result = evaluate(phenomena, labels)

    assert result.by_kind["BE"].precision == pytest.approx(0.0)
    assert result.by_kind["T"].precision == pytest.approx(1.0)


# --- training export --------------------------------------------------------------------------


def test_training_rows_flatten_numeric_evidence():
    rows = training_rows(
        [Label(phenomenon_id="be-1", verdict="confirmed")], [detection("be-1", "BE", 10.0)]
    )

    assert rows[0]["evidence_rise_time_sec"] == 2.0
    # Non-numeric evidence is not a feature and must not end up in the matrix.
    assert "evidence_text" not in rows[0]


def test_training_rows_keep_missed_labels_as_undetected():
    """They are the recall half; dropping them makes any measured recall meaningless."""
    rows = training_rows(
        [Label(phenomenon_id="missed-be-50.00", verdict="missed", kind="BE", t_start=50.0)], []
    )

    assert rows[0]["detected"] is False
    assert rows[0]["true_kind"] == "BE"
    assert rows[0]["t_start"] == 50.0
