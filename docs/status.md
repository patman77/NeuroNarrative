# Current state

Living snapshot: what is built, what it measures, and what is unproven. Updated 2026-08-02.

The reference documents are `mindwalking-domain.md` (the method, extracted from the two source
manuals), `phenomena-detection-design.md` (the detector, with an "as built" section recording
where the design turned out to be wrong) and `session-narrative-design.md` (the protocol parser
and the report).

---

## What exists

Stages 1–6 of the detection roadmap, plus the session narrative and the review UI. Exercised by
**198 backend tests** and **23 Playwright E2E tests**.

### Signal

| Layer | Module | What it does |
|---|---|---|
| L0 conditioning | `phenomena/conditioning.py` | Resolves any export to a continuous LP channel: `Data(16 bit)`+`Baseline` → `Resistance`+`Baseline` → `Resistance` → `Conductance` → bare `Baseline`. Reads the device's `Tag Number` annotations. Mirrored in `gsrParser.ts`, pinned by a shared golden fixture. |
| L0 artefacts | `detectors/artefact.py` | Rails, session-relative excessive movement, electrode settling. Movement is reported as `KB`, not silently dropped. |
| L1 primitives | `phenomena/primitives.py` | Tonic/phasic split; hysteresis leg segmentation with stall timeout and onset/peak trimming; robust noise scale. |
| L2 detectors | `detectors/{deflection,discharge,level}.py` | `A`, `T`, `BE`, `LPA_slow`, `LPB`, `LPD`. |
| L3 cross-modal | `detectors/stimulus.py`, `services/protocol.py` | BK3 cue inventory (duo, solo and observed phrasings), turn segmentation, function roles, the procedure/exercise tree, stimulus locking, `X`, `KVZ`. |
| Calibration | `phenomena/calibration.py` | Optional `lp_offset` and `a_unit_lp`. Without them no charge zone is named and every A-magnitude is flagged uncalibrated. |

### Review and reporting

| Feature | Module |
|---|---|
| Labels — confirmed / rejected / reclassified / missed, keyed on content-derived ids, atomic writes | `services/labels.py`, `/api/labels/*` |
| Evaluation — per-kind precision/recall/F1, ±2 s onset tolerance | `phenomena/evaluate.py` |
| Session narrative — one section per protocol segment, real times and charge levels, markdown export | `services/narrative.py`, `SessionNarrative.tsx` |
| Phenomena panel — ranked "Größte Ladung zuerst", kind filters with All/None, one-click verdicts | `PhenomenaPanel.tsx` |
| Cross-panel linking — filters drive the timeline markings; hovering anywhere highlights and scrolls everywhere else, including the detail chart travelling to a marker pointed at in the overview | `App.tsx`, `utils/smoothScroll.ts` |
| Marked position in both charts — violet cursor for the hovered or clicked moment; a narrative section shades its whole span | `SignalPreview.tsx` |
| Speech-bubble labels — kind and A-magnitude for what is being pointed at, packed into lanes so none overlaps | `SignalPreview.tsx` |
| Marker tooltips carrying the speech around a phenomenon, over an adjustable ±n s window (default 3) | `App.tsx`, `SignalPreview.tsx` |
| Resizable, scrollable panes for detected events and the transcript | `ResizablePane.tsx` |
| Two workspace layouts — plot pinned above the lists, or in its own column beside them; switched from the header, remembered | `App.tsx`, `styles.css` |

All three hover directions are verified against a real analysis to mark their target *and* to
leave it inside the visible area of its list — the distinction matters, because an earlier
version highlighted correctly while scrolling the row off screen, which looks identical to
highlighting nothing.

Pointing at a narrative section marks every filtered phenomenon it contains, in the list and as
labelled bubbles over both traces; pointing at a single phenomenon labels that one. The labels
are laid out in lanes and are guaranteed not to overlap — the E2E test checks every pair of
bubble rectangles, because a cluster of phenomena is exactly where the labels matter and exactly
where naive placement stacks them into one illegible pile. What does not fit is reported as
"+N more" rather than drawn on top of something else.

A click does two further things. It leaves the moment marked after the pointer has gone, so what
you jumped to is still identifiable while you read the row that produced it. And it repositions
the page on the **charts** rather than the top of the preview card — that card opens with some
700 px of gauge, metrics and waveform, so the old anchor left the charts mid-window and threw the
clicked row below the fold. Measured: the charts and their headings occupy ~1080 px, so in a
shorter window the charts and the row cannot both be shown and the charts win.

Scrolling down to a list used to take the plot off screen entirely. There are now two layouts for
that, switched from the header and remembered: **stacked** pins the charts to the top of the
window with the lists scrolling underneath — the gauge and waveform stay above them in the card
and scroll out of view — and the lists are sized to whatever the window has left rather than to a
fixed fraction of it. It needs a window at least 1000 px tall, because the two charts are ~790 px
together and a pinned plot on a shorter screen covers every row underneath. **Split** gives the
plot its own column beside the lists on a window at least 1180 px wide. The page is fluid to 1800 px rather than fixed at 1200, and the overview chart
follows its container instead of being a fixed 920 px — at the old page width that constant was
invisible, but in the split column it clipped the end of the recording off.

These are covered by `frontend/tests/e2e/linked_view.spec.ts`, which stubs the analysis from a
response captured from the backend, so it needs neither a backend nor a transcription run.

---

## Measured on the reference recording

53.9 minutes, 161 750 samples at 50 Hz, 1 576 transcript words.

| | |
|---|---|
| channel | `data+baseline`, 9.2e-5 LP resolution |
| conditioning / detection | 0.05 s / 0.09 s |
| A / T / BE / LPA_slow | 115 / 183 / 34 / 19 |
| X / KVZ / KB | 19 / 30 / 1 |
| LPB / LPD | 1.52 LP / 3.7 A-units per minute |
| artefact masked | 0.2% (one body-movement span, 6.98–12.36 s) |
| protocol tree | FRR 7.4–23.6 min (8 exercises), EZM 23.6–49.5 (5 passes), FRR 49.5–53.9 (2) |
| narrative | 12 sections tiling 00:00–53:55, LP 6.00 → 4.79 |
| instruction turns matched | 29 of 303 |
| stimulus-locked | 191 locked / 179 unlocked / 31 n/a |

The legacy `detect_events` path returned 23 events on this recording in the kΩ domain and 64
after the move to LP.

The narrative's content lines up with the operator's own hand-written summary of the same
session — the mixed-up key and the Pommes, the Alkohol discussion, the U-Boot with the Muttern,
the Kirschessen, the Physikpraktikum, the closing Orientierungsübung — but with times derived
from the spoken cues rather than estimated.

---

## What is wrong or unproven

Listed plainly, because the numbers above look more authoritative than they are.

**Nothing is validated against labels.** The tooling exists (stages 5 and 6) but **no labels have
been made**, so every figure above is a count, not an accuracy. Precision and recall are unknown.
Reviewing even the 34 BEs on the reference recording would give the project its first real
precision number — and would immediately show whether `BE_MAX_RISE_TIME_SEC` is anywhere near
right.

**The A-unit is a fallback** (0.060 LP on the reference recording), derived from the 75th
percentile of fall amplitudes rather than from a Dosendruck. Cross-kind ranking — a BE against an
A — is precisely the comparison the manual says needs that calibration.

**No charge zone is named by default.** The corpus reads LP 4.45–5.97, which without a
solo-electrode offset would print as "Kampfzone" for 54 minutes. The offset and A-unit inputs
exist in the UI but are empty until filled in.

**`BE_MAX_RISE_TIME_SEC = 5.0` is a guess.** The manual never quantifies "schnell". The
sensitivity across the three sessions is tabulated in `detectors/discharge.py`.

**Only 29 of 303 turns matched a cue.** Better than the 13 exact matching found, but the
transcript holds more instructions than that — turns like "Okay, beschreib." are real cues too
short to match without inviting false positives.

**Narrative prose is bounded by the local 7B model.** Two of twelve sections came back thin, and
it coins the occasional non-word. It also invented a timestamp once, which is why
`strip_invented_times` exists. The structure, times and levels do not depend on the model.

**`SN` and `FN` are not detected.** They are in the enum and the design; needle-state
discrimination is L3 work that needs labels.

**Transcript word count drifts slightly** — 1 576 this run against 1 589 previously. Under 1%,
far inside the 1 576–3 234 spread the `temperature=0.0` fix eliminated, but the earlier claim of
run-to-run identity does not hold across days.

**The release workflow has never run.** `.github/workflows/release.yml` builds the desktop app for
macOS (arm64 + Intel), Windows and Linux on a `v*` tag, and each platform is gated on a boot
check — but no tag has been pushed, so only the macOS arm64 path has ever been exercised, and
that locally. Windows and Linux bundles remain unproven: ctranslate2 and onnxruntime ship native
libraries that often need per-platform PyInstaller fixes. Expect the first tag to need a second.

---

## Next, in order

1. **Label a session.** Nothing else produces new information until this happens.
2. Rebuild the desktop bundle (`./scripts/build_desktop.sh`, then `smoke_desktop.sh` with the
   app quit).
3. Narrative design §4.2: topic rollup ranked by total discharge.
4. Weak supervision plus the BE-vs-KB and SN-vs-FN classifiers, once labels exist.
5. `SN` / `FN` detection — same blocker.
6. HSMM session states (Abflachung, ÜBZ, EE, zähe Sitzung).

---

## Local environment gotcha

If Docker is running it binds `*:8000` over IPv6, and `localhost` resolves to `::1` first — so
`npm run dev` proxies to Docker instead of the backend and every analysis returns 500 with
nothing in the backend log. Use `VITE_PROXY_TARGET=http://127.0.0.1:8000`, or stop Docker.
