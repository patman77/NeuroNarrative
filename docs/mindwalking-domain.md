# The MindWalking domain

Reference layer for the two source manuals. Everything in `phenomena-detection-design.md` and
`session-narrative-design.md` is built on the definitions here, so this file is the place to
correct a misreading of the method — not those two.

Sources, both by Rolf-Ulrich Kramer (`~/Documents/mindwalking/2025-10-10-Skripte/`):

- **mw-Kurs** — *Wie man den MindWalker benutzt*, version 24.08.2023. The device manual: what
  the instrument measures, how the session leader reads it, and the full glossary of phenomena.
- **BK3** — *Das Persönliche Entwicklungsprogramm (Basiskurs 3)*, version 10.09.2024. The session
  protocol: the PEP sequence and its scripted instructions, verbatim.

Together they say what a NeuroNarrative recording *is*: a MindWalking sitting, in which a session
leader (SL) reads a GSR instrument live while working a session partner (SP) through a scripted
recall procedure. The GSR CSV is the instrument trace; the WAV is the scripted dialogue. Our
analysis is a retrospective, automated version of the running commentary the SL is required to
keep by hand ("bitte jede Veränderung des LP notieren!").

---

## 1. The instrument

The *mindwalker* is a GSR biofeedback device. The SP holds electrodes (two hands in a duo
session, a single-hand electrode in solo); the device measures skin resistance between them and
presents it two ways:

- a **needle** (`Zeiger`) whose short-term movement shows momentary change, and
- a **Ladungspegel (LP)** — "charge level" — a digital read-out of the standing resistance on a
  compressed scale from **1.0 to 6.5**.

The manual gives the LP↔resistance anchors as roughly 1.0 ≈ 600 Ω, 2.0 ≈ 5 kΩ, 6.0 ≈ 280 kΩ and
notes the relationship is "approximately logarithmic". Our own recordings confirm this precisely
(§4): **LP is log-resistance, ~2.9× per LP unit.**

### Directionality — the single most important convention

| Needle | LP | Physiology | Meaning in the method |
|---|---|---|---|
| **falls** (to the right) | goes **down** | resistance drops | availability, relief, *truth* — "hier liege ich richtig" |
| **rises** (to the left) | goes **up** | resistance rises | resistance, defence, *untruth* or half-truth |

Note that this is inverted relative to the standard psychophysiology literature, which works in
**conductance** (µS), where an arousal response is a *rise*. Resistance down = conductance up = a
skin-conductance response. A `Blitzentladung` is, in EDA terms, a large fast SCR. This equivalence
is what lets us borrow forty years of validated EDA algorithms (§ *Signal decomposition* in the
detection design).

### The four charge zones

| LP range | Zone | Reading |
|---|---|---|
| 1.0 – 2.0 | **Opferzone** | no defence; the SP submits, sympathises, identifies with what surfaces |
| 2.0 – 3.0 | **Normalzone** (green) | no fixed attention, no tension |
| 3.0 – 3.5 | **Alarmzone** (yellow) | something is starting to boil |
| 3.5 – 6.5 | **Kampf-/Täterzone** (red) | active defence between wanting and not wanting to know |

A good end result settles the LP between 2.0 and 3.0 with a free needle.

**Zones are not directly usable on a raw recording.** The manual is explicit that the LP is
distorted upward by a single-hand solo electrode, dry or cold hands, and constricted circulation,
and downward by sweaty hands. The solo procedure is to measure LP two-handed, then with the solo
electrode, note the difference (e.g. "Dif. 0.8") and mentally subtract it for the rest of the
session. Any zone label we emit must carry the same correction, per recording — see calibration
in the detection design.

---

## 2. Phenomenon catalogue

Consolidated from the mw-Kurs body text and its `GLOSSAR DER ABKÜRZUNGEN`. Starred entries are
the ones the manual itself marks as mindwalker-user vocabulary. This is the target list for
detection; each row's signal signature is worked out in `phenomena-detection-design.md`.

### Needle-level

| Code | Name | Manual definition |
|---|---|---|
| **A*** | Ausschlag | A fall of the needle. Measured in scale divisions: `A`, `2A`, `3A`… Means the SP touched something available and true. Deflections under ½A are not taken up — too unreliable. |
| **T*** | Ticken | The smallest deflection, "like the second hand on a station clock". Noted, but a series of ticks is felt out, not drilled into. |
| **X*** | Kein Ausschlag | *No* deflection where one was expected. Recorded as an observation in its own right. |
| **SN*** | Schmutzige Nadel / Zitternadel | The needle dances back and forth in short movements — the SP oscillating between knowing and refusing to know. Can be as narrow as a tick or as wide as the whole scale. Means uncertainty about *what is at issue*, or the approach to something very violent. Follow it until it resolves into real A's or vanishes. |
| **FN*** | Freie Nadel / Alphanadel | Free, unimpeded swinging. Attention is no longer fixed, so nothing brakes or drives the needle. Marks an end result: recognition + cheerfulness + FN. May be broad or narrow, long or short. At a genuinely good end result the LP sits between 2.0 and 3.0. |
| **KB*** | Körperbewegung | Body movement. Produces a **large LPA that must never be confused with a BE** — the manual insists it be marked as an artifact in the protocol. |

The manual distinguishes three *kinds* of FN, which matter because only one is a real result:
the **Frohsinn-FN** (worked through to a genuine, consequential insight), the **Apathie-FN** (in
complete agreement with a hopeless conviction — certainty without relief), and the
**Paranoia-FN** (uncritical belief, unshakeable and unfounded). The signal cannot separate these;
only the transcript can, and even then only weakly. We should not claim otherwise.

### Level-level

| Code | Name | Manual definition |
|---|---|---|
| **LP*** | Ladungspegel | The standing charge level, 1.0–6.5. Every change is to be noted. |
| **BE*** | Blitzentladung | A *fast* charge drop on a specific utterance or question. The needle does **not** return to the measuring point by itself but stays right of it, so the SL must press the button. Size is irrelevant to whether it counts; smallest device unit is 0.05. Means: an important single statement — total pressure in the boiler went down, not just a transient. |
| **LPA*** | Ladungspegelabfall | (a) A *slow* discharge — the needle creeps right rather than snapping. (b) The total discharge on a topic: the sum of its A's and BE's. |
| **LPD*** | Ladungspegeldynamik | The LP moving busily up and down — the sign that "something is going on" in the session. Interest in a topic and LPD are directly proportional: hot topic = much LPD. |
| **LPB*** | Ladungspegelbereich | The span between the maximum and minimum LP within a session. |

Ranking rule the whole method leans on: **"Größte Ladung zuerst"** — pursue the largest discharge
first. Since a BE of 0.3 and a 3A deflection are not comparable without knowing the sensitivity
setting, the manual has the SL calibrate the A-unit against a can-squeeze before deciding.

### Session-level

| Code | Name | Manual definition |
|---|---|---|
| **EE** | Endergebnis | Charge gone, information present, freeing insight, FN. The target state. |
| **Abflachung** | flattening | A sub-point is exhausted: no emotional dynamic, no more deflections. Close it and move to where something still moves. |
| **ÜBZ** | Überziehung | Overshooting past a good point (EE or Abflachung). The LP will rise and the session degenerates into aimless talk. Requires an `ERK` (Erfolgsrekonstruktion) to repair. |
| **zähe Sitzung** | sticky session | The LP is chronically high and springs back up as soon as it touches normal, despite plenty of LPD. A named pathology, not a detection failure. |
| **KVZ** | Kommunikationsverzögerung | Delay between question and answer — the SP says nothing but the needle and LP move. More KVZ = more uncertainty. Explicitly a cross-modal phenomenon. |
| **SP sitzungsuntauglich** | unfit mid-session | Needle movement falls asleep and the LP rises *even on gains and insights* — the SP has become hungry or exhausted. |

### Calibration and fault

| Item | Definition |
|---|---|
| **Empfindlichkeit** | Sensitivity. Set so that a firm squeeze of the electrode ("Dosendruck") drops the needle by about a third of the scale = 3A. Typically 1–2.5. Defines the A-unit for the session. |
| **Atemtest (AT)** | Deep in, forceful out. The needle must fall (metabolic, not mental). A dead AT predicts a dead session and prompts the SL to check sleep/food/drink. |
| **Übergangswiderstand** | Contact resistance from skin moisture and grip pressure. Confounds the LP and must be watched but carries no mental meaning. |
| **Kabelbruch** | Broken cable. Documented symptom: LP pinned at 6.5, crashing to 0.95, back to 6.5. |

---

## 3. The session protocol (BK3)

BK3's **PEP** (Persönliches EntwicklungsProgramm) is a fixed sequence of named procedures, each
with **verbatim scripted instructions**. Those instructions are the grammar our transcript parser
keys on. Reproduced here as the authoritative cue inventory.

### 1. Das Mini-Interview
Establishes the session topic and the Negativprogramm (NP). `SAFRA?` is the routine opener after
a break: *"Ist dir seit der letzten Sitzung etwas durch den Kopf gegangen, das du sagen oder
fragen möchtest?"*

### 2. Der Freie Rückruf (FRR)
Lets the SP orient freely in memory; gradually heats the experiences underlying the hot topic.

> 1a. **"Ruf dir ein Erlebnis zurück, als … ⟨Sitzungsthema oder NP⟩"**
> 1b. **"Beschreib es mir."**
> 1c. **"Was ist dir dabei am deutlichsten?"**
> 2a. **"Ruf dir ein weiteres Erlebnis zurück, als …"**
> 2b. "Beschreib es mir." 2c. "Was ist dir dabei am deutlichsten?"

Repeated until the SP runs dry, then on to the KRR. Experiences are told in the **present tense**.

### 3. Der Kettenrückruf (KRR)
Recall in temporal chains rather than random order, to reach the Urerlebnis (URL) at the head of
the chain.

> 1a. **"Ruf dir das früheste Erlebnis zurück, an das du dich jetzt gerade erinnern kannst, als ⟨Thema/NP⟩."** — "Erzähl mir davon." — "Wann etwa war das?"
> 1b. **"Wann im Geschehnis hast du dich am stärksten so gefühlt wie ⟨Thema⟩?"**
> 2a. **"Ruf dir nun das nächstspätere Erlebnis in Richtung Gegenwart zurück, als ⟨Thema⟩."** — "Erzähl mir davon." — "Wann etwa war das?"

### 4. Die Erzählmethode (EZM)
Works one experience systematically from beginning to end, repeatedly, until the EE.

> 1. **"Was siehst du genau? Beschreibe mir, was du jetzt gerade siehst und empfindest."**
> 2. **"Geh das Erlebnis durch bis zum Ende. Beschreibe jede Einzelheit in aller Deutlichkeit."**
> 3. **"Geh zum frühesten Einstieg in das Erlebnis, der sich dir jetzt zeigt."**
> EZM "flott": **"Nochmal von Anfang bis Ende bitte, aber jeweils nur das, was dir deutlich ist!"**
> **"An welcher Stelle im Geschehnis entstand das NP?"**

Driving questions during the pass: *"Und was war dann?"* — *"Und dann?"* — *"Und wie war das
genau?"* The `D?` ("Deutlich?") question belongs here too. Steps 1–3 may cycle twenty to thirty
times over one Urerlebnis.

### 5. Die Wiederholungstechnik (WT)
Re-provokes a closed topic to confirm the FN holds under pressure.

### The action loop
The manual states the SL's operating cycle explicitly, and it is the reason cross-modal alignment
matters more than any signal trick:

> Anweisung bzw. Frage → Reaktion (psychisch / elektronisch) → Auswertung → Anweisung … bis
> schließlich: Frage → Erkenntnis & FN → Schluss.

with the constraint, from the **Eiserne Regeln**:

> - Nur aufgreifen, was ausschlägt!
> - **Nur Ausschläge berücksichtigen, die am Ende der Frage des SL oder der Äußerung des SP auftreten!**
> - Die Antwort sollte auch ausschlagen, idealerweise so groß wie die Frage.
> - Größte Ladung als erstes aufgreifen!
> - Jedes aufgegriffene Thema zum Abschluss mit FN bringen!

A deflection that is not time-locked to an utterance boundary is, by the method's own rule, not
evidence. Our current detector has no notion of this.

---

## 4. What the recordings actually contain

Measured on `~/Documents/mindwalking/2024-11-SVB-Solo/mindwalker-recordings/` (three substantial
solo sessions plus two fragments; 24.0, 28.4 and 53.9 minutes, each with a paired WAV).

The real export schema is **not** what our fixtures use:

```
Time(msec), Data(16 bit), Baseline, Resistance(kOhm), Tag Number
        0,        60058,       6.0,        213.3044,
       20,        60066,       6.0,        213.6474,
```

- **50 Hz** (20 ms), uniform, across every file.
- `Baseline` is the **LP**, quantised to 0.05 steps, auto-tracking (948 window changes in 54 min).
- `Resistance(kOhm)` is the derived resistance.
- `Data(16 bit)` is the raw ADC value and is a **perfectly linear function of LP**:
  `Data = 10883·LP − 5235` (fit against Baseline; residual ≤ 0.027 LP, which is the 0.05
  quantisation of Baseline itself). It therefore carries LP at a resolution of **~0.0001 LP**,
  ~500× finer than `Baseline`.
- The log relationship is confirmed: `ln R[kΩ] = 1.0157·LP − 1.0045`, r² = 0.988 → **×2.76 per LP
  unit** (manual's anchors imply ~2.9; close enough that the manual's figures are round numbers).
- Noise floor on continuous LP: per-sample MAD **0.00018 LP**. The device's own smallest quoted
  unit (0.05 LP) is ~270× that. Even a `Ticken` is comfortably resolvable.
- `Tag Number` exists in every file and is **empty in all of them**. It is a per-sample annotation
  channel the device already supports — the obvious carrier for ground-truth labels.

Two consequences that change the current implementation, not just the future one:

1. **`Data(16 bit)` is the signal we should be analysing**, converted to a continuous LP. The
   backend currently analyses `Resistance(kOhm)`, i.e. an exponential warp of the perceptual
   scale — the same physiological event at LP 5.5 produces roughly 15× the kΩ delta it produces
   at 2.5, so thresholds cannot be uniform across a session. The frontend, independently, scores
   the `Baseline` column *highest* (`{ match: /baseline/, bonus: 0.4 }` in `gsrParser.ts`) and so
   draws the 0.05-quantised staircase. That is the true cause of the "jagged, low resolution"
   plot reported earlier; the monotone spline smoothed the symptom.
2. **This corpus is solo.** Its LP runs 4.42–6.02 — nominally "Kampfzone for 54 minutes", which
   is not a plausible reading. It is the single-hand electrode offset the manual warns about. Zone
   labelling without a per-recording offset would be confidently wrong on every real session we
   have.

### Order-of-magnitude event rate

On the 54-minute session, counting 3-second falls in continuous LP: **492 exceed 0.05 LP** (the
device's own BE granularity) and **131 exceed 0.10 LP** — about 2.4 per minute. The current
detector returns **23 events** for that recording. Whatever the right operating point turns out
to be, the phenomenology implies we are an order of magnitude short of the manual's own notion of
what is worth writing down.

---

## 5. Glossary of abbreviations used in these docs

`A` Ausschlag · `AT` Atemtest · `BE` Blitzentladung · `BK3` Basiskurs 3 · `D?` "Deutlich?" ·
`EE` Endergebnis · `ERK` Erfolgsrekonstruktion · `EZM` Erzählmethode · `FN` Freie Nadel ·
`FRR` Freier Rückruf · `KB` Körperbewegung · `KRR` Kettenrückruf · `KVZ`
Kommunikationsverzögerung · `LP` Ladungspegel · `LPA` Ladungspegelabfall · `LPB`
Ladungspegelbereich · `LPD` Ladungspegeldynamik · `NP` Negativprogramm · `PEP` Persönliches
EntwicklungsProgramm · `SAFRA` routine re-entry question · `SL` Sitzungsleiter · `SN` Schmutzige
Nadel · `SP` Sitzungspartner · `T` Ticken · `ÜBZ` Überziehung · `URL` Urerlebnis · `WT`
Wiederholungstechnik · `X` kein Ausschlag · `2G` Zwiegespräch
