from __future__ import annotations

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
