# Session narrative: protocol parsing and summaries — system design

How the BK3 protocol should structure the transcript, and how summaries should change once the
structure and the phenomenon set from `phenomena-detection-design.md` exist.

Read `mindwalking-domain.md` §3 for the cue inventory this is built on.

**Status (2026-08-02).** Implemented: §2 (cue inventory, turn segmentation, function roles, the
parse tree) in `services/protocol.py`; §3 (tree-bounded excerpt selection) in
`services/transcript.py`; and **§4.3, the automatic Sitzungsbericht**, in `services/narrative.py`
with `SessionNarrative.tsx` rendering it and a markdown export.

Not implemented: §4.1 (per-phenomenon summary prompts — per-event summaries still use the single
neutral prompt) and §4.2 (topic rollup ranked by total discharge).

§6 records what building the parser taught us; §7 what building the report taught us.

---

## 1. Where we are

`_context_words` in `analysis.py` picks a transcript excerpt for an event through three tiers:

1. the configured pre/post window (5 s / 7 s),
2. widened to `summary_context_sec` (45 s) when the exact window holds fewer than
   `summary_min_words`,
3. `protocol_segment` in `transcript.py` — a first pass at the BK3 grammar, keying on "ruf …
   zurück" as an opener, "Danke" as a closer, and `beschreibe` / `was siehst du noch` / `was ist
   am deutlichsten` as subsection openers.

On the reference 54-minute recording this took summarised events from 6 to 21 of 23. It works, and
the manuals confirm the approach was right. They also show it is using about a third of the
available grammar, and that three assumptions in it are wrong:

- **"Danke" is not a protocol closer.** It appears nowhere in BK3 as an instruction. It is
  ordinary acknowledgement — the SL's Bestätigung, which the mw-Kurs says happens constantly and
  is the single most important thing the SL does ("alle Technik reduziert sich letztlich auf
  KF 5: die angemessene Bestätigung"). Treating it as an exercise boundary will cut segments
  short at arbitrary points. The real closer is the *next opener*, or an EE.
- **"Was siehst du noch"** is not in BK3. The actual EZM cues are "Was siehst du genau?",
  "Beschreibe mir, was du jetzt gerade siehst und empfindest", "Und was war dann?", "Und dann?".
- **There is no speaker model.** Cues are SL utterances and content is SP speech, but excerpts
  currently mix both, so a summary can end up paraphrasing the facilitator's question rather than
  the partner's answer.

---

## 2. Protocol grammar

Replace the flat opener/section/closer marker list with an explicit grammar over the PEP
procedures. The cues are verbatim and scripted, which makes this a genuinely tractable parsing
problem rather than a general NLU one.

### 2.1 Cue inventory

Structured as `(procedure, step, patterns)`, all matched on normalised tokens (lowercased,
umlaut-folded `ä→ae ö→oe ü→ue ß→ss`, punctuation stripped — as `_norm` already does):

| Procedure | Step | Cue |
|---|---|---|
| Interview | re-entry | `SAFRA`: "ist dir seit der letzten sitzung etwas durch den kopf gegangen" |
| **FRR** | open | "ruf dir ein erlebnis zurueck als …" |
| FRR | next | "ruf dir ein weiteres erlebnis zurueck" |
| FRR | describe | "beschreib es mir" |
| FRR | resolve | "was ist dir dabei am deutlichsten" |
| **KRR** | open | "ruf dir das frueheste erlebnis zurueck an das du dich jetzt gerade erinnern kannst" |
| KRR | step | "ruf dir nun das naechstspaetere erlebnis in richtung gegenwart zurueck" |
| KRR | narrate | "erzaehl mir davon" · "wann etwa war das" |
| KRR | locate | "wann im geschehnis hast du dich am staerksten so gefuehlt wie" |
| **EZM** | orient | "was siehst du genau" · "beschreibe mir was du jetzt gerade siehst und empfindest" |
| EZM | run | "geh das erlebnis durch bis zum ende" · "beschreibe jede einzelheit in aller deutlichkeit" |
| EZM | re-enter | "geh zum fruehesten einstieg in das erlebnis" |
| EZM | flott | "nochmal von anfang bis ende bitte aber jeweils nur das was dir deutlich ist" |
| EZM | NP locate | "an welcher stelle im geschehnis entstand das negativprogramm" |
| EZM | drive | "und was war dann" · "und dann" · "und wie war das genau" |
| any | `D?` | "deutlich" as a bare question |
| **WT** | repeat | topic re-provocation (no fixed wording; detect by verbatim repetition of the session topic) |

Matching must be fuzzy in one direction only: **the cue is a fixed template with a variable
slot** ("… als ⟨Thema⟩"). Match the fixed prefix, capture the slot. Given ASR error rates on
German, exact token-sequence matching will miss real cues; use token-level fuzzy matching
(normalised edit distance over the cue's content words, threshold tuned on the reference
recording) and require the *ordered* content words rather than a bag.

Extracting the topic slot is worth doing on its own: **"⟨Thema⟩" is the session's
Negativprogramm**, spoken repeatedly and verbatim. Recovering it gives the report a title, and
gives the WT detector its repetition target.

### 2.2 The parse

A shift-reduce parse over the utterance stream produces a tree, not a flat marker list:

```
Session
├── Interview               [t0 … t1]   topic = "…"
├── FRR                     [t1 … t2]
│   ├── Erlebnis 1          [.. ]  opener slot, describe, resolve
│   └── Erlebnis 2          [.. ]
├── KRR                     [t2 … t3]
│   └── Kette 1 → n         [.. ]
└── EZM                     [t3 … t4]
    └── Urerlebnis
        ├── Durchlauf 1     [.. ]
        ├── Durchlauf 2     [.. ]
        └── …
```

Rules from the method, used as grammar constraints: FRR precedes KRR precedes EZM; an EZM pass
begins at "geh zum frühesten Einstieg" and ends at the next one; a procedure ends when the next
procedure's opener appears. Ambiguity is resolved in favour of the sequence the manual prescribes
— a cue that would require going backwards is a probable ASR artefact.

Segments carry timestamps, so **every phenomenon lands in a known node of this tree**, which is
what makes the rest of the design possible.

### 2.3 Function roles — and why this is a solo system

**The target corpus is solo.** Every recording in the operator's archive is a single-operator
session, and the intended use of NeuroNarrative is one person reviewing their own session
afterwards. That is not a detail — it invalidates the speaker-diarisation
approach and changes what the transcript can be expected to contain.

There is **one voice**. The operator alternates between two *functions*: issuing the instruction
(the SL function) and answering it (the SP function). So:

- **Drop diarisation entirely.** It cannot separate what needs separating, and it would have cost
  a torch dependency and a model download against the desktop-bundle budget for nothing.
- **Cue matching is not a bootstrap for role assignment — it *is* the role signal.** A turn
  matching the cue inventory is an instruction turn; everything between two instructions is
  content. This is more robust than the duo case, not less, because there is no speaker-change
  ambiguity to resolve.
- Excerpts default to **content turns**, i.e. everything that is not a matched cue, with the
  governing instruction attached separately as context.

The mw-Kurs has a dedicated `BESONDERHEITEN BEI SOLOSITZUNGEN` section, and two of its points
land directly on this design:

1. **Solo phrasing differs from BK3's duo scripts.** The solist addresses their memory store, not
   themselves: *"Gibt es ein Geschehnis, als …?"* — explicitly **not** *"Habe ich ein Geschehnis
   mit …?"*. The cue inventory in §2.1 is the duo wording and needs solo variants beside each
   entry: `gibt es ein geschehnis als …`, `zum thema ⟨X⟩ sind geschehnisse verfuegbar`, alongside
   the second-person forms, which a solist may still use out of habit.
2. **Solo is fast, and speech is optional.** The manual's stated reason for forbidding an
   assistant is that verbalising slows the session down. Sparse audio is therefore the *expected*
   regime, not a degraded recording.

That second point reframes a problem we treated as a defect. The reference recording holds 1589
words across 54 minutes — about 29 words per minute — which we previously read as "sessions are
mostly silent" and worked around with the widened window and the protocol fallback. It is better
understood as structural: in solo, much of the work is not spoken at all. Consequences:

- The three-tier fallback is **load-bearing, not a patch**, and should be designed for rather than
  apologised for.
- Some phenomena will have **no verbal correlate at any window size**, and the honest output is
  the phenomenon with its signal evidence and no summary — not a summary stretched from unrelated
  speech minutes away. The tree-bounded widening in §3 matters more here than it would in a duo
  session, because a flat 45-second radius in a sparse recording is very likely to cross into a
  different exercise.
- Signal-side detection carries proportionally more of the analytical weight than the transcript
  does. The phenomenon catalogue is the primary product for this corpus; summaries are enrichment.

---

## 3. Excerpt selection, revised

Today's tiers pick a window by word count. With the parse tree and the phenomenon set, selection
becomes structural:

```
for a phenomenon p at time t:
    node   = innermost tree node containing t
    window = content words (non-cue turns) in [t - pre, t + post]
    if enough words: use it
    else: widen within `node` only  (never across a procedure boundary)
    else: use the whole of `node`
    else: use node.parent
```

The key change is that widening is **bounded by the tree** rather than by a flat 45-second radius.
A window that crosses from one Erlebnis into the next produces a summary describing two unrelated
memories, which is worse than no summary. The current tier 2 can do exactly that.

Retain `drop_hallucinated_tokens` and `_reject_implausible_rate` — the manuals change nothing
about Whisper's behaviour over room tone.

---

## 4. Summaries

### 4.1 Phenomenon-aware prompting

The current prompt asks for a neutral one-sentence summary with no notion of what kind of moment
it is. A `BE` and an `FN` are different questions:

| Phenomenon | What the summary should answer |
|---|---|
| `BE` | Which single statement caused the discharge? Quote or paraphrase it tightly. |
| `A` (large) | What became available here? |
| `LPA_slow` | What was being worked through across this stretch? |
| `SN` | What is the SP uncertain or ambivalent about? |
| `FN` / `EE` | What was recognised? Is there relief, or is this an Apathie-/Paranoia-FN? |
| `X` | The SL asked; nothing responded. Report the question, not an answer. |
| `KVZ` | The SP went quiet while the signal moved. Report what preceded the silence. |

Each gets its own instruction appended to the shared system prompt, along with the node's position
in the tree ("EZM, third pass over the Urerlebnis") and the session topic. Keep the existing
guarantees: same language as the excerpt, `NONE` when there is genuinely nothing, no speculation.

Two things to be careful about, because the domain invites overreach:

- **Do not let the LLM infer psychological content from the signal.** The excerpt is the evidence;
  the phenomenon label is context for *what to look for*, not licence to assert what the SP felt.
  The manual's own epistemics are strict about this ("als Belege gelten nur solche geistigen
  Eindrucksbilder, die mit somatischen und emotionalen Wallungen einhergehen") and the report is
  more useful if it stays on the evidence side of that line.
- **Do not label FN subtypes from the transcript alone.** Frohsinn vs Apathie vs Paranoia is a
  clinical judgement the manual gives to the SL. Surface the FN and the excerpt; offer the
  distinction as a question, never as a verdict.

### 4.2 Topic-level rollup

The unit the SL acts on is not the event, it is the topic. For each tree node, produce:

- total discharge `LPA_total` (the "größte Ladung" ranking key),
- the constituent phenomena in order,
- whether the node closed with an FN,
- a short synthesis over the node's SP speech.

Ranked by `LPA_total`, this is the report's main view — and it is what the flat event list should
become.

### 4.3 Automatic Sitzungsbericht

The method *requires* a session report, and specifies what must be in it: every LP change, every
deflection, the SL's reasoning, the result. Almost all of the bookkeeping half is now derivable:

```
Sitzung ⟨date⟩ · Thema: ⟨extracted NP⟩ · Dauer 53:54
LPB 4.42 – 6.02  (unkalibriert: Solo-Elektrode, kein Offset angegeben)
LPD  ⟨track⟩ · Ausschläge: 131 A, 24 BE, 6 SN, 3 FN

FRR
  Erlebnis 1 (07:22 – 14:10)   LPA_total 1.4 A   3 BE   FN am Ende ✓
    "…"
  Erlebnis 2 (14:10 – 20:31)   LPA_total 0.3 A   kein FN
…
```

This is the highest-value output of the whole system: it turns an hour of manual note-taking into
something the SL edits rather than writes, and its accuracy is directly checkable against the
notes the SL took anyway — which is also how we get the evaluation labels the detection design
needs. The two goals are the same work.

The judgement half — why the SL went where they went — stays with the SL. The report should leave
space for it, not generate it.

---

## 5. What this changes in the existing code

| File | Change |
|---|---|
| `services/transcript.py` | `find_session_markers` → full cue inventory with fuzzy template matching and slot capture; `protocol_segment` → tree parse; drop "Danke" as a closer; add role tagging |
| `services/analysis.py` | `_context_words` selects within the tree instead of by flat radius; pass phenomenon kind and node path to the summariser |
| `services/summary.py` | per-phenomenon prompt variants; topic-level rollup call; `NONE` semantics unchanged |
| `api/schemas.py` | expose the tree and per-node rollups alongside the flat event list |
| frontend | timeline gains procedure/exercise bands; events nest under topics ranked by total discharge |
| `TODO.md` | protocol-cue row updated once any of this lands |

Sequencing: the tree parse (§2) is independent of the detection work and could be done first — it
improves summaries on its own. Everything in §4.2 and §4.3 needs the phenomenon set, so it follows
stages 2–4 of the detection roadmap.


---

## 6. As built — what the reference transcript taught us

The cue inventory in §2.1 is the manual's. The transcript is not.

**Exact token matching found 13 instruction turns out of 303.** Two changes took that to 29:

1. **Stem-tolerant token comparison.** Whisper renders "Ruf dir" as "ruft ihr", "Ruf der",
   "Rucht ihr", "Huf dir" and "Hufe dir"; "beschreib" as "beschreibe", "beschreibst" and
   "Beschreiwest"; "deutlichsten" as "allerdeutlichsten". Tokens now match on equality, on a
   shared prefix of ≥3 characters, or on containment for longer stems.
2. **A separate group of observed phrasings.** The operator says "Was ist jetzt am deutlichsten"
   where BK3 scripts "Was ist dir dabei am deutlichsten", and uses "Was siehst du noch" — which,
   as §1 notes, is *not* in BK3 at all. These live in `CUE_INVENTORY` under an explicit
   "observed in practice, NOT in BK3" heading, because the distinction matters: the manual is the
   authority on the method, the transcript on what was said.

Note the irony in the second point. "Was siehst du noch" was one of the two cues §1 called out as
wrong, and it *is* wrong as a claim about BK3 — but the operator does say it, so removing it
outright would have lost real segment boundaries. The correct fix was to keep it and be honest
about where it comes from. "Danke" is different: it appears nowhere as an instruction and is
ordinary acknowledgement, so it stays out.

Two bugs underneath, both of which produced plausible-looking output:

- `_ordered_overlap` advanced its cursor past the haystack on a miss, so a single dropped word
  ("ein") made every subsequent token unmatchable and no cue ever cleared the threshold.
- Scoring by raw matched-token count tied "ruf dir ein Erlebnis zurück" (5 of 5) against "ruf dir
  ein weiteres Erlebnis zurück" (5 of 6), so inventory order decided it, every opener was read as
  a mid-exercise "next" cue, and **no procedure ever opened**. Scoring is now by completeness
  ratio, then cue length.

**The parse on the reference recording:** FRR 7.4-23.6 min (8 exercises), EZM 23.6-49.5 min
(5 passes), FRR 49.5-53.9 min (2). That follows BK3's prescribed FRR-before-EZM order without
being told to, which is weak but real evidence the matcher is finding the right things.

**A structural fix in `protocol_segment`:** the final procedure now runs to the end of the
session rather than to the last spoken word. In a solo session speech is sparse, so an event
minutes after an exercise's last utterance still belongs to it; bounding at the last word left
exactly those events — the ones the fallback exists for — with no segment at all.


---

## 7. As built — the Sitzungsbericht

`services/narrative.py`. One section per protocol segment, each with a title, a few sentences,
highlights, the charge level at its boundaries and the phenomena inside it.

**The model never chooses a timestamp.** Section boundaries come from the BK3 cues actually
spoken; charge levels are read from the conditioned signal at those instants; counts come from
the detectors. This was the design intent and it turned out to need enforcing rather than merely
requesting: even instructed not to, a real run emitted *"Die Sitzung endet um 4:07"* for a section
ending at 53:55. `strip_invented_times` drops any sentence carrying a clock reference — ages,
counts and charge levels survive, since those are content. One invented number would discredit
the eleven correct headings around it.

Without a transcript it falls back to fixed five-minute windows. Those are still real ranges
rather than estimates, which is the property that matters.

Silence is reported as silence. In a solo session a quiet stretch is an observation, not a gap
to apologise for.

**On the reference recording:** 12 sections tiling 00:00–53:55 with no gaps or overlap, LP
6.00 → 4.79. The content lines up with the operator's own hand-written summary of that session —
the mixed-up key and the Pommes, the Alkohol discussion, the U-Boot with the Muttern, the
Kirschessen, the Physikpraktikum, the closing Orientierungsübung — but with times derived from
the cues rather than estimated, which is the whole point of the exercise.

**Prose quality is bounded by the local model.** With qwen2.5:7b, two of twelve sections came
back thin and it coins the occasional non-word. The structure, the times and the levels do not
depend on it.
