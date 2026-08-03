# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

NeuroNarrative is a local-first web app that aligns GSR (galvanic skin response) recordings with audio sessions, detects physiologically significant events, transcribes speech around them, and optionally summarises each event with a local LLM. FastAPI backend + React/Vite frontend. Everything runs on the user's machine.

`TODO.md` is the authoritative feature-status list and carries the known-issues table. `docs/system-design.md` is aspirational, not a description of the code — don't treat it as spec; its "Where the implementation diverges" section at the top maps plan to reality. The markdown files were reconciled against the code on 2026-08-02; if you change behaviour, update `TODO.md` alongside it.

## The method behind the recordings

A NeuroNarrative session is a **MindWalking** sitting: someone works through a scripted recall protocol while a *mindwalker* GSR device tracks their charge level. The GSR trace is the instrument, the audio is the spoken protocol, and our analysis automates the running notes the operator would otherwise keep by hand.

**These are solo sessions** — one person, running the protocol on themselves and reviewing it afterwards. That is the design target, not an edge case: there is a single voice (alternating between instruction and content, separated by cue matching rather than diarisation), the single-hand electrode shifts the LP so absolute zone labels need a per-recording offset, and the audio is sparse by design (~29 words/min on the reference recording) because verbalising slows a solo session down. Don't add speaker diarisation, and don't treat quiet stretches as a broken recording. `docs/mindwalking-domain.md` is the reference extracted from the two source manuals (BK3 and the mw-Kurs, held locally by the operator and not in this repository) — device physics, the phenomenon catalogue (LP, A, T, X, BE, LPA, LPD, SN, FN, KB, EE, ÜBZ…), the verbatim BK3 cue inventory, and measurements from the operator's own 50 Hz recordings, which live outside this repository. Correct a misreading of the method there, not in the two design docs that build on it: `docs/phenomena-detection-design.md` (detection framework, roadmap in §11) and `docs/session-narrative-design.md` (protocol parsing and summaries). Both carry an "as built" section recording where building them proved the design wrong.

**Stages 1-6 of that roadmap are done** (2026-08-02), plus the session narrative and the review UI. `docs/status.md` is the current-state snapshot and is explicit about what is unproven — read it before trusting any number the app prints.

- **Stage 1**: channel resolution and the LP domain (see "Two CSV parsers, one resolution order" below). Detection runs on `lp`; `delta_kohm` is derived and kept only for the API contract — do not threshold on it.
- **Stage 2**: `services/phenomena/` detects A / T / BE / LPA / LPD / LPB.
- **Stage 3**: `services/protocol.py` parses the BK3 grammar; `detectors/stimulus.py` locks phenomena to utterances and adds `X` and `KVZ`.
- **Stage 4**: `calibration.py` and `detectors/artefact.py`. `lp_offset` and `a_unit_lp` are optional on `/api/analyze`; **without an offset no charge zone is named at all**, because a solo electrode reads a whole session as Kampfzone. Don't "fix" that by naming one anyway.

- **Stage 5**: `services/labels.py` + `/api/labels/*`. Verdicts key on the content-derived `Phenomenon.id` and the recording on a content hash of the CSV, so labels survive re-analysis and re-staging. Writes are atomic — a truncated JSON file would destroy hours of annotation.
- **Stage 6**: `phenomena/evaluate.py`. Per-kind precision/recall/F1. **Recall is never claimed from confirmations alone** — that would be 1.0 by construction — so `missed` labels are a first-class verdict and `has_recall_evidence` gates the claim. An unreviewed detection counts as unknown, not wrong.

**No labels have been made yet**, so every number the app prints is still a count, not an accuracy. Don't quote them as accuracy.

Rendered by `components/PhenomenaPanel.tsx`. The legacy `events` list and `EventTimeline` still exist alongside.

Things in `phenomena/` and `protocol.py` that will bite if you edit them. `primitives.py` segments the signal with **hysteresis legs, not peak finding**: a Blitzentladung is by definition a fall that stays down, which has no local minimum, so `find_peaks` structurally could not see the catalogue's most important phenomenon. Legs also need both the stall timeout (two discharges separated by a plateau never reverse, so they merged into one) and the onset/peak trimming (a leg starts at the previous turning point, which made `rise_time_sec` the age of the recording — and rise time is the BE criterion, so getting it wrong silently disabled BE detection). All three were real bugs, each caught by an injection test in `tests/test_phenomena.py`.

In `protocol.py`, cue matching is **stem-tolerant and scored by completeness ratio**. Both are load-bearing: Whisper renders "Ruf dir" as "ruft ihr" / "Rucht ihr" / "Huf dir", and scoring by raw matched-token count tied the FRR opener (5 of 5) against the "next" cue (5 of 6) so inventory order decided it and *no procedure ever opened*. `CUE_INVENTORY` has an explicit "observed in practice, NOT in BK3" group — keep that distinction; the manual is the authority on the method, the transcript on what was said. "Danke" is still not a cue.

Artefact thresholds are **session-relative** (`median + 40*MAD` of |dLP/dt|), with a floor at 1.0 LP/s. A fixed 2.0 LP/s missed the clearest artefact in the corpus; a 0.15 LP/s floor masked genuine deflections. LP is log resistance, so 1.0 LP/s is a 2.76x resistance change per second — nothing physiological reaches it.

## Commands

```bash
# Backend (from backend/)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,asr,gpu]"      # gpu = MLX, Apple silicon only (no-op elsewhere)
uvicorn app.main:app --reload         # http://localhost:8000
pytest tests/ -v
pytest tests/test_events.py::test_detect_events_empty -v   # single test

# Frontend (from frontend/)
npm install
npm run dev            # http://localhost:5173, proxies /api/* → :8000
npm run lint           # ESLint 8 (.eslintrc.cjs, legacy config format)
npm run typecheck      # tsc --noEmit
npm run build

# E2E (from frontend/) — playwright.config.ts hardcodes baseURL http://localhost:5175,
# so the dev server must be on that port, not the default 5173:
npx vite --port 5175 &
npx playwright install chromium   # once, or after a @playwright/test version bump
npx playwright test

# Docker (from repo root)
docker compose --project-directory "$(pwd)" -f docker/compose.local.yml up --build
```

CI (`.github/workflows/ci.yml`) runs frontend lint + typecheck + build and backend pytest. It does **not** run E2E — those need a dev server on 5175 and browser binaries, so run them locally when touching `SignalPreview`/`UploadPanel`.

Test fixtures `test_gsr.csv` / `test_audio.wav` live at the repo root (the Playwright spec resolves them via `../../../`) and are regenerated by `scripts/generate_synthetic_data.py`. `frontend/tests/e2e/fixtures/analysis_result.json` is a real `/api/analyze` response captured from the backend; `linked_view.spec.ts` replays it through `page.route` so the linked-view tests need no backend and no transcription run — regenerate it by POSTing the two root fixtures to a running backend if the response schema changes. `scripts/test_api.py` drives upload+analyze against a running backend.

## Architecture

### Request flow

Analysis is a **two-call, path-based** protocol, not a single upload-and-analyze:

1. `POST /api/upload` (multipart `gsr` + `audio`) stages both files in `settings.upload_dir` (a per-user cache dir via `platformdirs`, overridable with `NEURONARRATIVE_UPLOAD_DIR`) and returns their absolute paths. Each upload also prunes files older than `upload_retention_hours`.
2. `POST /api/analyze` takes those paths back in the JSON body along with `ruleset_name` and pre/post window seconds. It returns **`202 {job_id}`** without waiting — the work runs as a background task and progress is polled via `GET /api/analyze/{job_id}`.

**Analysis must never be a synchronous request.** A 54-minute recording takes minutes to transcribe and WKWebView enforces its own per-request timeout (~60 s) that the client cannot raise — a synchronous endpoint fails regardless of any axios `timeout`. `services/jobs.py` holds an in-process, thread-safe `JobStore`; `run_analysis` takes a `progress(stage, fraction)` callback, and the transcription stage reports real completion from `segment.end / info.duration`. Callbacks arrive on the worker thread, hence the lock.

The server keeps no session state — the returned paths *are* the handle. `_resolve_staged_path` in `routes.py` confines both paths to the upload dir (400 otherwise), so don't pass arbitrary filesystem paths in tests; `/api/analyze` 404s if a confined path doesn't exist. In Docker, `/data` is a named volume holding both uploads and the ASR model cache.

`run_analysis` (`backend/app/services/analysis.py`) is the orchestrator: load GSR → detect events → transcribe whole audio → for each event, slice transcript words to its window and summarise. Per-event work runs concurrently via `asyncio.gather`.

### Two CSV parsers, one resolution order

The **frontend** parses the GSR CSV itself for the live preview (`frontend/src/utils/gsrParser.ts`); the **backend** parses the same file again for analysis (`_load_gsr` → `services/phenomena/conditioning.py`). They still share no code — that is the standing risk — but they now implement the *same* documented channel-resolution order and are pinned to it by a golden fixture (`tests/fixtures/mindwalker_export.csv`) that `backend/tests/test_conditioning.py` and the `channel resolution` Playwright spec both assert against. **Change both, and update the fixture expectations, when touching channel handling.**

Both resolve any export to a continuous **LP** (Ladungspegel) channel, preferring, in order: `Data(16 bit)` anchored on `Baseline` → `Resistance` fitted against `Baseline` → `Resistance` with nominal constants → `Conductance` → bare `Baseline` (quantised, flagged). Time units come from the median sample interval, never the maximum.

They previously diverged badly: the frontend scored `/baseline/` highest and drew the 0.05-quantised staircase, while the backend analysed `Resistance(kOhm)` — different signals from the same file, and the cause of the "jagged" preview.

### Event detection

`backend/app/services/events.py` unions two candidate sets — derivative z-score threshold and `ruptures` PELT changepoints — then enforces a minimum inter-event gap.

**Never feed the full signal to `rpt.Pelt(model="rbf")`.** The rbf cost builds an n×n Gram matrix, so memory grows quadratically: 10k samples ≈ 2.6 GB, 90k ≈ 64 GB. A real 30-minute recording froze the machine at 32 GB. `_changepoint_candidates` decimates to `CHANGEPOINT_MAX_SAMPLES` (2000) and maps indices back; the derivative rule still runs at full rate for precise timing. `KernelCPD` is quadratic in this ruptures version too — bound the input, don't swap the algorithm. `test_long_recording_stays_bounded` guards this with time and RSS assertions.

Time units are decided by **median sample interval**, not by the maximum (`_time_divisor`). The old max-based rule compressed any >16.7-minute recording logged in seconds down to milliseconds-scale. The three rulesets (`default` / `sensitive` / `strict`) are just `EventRule` tuples in `DEFAULT_RULESET`; adding a preset means adding an entry there and an option in `frontend/src/components/RuleSelector.tsx`. `event_id` is derived from the sample index (`evt-{idx}`), so it is not stable across re-parses.

### Optional dependencies degrade differently

- **ASR backends**: both are imported lazily; `ImportError` or any runtime failure logs a warning and yields an empty transcript, so analysis still succeeds but without excerpts or summaries. The default `small` model downloads (~465 MB) on first use into `settings.asr_model_dir`. faster-whisper's `model.transcribe()` returns a **generator** — transcription only runs as segments are consumed.
- **Ollama**: `summarize_with_local_llm` catches `httpx.HTTPError`/`ValueError` and returns `None`, so an unreachable Ollama costs you summaries but not the analysis. `_configure_summarizer` probes at startup and records why in `settings.summarizer_status`.

### Configuration

`pydantic-settings` with env prefix `NEURONARRATIVE_` and an optional `backend/.env`; `get_settings()` is `lru_cache`d and injected via FastAPI `Depends`. CORS allows any `localhost`/`127.0.0.1` port via `allow_origin_regex`, so Vite falling back to a different port is fine.

### Frontend state and cross-component seeking

`App.tsx` holds all session state (files, parsed preview, ruleset, windows) — no Zustand/Redux despite what the design doc says. Analysis runs through a single React Query `useMutation`.

Playback seeking uses a **ref-callback bridge**: `App` owns `seekRequestRef`, `SignalPreview` writes its internal `seekTo` into it on mount, and `EventTimeline` / `TranscriptTimeline` invoke `seekRequestRef.current?.(time)`. Nothing else wires those components together, so a seek silently no-ops whenever the preview isn't mounted.

`SignalPreview.tsx` (~930 lines) is hand-rolled SVG: semicircular resistance gauge, zoomed detail chart, full-recording overview chart with click-to-seek, event markers, plus WaveSurfer.js for the waveform. No charting library — new visualisations follow the same manual-SVG idiom (`describeArc` / `polarToCartesian` helpers).

Frontend logging goes through `logEvent` in `src/utils/logger.ts`, which prefixes `[NeuroNarrative]` — useful as a console filter pattern when debugging in the browser.

### ASR backends

`services/asr.py` is the single entry point; `utils/accelerator.py` picks the backend at runtime (MLX → CUDA → CPU). Three hard-won constraints:

- **onnxruntime and MLX cannot share a process.** Loading onnxruntime's OpenMP runtime (which Silero VAD pulls in via faster-whisper) before MLX runs *segfaults* — verified, order-dependent, and `KMP_DUPLICATE_LIB_OK` does not fix it. That is why the MLX path uses `detect_speech_regions`, a numpy energy VAD, and never imports `faster_whisper`. Don't "unify" the two VAD paths.
- **MLX has no VAD of its own**, so windowing happens here, and word times come back **relative to each window** — `_transcribe_mlx` adds the window offset. Get that wrong and every transcript excerpt is silently misaligned against its event.
- The `auto` probe checks MLX **first**, which also happens to load MLX before anything can pull in onnxruntime.
- **MLX must be touched from exactly one thread.** `detect_accelerator` is `lru_cache`d because `/api/health` calls it on the HTTP thread — re-probing Metal while transcription runs on a worker thread crashed the process. Transcription itself runs on a dedicated single-thread executor (`_ASR_EXECUTOR`), not `asyncio.to_thread`, so consecutive analyses cannot drive the GPU from different threads.
- **`mlx_whisper.transcribe` reloads the model on every call.** Since this transcribes window by window, a 54-minute recording reloaded ~500 MB of weights 107 times. `_prepare_mlx_model` memoises `load_models.load_model` and resolves the repo to a local path first (which also stops huggingface_hub spawning fetch workers). Roughly halved the runtime.

### Transcript determinism

Whisper's default `temperature` is a **fallback chain** (0.0 → 1.0): a segment tripping the repetition detector is re-decoded with *random sampling*. That made the same 54-minute recording yield 1576–3234 words across runs, with individual windows returning 237 words in 30 s. `settings.asr_temperature` defaults to `0.0` (greedy, deterministic) and `_reject_implausible_rate` drops any window above 6 words/s — German speech runs 2–3. Verified: two full runs, 1589 words each, zero differing windows. Don't restore the fallback chain to "improve quality"; it costs determinism and 40 % runtime.

### Summarisation availability

`_configure_summarizer` (in `main.py`) runs at startup and writes `settings.summarizer_status`, surfaced via `/api/health`. It replaced a CUDA-only GPU check that disabled summaries on every Apple silicon Mac. `probe_summarizer` also resolves the configured Ollama model against `/api/tags` and substitutes a same-family tag when the exact one is not pulled — a wrong tag otherwise fails per event with no visible cause.

Even with Ollama healthy, most events showed no summary, for reasons that have nothing to do with the LLM:

- **Sessions are mostly silent.** A real 54-minute recording held 1589 words, so the configured pre/post window (5 s + 7 s) was empty for 17 of 23 events. `_context_words` in `analysis.py` therefore widens the search to `summary_context_sec` (45 s) *only* when the exact window holds fewer than `summary_min_words`; dense passages keep the tighter, more precise window. Don't "simplify" this by just enlarging the default window — that would blur excerpts everywhere to fix the sparse case.
- **Some events sit minutes from any speech**, so even 45 s finds nothing. The recordings follow a guided-recall protocol with fixed facilitator cues, and `protocol_segment` in `transcript.py` uses them as a third fallback tier: "Ruf … zurück" (any "ruf" with "zurück" within 6 tokens) opens an exercise, "Danke" closes it, and "Beschreibe" / "Was siehst du noch" / "Was ist am deutlichsten" open nested subsections. The event's innermost subsection is used when it holds `summary_min_words`, else the whole exercise; the closing cue is excluded from the excerpt (it's a cue, not content). Cue matching folds umlauts (`zurück` ≡ `zurueck`) and strips punctuation. On the reference recording this covered the four intro events that had nothing within 45 s.
- **Whisper emits non-words over room tone** — `ლლლლ` (Georgian), `සිවිිිි` (Sinhala), `ʕ ʔ ʔ` (IPA). `_reject_implausible_rate` cannot catch them, since two tokens in a 30 s window is a plausible *rate*; they nonetheless became the excerpt. `drop_hallucinated_tokens` in `asr.py` takes the script the transcript is overwhelmingly written in and drops tokens carrying no letter of it. It keys on the Unicode *name* (`<SCRIPT> SMALL/CAPITAL LETTER …`) rather than the category, because `ʕ` is `Ll` and claims Latin. Numbers and punctuation are always kept — spoken meter readings are real content — and an uncased-script transcript (CJK, Arabic) passes through untouched.

Together these took the user's recording from 6 to 21 summarised events out of 23 (17 from the widened window, 4 more from the protocol cues). The remaining 2 are honest — pure filler the LLM correctly answers `NONE` on. The UI distinguishes those cases now instead of blaming the setup.

### CPU budgeting

`app/utils/cpu.py` decides how many threads transcription gets. Two counter-intuitive points, both measured rather than assumed:

- **Efficiency cores are excluded from the budget.** On an M1 Pro the topology is 8P+2E; spreading the pool across both core types slows the run down.
- **More threads is slower.** 3 min of speech on that machine: 4 threads 29 s, 6 threads 32 s, 8 threads 51 s, 10 threads 70 s. The default is therefore half the performance cores — fastest *and* leaves the UI responsive. Don't "optimise" this by raising it; re-measure first.

Affinity (`sched_getaffinity`) and cgroup v1/v2 quotas are honoured, so a 2-core container gets 1 thread rather than the host's core count. `GET /api/health` exposes the detection and the resulting `asr_threads`.

### Audio decoding

`_decode_for_asr` reads WAV via `soundfile`, downmixes to mono and resamples to 16 kHz with `scipy.signal.resample_poly`, then hands the ndarray to the model. This is deliberate: the ASR libraries would otherwise shell out to the **ffmpeg CLI**, which is a shipped-binary and licensing problem for desktop builds. Don't reintroduce a path-based `transcribe()` call. `librosa` is intentionally *not* a dependency — it dragged in numba/llvmlite/scikit-learn (~196 MB) and was never imported.

### Serving the frontend

Setting `NEURONARRATIVE_FRONTEND_DIST` mounts the built SPA at `/` through `SpaStaticFiles`, a `StaticFiles` subclass that falls back to `index.html` on 404 (plain `html=True` only covers directory indexes). API routes are registered *before* the mount, so they still win. This is the single-process mode desktop packaging will use — same origin, no proxy, no CORS.

### Resizable panes

`components/ResizablePane.tsx` wraps the detected-events list and the transcript. It uses the
native CSS `resize` handle rather than a hand-rolled drag — one line, accessible, and it behaves
like the rest of the OS. **`resize` is ignored unless `overflow` is not `visible`**, so the
scrolling and the handle have to be on the same element; putting them on separate elements
silently produces no handle.

Heights persist per `storageKey` in localStorage, read back through a range guard so a corrupt
entry cannot leave a pane unusable. The native handle fires no event, so a `ResizeObserver`
records the height.

Don't nest a second scroller inside a pane: the inner one traps the wheel and you get two bars.

### Cross-panel hover linking

The plot, the phenomena list and the narrative are one linked view. `App.tsx` owns both pieces of
shared state: `hiddenKinds` (the filter chips, which also decide which vertical markings the
charts draw) and `hover: {timeSec, source}`.

**The `source` field is load-bearing.** A panel must not auto-scroll in response to its *own*
hover, or the row under the cursor slides away as you read it. Each panel ignores hovers whose
source is itself.

Marker hit areas are invisible `<rect>`s around each line: a 2 px dashed line is close to
unhoverable. Colours come from `utils/phenomenaVisuals.ts`, shared with the filter chips — a `BE`
marker that is not the same colour as its `BE` chip makes the link invisible.

Scrolling uses `utils/smoothScroll.ts`, not `scrollIntoView({behavior:"smooth"})`, whose duration
the browser picks and grows with distance — across a 54-minute timeline that ran long enough for
a second hover to arrive mid-flight. Ours eases in and out and is capped at 2 s.

Resting on a marker gives the browser's own delayed tooltip, from the SVG `<title>`. It carries
the kind and time **and what was said around it** — `excerptAround` in `App.tsx`, ±`n` seconds,
default 3, adjustable from the control beside the detail chart's zoom buttons. The label is built
in `App` because that is where the transcript lives; `SignalPreview` owns only the control. A word
counts when it *overlaps* the window rather than starting inside it, so a long word spanning the
moment is not dropped, and "no speech within ±n s" is printed rather than left blank — in a solo
session silence is the common case and a real answer, not a gap. Capped at 400 characters: a
native tooltip is not a reading surface.

The **two charts are separate hover sources**, `plot` (detail) and `overview`, not one "plot".
The detail chart ignores hovers from its own markers, or it would drag itself out from under the
pointer — but a hover in the overview is precisely when it *should* travel, since the moment
being pointed at is usually far outside the zoomed window. It only travels when the target is not
already comfortably on screen (a 15 %-of-width margin, capped at 120 px); re-centring something
you can see is motion for its own sake, and at a shallow zoom every marker would be a jump.

`scrollChildIntoView` measures with `getBoundingClientRect`, **not `offsetTop`**. `offsetTop` is
relative to the nearest *positioned* ancestor and these lists are not positioned, so it produced
an offset measured from further up the tree and the list scrolled somewhere else entirely. The
row was highlighted the whole time — it just was not on screen, which is indistinguishable from
nothing being highlighted.

Both charts mark what the other panels point at, in violet (`HIGHLIGHT_COLOUR`) — deliberately
outside the phenomenon palette and away from the red playhead, because it is neither. `hover`
drives it while the pointer is on a row; a click parks a `PlotSelection` that outlives the pointer,
so the moment you jumped to stays identifiable while you read. A live hover wins over the last
click. A narrative section passes its `endSec`, and the charts shade the **whole span** behind the
trace with both edges drawn — "from when to when" is the question a section heading raises, and a
single line at its start does not answer it. Guarded by `tests/e2e/linked_view.spec.ts`, which
stubs the analysis from a captured backend response so it needs no backend.

`HoverTarget` carries an optional `endSec`. A narrative section spans minutes, so it highlights
**every** filtered phenomenon inside it, not a representative one — the reason to point at a
section is to see the cluster it contains, and marking only the first said the section was about
that single moment. The first one is still singled out as `leadId`, but only to decide where the
list scrolls to; nearest-to-the-section-start finds nothing at all, because sections begin on a
spoken cue and phenomena cluster later.

Both charts also label what is being pointed at with **speech bubbles** (`BubbleLayer` in
`SignalPreview.tsx`): a dashed line says *that* something was detected, the bubble says *what*.
They follow the same source as the markings — `markers`, already filtered by the kind chips — so
a hidden kind is silent in both. A span labels everything inside it; a single moment labels the
one phenomenon within 0.5 s of it, and nothing when there is none. Never the whole catalogue: on
a 54-minute session that is several hundred labels and no visible trace.

`packBubbles` is greedy first-fit **by time into lanes**, and the no-overlap rule is load-bearing
rather than cosmetic — phenomena cluster, so centring each label on its own marker piles them
into an unreadable stack. Anything that would need a lane past `maxLanes` (5 in the detail chart,
2 in the 120 px overview) is dropped and counted as "+N more" rather than drawn over its
neighbour. Each bubble draws a connector back to its marker, because a bubble pushed sideways to
clear a neighbour otherwise points at the wrong line. The overview shows the kind alone; the
whole session in 860 px cannot carry magnitudes as well.

`BubbleLegend` is **always rendered** and merely hidden when idle. Appearing and disappearing
moved both charts 12 px down and back every time the pointer entered a row, and a plot that jumps
under the cursor is worse than a permanently reserved line — caught by the reveal-geometry E2E
test, not by eye.

The detail chart's scroll container is **`.signal-chart`**, which carries `overflow-x: auto`, not
the `detailWrapRef` wrapper around it. Scrolling the wrapper is a silent no-op.

### The session narrative

`services/narrative.py` builds the automatic Sitzungsbericht: one section per protocol segment,
with a title, prose and highlights from the LLM. The load-bearing rule is that **the model never
chooses a timestamp**. Section boundaries come from the BK3 cues actually spoken; charge levels
come from the conditioned signal; phenomenon counts come from the detectors. A model asked to
segment a transcript by theme produces plausible times that are minutes off, and a report whose
headings disagree with the trace is worse than none — the operator seeks to them and finds nothing.

The prompt forbids inventing times and the model mostly complies, but not always: a real run
emitted "Die Sitzung endet um 4:07" for a section ending at 53:55. `strip_invented_times` drops
any sentence containing a clock reference. Keep it — one wrong number discredits the correct
headings around it.

Without a transcript it falls back to fixed 5-minute windows, which are still real ranges rather
than estimates. `summarize_section` in `summary.py` is separate from the one-sentence event
summariser and asks for JSON.

**Local gotcha:** if Docker is running it binds `*:8000` over IPv6, and `localhost` resolves to
`::1` first — so `npm run dev` proxies to Docker instead of the backend and every analysis 500s.
Use `VITE_PROXY_TARGET=http://127.0.0.1:8000`.

### The two workspace layouts

`App.tsx` owns a `WorkspaceLayout` (`stacked` | `split`), toggled from the header and kept in
localStorage. Both answer the same complaint — scrolling down to a list took the plot off screen —
and which one works depends on the monitor, so it is a switch rather than a decision baked into
the CSS. `.app-main` is fluid to **1800 px** now, not a fixed 1200, which left ~400 px unused on
either side of a wide window.

**`stacked`** pins the charts to the top of the window. Three things it has to get right:

- The sticky element must be `.workspace-plot`, **not** the chart stack inside the card. A sticky
  box can only travel inside its *parent's* box, and `.plot-stack`'s parent is the card it ends —
  pinning it there gives it no travel at all and it scrolls away exactly as before.
  `.workspace-plot`'s parent is the whole workspace, which is what actually spans the lists.
- Pinning that at `top: 0` shows the card's *top* — 700 px of gauge, metrics and waveform — with
  the charts below the fold. The offset is therefore **negative**: `--plot-offset` is the measured
  height of everything above the charts, so the card slides up by exactly that much and stops with
  the charts against the window edge. `order: -1` on `.plot-stack` also worked, but it put the
  gauge *below* the charts and the page read backwards. Don't reintroduce it.
- Everything is gated on `@media (min-height: 1000px)`. The two charts total ~790 px, so on a
  720 px window a pinned plot covers the whole viewport and every row underneath becomes
  unreachable — not cramped, *unclickable*. Below the gate this layout behaves as it always did.

`--plot-offset` and `--plot-height` are measured by SignalPreview (`onPlotMetrics`, a
`ResizeObserver` on the card and the stack, since the waveform appears late and the file-name
lines wrap) and set as inline custom properties on `.workspace`. `--plot-height` also caps
`.analysis-column`, which otherwise kept its 85vh and put most of its rows permanently behind the
plot, and drives `scroll-margin-top` on everything the browser might scroll to the top — the
classic sticky-header trap, where a scrolled-to row lands behind the header and cannot be
clicked. The opaque background is required too: the card's own is translucent and list rows would
otherwise show through the trace.

How long the plot stays pinned is bounded by the workspace's own height, which is correct — once
the lists are fully on screen there is nothing left to scroll under it, and below the workspace
the plot scrolls away like anything else. A test that scrolls past that point is testing the
wrong thing.

**`split`** (≥1180 px) gives the plot its own sticky column and stacks the two lists in the
other, so nothing needs pinning. Below that width both columns would be too narrow for a row and
it falls back to stacked regardless of the setting.

`OverviewChart` measures its container with a `ResizeObserver` instead of being a fixed 920 px
SVG. At 1200 px page width that constant was invisible; once the page went fluid it left dead
space on a wide window and **overflowed its column in the split layout, clipping the end of the
recording off**. There is a 600 px floor below which the container scrolls.

Note for tests: in stacked mode the gauge is scrolled out by the *sticky* rule, not by the page
scroll, so "did the page scroll back to the head of the card" can no longer be asserted by
checking the gauge is off-screen. Assert on the charts' position instead.

### Seeking, and the two-column results layout

Phenomena (left) and detected events (right) sit in `.analysis-columns`, a 50/50 grid that
collapses to one column only below **720 px**. The breakpoint was originally 1100 px, which is
wider than the desktop window — so the layout collapsed to a single column *and* dropped the
height cap, and the feature was simply absent where it was meant to be used. Don't raise it.
Both columns render unconditionally; a conditional column would leave the grid half empty. Tracks
are `minmax(0, 1fr)`, not `1fr`, so a long unbreakable row cannot push one column wider than its
share, and `box-sizing: border-box` keeps the card padding from being added on top of the 70vh
cap. Each column is `display:flex` with a bounded `max-height`;
the **list** inside scrolls, not the card, so the kind filters and the uncalibrated/artefact
caveats stay visible while you read. `min-height: 0` on the scrolling child is what actually
allows a flex item to shrink enough to scroll — remove it and the column just grows.

Every row seeks: the whole `.phenomenon-row` and `.timeline-event-card` are click targets, with
`stopPropagation` on the verdict and "Jump to" buttons so those do not also fire a seek. A click
also scrolls the charts back into view (`revealPlot`), since the columns sit below them and you
would otherwise seek something you cannot see.

`revealPlot` anchors on **`.overview-section`, not the top of the preview card** — the card opens
with some 700 px of gauge, metrics and waveform, so anchoring on it left the charts mid-window and
threw the clicked row far below the fold. It takes `min(chartsTop, rowBottom - viewportHeight)`
from the row that was clicked, which is why `SeekOptions.origin` exists: rows pass their own `<li>`
(the "Jump to" buttons pass `closest("li")`, since pinning a 40 px button to the bottom edge hides
the row it belongs to). Measured: the two charts and their headings are ~1080 px, so below that
window height the two cannot both fit and the charts win — the row is the thing you can scroll back
to. `SignalPreview` publishes the section through `plotSectionRef`, the same pattern as `seekRef`.

Seeks go through `handleSeek` in `App.tsx`, **not** `seekRequestRef.current` directly. The ref is
only populated while `SignalPreview` is mounted, so a click with the preview collapsed used to do
nothing at all; `handleSeek` opens the preview, parks the time in `pendingSeekRef`, and flushes it
across `requestAnimationFrame` once the ref appears (refs do not re-render, so there is nothing to
wait on declaratively). WaveSurfer's `seekTo` moves the playback head, so pressing play afterwards
resumes from the clicked moment.

### File dialog filters

`<input type="file" accept="...">` needs **MIME types, not just extensions**, or the desktop shell shows no filter at all. WKWebView hands pywebview only `_acceptedMIMETypes()` (`webview/platforms/cocoa.py`, the `runOpenPanel` delegate), and that array is *empty* for an extension-only accept list — so `accept=".csv"` produced an unfiltered open panel listing every file on the machine, while the WAV input filtered correctly because it happened to carry `audio/wav`.

pywebview maps each MIME type through `UTType.typeWithMIMEType_` and drops anything that resolves to a `dyn.` identifier, so only real UTIs survive: `text/csv` and `text/comma-separated-values` both give `public.comma-separated-values-text`. Don't add `application/vnd.ms-excel` — macOS maps it to `com.microsoft.excel.xls` and it would let spreadsheets through. Guarded by the `file dialog filters` Playwright spec.

### Desktop build

`app/desktop.py` is the PyInstaller entrypoint (`./scripts/build_desktop.sh`, spec in `packaging/`). Things that will bite you if you edit it:

- It **must use absolute imports** (`from app.main import app`). When frozen, the entry script runs as `__main__` with no parent package, so a relative import raises `ImportError` — this already happened once.
- **Threading is load-bearing.** The pywebview GUI loop must own the main thread (a hard macOS requirement), so uvicorn runs on a worker thread and the window blocks main. The headless path (`NEURONARRATIVE_NO_BROWSER=1`) inverts this and runs the server on main. Don't "simplify" by moving the GUI off main.
- Closing the window quits through AppKit **without unwinding the `finally`**, so the instance state file can outlive the process. Never trust that file's existence — always health-probe it (`_existing_instance_url` does, and clears it when the probe fails).
- **`multiprocessing.freeze_support()` must stay the first statement in `main()`.** In a frozen bundle, a child process spawned by *any* library re-executes the binary from the top. Without it, transcription's worker processes each booted a whole new app, hit the single-instance guard, and opened a browser window mid-analysis. Symptom to recognise: "already running" in the log seconds after an analysis starts.
- The single-instance path focuses the running app via `NSRunningApplication` (bundle id must match the spec's `info_plist`), falling back to a browser only if that fails.
- Env vars are set *before* importing `app.main`, because `get_settings()` is `lru_cache`d on first access and `main.py` builds the app at import time.
- `_bundle_root()` resolves via `sys._MEIPASS` when frozen; bundled data lands at `Contents/Frameworks/{frontend_dist,asr_models}` inside the `.app`.
- The port is ephemeral. The socket is bound *before* uvicorn starts and passed in via `server.run(sockets=[sock])`, so nothing can race for it. The port is written to a state file for the single-instance check.
- Verify any change with `./scripts/smoke_desktop.sh`, which runs the bundle with `env -i` (no venv, no Python on PATH) and `HF_HUB_OFFLINE=1`, then drives upload → analyze → transcription using speech synthesised by `say`. A sine-wave fixture cannot prove ASR works, because a failed transcription also returns zero words.

### API base URL vs. proxy

`App.tsx`'s axios client uses `VITE_API_BASE_URL` (default empty) and then requests paths that already begin with `/api` — so if you ever set that variable it must be **origin-only**, never ending in `/api`. In Docker the frontend container runs the Vite dev server, so the backend is reached through the proxy instead: `VITE_PROXY_TARGET` (default `http://localhost:8000`) overrides the proxy target, and `compose.local.yml` sets it to `http://backend:8000`.
