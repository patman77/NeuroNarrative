"""Stimulus locking, `X` and `KVZ` — the cross-modal layer.

The Eiserne Regeln make timing relative to speech constitutive, not decorative:

    Nur aufgreifen, was ausschlägt!
    Nur Ausschläge berücksichtigen, die am Ende der Frage des SL oder der Äußerung des SP
    auftreten!

So a deflection that is not time-locked to an utterance boundary is, by the method's own rule,
not evidence. That turns detection from "find changes in a time series" into "find stimulus-locked
responses", which is both better posed and much more precise — and we already compute the word
timings needed for it.

**Unlocked is not deleted.** In a duo session unlocked would be suspicious; in a solo session it
usually just means the operator was working quietly, and the reference recording averages 29
words per minute. Locking is therefore a confidence input, never a filter
(`docs/phenomena-detection-design.md` §5).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

import numpy as np

from ...protocol import Utterance
from ..primitives import Primitives
from ..schema import Phenomenon, PhenomenonKind

# Skin conductance responses follow their stimulus by roughly 1-4 s. Widened slightly at both
# ends for ASR timing slop.
RESPONSE_MIN_SEC = 0.5
RESPONSE_MAX_SEC = 6.0

# Confidence applied to a deflection with no utterance ending before it.
UNLOCKED_CONFIDENCE = 0.5

# `X`: an instruction that produced nothing. Only counted when the operator was actually
# recording speech nearby, otherwise every instruction in a quiet stretch would raise one.
X_MIN_AMPLITUDE_A = 0.5

# `KVZ`: signal moving while nothing is said. Needs a real silence, not an ordinary pause.
KVZ_MIN_SILENCE_SEC = 8.0
KVZ_MIN_MOVEMENT_A = 1.0


def apply_stimulus_locking(
    phenomena: Sequence[Phenomenon], utterances: Sequence[Utterance]
) -> list[Phenomenon]:
    """Tag each phenomenon with the utterance it responds to, if any."""
    if not utterances:
        return list(phenomena)

    ends = np.array([u.end for u in utterances])
    order = np.argsort(ends)
    ends = ends[order]
    ordered = [utterances[i] for i in order]

    tagged: list[Phenomenon] = []
    for phenomenon in phenomena:
        if phenomenon.kind is PhenomenonKind.KOERPERBEWEGUNG:
            tagged.append(phenomenon)
            continue

        window_start = phenomenon.t_start - RESPONSE_MAX_SEC
        window_end = phenomenon.t_start - RESPONSE_MIN_SEC
        low, high = np.searchsorted(ends, [window_start, window_end], side="left")
        candidates = ordered[low:high]

        if candidates:
            # The closest preceding utterance end is the most likely stimulus.
            source = candidates[-1]
            tagged.append(
                replace(
                    phenomenon,
                    stimulus_locked=True,
                    utterance_id=source.id,
                    evidence={
                        **phenomenon.evidence,
                        "latency_sec": phenomenon.t_start - source.end,
                        "stimulus_is_instruction": source.is_instruction,
                    },
                )
            )
        else:
            tagged.append(
                replace(
                    phenomenon,
                    stimulus_locked=False,
                    confidence=phenomenon.confidence * UNLOCKED_CONFIDENCE,
                )
            )
    return tagged


def detect_kein_ausschlag(
    phenomena: Sequence[Phenomenon], utterances: Sequence[Utterance]
) -> list[Phenomenon]:
    """`X`: a protocol instruction whose response window stayed empty.

    Undetectable without the transcript, and one of the manual's own notations — "Kein Ausschlag
    (wo einer zu erwarten gewesen wäre) wird mit x notiert". Only instructions count: the method
    expects a response to a question, not to every remark.
    """
    responded = {p.utterance_id for p in phenomena if p.utterance_id}
    found: list[Phenomenon] = []

    for utterance in utterances:
        if not utterance.is_instruction or utterance.id in responded:
            continue
        found.append(
            Phenomenon(
                kind=PhenomenonKind.KEIN_AUSSCHLAG,
                t_start=utterance.end,
                t_end=utterance.end + RESPONSE_MAX_SEC,
                utterance_id=utterance.id,
                stimulus_locked=True,
                detector="stimulus",
                confidence=0.7,
                evidence={
                    "cue": utterance.cue.step if utterance.cue else None,
                    "text": utterance.text[:200],
                },
            )
        )
    return found


def detect_kvz(
    primitives: Primitives, utterances: Sequence[Utterance], a_unit_lp: float
) -> list[Phenomenon]:
    """`KVZ`: the partner says nothing while the needle and level move.

    The glossary defines it exactly this way — "Während der Sitzung: SP sagt nichts, aber Nadel &
    LP bewegen sich" — and reads more of it as more uncertainty. Purely cross-modal: neither
    channel alone shows it.
    """
    if len(utterances) < 2 or a_unit_lp <= 0:
        return []

    time_sec = primitives.time_sec
    tonic = primitives.tonic
    travel = np.concatenate([[0.0], np.cumsum(np.abs(np.diff(tonic)))])

    found: list[Phenomenon] = []
    for previous, following in zip(utterances, utterances[1:]):
        silence = following.start - previous.end
        if silence < KVZ_MIN_SILENCE_SEC:
            continue

        low, high = np.searchsorted(time_sec, [previous.end, following.start], side="left")
        high = min(high, travel.size - 1)
        if high <= low:
            continue

        movement_a = float(travel[high] - travel[low]) / a_unit_lp
        if movement_a < KVZ_MIN_MOVEMENT_A:
            continue

        found.append(
            Phenomenon(
                kind=PhenomenonKind.KVZ,
                t_start=float(previous.end),
                t_end=float(following.start),
                amplitude_a=movement_a,
                amplitude_lp=float(tonic[high] - tonic[low]),
                utterance_id=previous.id,
                detector="stimulus",
                confidence=0.7,
                evidence={"silence_sec": silence, "movement_a": movement_a},
            )
        )
    return found
