"""The session narrative: a time-segmented, thematic account of a whole sitting.

This is the automatic Sitzungsbericht from `docs/session-narrative-design.md` §4.3. The method
*requires* the operator to write one, and specifies what belongs in it: every LP change, every
deflection, and what was worked. Most of that bookkeeping is derivable.

The design rule that matters most: **the LLM never chooses a timestamp.** Section boundaries come
from the BK3 protocol cues actually spoken (`services/protocol.py`), or from fixed windows when
there is no usable transcript. Charge levels come from the conditioned signal. Phenomenon counts
come from the detectors. The model is given a bounded excerpt and asked only to say what is in it.

That distinction is the whole point. A model asked to segment a transcript by theme will happily
produce plausible times that are off by minutes, and a report whose timestamps do not line up
with the trace is worse than no report — the operator would seek to them and find nothing.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from ..core.config import Settings
from .protocol import Segment, Utterance, content_words
from .summary import summarize_section

logger = logging.getLogger(__name__)

# Sections shorter than this are folded into their neighbour: a 20-second fragment gets a heading
# in the report and says nothing.
MIN_SECTION_SEC = 45.0
# When there is no protocol structure to segment by, fall back to fixed windows. Long enough to
# hold a theme, short enough that a heading still locates something.
FALLBACK_WINDOW_SEC = 300.0
# Below this a section has nothing to summarise and is reported as a quiet stretch instead.
MIN_WORDS_FOR_PROSE = 12

# Clock-like tokens the model may have invented: "4:07", "um 12:30", "Minute 14", "bei 3 Minuten".
_INVENTED_TIME_RE = re.compile(
    r"\b\d{1,2}:\d{2}\b|\bMinute\s+\d+|\b\d+\s*Minuten\b", re.IGNORECASE
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def strip_invented_times(text: str) -> str:
    """Drop any sentence containing a clock reference the model made up.

    The prompt forbids this and the model mostly complies, but not always: a real run produced
    "Die Sitzung endet um 4:07" for a section ending at 53:55. Section times are decided by the
    protocol parse and the signal, so a time inside the prose can only be invented — and one
    wrong number discredits the twelve correct headings around it.

    Dropping the whole sentence rather than the token keeps the text readable; a sentence with a
    hole in it reads as a bug.
    """
    if not text:
        return text
    kept = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if not _INVENTED_TIME_RE.search(s)]
    cleaned = " ".join(kept).strip()
    if cleaned != text.strip():
        logger.info("Removed an invented time reference from a narrative section")
    return cleaned


@dataclass
class NarrativeSection:
    start_sec: float
    end_sec: float
    label: str
    """Structural label from the protocol parse (e.g. "FRR 3"), or a time range."""
    procedure: str | None
    title: str
    summary: str
    highlights: list[str] = field(default_factory=list)
    lp_start: float | None = None
    lp_end: float | None = None
    lp_min: float | None = None
    lp_max: float | None = None
    word_count: int = 0
    phenomena_counts: dict[str, int] = field(default_factory=dict)

    @property
    def lp_delta(self) -> float | None:
        if self.lp_start is None or self.lp_end is None:
            return None
        return self.lp_end - self.lp_start

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "label": self.label,
            "procedure": self.procedure,
            "title": self.title,
            "summary": self.summary,
            "highlights": self.highlights,
            "lp_start": self.lp_start,
            "lp_end": self.lp_end,
            "lp_min": self.lp_min,
            "lp_max": self.lp_max,
            "lp_delta": self.lp_delta,
            "word_count": self.word_count,
            "phenomena_counts": self.phenomena_counts,
        }


def format_clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _section_bounds(
    segments: Sequence[Segment], duration_sec: float
) -> list[tuple[float, float, str, str | None]]:
    """(start, end, label, procedure) for each section, from the protocol parse where possible."""
    leaves: list[tuple[float, float, str, str | None]] = []
    for segment in segments:
        children = segment.children or []
        if children:
            for child in children:
                leaves.append((child.start, child.end, child.label, child.procedure.value))
        else:
            leaves.append((segment.start, segment.end, segment.label, segment.procedure.value))

    if not leaves:
        # No protocol structure — fixed windows still give honest, checkable anchors.
        bounds = []
        start = 0.0
        while start < duration_sec:
            end = min(start + FALLBACK_WINDOW_SEC, duration_sec)
            bounds.append((start, end, f"{format_clock(start)}–{format_clock(end)}", None))
            start = end
        return bounds

    leaves.sort(key=lambda item: item[0])

    # An opening stretch before the first cue is real session time (settling, the interview) and
    # would otherwise vanish from the report entirely.
    if leaves[0][0] > MIN_SECTION_SEC:
        leaves.insert(0, (0.0, leaves[0][0], "Einstieg", None))
    if duration_sec - leaves[-1][1] > MIN_SECTION_SEC:
        leaves.append((leaves[-1][1], duration_sec, "Abschluss", None))

    merged: list[tuple[float, float, str, str | None]] = []
    for bound in leaves:
        if merged and bound[1] - bound[0] < MIN_SECTION_SEC:
            previous = merged[-1]
            merged[-1] = (previous[0], bound[1], previous[2], previous[3])
        else:
            merged.append(bound)
    return merged


def _signal_window(
    time_sec: np.ndarray, lp: np.ndarray, start: float, end: float
) -> tuple[float | None, float | None, float | None, float | None]:
    low, high = np.searchsorted(time_sec, [start, end], side="left")
    high = min(max(high, low + 1), lp.size)
    if low >= lp.size or high <= low:
        return None, None, None, None
    window = lp[low:high]
    return float(window[0]), float(window[-1]), float(window.min()), float(window.max())


async def build_narrative(
    utterances: Sequence[Utterance],
    segments: Sequence[Segment],
    phenomena: Sequence[dict[str, Any]],
    time_sec: np.ndarray,
    lp: np.ndarray,
    duration_sec: float,
    settings: Settings,
) -> list[NarrativeSection]:
    """One narrative section per protocol segment, summarised concurrently."""
    bounds = _section_bounds(segments, duration_sec)
    if not bounds:
        return []

    async def build(bound: tuple[float, float, str, str | None]) -> NarrativeSection:
        start, end, label, procedure = bound
        words = content_words(utterances, start, end)
        excerpt = " ".join(w.text for w in words)

        counts: dict[str, int] = {}
        for phenomenon in phenomena:
            if start <= phenomenon["t_start"] < end:
                counts[phenomenon["kind"]] = counts.get(phenomenon["kind"], 0) + 1

        lp_start, lp_end, lp_min, lp_max = _signal_window(time_sec, lp, start, end)

        title, summary, highlights = label, "", []
        if len(words) >= MIN_WORDS_FOR_PROSE and settings.summarizer_enabled:
            result = await summarize_section(
                excerpt,
                settings=settings,
                resolved_model=settings.resolved_ollama_model,
                procedure=procedure,
            )
            if result:
                title = strip_invented_times(result.get("title") or "") or label
                summary = strip_invented_times(result.get("summary") or "")
                highlights = [
                    cleaned
                    for cleaned in (strip_invented_times(h) for h in (result.get("highlights") or []))
                    if cleaned
                ][:6]
        elif not words:
            # Silence is a real observation in a solo session, not a gap to apologise for.
            summary = "Kein gesprochener Inhalt in diesem Abschnitt."

        return NarrativeSection(
            start_sec=start,
            end_sec=end,
            label=label,
            procedure=procedure,
            title=title,
            summary=summary,
            highlights=highlights,
            lp_start=lp_start,
            lp_end=lp_end,
            lp_min=lp_min,
            lp_max=lp_max,
            word_count=len(words),
            phenomena_counts=counts,
        )

    sections = await asyncio.gather(*[build(bound) for bound in bounds])
    logger.info("Narrative: %d sections over %.1f min", len(sections), duration_sec / 60)
    return list(sections)


def to_markdown(sections: Sequence[NarrativeSection], topic: str | None = None) -> str:
    """The report as markdown, for export.

    Deliberately close to what an operator would write by hand: time range, heading, prose,
    highlights, and the charge level at the boundaries.
    """
    lines: list[str] = ["# Sitzung nach Zeit- und Themenabschnitten", ""]
    if topic:
        lines += [f"**Thema:** {topic}", ""]

    for section in sections:
        span = f"{format_clock(section.start_sec)}–{format_clock(section.end_sec)}"
        lines.append(f"## {span} | {section.title}")
        lines.append("")
        if section.summary:
            lines.append(section.summary)
            lines.append("")
        for highlight in section.highlights:
            lines.append(f"* {highlight}")
        if section.highlights:
            lines.append("")

        facts: list[str] = []
        if section.lp_start is not None and section.lp_end is not None:
            facts.append(f"Ladungspegel {section.lp_start:.2f} → {section.lp_end:.2f}")
        if section.phenomena_counts:
            facts.append(
                ", ".join(f"{count}× {kind}" for kind, count in sorted(section.phenomena_counts.items()))
            )
        if facts:
            lines.append(f"*{' · '.join(facts)}*")
            lines.append("")
        lines.append("---")
        lines.append("")

    if sections:
        first, last = sections[0], sections[-1]
        if first.lp_start is not None and last.lp_end is not None:
            lines.append(
                f"Ladungspegel über die Sitzung: {first.lp_start:.2f} → {last.lp_end:.2f} "
                f"({last.lp_end - first.lp_start:+.2f})."
            )
    lines.append("")
    lines.append(
        "Die Zeitangaben stammen aus den Protokoll-Anweisungen im Transkript und aus dem "
        "gemessenen Signal, nicht aus einer Schätzung."
    )
    return "\n".join(lines)
