# Phenomenon detection: system design

How NeuroNarrative should detect the full MindWalking phenomenon set — A, T, X, BE, LPA, LPD,
LPB, SN, FN, KB, Abflachung, ÜBZ, EE, KVZ, zähe Sitzung — from a paired GSR + audio recording,
with accuracy and coverage as the ranking criteria.

Read `mindwalking-domain.md` first; every phenomenon name and every constant quoted here comes
from there.

**Status (2026-08-02): stages 1-6 of the §11 roadmap are implemented.** Sections 1-10 are the
design as originally reasoned through; §12 records where building it proved the design wrong,
§12a covers labelling and evaluation as built, and §13 gives measured results on the reference
recording. Where the design and §12 disagree, §12 is what the code does.

Stages 7 and 8 are blocked on the same thing: **no labels have been made**, so nothing here is
validated. See `status.md`.

---

## 0. Summary of the argument

Five claims drive the whole design. Each is defended in its own section.

1. **Analyse continuous LP, not kΩ.** The device's `Data(16 bit)` column is linear in LP at
   0.0001 LP resolution. LP is log-resistance, and log-resistance is the scale on which the
   method's own thresholds (0.05 LP, "3A", zone boundaries) are defined. Working in kΩ makes
   every threshold session-position-dependent. (§2)
2. **Detection must be stimulus-locked.** The method's own Eiserne Regel is that only deflections
   at the end of an SL question or SP utterance count. We already produce word-level transcript
   timings and throw that information away. Adding a response-window gate is the single largest
   available precision gain, and it is free. (§5)
3. **Decompose before you classify.** Tonic (level) and phasic (deflection) components answer
   different phenomena — LP/LPA/zones are tonic, A/T/BE are phasic, SN/FN live in a third,
   oscillatory band. One threshold on one signal cannot serve all three. Standard EDA
   decomposition applies directly once the resistance→conductance polarity flip is done. (§3)
4. **Rules first, ML where rules are provably ambiguous, DL only after labels exist.** Most of the
   catalogue is deterministic given good primitives. Three discriminations genuinely need learning
   (BE vs KB, SN vs FN, real-A vs noise). Nothing in the corpus today justifies a deep model, and
   the design says so rather than pretending otherwise. (§6, §7, §8)
5. **Calibrate per recording or emit nothing absolute.** Sensitivity sets the A-unit; the solo
   electrode shifts LP by an amount the SL is instructed to measure each session. Without those,
   "3A" and "Kampfzone" are meaningless numbers. (§4)

---

## 1. Architecture

A layered pipeline. Each layer is independently testable and each produces a persisted,
versioned artefact, so a later layer can be re-run without repeating transcription.

```
  GSR CSV                      WAV
     │                          │
     ▼                          ▼
┌─────────────────┐    ┌──────────────────────┐
│ L0 Conditioning │    │ ASR + word timings   │   (existing services/asr.py)
│  • schema map   │    │ + turn segmentation  │
│  • LP domain    │    │ + SL/SP role tagging │
│  • artefact mask│    └──────────┬───────────┘
│  • resample     │               │
└────────┬────────┘               │
         ▼                        │
┌─────────────────┐               │
│ L1 Primitives   │               │
│  tonic / phasic │               │
│  oscillation    │               │
│  derivatives    │               │
└────────┬────────┘               │
         ▼                        ▼
┌──────────────────────────────────────────────┐
│ L2 Phenomenon detectors (rule-based)         │
│  needle: A T X SN FN KB                      │
│  level:  BE LPA LPD LPB zones                │
└────────────────────┬─────────────────────────┘
                     ▼
┌──────────────────────────────────────────────┐
│ L3 Discriminators (classical ML)             │
│  BE vs KB · SN vs FN · A vs noise · confidence│
└────────────────────┬─────────────────────────┘
                     ▼
┌──────────────────────────────────────────────┐
│ L4 Session state & episodes (sequence model) │
│  Abflachung · ÜBZ · EE · zähe Sitzung · KVZ  │
│  protocol phase alignment (BK3 grammar)      │
└────────────────────┬─────────────────────────┘
                     ▼
              Fusion & ranking  →  report
```

Proposed package layout, replacing today's single `services/events.py`:

```
backend/app/services/phenomena/
    schema.py         # Phenomenon dataclass, versioned enum, confidence contract
    conditioning.py   # L0
    primitives.py     # L1
    calibration.py    # sensitivity / solo offset / zone mapping
    detectors/        # L2, one module per phenomenon family
        deflection.py     # A, T, X
        discharge.py      # BE, LPA
        needle_state.py   # SN, FN
        artefact.py       # KB, cable fault, electrode loss
        level.py          # LP, LPD, LPB, zones
    discriminate.py   # L3
    session.py        # L4
    fusion.py         # merge, dedupe, rank, "größte Ladung zuerst"
```

`detect_events()` stays as a thin adapter over `fusion.py` so the existing API contract and the
frontend keep working while the new surface is added alongside.

---

## 2. L0 — Conditioning

### 2.1 Schema mapping

The real export is `Time(msec), Data(16 bit), Baseline, Resistance(kOhm), Tag Number`; our
fixtures are `time, resistance`. Support both, plus conductance-only files, via an explicit
**channel-role resolver** rather than the two independent substring heuristics we have now
(`_load_gsr` in `analysis.py` and `gsrParser.ts` — which currently disagree, see domain doc §4).

Resolution order for the LP channel, best first:

1. `Data(16 bit)` + `Baseline` present → fit `Data = k·LP + c` by robust regression on Baseline,
   invert to continuous LP. **Preferred.** Highest resolution, no assumptions.
2. `Resistance(kOhm)` present → `LP = (ln R − c) / k` using the per-recording fit if `Baseline`
   is available to anchor it, else the manual's nominal `k = 1.016, c = −1.0045`.
3. `Baseline` alone → usable but quantised to 0.05; flag the report as reduced-resolution.
4. Conductance → `R = 1/G`, then as (2).

The resolver must be **one implementation, shared by both parsers**. The frontend importing the
same JSON-described channel map (or the backend returning the resolved channel with the upload
response) ends the drift permanently. This is a prerequisite, not a nice-to-have: a preview that
plots a different column than the analysis is a correctness bug the user sees as "jagged".

### 2.2 Artefact masking

Run before anything else so no downstream detector ever sees a mechanical event as a mental one.
The manual is emphatic that `KB` must never be confused with a `BE`.

| Artefact | Signature | Action |
|---|---|---|
| Electrode grab / settling | very large monotone excursion in the first ~30 s; in our 54-min file the two largest 3 s falls in the whole session (0.36, 0.29 LP) are at t < 10 s | mask a leading window until `|dLP/dt|` falls below the session's robust noise band for ≥5 s |
| Cable fault | LP pinned at a rail (≥6.4 or ≤1.05), or excursions faster than physiologically possible (`|dLP/dt| > ~2 LP/s`) | mask, warn in the report |
| Electrode loss / regrip | step change with rail contact, then return | mask |
| Body movement (KB) | fast bipolar spike, rise time far below the SCR range, often with an unrecovered step | flag as *candidate*, not masked — L3 decides KB vs BE |

Masked spans are carried forward as a first-class `mask` array; no detector may report inside one,
and coverage metrics must be computed on unmasked duration so a bad recording does not silently
look like a quiet one.

### 2.3 Resampling

Real files are uniform 50 Hz. Do not assume it. Resample to a fixed internal rate (**20 Hz**
proposed: well above the 0.5 Hz upper edge of the phasic band, cheap, and 20 Hz keeps a 54-minute
session at 65k samples) using anti-aliased polyphase resampling on the LP channel, and keep the
native-rate channel for oscillation features (§3.3) that need the high band.

---

## 3. L1 — Primitives

### 3.1 Why decomposition, and the polarity flip

Skin conductance decomposes into a slowly varying **tonic** level (SCL) and superimposed
**phasic** responses (SCRs). The MindWalking vocabulary is the same split under different names:
`LP`/`LPA`/zones are tonic statements; `A`/`T`/`BE` are phasic ones. A single derivative
threshold — what `events.py` does today — collapses them.

Because the mindwalker reports **resistance**, an arousal response is a *fall*. Convert once, at
the top of L1: work on **negated LP**, `S(t) = −LP(t)`, so that "SP releases" is a positive-going
response and the entire EDA literature applies unmodified. All amplitudes are reported back in
signed LP units in the output schema (falls negative), because that is what the SL writes down.

Decomposition options, in order of preference:

1. **cvxEDA** (Greco et al. 2016) — convex optimisation, sparse-driver model, principled and
   available under GPL. Cost is a QP over the session; chunk into overlapping ~5-minute blocks.
2. **Continuous Decomposition Analysis** (Benedek & Kaernbach 2010, the Ledalab method) —
   deconvolution against a Bateman impulse response. Well validated, moderate cost.
3. **High-pass / low-pass split** — tonic = zero-phase Butterworth low-pass at ~0.05 Hz, phasic =
   the residual band 0.05–0.5 Hz. Crude, but robust, cheap, and dependency-free.

**Ship (3) first, keep (1) behind a flag.** (3) is enough to define every phenomenon below, has
no license or performance risk, and gives a baseline that (1) must beat on the evaluation set
before it replaces anything. Do not adopt a decomposition because it is more principled; adopt it
because it moved F1.

### 3.2 The primitive set

Computed once, cached alongside the conditioned signal:

- `lp(t)` — continuous LP.
- `tonic(t)` — low-passed LP; the "Ladungspegel" as the SL would read it.
- `phasic(t)` — residual; the needle's momentary movement.
- `dtonic(t)` — tonic slope, LP/s. Sign carries the truth/untruth direction.
- `deflections` — a list of phasic excursions: onset time, peak time, signed amplitude ΔLP, rise
  time, recovery time, recovery fraction (how much of the amplitude returned within N seconds).
  This object *is* the `A`/`T`/`BE` substrate; everything in §6 is a predicate over it.
- `osc(t)` — short-window oscillation descriptors on the native-rate signal: band power in
  0.5–5 Hz, zero-crossing rate of the mean-removed signal, envelope amplitude, and a periodicity
  score (peak of the normalised autocorrelation in the 0.2–2 s lag range).
- `noise_floor` — robust per-session scale from the MAD of the first difference (measured:
  0.00018 LP/sample at 50 Hz). Every threshold below is expressed as a multiple of this or in
  calibrated A-units, never as a bare LP constant.

### 3.3 Why oscillation gets its own band

`SN` and `FN` are not amplitude phenomena; they are *texture* phenomena. Both are the needle
moving without net displacement. They are distinguishable from each other by character, which is
exactly what spectral and periodicity descriptors capture:

|  | SN (schmutzige Nadel) | FN (freie Nadel) |
|---|---|---|
| character | jerky, "flickers up and vanishes" | smooth, free swinging |
| periodicity | low — irregular | higher — pendulum-like |
| net tonic drift | may be rising | flat or gently settling |
| context | mid-conflict, often before a big BE | after discharge, at an EE |
| LP level | anywhere | preferentially 2.0–3.0 (corrected) |
| transcript | uncertainty, hedging, "weiß nicht" | closure, relief, laughter, "ja, genau" |

That table is the feature specification for the L3 discriminator. Note both entries in the last
two rows are *context*, not signal — which is why this discrimination is where a learned model
earns its place.

---

## 4. Calibration

Without this section every absolute claim the system makes is wrong. Three quantities:

**Sensitivity → the A-unit.** The manual defines correct sensitivity as a can-squeeze
(`Dosendruck`) producing a needle fall of one third of the scale = `3A`. The A-unit is therefore
device-and-session specific and *not* derivable from the CSV alone.

- *If* the session contains the calibration ritual, it is detectable: an early, deliberate,
  unusually clean monotone fall, typically with a matching spoken cue. Use it: `1A = Δ/3`.
- *Else* fall back to a **robust per-session amplitude scale**: `1A ≜ ` the 75th percentile of
  unmasked deflection amplitudes, or, when the session is too sparse for that to be stable, the
  nominal `1A = 0.05 LP` (the device's own smallest unit).
- Either way, **report which one was used**, and never print "3A" from the fallback without
  marking it as uncalibrated. A wrong A-unit corrupts the "größte Ladung zuerst" ranking, which
  is the one number the SL acts on.

**Solo offset → the zones.** Our entire real corpus sits at LP 4.4–6.0, which reads naively as an
hour in the Kampfzone. It is the single-hand electrode. The manual's own procedure is to measure
two-handed LP, then solo LP, and carry the difference. We cannot recover that from the file, so:

- accept an optional per-recording `lp_offset` in the analyse request — the solo procedure already
  requires measuring it at every session start and noting it as "Dif.", so this is transcribing a
  number the operator has, not asking for new work — and
- when it is absent, **suppress absolute zone labels entirely** and report *relative* level
  language instead ("upper third of this session's range", LPB, time-in-band). Emitting
  "Kampfzone" for a whole solo session would be a confident, systematic, wrong answer.

**Atemtest → session validity.** If the breath test is present and the needle does not fall, the
manual predicts a dead session. Surfacing that as a report-level warning is cheap and matches
what the SL would conclude.

---

## 5. Cross-modal alignment — the precision lever

The Eiserne Regeln say a deflection counts only if it occurs **at the end of an SL question or an
SP utterance**. That converts the problem from "find changes in a time series" to "find
stimulus-locked responses", which is both a much better-posed problem and much more precise.

Machinery needed:

1. **Turn segmentation** from existing word timings — group words into utterances on pause
   thresholds, and record each utterance's *end* time. These are the stimulus onsets.
2. **Function roles (instruction vs content).** The target corpus is **solo** — one operator,
   one voice, alternating between issuing an instruction and answering it. **Do not add
   diarisation**: there is no second speaker to separate, and `pyannote.audio` would cost a torch
   dependency and a model download against the desktop-bundle budget for nothing. Cue matching
   against the BK3 inventory (plus its solo phrasings) is the role signal directly: a matched turn
   is an instruction, everything between two instructions is content. See
   `session-narrative-design.md` §2.3.
3. **Response window.** Physiological SCR latency is ~1–4 s after stimulus. Score each deflection
   by its onset's position in a response window opened at each utterance end; a deflection with no
   utterance end in the preceding ~1–5 s is *unlocked*.
4. **Instruction/answer amplitude pairing.** "Die Antwort sollte auch ausschlagen, idealerweise so
   groß wie die Frage" — compare the response following an instruction turn against the response
   following the content turn that answers it. A large instruction-response with no
   answer-response is itself a finding.

**Coverage caveat for solo.** Stimulus locking is only as good as the audio, and a solo session
is sparse by design — the reference recording averages 29 words per minute, and some stretches
are worked silently. A large fraction of genuine phenomena will therefore be *unlocked* simply
because nothing was said. This is the strongest reason the `stimulus_locked` flag must be a
confidence input and never a filter: in a duo session, unlocked means suspicious; in a solo
session, it frequently just means quiet.

This buys three things at once: precision (unlocked deflections are down-weighted, not deleted —
coverage matters), the ability to detect **`X`** at all (an SL question with *no* response in its
window — undetectable without the transcript), and **`KVZ`** (signal activity during transcript
silence).

Keep unlocked deflections in the output with a `stimulus_locked: false` flag rather than dropping
them. The user asked for coverage; the right instrument is a confidence field, not a filter.

---

## 6. L2 — Rule-based detectors

Operational definitions. Thresholds are stated as *starting points to be tuned on the evaluation
set*, not as settled values — anything quoted as a bare number here is a hypothesis.

### Deflections: A, T, X

```
deflection d qualifies as an event if
    amplitude(d) is a fall  and  |amplitude(d)| ≥ max(0.5·A_unit, 6·noise_floor·√w)
classify:
    |amp| <  0.5·A_unit          → T   (Ticken)         [reported, not "taken up"]
    |amp| >= 0.5·A_unit          → A   with magnitude round(|amp| / A_unit) in A-units
X: an SL question whose response window contains no deflection ≥ 0.5·A_unit
```

The `0.5A` floor is the manual's own ("Ausschläge unter einem halben A greifen wir nicht auf. Zu
unsicher!"). Encoding the method's stated reliability threshold rather than inventing one is the
whole point.

### BE (Blitzentladung)

The defining property in the manual is not size — it is explicitly "die Größe spielt keine Rolle"
— but that **the needle does not return by itself**. That is a *non-recovering* response: a fast
fall whose level does not come back.

```
BE if:
    fast fall:      rise_time ≤ ~3 s  and  |amp| ≥ 0.05 LP (device granularity)
    non-recovery:   recovery_fraction ≤ ~0.3 within 10 s
                    i.e. a persistent tonic step accompanies the phasic response
    not an artefact: passes the KB discriminator (§7)
magnitude: ΔLP of the tonic step, in LP (the SL reads this off the display)
```

The tonic-step test is what separates BE from a large ordinary `A` (which recovers) and is only
computable because we decomposed. Measured incidence at ≥0.10 LP over 3 s: 131 in 54 minutes.

### LPA (Ladungspegelabfall)

Two distinct things sharing one abbreviation; emit them as separate types:

- `LPA_slow` — a sustained tonic decline without a fast onset: `dtonic < 0` held for ≥ ~20 s with
  total drop ≥ 1 A-unit and no qualifying BE inside. The needle "creeps right".
- `LPA_total` — an aggregate, not an event: the summed discharge over a topic segment (§8), i.e.
  `tonic(start) − tonic(end)` plus the enclosed A and BE magnitudes. This is the quantity the
  "größte Ladung zuerst" ranking is actually over, so it must be computed per topic segment, not
  per event.

### LPD, LPB, zones

Windowed session statistics rather than point events:

- `LPD` — total variation of the tonic signal per minute, in A-units/min, over a sliding window
  (~2 min). High LPD = "something is going on". Report as a continuous track, plus per-topic
  aggregates, because the manual ties LPD proportionally to the SP's interest in a topic.
- `LPB` — max − min of tonic LP over the session. One number.
- zones — only with a calibrated offset (§4); otherwise relative bands.

### SN and FN

Rule-based *candidate generation*; the actual SN/FN decision is L3.

```
oscillatory span candidate if, over a window of ≥ ~5 s:
    envelope amplitude ≥ 3·noise_floor
    |net tonic displacement| < 0.3 · envelope amplitude      (movement without displacement)
then FN-leaning if:  periodicity high, envelope smooth (low envelope-derivative variance),
                     |dtonic| small, preceded within ~60 s by discharge (A/BE), LP settling
     SN-leaning if:  periodicity low, envelope ragged, dtonic ≥ 0
```

`FN` additionally has strong contextual priors — it terminates a topic, it co-occurs with the SL
confirming ("gute Bestätigung macht gute FNs"), and at a real EE the corrected LP is 2.0–3.0.
Those go to the discriminator as features, not into the rule.

### KB and faults

Candidate artefacts from §2.2 that survived masking. A KB's discriminating property against a BE
is *kinematic*: rise times below the SCR physiological floor (~0.5 s), symmetric bipolar shape,
and no accompanying utterance in the response window.

---

## 7. L3 — Classical machine learning

### Where learning is actually needed

Only where a rule is provably ambiguous. Three binary problems, in descending order of value:

1. **BE vs KB** — the manual singles this confusion out. Consequence of an error: a body movement
   is reported as an important statement, and the SL is sent to the wrong place in the transcript.
2. **SN vs FN** — opposite meanings (conflict vs resolution) from superficially similar traces.
   Consequence of an error: the report claims a session reached its end result when it did not.
3. **Real A vs noise** near the 0.5A floor — pure coverage/precision trade, and the place where a
   calibrated probability is worth more than any threshold.

Everything else the rules do adequately, and a classifier over them would add opacity for nothing.

### Model choice

**Gradient-boosted trees** (`scikit-learn` `HistGradientBoosting`, or LightGBM) on engineered
features. Reasons, in order: works at n ≈ hundreds of labelled examples where a neural net does
not; handles heterogeneous feature scales; gives feature importances the domain expert can
sanity-check against the manual; ships in a few MB, which matters for the PyInstaller bundle.
Calibrate probabilities with isotonic regression on a held-out fold — the confidence field is
consumed by the UI ranking, so it needs to mean something.

Feature vector per candidate (≈40 features): amplitude (LP and A-units), rise/recovery times,
recovery fraction, tonic step, pre/post tonic slope, oscillation descriptors in three windows
(2/5/15 s), local noise floor ratio, position in session (fraction), local LPD, distance to
nearest utterance end, speaker role of that utterance, silence duration around the event, word
rate in ±10 s, and a handful of lexical flags (BK3 cue present, hedging markers, confirmation
markers, laughter).

### The label problem, and how to get around it

There are no labels. There are three sessions. Standard supervised learning is not available yet,
so the design has to include the bootstrap:

- **Weak supervision.** The L2 rules *are* labelling functions in the Snorkel sense. Write several
  deliberately different ones per class (a conservative BE rule, an aggressive one, a
  transcript-only one), fit a label model over their agreements, and train the classifier on the
  probabilistic labels. This gets a working model with zero human annotation and — importantly —
  makes rule disagreement measurable, which is where annotation effort should be spent.
- **Active learning.** Rank unlabelled candidates by classifier uncertainty and ask the human to
  label only those. At ~500 BE candidates per session, labelling the 50 most ambiguous is an
  evening, not a project.
- **The `Tag Number` column.** The device already exports a per-sample annotation channel and it
  is empty in every file. If the SL can tag during a session, ground truth arrives for free with
  every future recording. Supporting tag ingestion is a small change with a large long-term
  payoff and should be near the front of the roadmap.
- **The Sitzungsbericht.** The method *requires* the SL to write down every LP change and every
  deflection. Existing handwritten protocols are a gold-standard corpus that already exists;
  parsing even a few into event lists would give a real evaluation set immediately.

### Session-state modelling

`Abflachung`, `ÜBZ`, `zähe Sitzung` and `EE` are *persistent states*, not instants, and they have
strong transition structure (you cannot have an ÜBZ that is not preceded by an EE or an
Abflachung). Model them as such rather than as thresholds:

- **HSMM / semi-Markov CRF** over 5-second frames with states
  `{exploring, heating, discharging, flattening, end_result, overrun, sticky, artefact}`.
  Explicit duration modelling matters — an EE is not a 5-second state, and a Markov chain will
  fragment it.
- Emissions from the L1/L2 feature track plus transcript features.
- Enforce the method's own grammar as hard transition constraints. This is where domain knowledge
  buys accuracy that data cannot: `overrun` reachable only from `end_result`/`flattening`, and
  `sticky` as a session-level latent rather than a segment.

An HSMM trained with weak labels from the rules is a genuinely better fit here than any
discriminative frame classifier, because the constraint structure is known and the data is small.

---

## 8. Deep learning — when, and only when

Being direct: **the corpus today is ~106 minutes across three sessions from one subject, with no
labels.** No deep model should be trained on that, and a design that promised one would be
selling something. What the design should specify is the threshold at which DL becomes the right
answer, and which architecture to reach for then.

### Preconditions

- ≥ 50 sessions, ideally multiple SPs (inter-subject variability in EDA is large; a model fit to
  one person's electrodermal habitus will not transfer, and with one subject we cannot even
  measure that it hasn't).
- A labelled evaluation set built as in §7, independent of the training labels.
- A demonstrated ceiling: the boosted-tree + HSMM stack has stopped improving with more features
  and more labels.

### Architectures, matched to the phenomena

1. **Dense segmentation — 1D U-Net or TCN over the conditioned LP channel.** Multi-label
   per-sample output (`A`, `BE`, `SN`, `FN`, `KB`, background). Right shape for the problem: the
   phenomena are spans of varying length, exactly what segmentation architectures do, and dilated
   convolutions give the multi-minute receptive field that `zähe Sitzung` needs. Would replace
   L2+L3 for the needle phenomena, not L0/L1.
2. **Self-supervised pretraining.** The blocker is labels, not signal — unlabelled mindwalker
   recordings are cheap. Masked-reconstruction or contrastive pretraining (TS2Vec / TF-C style) on
   all available raw sessions, then fine-tune a small head on the few labelled ones. This is the
   highest-value DL direction *specifically because* it converts the abundant resource into the
   scarce one.
3. **Cross-modal fusion transformer.** For the phenomena that are irreducibly bimodal — `EE`,
   `ÜBZ`, `X`, `KVZ`, and the Frohsinn/Apathie/Paranoia FN distinction. Signal encoder (from 2)
   plus a German sentence encoder over transcript turns, cross-attention, sequence head. This is
   the only place where DL does something the classical stack structurally cannot: judge whether
   what was *said* around an FN indicates a genuine insight.
4. **What not to do.** Do not put a raw end-to-end model in front of the whole pipeline. The L0
   conditioning and calibration are domain physics, not learnable nuisance, and discarding them
   would force the model to rediscover log-resistance from three sessions. Do not use a large
   pretrained time-series foundation model here either — the sampling regime and the semantics are
   far outside its pretraining distribution, and it would blow the desktop bundle budget.

### Deployment constraint

Anything shipped must survive `CLAUDE.md`'s packaging rules: no ffmpeg CLI, no unbounded model
downloads, MLX/onnxruntime cannot share a process. A TCN small enough to run in ONNX or MLX is
fine; anything requiring torch at runtime needs its own decision about whether the desktop build
carries it. Prefer exporting to a runtime already in the bundle over adding a second one.

---

## 9. Fusion, ranking, output

### Schema

One `Phenomenon` type replaces today's untyped event dict:

```python
@dataclass
class Phenomenon:
    id: str
    kind: PhenomenonKind          # A | T | X | BE | LPA_SLOW | SN | FN | KB | ...
    t_start: float                # seconds
    t_end: float                  # == t_start for instants
    amplitude_lp: float | None    # signed; falls negative
    amplitude_a: float | None     # in calibrated A-units; None if uncalibrated
    confidence: float             # calibrated probability
    stimulus_locked: bool
    utterance_id: str | None      # the turn it responds to
    detector: str                 # which layer/rule produced it
    evidence: dict                # features, for the UI's "why" panel
```

`id` must be **content-derived and stable** — hash of `(kind, rounded t_start, rounded amplitude)`
— not the sample index. Today's `evt-{idx}` changes whenever the parse changes, which breaks any
attempt to persist human labels against events. Since labelling is the critical path for
everything in §7, stable ids are a prerequisite, not polish.

### Ranking

The method's own rule is **"Größte Ladung zuerst"**, over `LPA_total` per topic segment, not over
individual deflection amplitude. Ranking must therefore be computed after topic segmentation
(§ session-narrative design), and the UI should present topics ranked by total discharge with
their constituent phenomena nested — which is how the SL thinks — rather than a flat event list.

### Coverage vs accuracy

The user's stated priority is both, which in practice means: **detect generously, rank honestly.**

- Report everything above the manual's own floors, including `T` and unlocked deflections.
- Never hide a detection behind a threshold when a confidence field can carry the doubt.
- Offer operating points as presets rather than one setting, replacing today's
  `default`/`sensitive`/`strict`: a recall-first mode for review, and a precision-first mode for
  the auto-generated Sitzungsbericht where a false BE is expensive.

---

## 10. Evaluation

Without this the rest is unfalsifiable.

**Ground truth**, in order of availability: existing handwritten Sitzungsberichte (parse to event
lists); `Tag Number` annotations from future sessions; a labelling mode in the NeuroNarrative UI
itself, which is the natural home for it since the operator is already looking at the trace with
the audio aligned.

**Metrics.**

- Event-level precision/recall/F1 per phenomenon class, with a matching tolerance on onset (±1 s
  is the convention in the SCR literature; ±2 s is defensible here given ASR timing slop).
- Report the **full PR curve**, not a single F1 at a fixed threshold — the whole point of the
  confidence field is choosing an operating point per use case.
- Span phenomena (`SN`, `FN`, states) scored by frame-wise F1 *and* segment IoU; the two disagree
  in informative ways when a detector fragments a long span.
- Session-level: LPB and LPD error against the SL's own notes; agreement on whether an EE occurred.
- **Ablations that must be run**, because each corresponds to a claim in §0: kΩ vs LP domain;
  with vs without stimulus locking; rule-only vs rule+ML; decomposition (3) vs (1).

**Guard tests** to keep in `backend/tests/`, in the spirit of the existing
`test_long_recording_stays_bounded`: a synthetic signal with injected phenomena of known type and
time (round-trip recovery), an artefact-injection test (KB never reported as BE), a calibration
test (same physiological event at LP 2.5 and LP 5.5 yields the same A-magnitude — this fails
today by construction), and a runtime/RSS bound on a 60-minute 50 Hz input.

---

## 11. Roadmap

Ordered by value per unit of risk. Each stage is independently shippable and independently
verifiable. **Stages 1-6 are implemented** (2026-08-02); §12 records where the implementation
diverged from the plan and why. Stages 7 and 8 are both blocked on labels, which have not been
made — see `status.md`.

| # | Stage | Status |
|---|---|---|
| 1 | **L0 conditioning + shared channel resolver + LP domain** | ✅ `phenomena/conditioning.py`, mirrored in `gsrParser.ts` |
| 2 | **L1 primitives + `A`/`T`/`BE`/`LPA`/`LPD`/`LPB` rules** | ✅ `phenomena/primitives.py`, `detectors/{deflection,discharge,level}.py` |
| 3 | **Stimulus locking + `X` + `KVZ`** | ✅ `protocol.py`, `detectors/stimulus.py` |
| 4 | **Calibration + artefact masking + honest zone reporting** | ✅ `calibration.py`, `detectors/artefact.py` |
| 5 | **Stable ids + labelling mode + `Tag Number` ingestion** | ✅ `services/labels.py`, `/api/labels/*`, verdict buttons in `PhenomenaPanel.tsx`, tags read in `conditioning.py` |
| 6 | **Evaluation harness** | ✅ `phenomena/evaluate.py` + `POST /api/labels/{id}/evaluate`. **Weak supervision and the BE-vs-KB / SN-vs-FN classifiers are not started** — they need labels to exist first, and none have been made yet |
| 7 | **HSMM session states: Abflachung, ÜBZ, EE, zähe Sitzung** | ◻ |
| 8 | **DL, if and only if §8's preconditions are met** | ◻ gated |

Stage 5 is built, which moves the bottleneck from *tooling* to *effort*: the app can now record
verdicts, but no verdicts have been recorded. Until some are, every accuracy number in §13 is
still a count rather than a measurement. Reviewing even the 34 BEs on the reference recording
would give the first real precision figure the project has ever had.

---

## 12. As built — where the plan was wrong

Recorded because each of these was a real defect that produced *plausible* output, which is the
dangerous kind.

**Peak finding cannot represent a Blitzentladung.** §6 specified deflections as extremum pairs.
A BE is by definition a fall that stays down, and a monotone step has no local minimum, so
`find_peaks` could only ever catch the ones where noise happened to leave a dip — 13 on the
reference recording, against 34 once the segmentation was replaced with hysteresis legs. This was
the single most important phenomenon in the catalogue, silently under-detected by ~3x.

Hysteresis segmentation then needed two corrections of its own, neither anticipated:

- a **stall timeout**, because two discharges separated by a quiet plateau never reverse and so
  merged into one leg reporting their combined amplitude;
- **onset and peak trimming**, because a leg begins at the previous turning point and ends at a
  running extreme, which made `rise_time_sec` the age of the recording rather than the speed of
  the response. Rise time is the BE criterion, so this disabled BE detection a second time.

**`BE_MAX_RISE_TIME_SEC = 3.0` cut the population at its median.** Measured on the reference
recording the median rise time is 3.62 s, so the proposed threshold discarded about as many
candidates as it kept. Now 5.0 s — the upper edge of the standard SCR range, and where the count
plateaus in all three sessions. Still unvalidated; the manual never quantifies "schnell".

**A fixed artefact rate threshold does not work.** §2.2 proposed `|dLP/dt| > ~2 LP/s`. The
clearest artefact in the corpus — a 0.37 LP excursion eight seconds into the 54-minute session, 23x that
session's normal maximum rate — sits at 1.57 LP/s and slipped under it. The rule is now
session-relative (`median + 40*MAD`) with a floor at 1.0 LP/s. The floor matters in the other
direction: an initial 0.15 LP/s floor was *inside* the physiological range and masked genuine
deflections.

**Body movements are reported, not silently masked.** The manual requires a `KB` to be marked in
the protocol. An operator reading "body movement at 0:09" is better served than one wondering why
a visible excursion produced nothing.

**Per-kind ranking weights were removed.** An earlier version weighted BE 3x and LPA 2x, which
let a 0.29 LP slow discharge outrank a 0.36 LP deflection. "Größte Ladung zuerst" is a statement
about charge; the weighting was us ranking, not the method. Only `T` is deprioritised, and only
because the manual explicitly says it is too uncertain to take up.

**Cue matching had to become tolerant, twice.** Exact token equality matched 13 instruction turns
out of 303 on the reference transcript. Two fixes took it to 29: stem-tolerant token comparison
(the transcript renders "Ruf dir" as "ruft ihr", "Ruf der", "Rucht ihr", "Huf dir", "Hufe dir";
"beschreib" as "beschreibe"/"beschreibst"/"Beschreiwest") and a separate group of cue phrasings
**observed in this operator's practice but absent from BK3** — "Was ist jetzt am deutlichsten",
"Was siehst du noch". The manual is the authority on the method; the transcript is the authority
on what was said. Two subtler bugs sat underneath: `_ordered_overlap` advanced its cursor on a
miss, so one dropped word made every later token unmatchable, and scoring by raw matched count
tied "ruf dir ein Erlebnis zurück" (5 of 5) against "ruf dir ein weiteres Erlebnis zurück" (5 of
6) so that inventory order decided it and no procedure ever opened.

**Deviations from the plan that were deliberate.** Resampling to 20 Hz (§2.3) is not implemented:
real exports are 50 Hz and filtering 161k samples costs milliseconds, so it would add index
mapping for no measured benefit. Signals stay in LP rather than being negated to conductance
polarity (§3.1); the flip only matters when adopting a published decomposition, which is still
deferred. Diarisation (§5) was dropped entirely — the corpus is solo, one voice, so there is
nothing to separate and cue matching carries the role signal by itself.

---

## 12a. Labelling and evaluation, as built

**Recording identity is a content hash** of the GSR export, not a filename. The same recording is
copied and re-staged into the upload cache under a fresh name every time it is analysed, and a
label set that did not survive that would be worthless.

**Four verdicts**, because two are not enough to measure both halves:

| verdict | meaning | scores as |
|---|---|---|
| `confirmed` | the detection is real | true positive for its kind |
| `rejected` | it is not | false positive for its kind |
| `reclassified` | real, but a different kind | false positive for the claimed kind *and* a false negative for the actual one |
| `missed` | something real the detector never proposed | false negative for its kind |

`missed` is the one that matters most and the easiest to leave out. Without it recall is 1.0 by
construction, so `Evaluation.has_recall_evidence` is reported alongside every result and the
report says so in plain words when it is false.

**An unreviewed detection is unknown, not wrong.** It counts toward `unlabelled` and toward
nothing else. Treating unreviewed detections as false positives would make precision a function
of how tired the operator was.

**Matching tolerance is ±2 s** by default. The SCR literature conventionally uses ±1 s; the extra
second covers ASR timing slop and the 0.5 s smoothing window, and it is a request parameter so it
can be tightened once there is enough data to see whether it matters.

**Device tags are ingested.** `Tag Number` exists in every export and is empty in all of them.
`conditioning.py` reads it, collapsing consecutive identical values, and surfaces the marks on the
analysis result. If the operator starts tagging during a session, ground truth arrives for free
with every future recording.

---

## 13. Measured, on the reference recording

`the 54-minute reference session, 53.9 minutes, 161 750 samples at 50 Hz, 1 576 transcript
words.

| | |
|---|---|
| channel | `data+baseline`, 9.2e-5 LP resolution |
| conditioning + detection | 0.05 s and 0.09 s |
| A / T / BE / LPA_slow | 115 / 183 / 34 / 19 |
| X / KVZ / KB | 19 / 30 / 1 |
| LPB / LPD | 1.52 LP / 3.7 A-units per minute |
| artefact masked | 0.2% (one span, 6.98-12.36 s, body movement) |
| protocol tree | FRR 7.4-23.6 min (8 exercises), EZM 23.6-49.5 min (5 passes), FRR 49.5-53.9 min (2) |
| instruction turns matched | 29 of 303 |
| stimulus-locked | 191 locked, 179 unlocked, 31 not applicable; 68 of 149 A/BE locked |

The protocol tree follows BK3's prescribed order (FRR before EZM) without being told to, which is
weak but real evidence that the cue matching is finding the right things.

Two caveats on these numbers. The A-unit is a **fallback** (0.060 LP), so every A-magnitude is
indicative and no charge zone is named — the session reads LP 4.45-5.97, which without a
solo-electrode offset would print as "Kampfzone" for 54 minutes. And nothing here is validated
against labels; these are self-consistency checks, not accuracy measurements. That is what stage
6 is for.
