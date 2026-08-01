"""The BK3 session protocol as a parser over the transcript.

The PEP procedures are scripted with verbatim instructions, which makes this a tractable parsing
problem rather than a general NLU one. The inventory below is transcribed from BK3 and checked
against the source PDF; see `docs/mindwalking-domain.md` §3 for the German originals.

Three corrections to the earlier cue set, all verified by grepping both manuals:

- **"Danke" is not a protocol closer.** It appears nowhere in either manual as an instruction —
  only inside an anecdote about a Paranoia-FN. It is ordinary acknowledgement, which the mw-Kurs
  says is the single most important thing the session leader does ("alle Technik reduziert sich
  letztlich auf KF 5: die angemessene Bestätigung"). Treating it as a boundary cut exercises
  short at arbitrary points. A procedure ends where the next one begins.
- **"Was siehst du noch" is not in BK3.** The actual Erzählmethode cue is "Was siehst du genau?".
- **Solo phrasings were missing entirely.** These are solo sessions, and the mw-Kurs is explicit
  that the solist addresses their memory store rather than themselves: "Gibt es ein Geschehnis,
  als ...?", *not* "Habe ich ein Geschehnis mit ...?".

There is one voice in a solo session, alternating between issuing an instruction and answering
it, so roles here are **functions, not speakers**, and diarisation would have nothing to separate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

from .transcript import TranscribedWord

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_NON_LETTER_RE = re.compile(r"[^a-z]")

# A pause longer than this ends an utterance. German conversational pauses run well under a
# second; this is loose enough to keep a sentence together and tight enough to split turns.
TURN_GAP_SEC = 1.5

# Fraction of a cue's content words that must appear, in order, for it to match. ASR on German
# is not exact enough for literal token equality, and a missed cue costs a whole segment.
CUE_MATCH_RATIO = 0.7


class Procedure(str, Enum):
    INTERVIEW = "Interview"
    FRR = "FRR"
    KRR = "KRR"
    EZM = "EZM"
    WT = "WT"


@dataclass(frozen=True)
class Cue:
    procedure: Procedure
    step: str
    tokens: tuple[str, ...]
    opens_procedure: bool = False
    opens_section: bool = False


def _norm(token: str) -> str:
    """Lowercased letters only, umlauts folded so 'zurück' and 'zurueck' both match."""
    return _NON_LETTER_RE.sub("", token.lower().translate(_UMLAUTS))


def _cue(procedure: Procedure, step: str, phrase: str, **flags: bool) -> Cue:
    tokens = tuple(t for t in (_norm(p) for p in phrase.split()) if t)
    return Cue(procedure=procedure, step=step, tokens=tokens, **flags)


# Ordered longest-first within each procedure so a specific cue wins over a generic one.
CUE_INVENTORY: tuple[Cue, ...] = (
    # --- Interview ---
    _cue(Procedure.INTERVIEW, "safra", "ist dir seit der letzten sitzung etwas durch den kopf gegangen"),
    # --- Freier Rückruf ---
    _cue(Procedure.FRR, "next", "ruf dir ein weiteres erlebnis zurueck", opens_section=True),
    _cue(Procedure.FRR, "open", "ruf dir ein erlebnis zurueck", opens_procedure=True, opens_section=True),
    # Solo phrasings: the solist queries the memory store, not themselves.
    _cue(Procedure.FRR, "open_solo", "gibt es ein geschehnis als", opens_procedure=True, opens_section=True),
    _cue(Procedure.FRR, "open_solo2", "sind geschehnisse verfuegbar", opens_procedure=True, opens_section=True),
    _cue(Procedure.FRR, "describe", "beschreib es mir"),
    _cue(Procedure.FRR, "resolve", "was ist dir dabei am deutlichsten"),
    # --- Kettenrückruf ---
    _cue(Procedure.KRR, "open", "ruf dir das frueheste erlebnis zurueck", opens_procedure=True, opens_section=True),
    _cue(Procedure.KRR, "step", "ruf dir nun das naechstspaetere erlebnis in richtung gegenwart zurueck", opens_section=True),
    _cue(Procedure.KRR, "narrate", "erzaehl mir davon"),
    _cue(Procedure.KRR, "when", "wann etwa war das"),
    _cue(Procedure.KRR, "locate", "wann im geschehnis hast du dich am staerksten so gefuehlt wie"),
    # --- Erzählmethode ---
    _cue(Procedure.EZM, "orient", "was siehst du genau", opens_procedure=True, opens_section=True),
    _cue(Procedure.EZM, "orient2", "beschreibe mir was du jetzt gerade siehst und empfindest"),
    _cue(Procedure.EZM, "run", "geh das erlebnis durch bis zum ende", opens_section=True),
    _cue(Procedure.EZM, "detail", "beschreibe jede einzelheit in aller deutlichkeit"),
    _cue(Procedure.EZM, "reenter", "geh zum fruehesten einstieg in das erlebnis", opens_section=True),
    _cue(Procedure.EZM, "flott", "nochmal von anfang bis ende bitte aber jeweils nur das was dir deutlich ist", opens_section=True),
    _cue(Procedure.EZM, "np", "an welcher stelle im geschehnis entstand das negativprogramm"),
    _cue(Procedure.EZM, "drive", "und wie war das genau"),
    _cue(Procedure.EZM, "drive2", "und was war dann"),
    # --- Observed in practice, NOT in BK3 -------------------------------------------------
    # These are how the operator actually phrases the scripted steps on the reference
    # recording. They are listed separately on purpose: the manual is the authority on the
    # method, but the transcript is the authority on what was said. Without them a third of
    # the real cues go unmatched, and every one of those costs a segment boundary.
    _cue(Procedure.FRR, "resolve_obs", "was ist jetzt am deutlichsten"),
    _cue(Procedure.FRR, "resolve_obs2", "was ist am allerdeutlichsten"),
    _cue(Procedure.EZM, "orient_obs", "was siehst du noch", opens_section=True),
    _cue(Procedure.FRR, "describe_obs", "beschreib mir das erlebnis"),
    _cue(Procedure.FRR, "describe_obs2", "beschreib mir was du siehst"),
)


@dataclass
class Utterance:
    index: int
    start: float
    end: float
    words: list[TranscribedWord]
    cue: Cue | None = None

    @property
    def id(self) -> str:
        return f"utt-{self.index}"

    @property
    def is_instruction(self) -> bool:
        """A matched protocol cue. In solo this is the only role signal there is — and it is a
        function, not a speaker, since the operator both asks and answers."""
        return self.cue is not None

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Segment:
    """A node of the parse tree: a procedure, or an exercise/pass inside one."""

    procedure: Procedure
    label: str
    start: float
    end: float
    children: list["Segment"] = field(default_factory=list)

    def contains(self, when: float) -> bool:
        return self.start <= when <= self.end

    def innermost(self, when: float) -> "Segment":
        for child in self.children:
            if child.contains(when):
                return child.innermost(when)
        return self

    def as_dict(self) -> dict:
        return {
            "procedure": self.procedure.value,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "children": [c.as_dict() for c in self.children],
        }


def segment_turns(words: Sequence[TranscribedWord]) -> list[Utterance]:
    """Group words into utterances on pause length, then tag any that match a protocol cue."""
    timed = [w for w in words if w.start is not None]
    if not timed:
        return []

    utterances: list[Utterance] = []
    current: list[TranscribedWord] = [timed[0]]
    for previous, word in zip(timed, timed[1:]):
        previous_end = previous.end if previous.end is not None else previous.start
        if word.start - previous_end > TURN_GAP_SEC:
            utterances.append(_finish(len(utterances), current))
            current = []
        current.append(word)
    utterances.append(_finish(len(utterances), current))

    for utterance in utterances:
        utterance.cue = match_cue([w.text for w in utterance.words])
    return utterances


def _finish(index: int, words: list[TranscribedWord]) -> Utterance:
    start = words[0].start or 0.0
    last = words[-1]
    return Utterance(index=index, start=start, end=last.end or last.start or start, words=list(words))


def match_cue(tokens: Sequence[str]) -> Cue | None:
    """Best cue whose content words appear in order within `tokens`.

    Subsequence rather than contiguous match, and a ratio rather than all-or-nothing: ASR drops
    and mangles short German function words constantly, and requiring the literal phrase would
    miss most real cues. Longest match wins so "ruf dir das früheste Erlebnis zurück" (KRR) is
    not swallowed by "ruf dir ein Erlebnis zurück" (FRR).
    """
    # Normalise here rather than trusting the caller: this is the entry point used by tests and
    # by anything reasoning about a phrase, and silently failing on "zurück" would be a trap.
    present = [t for t in (_norm(token) for token in tokens) if t]
    if not present:
        return None

    # Rank by how *completely* the cue is present, then by cue length. Ranking by raw matched
    # count alone tied "ruf dir ein Erlebnis zurück" (5 of 5) against "ruf dir ein weiteres
    # Erlebnis zurück" (5 of 6), and inventory order decided it — so every Freier-Rückruf opener
    # was read as a mid-exercise "next" cue and no procedure ever opened.
    best: Cue | None = None
    best_key = (0.0, 0)
    for cue in CUE_INVENTORY:
        matched = _ordered_overlap(cue.tokens, present)
        ratio = matched / len(cue.tokens)
        if ratio < CUE_MATCH_RATIO:
            continue
        key = (ratio, matched)
        if key > best_key:
            best, best_key = cue, key
    return best


def _tokens_match(cue_token: str, heard: str) -> bool:
    """Token equality, tolerant of German inflection and ASR damage.

    The reference transcript renders "Ruf dir" as "ruft ihr", "Ruf der", "Rucht ihr", "Huf dir"
    and "Hufe dir"; "beschreib" appears as "beschreibe", "beschreibst" and "Beschreiwest";
    "deutlichsten" as "allerdeutlichsten". Exact equality missed roughly a third of the real
    cues, and each miss costs a segment boundary.
    """
    if cue_token == heard:
        return True
    shorter, longer = sorted((cue_token, heard), key=len)
    if len(shorter) >= 3 and longer.startswith(shorter):
        return True
    # Catches prefixed intensifiers such as "aller-deutlichsten".
    return len(shorter) >= 6 and shorter in longer


def _ordered_overlap(needle: Sequence[str], haystack: Sequence[str]) -> int:
    """How many of `needle`'s tokens appear in `haystack` in order."""
    matched = 0
    position = 0
    for token in needle:
        # Probe from the current position, but only *commit* it on a hit. Advancing the cursor
        # on a miss consumed the rest of the haystack, so one dropped word ("ein") made every
        # later token unmatchable and no real cue ever scored above the threshold.
        probe = position
        while probe < len(haystack) and not _tokens_match(token, haystack[probe]):
            probe += 1
        if probe < len(haystack):
            matched += 1
            position = probe + 1
    return matched


def parse_session(utterances: Sequence[Utterance], duration_sec: float) -> list[Segment]:
    """Build the procedure/exercise tree from the cue-tagged utterances.

    A procedure runs until the next procedure opens — *not* until a "Danke", which is what the
    earlier implementation did and is why segments ended arbitrarily.
    """
    openers = [u for u in utterances if u.cue and u.cue.opens_procedure]
    if not openers:
        return []

    segments: list[Segment] = []
    for position, utterance in enumerate(openers):
        assert utterance.cue is not None
        end = openers[position + 1].start if position + 1 < len(openers) else duration_sec
        if end <= utterance.start:
            continue
        segments.append(
            Segment(
                procedure=utterance.cue.procedure,
                label=utterance.cue.procedure.value,
                start=utterance.start,
                end=end,
            )
        )

    # Merge consecutive segments of the same procedure: repeated FRR openers are separate
    # exercises within one Freier Rückruf, not separate procedures.
    merged: list[Segment] = []
    for segment in segments:
        if merged and merged[-1].procedure == segment.procedure:
            merged[-1].end = segment.end
        else:
            merged.append(segment)

    for segment in merged:
        segment.children = _sections(utterances, segment)
    return merged


def _sections(utterances: Sequence[Utterance], parent: Segment) -> list[Segment]:
    marks = [
        u
        for u in utterances
        if u.cue and u.cue.opens_section and parent.start <= u.start < parent.end
    ]
    children: list[Segment] = []
    for position, utterance in enumerate(marks):
        end = marks[position + 1].start if position + 1 < len(marks) else parent.end
        if end <= utterance.start:
            continue
        children.append(
            Segment(
                procedure=parent.procedure,
                label=f"{parent.procedure.value} {position + 1}",
                start=utterance.start,
                end=end,
            )
        )
    return children


def segment_for(segments: Sequence[Segment], when: float) -> Segment | None:
    for segment in segments:
        if segment.contains(when):
            return segment.innermost(when)
    return None


def content_words(utterances: Iterable[Utterance], start: float, end: float) -> list[TranscribedWord]:
    """Words in `[start, end]` from non-cue utterances.

    Excerpts should be what was recounted, not the scripted question that prompted it.
    """
    selected: list[TranscribedWord] = []
    for utterance in utterances:
        if utterance.is_instruction or utterance.end < start or utterance.start > end:
            continue
        selected.extend(w for w in utterance.words if w.start is not None and start <= w.start <= end)
    return selected
