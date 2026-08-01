"""The session narrative.

The property under test throughout is that **timestamps come from structure, never from the
model**: section boundaries from the BK3 cues actually spoken, charge levels from the signal.
A report whose headings disagree with the trace is worse than no report, because the operator
would seek to them and find nothing there.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from app.core.config import Settings
from app.services.narrative import (
    FALLBACK_WINDOW_SEC,
    build_narrative,
    format_clock,
    to_markdown,
)
from app.services.protocol import parse_session, segment_turns
from app.services.transcript import TranscribedWord

RATE = 50.0


def speech(text: str, start: float, step: float = 0.4) -> list[TranscribedWord]:
    return [
        TranscribedWord(text=token, start=start + i * step, end=start + i * step + 0.3, confidence=0.9)
        for i, token in enumerate(text.split())
    ]


def signal(duration: float, level: float = 5.0, drift: float = 0.0):
    t = np.arange(0.0, duration, 1.0 / RATE)
    return t, level + np.linspace(0.0, drift, t.size)


def run(coro):
    return asyncio.run(coro)


def quiet_settings(**kwargs) -> Settings:
    """Summariser off, so the tests exercise segmentation rather than a language model."""
    return Settings(summarizer_enabled=False, **kwargs)


# --- clock ------------------------------------------------------------------------------------


@pytest.mark.parametrize("seconds, expected", [(0, "00:00"), (61, "01:01"), (3599, "59:59"), (3600, "60:00")])
def test_clock_formatting(seconds, expected):
    assert format_clock(seconds) == expected


# --- segmentation -----------------------------------------------------------------------------


def test_sections_follow_the_spoken_protocol_cues():
    words = (
        speech("ruf dir ein erlebnis zurueck als du ausgesperrt warst", 100.0)
        + speech("ich stand vor der tuer und hatte keinen schluessel dabei", 160.0)
        + speech("was siehst du genau", 600.0)
        + speech("ein bullauge und eine schwere metalltuer mit grossen muttern", 640.0)
    )
    utterances = segment_turns(words)
    segments = parse_session(utterances, duration_sec=1200.0)
    t, lp = signal(1200.0)

    sections = run(
        build_narrative(utterances, segments, [], t, lp, 1200.0, quiet_settings())
    )

    starts = [round(s.start_sec) for s in sections]
    # 100 s and 600 s are where the cues were actually spoken.
    assert 100 in starts
    assert 600 in starts


def test_time_before_the_first_cue_is_not_dropped():
    """Settling and the interview are real session time and must appear in the report."""
    words = speech("ruf dir ein erlebnis zurueck", 300.0) + speech("ich war im garten", 340.0)
    utterances = segment_turns(words)
    segments = parse_session(utterances, duration_sec=900.0)
    t, lp = signal(900.0)

    sections = run(build_narrative(utterances, segments, [], t, lp, 900.0, quiet_settings()))

    assert sections[0].start_sec == pytest.approx(0.0)


def test_without_protocol_cues_it_falls_back_to_fixed_windows():
    """Still honest anchors: a fixed window is a real time range, not an estimate."""
    words = speech("nur normale sprache ohne jede anweisung", 100.0)
    utterances = segment_turns(words)
    t, lp = signal(1200.0)

    sections = run(build_narrative(utterances, [], [], t, lp, 1200.0, quiet_settings()))

    assert len(sections) == pytest.approx(1200.0 / FALLBACK_WINDOW_SEC, abs=1)
    assert sections[0].start_sec == 0.0
    assert sections[-1].end_sec == pytest.approx(1200.0)


def test_sections_tile_the_session_without_gaps_or_overlap():
    words = (
        speech("ruf dir ein erlebnis zurueck", 100.0)
        + speech("ich war im garten", 150.0)
        + speech("ruf dir ein weiteres erlebnis zurueck", 400.0)
        + speech("ich war am see", 450.0)
    )
    utterances = segment_turns(words)
    segments = parse_session(utterances, duration_sec=900.0)
    t, lp = signal(900.0)

    sections = run(build_narrative(utterances, segments, [], t, lp, 900.0, quiet_settings()))

    for previous, following in zip(sections, sections[1:]):
        assert previous.end_sec == pytest.approx(following.start_sec, abs=0.01)
    assert sections[-1].end_sec == pytest.approx(900.0, abs=1.0)


# --- signal association -----------------------------------------------------------------------


def test_charge_levels_come_from_the_signal():
    words = speech("ruf dir ein erlebnis zurueck", 10.0) + speech("ich war im garten", 60.0)
    utterances = segment_turns(words)
    segments = parse_session(utterances, duration_sec=600.0)
    # Falls a clean 1.0 LP across the session.
    t, lp = signal(600.0, level=6.0, drift=-1.0)

    sections = run(build_narrative(utterances, segments, [], t, lp, 600.0, quiet_settings()))

    assert sections[0].lp_start == pytest.approx(6.0, abs=0.05)
    assert sections[-1].lp_end == pytest.approx(5.0, abs=0.05)
    assert sections[-1].lp_delta is not None and sections[-1].lp_delta < 0


def test_phenomena_are_counted_into_the_section_that_contains_them():
    words = (
        speech("ruf dir ein erlebnis zurueck", 100.0)
        + speech("ich war im garten", 140.0)
        + speech("ruf dir ein weiteres erlebnis zurueck", 400.0)
        + speech("ich war am see", 440.0)
    )
    utterances = segment_turns(words)
    segments = parse_session(utterances, duration_sec=800.0)
    t, lp = signal(800.0)
    phenomena = [
        {"id": "be-1", "kind": "BE", "t_start": 150.0},
        {"id": "be-2", "kind": "BE", "t_start": 160.0},
        {"id": "a-1", "kind": "A", "t_start": 500.0},
    ]

    sections = run(build_narrative(utterances, segments, phenomena, t, lp, 800.0, quiet_settings()))

    first = next(s for s in sections if s.start_sec <= 150 < s.end_sec)
    second = next(s for s in sections if s.start_sec <= 500 < s.end_sec)
    assert first.phenomena_counts.get("BE") == 2
    assert second.phenomena_counts.get("A") == 1


def test_only_content_words_are_counted_not_the_instructions():
    words = speech("ruf dir ein erlebnis zurueck", 10.0) + speech("ich war im garten", 60.0)
    utterances = segment_turns(words)
    segments = parse_session(utterances, duration_sec=300.0)
    t, lp = signal(300.0)

    sections = run(build_narrative(utterances, segments, [], t, lp, 300.0, quiet_settings()))

    # Four content words ("ich war im garten"), not the nine including the cue.
    assert sum(s.word_count for s in sections) == 4


def test_a_silent_section_says_so_rather_than_inventing_content():
    words = speech("ruf dir ein erlebnis zurueck", 10.0)
    utterances = segment_turns(words)
    segments = parse_session(utterances, duration_sec=600.0)
    t, lp = signal(600.0)

    sections = run(build_narrative(utterances, segments, [], t, lp, 600.0, quiet_settings()))

    assert any("Kein gesprochener Inhalt" in s.summary for s in sections)


# --- markdown export --------------------------------------------------------------------------


def test_markdown_carries_real_times_and_levels():
    words = speech("ruf dir ein erlebnis zurueck", 120.0) + speech("ich war im garten", 180.0)
    utterances = segment_turns(words)
    segments = parse_session(utterances, duration_sec=600.0)
    t, lp = signal(600.0, level=5.5, drift=-0.5)

    sections = run(build_narrative(utterances, segments, [], t, lp, 600.0, quiet_settings()))
    markdown = to_markdown(sections, topic="Ich bin ausgesperrt")

    assert "## 00:00–02:00" in markdown
    assert "Ich bin ausgesperrt" in markdown
    assert "Ladungspegel" in markdown
    # The provenance note is the point of the whole module.
    assert "nicht aus einer Schätzung" in markdown


def test_markdown_survives_an_empty_session():
    assert "Sitzung nach Zeit" in to_markdown([])


# --- invented timestamps ----------------------------------------------------------------------


def test_invented_clock_times_are_stripped_from_prose():
    """A real run produced "Die Sitzung endet um 4:07" for a section ending at 53:55.

    Section times come from the protocol parse and the signal, so any time in the prose is the
    model's invention — and one wrong number discredits the correct headings around it.
    """
    from app.services.narrative import strip_invented_times

    text = "Der Sprecher beschreibt eine Orientierungsübung. Die Sitzung endet um 4:07."
    assert strip_invented_times(text) == "Der Sprecher beschreibt eine Orientierungsübung."


@pytest.mark.parametrize(
    "text",
    [
        "Das geschieht in Minute 14 der Sitzung.",
        "Nach etwa 3 Minuten wechselt das Thema.",
        "Um 12:30 beginnt der nächste Abschnitt.",
    ],
)
def test_various_time_shapes_are_caught(text):
    from app.services.narrative import strip_invented_times

    assert strip_invented_times(text) == ""


def test_ordinary_numbers_survive():
    """Charge levels, ages and counts are real content and must not be scrubbed."""
    from app.services.narrative import strip_invented_times

    text = "Er war ungefähr 13 Jahre alt. Es waren etwa 6 Jugendliche dabei."
    assert strip_invented_times(text) == text
