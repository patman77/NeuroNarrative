from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class TranscribedWord:
    text: str
    start: float | None
    end: float | None
    confidence: float | None = None


def align_transcript(
    words: Iterable["TranscribedWord"],
    event_time: float,
    pre_window: float,
    post_window: float,
    min_confidence: float = 0.5,
) -> List["TranscribedWord"]:
    start = event_time - pre_window
    end = event_time + post_window
    selected: List[TranscribedWord] = []
    for word in words:
        if word.start is None:
            continue
        if word.confidence is not None and word.confidence < min_confidence:
            continue
        if start <= word.start <= end:
            selected.append(word)
    return selected


# The recordings follow a guided-recall protocol with fixed facilitator cues (German):
# an exercise opens with "Ruf dir ein Erlebnis zurück" (any "ruf … zurück" counts),
# "Beschreibe …" drills into a detail, "Was siehst du noch?" asks for another
# clarification pass, "Was ist am deutlichsten?" resolves it, and "Danke" closes the
# exercise. These cues bound the exercise an event belongs to, so they are the natural
# fallback window when the time-based windows around an event hold no speech.

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_NON_LETTER_RE = re.compile(r"[^a-z]")

# Cues that open a nested subsection inside an exercise, tightest scope first.
_SECTION_PHRASES: tuple[tuple[str, ...], ...] = (
    ("beschreibe",),
    ("was", "siehst", "du", "noch"),
    ("was", "ist", "am", "deutlichsten"),
)
# "ruf" must be followed by "zurueck" within this many tokens to count as an opener
# ("Ruf dir ein Erlebnis zurück" spans five).
_BEGIN_MAX_SPAN = 6


def _norm(token: str) -> str:
    """Lowercased letters only, umlauts folded so 'zurück' and 'zurueck' both match."""
    return _NON_LETTER_RE.sub("", token.lower().translate(_UMLAUTS))


@dataclass
class SessionMarker:
    time: float
    kind: str  # "begin" | "section" | "end"


def find_session_markers(words: Iterable["TranscribedWord"]) -> List[SessionMarker]:
    """Protocol cues in transcript order. Tokens are matched after normalisation."""
    tokens = [
        (_norm(word.text), word.start)
        for word in words
        if word.start is not None and _norm(word.text)
    ]
    markers: List[SessionMarker] = []
    for i, (norm, start) in enumerate(tokens):
        if norm == "danke":
            markers.append(SessionMarker(start, "end"))
        elif norm == "ruf":
            following = [t[0] for t in tokens[i + 1 : i + _BEGIN_MAX_SPAN]]
            if "zurueck" in following:
                markers.append(SessionMarker(start, "begin"))
        else:
            for phrase in _SECTION_PHRASES:
                if norm == phrase[0] and tuple(t[0] for t in tokens[i : i + len(phrase)]) == phrase:
                    markers.append(SessionMarker(start, "section"))
                    break
    return markers


def protocol_segment(
    words: List["TranscribedWord"], event_time: float, min_words: int
) -> List["TranscribedWord"] | None:
    """Words of the protocol exercise containing the event, or None when no cues bound it.

    Prefers the innermost subsection (between adjacent "Beschreibe" / "Was siehst du noch" /
    "Was ist am deutlichsten" cues) when it alone holds `min_words`; otherwise falls back to
    the whole exercise from its "ruf … zurück" opener to the closing "Danke". Returns None
    when even the full exercise is too sparse, so the caller keeps its time-based window.
    """
    markers = find_session_markers(words)
    begins = [m.time for m in markers if m.kind == "begin" and m.time <= event_time]
    ends = [m.time for m in markers if m.kind == "end" and m.time >= event_time]
    if not begins and not ends:
        return None
    seg_start = begins[-1] if begins else 0.0
    seg_end = ends[0] if ends else float("inf")

    def _slice(start: float, end: float) -> List[TranscribedWord]:
        # The end boundary is a cue ("Danke" or the next subsection opener), not content —
        # keep it out of the excerpt. The opening cue leads into content, so it stays in.
        return align_transcript(words, event_time, event_time - start, end - event_time - 1e-6)

    # Subsection cues inside the exercise split it further; take the one around the event.
    bounds = sorted(
        {m.time for m in markers if m.kind != "end" and seg_start <= m.time <= seg_end}
    )
    sec_start = max((b for b in bounds if b <= event_time), default=seg_start)
    sec_end = min((b for b in bounds if b > event_time), default=seg_end)
    section = _slice(sec_start, sec_end)
    if len(section) >= min_words:
        return section

    segment = _slice(seg_start, seg_end)
    return segment if len(segment) >= min_words else None
