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


def protocol_segment(
    words: List["TranscribedWord"], event_time: float, min_words: int
) -> List["TranscribedWord"] | None:
    """Words of the protocol segment containing the event, or None when no cue bounds it.

    Delegates to `services.protocol`, which carries the verified BK3 cue inventory including the
    solo phrasings. The earlier implementation here keyed on "Danke" as an exercise closer and
    "Was siehst du noch" as a subsection opener; **neither appears in either manual** — "Danke" is
    ordinary acknowledgement, and the real Erzählmethode cue is "Was siehst du genau?". Segments
    therefore ended at arbitrary points.

    Prefers the innermost segment when it alone holds `min_words`, then its parent, then None so
    the caller keeps its time-based window.
    """
    # Imported here: `protocol` imports `TranscribedWord` from this module.
    from .protocol import content_words, parse_session, segment_for, segment_turns

    utterances = segment_turns(words)
    if not utterances:
        return None

    # The final procedure runs to the end of the *session*, not to the last spoken word. In a
    # solo session speech is sparse, so an event minutes after the last utterance of an exercise
    # still belongs to it — bounding at the last word left those events with no segment at all.
    duration = max(max((u.end for u in utterances), default=event_time), event_time) + 1.0
    segments = parse_session(utterances, duration)
    node = segment_for(segments, event_time)
    while node is not None:
        selected = content_words(utterances, node.start, node.end)
        if len(selected) >= min_words:
            return selected
        node = _parent(segments, node)
    return None


def _parent(segments, node):
    for segment in segments:
        if node in segment.children:
            return segment
    return None
