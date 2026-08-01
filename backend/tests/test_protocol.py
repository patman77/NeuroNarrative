"""BK3 protocol parsing, artefact masking, calibration and the cross-modal layer."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.phenomena.calibration import Calibration, relative_band
from app.services.phenomena.detectors.artefact import compute_artefact_mask
from app.services.phenomena.detectors.stimulus import (
    detect_kein_ausschlag,
    detect_kvz,
)
from app.services.phenomena.fusion import detect_phenomena
from app.services.phenomena.primitives import compute_primitives
from app.services.phenomena.schema import PhenomenonKind
from app.services.protocol import (
    Procedure,
    content_words,
    match_cue,
    parse_session,
    segment_for,
    segment_turns,
)
from app.services.transcript import TranscribedWord

RATE = 50.0


def speech(text: str, start: float, step: float = 0.5) -> list[TranscribedWord]:
    return [
        TranscribedWord(text=token, start=start + i * step, end=start + i * step + 0.3, confidence=0.9)
        for i, token in enumerate(text.split())
    ]


def quiet(duration: float, level: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(0.0, duration, 1.0 / RATE)
    rng = np.random.default_rng(1)
    return t, np.full(t.size, level) + rng.normal(0.0, 2e-4, t.size)


# --- cue inventory ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase, procedure",
    [
        ("ruf dir ein erlebnis zurueck als du ausgesperrt warst", Procedure.FRR),
        ("ruf dir das frueheste erlebnis zurueck an das du dich erinnern kannst", Procedure.KRR),
        ("gibt es ein geschehnis als ich das gefuehlt habe", Procedure.FRR),
        ("was siehst du genau", Procedure.EZM),
        ("geh zum fruehesten einstieg in das erlebnis", Procedure.EZM),
    ],
)
def test_known_cues_match_their_procedure(phrase, procedure):
    cue = match_cue(phrase.split())
    assert cue is not None and cue.procedure is procedure


@pytest.mark.parametrize(
    "phrase",
    [
        "ruf mich spaeter bitte nochmal kurz an",
        "danke das war sehr hilfreich",
        "ich weiss es wirklich nicht mehr genau",
    ],
)
def test_ordinary_speech_is_not_a_cue(phrase):
    """"Danke" in particular: it is Bestätigung, not an instruction, and is in no manual."""
    assert match_cue(phrase.split()) is None


def test_umlauts_match_either_spelling():
    assert match_cue("ruf dir ein Erlebnis zurück".split()) is not None
    assert match_cue("ruf dir ein Erlebnis zurueck".split()) is not None


# --- turn segmentation and the tree -----------------------------------------------------------


def test_turns_split_on_pauses_and_cues_are_tagged():
    words = speech("ruf dir ein erlebnis zurueck", 10.0) + speech("ich war im garten", 40.0)

    utterances = segment_turns(words)

    assert len(utterances) == 2
    assert utterances[0].is_instruction
    assert not utterances[1].is_instruction


def test_content_words_exclude_the_instruction():
    words = speech("ruf dir ein erlebnis zurueck", 10.0) + speech("ich war im garten", 40.0)
    utterances = segment_turns(words)

    text = " ".join(w.text for w in content_words(utterances, 0.0, 100.0))

    assert "garten" in text
    assert "ruf" not in text


def test_a_procedure_runs_until_the_next_one_opens():
    words = (
        speech("ruf dir ein erlebnis zurueck", 10.0)
        + speech("ich war im garten und es regnete", 40.0)
        + speech("was siehst du genau", 200.0)
        + speech("einen baum vor dem fenster", 230.0)
    )

    segments = parse_session(segment_turns(words), duration_sec=400.0)

    assert [s.procedure for s in segments] == [Procedure.FRR, Procedure.EZM]
    assert segments[0].end == pytest.approx(200.0, abs=1.0)
    assert segments[1].end == pytest.approx(400.0)


def test_repeated_openers_stay_one_procedure_with_children():
    words = (
        speech("ruf dir ein erlebnis zurueck", 10.0)
        + speech("ich war im garten", 40.0)
        + speech("ruf dir ein weiteres erlebnis zurueck", 100.0)
        + speech("ich war am see", 130.0)
    )

    segments = parse_session(segment_turns(words), duration_sec=300.0)

    assert len(segments) == 1
    assert len(segments[0].children) == 2


def test_segment_lookup_finds_the_innermost_node():
    words = (
        speech("ruf dir ein erlebnis zurueck", 10.0)
        + speech("ich war im garten", 40.0)
        + speech("ruf dir ein weiteres erlebnis zurueck", 100.0)
    )
    segments = parse_session(segment_turns(words), duration_sec=300.0)

    node = segment_for(segments, 50.0)

    assert node is not None and node.children == []


# --- artefacts --------------------------------------------------------------------------------


def test_a_rail_excursion_is_masked():
    t, lp = quiet(120.0)
    lp[(t >= 40) & (t < 45)] = 6.45  # pinned at the top of the scale

    mask = compute_artefact_mask(t, lp, noise_lp=3e-4)

    assert mask.mask[(t >= 41) & (t < 44)].all()
    assert any("rail" in reason for _, _, reason in mask.spans)


def test_movement_far_faster_than_the_session_is_masked():
    """The real case: Solo46 has a 1.57 LP/s excursion where the session never exceeds 0.067."""
    t, lp = quiet(120.0)
    spike = (t >= 60) & (t < 60.2)
    lp[spike] -= 0.35

    mask = compute_artefact_mask(t, lp, noise_lp=3e-4)

    assert mask.mask[(t >= 60) & (t < 60.2)].any()
    assert any("movement" in reason for _, _, reason in mask.spans)


def test_a_physiological_deflection_is_not_masked_as_movement():
    """A strong 0.3 LP response over two seconds is real, and must survive."""
    t, lp = quiet(200.0)
    fall = (t >= 100) & (t < 102)
    lp[fall] -= 0.3 * (t[fall] - 100) / 2
    lp[t >= 102] -= 0.3

    mask = compute_artefact_mask(t, lp, noise_lp=3e-4)

    assert not mask.mask[(t >= 100) & (t < 103)].any()


def test_a_quiet_start_is_not_masked_as_settling():
    """Regression: the settle scan once ran to the last disturbance in the first two minutes,
    so a deflection at 100 s caused half the recording to be masked."""
    t, lp = quiet(300.0)
    fall = (t >= 100) & (t < 102)
    lp[fall] -= 0.3 * (t[fall] - 100) / 2
    lp[t >= 102] -= 0.3

    mask = compute_artefact_mask(t, lp, noise_lp=3e-4)

    assert mask.masked_fraction < 0.05


def test_movement_is_reported_as_a_koerperbewegung():
    """The manual requires a KB to be marked in the protocol, not silently dropped."""
    t, lp = quiet(200.0)
    lp[(t >= 100) & (t < 100.2)] -= 0.35

    result = detect_phenomena(t, lp)

    assert any(p.kind is PhenomenonKind.KOERPERBEWEGUNG for p in result.phenomena)


# --- calibration ------------------------------------------------------------------------------


def test_no_zone_is_named_without_an_offset():
    """Naming one anyway reports an entire solo session as Kampfzone."""
    calibration = Calibration(a_unit_lp=0.05, a_unit_calibrated=False, lp_offset=None)

    assert calibration.zone(5.5) is None
    assert not calibration.zones_available


@pytest.mark.parametrize(
    "corrected, expected",
    [(1.5, "Opferzone"), (2.5, "Normalzone"), (3.2, "Alarmzone"), (4.0, "Kampfzone")],
)
def test_zones_follow_the_manual_when_an_offset_is_given(corrected, expected):
    calibration = Calibration(a_unit_lp=0.05, a_unit_calibrated=False, lp_offset=1.0)

    assert calibration.zone(corrected + 1.0) == expected


def test_an_operator_supplied_a_unit_is_marked_calibrated():
    t, lp = quiet(200.0)

    result = detect_phenomena(t, lp, a_unit_lp=0.04)

    assert result.metrics.a_unit_calibrated
    assert result.metrics.a_unit_lp == pytest.approx(0.04)


def test_relative_band_describes_level_without_claiming_a_zone():
    assert "upper" in relative_band(5.9, 4.4, 6.0)
    assert "lower" in relative_band(4.5, 4.4, 6.0)


# --- stimulus locking, X, KVZ -----------------------------------------------------------------


def test_a_deflection_after_an_utterance_is_locked_to_it():
    t, lp = quiet(200.0)
    fall = (t >= 102) & (t < 104)
    lp[fall] -= 0.3 * (t[fall] - 102) / 2
    lp[t >= 104] -= 0.3

    utterances = segment_turns(speech("ruf dir ein erlebnis zurueck", 96.0))
    result = detect_phenomena(t, lp, utterances=utterances)

    locked = [p for p in result.phenomena if p.stimulus_locked]
    assert locked, "a fall two seconds after a question is the textbook locked response"
    assert locked[0].utterance_id == utterances[0].id


def test_an_isolated_deflection_is_flagged_unlocked_but_kept():
    """Coverage matters: in solo, unlocked usually means the operator was working quietly."""
    t, lp = quiet(300.0)
    fall = (t >= 200) & (t < 202)
    lp[fall] -= 0.3 * (t[fall] - 200) / 2
    lp[t >= 202] -= 0.3

    utterances = segment_turns(speech("ruf dir ein erlebnis zurueck", 10.0))
    result = detect_phenomena(t, lp, utterances=utterances)

    unlocked = [p for p in result.phenomena if p.stimulus_locked is False]
    assert unlocked
    assert all(p.confidence < 1.0 for p in unlocked)


def test_an_instruction_with_no_response_yields_x():
    t, lp = quiet(200.0)  # nothing happens at all
    utterances = segment_turns(speech("ruf dir ein erlebnis zurueck", 100.0))

    found = detect_kein_ausschlag([], utterances)

    assert len(found) == 1
    assert found[0].kind is PhenomenonKind.KEIN_AUSSCHLAG


def test_ordinary_speech_does_not_yield_x():
    """The method expects a response to a question, not to every remark."""
    utterances = segment_turns(speech("ich war damals im garten", 100.0))

    assert detect_kein_ausschlag([], utterances) == []


def test_movement_during_silence_is_kvz():
    t, lp = quiet(300.0)
    ramp = (t >= 60) & (t < 90)
    lp[ramp] -= 0.3 * (t[ramp] - 60) / 30
    lp[t >= 90] -= 0.3

    utterances = segment_turns(speech("ich war im garten", 40.0) + speech("und dann kam sie", 150.0))
    primitives = compute_primitives(t, lp)

    found = detect_kvz(primitives, utterances, a_unit_lp=0.05)

    assert found and found[0].kind is PhenomenonKind.KVZ


def test_a_short_pause_is_not_kvz():
    t, lp = quiet(200.0)
    utterances = segment_turns(speech("ich war im garten", 40.0) + speech("und dann", 45.0))
    primitives = compute_primitives(t, lp)

    assert detect_kvz(primitives, utterances, a_unit_lp=0.05) == []


def test_without_a_transcript_locking_stays_unknown():
    """None means "we do not know", which is different from "not locked"."""
    t, lp = quiet(200.0)
    lp[t >= 100] -= 0.3

    result = detect_phenomena(t, lp)

    assert all(p.stimulus_locked is None for p in result.phenomena)
