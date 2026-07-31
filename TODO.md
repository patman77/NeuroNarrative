# NeuroNarrative – Project TODO

Status legend: ✅ Done · 🔧 Partial · ❌ Not started · 🧪 Stubbed

---

## P0 – Scaffold & Core Pipeline

| Item | Status | Notes |
|------|--------|-------|
| FastAPI backend (health, upload, analyze routes) | ✅ | `backend/app/api/routes.py` |
| React + Vite frontend shell | ✅ | `frontend/src/` |
| Docker Compose local stack | ✅ | `docker/compose.local.yml` – both services |
| Vite proxy → backend on :8000 | ✅ | `frontend/vite.config.ts`; override with `VITE_PROXY_TARGET` (compose points it at `http://backend:8000`) |
| CORS for any localhost port | ✅ | `backend/app/main.py` – `allow_origin_regex` covers `localhost`/`127.0.0.1` on any port |
| CSV + WAV paired file upload | ✅ | `POST /api/upload`, `UploadPanel.tsx` |
| GSR CSV parsing (column auto-detect) | ✅ | `frontend/src/utils/gsrParser.ts` |

---

## P1 – Signal Preview UI

| Item | Status | Notes |
|------|--------|-------|
| Semicircular gauge (1–6.5 kΩ) | ✅ | `SignalPreview.tsx` – SVG gauge |
| Gauge needle tracks resistance | ✅ | `calculateGaugePosition()` |
| Orange baseline marker on gauge | ✅ | Drawn at `baselineAngle` |
| Scrolling detail chart (zoomed) | ✅ | `SignalChart` component |
| Full-recording overview chart | ✅ | `OverviewChart` – click to seek |
| Click-to-seek on overview | ✅ | `handleClick` + `onSeek` |
| Timeline navigation buttons (⏮ -10s +10s 25% 50% 75% ⏭) | ✅ | 7 buttons in `SignalPreview` |
| Synchronized audio playback | ✅ | `<audio>` + `requestAnimationFrame` |
| Backend health status pill in header | ✅ | `App.tsx` – polls `/api/health` every 30 s, retries every 5 s while offline |
| Analyze error banner (above fold) | ✅ | Replaces buried error text |
| Drag-and-drop file upload | ✅ | `UploadPanel.tsx` – per-field D&D with extension validation |
| Auto-spaced overview x-axis ticks | ✅ | Smart interval selection, no overlap |
| Gauge tick readability | ✅ | Light color (#cbd5e1), 0.8rem bold |

---

## P2 – Event Detection

| Item | Status | Notes |
|------|--------|-------|
| Derivative-based event detection | ✅ | `backend/app/services/analysis.py` |
| Changepoint detection (ruptures) | ✅ | Uses `ruptures` library |
| Rule presets (default / sensitive / strict) | ✅ | `DEFAULT_RULESET` in `events.py` + `RuleSelector.tsx`; `default` is labelled "Balanced" in the UI |
| Pre/post event window config | ✅ | Sliders in `RuleSelector.tsx` |
| Event list in `EventTimeline` component | ✅ | Polished cards: badge, score, delta_kohm color, seek-to button |
| Event bubbles overlaid on signal chart | ✅ | Orange markers on `OverviewChart` + `SignalChart` |

---

## P3 – Speech Processing

| Item | Status | Notes |
|------|--------|-------|
| GPU acceleration, autodetected | ✅ | MLX on Apple silicon (Metal), CUDA on NVIDIA, CPU everywhere else — `utils/accelerator.py`, chosen at runtime with graceful fallback. M1 Pro: **0.0 % WER at 6.3× realtime** vs. 3.3 % at 1.6× on CPU, so a 54-min recording drops from ~33 to ~8.5 min. Verified inside the frozen bundle, offline. |
| onnxruntime + MLX segfault | ✅ | Silero VAD (onnxruntime) crashes the process when MLX is used. MLX path now uses a numpy energy VAD (3 ms vs 168 ms, same region detected); CPU path keeps Silero. |
| Transcript quality | ✅ | Default model raised `tiny` → `small` after measuring WER on noisy German: tiny 16.7 %, base 6.7 %, small 3.3 %. Costs runtime (54-min recording: 8 → 35 min); `NEURONARRATIVE_ASR_MODEL=base` is the middle ground. |
| Hallucination loops ("Gehören Sie gleich." ×200) | ✅ | `condition_on_previous_text=False` stops Whisper feeding its own output back as context; VAD filtering stops it inventing speech over silence. Could not be reproduced with synthetic noise — mitigation is the documented standard fix, **not verified against the user's recording**. |
| Audio transcription | ✅ | `faster-whisper` (CTranslate2), int8 on CPU; `_decode_for_asr()` feeds it a mono 16 kHz ndarray via soundfile+scipy, so **no ffmpeg CLI** is needed; graceful `[]` fallback if import fails |
| Word-level ASR confidence | ✅ | faster-whisper `word.probability` populates `TranscribedWord.confidence`, which activates the previously inert `min_confidence` filter in `align_transcript()` |
| Speaker diarisation | ❌ | Not started |
| Transcript-to-event time alignment | ✅ | `align_transcript()` in `transcript.py` – runs when transcript is non-empty |
| Transcript timeline viewer in UI | ✅ | `TranscriptTimeline.tsx` – word-level click-to-seek; empty-state message when no transcript |

---

## P4 – LLM Summarisation

| Item | Status | Notes |
|------|--------|-------|
| Ollama HTTP client integration | ✅ | `backend/app/services/summary.py` |
| GPU guard / CPU fallback env var | ✅ | `NEURONARRATIVE_REQUIRE_GPU_FOR_SUMMARIZER` |
| Summarisation per detected event | ✅ | Verified end-to-end on a 54-min German recording: 21 of 23 events summarised, in German. The 2 without one are pure filler the LLM correctly declines — the UI names which |
| Context window for sparse recordings | ✅ | `_context_words` widens to `NEURONARRATIVE_SUMMARY_CONTEXT_SEC` (45 s) when the 5 s/7 s window holds fewer than `SUMMARY_MIN_WORDS` |
| Protocol-cue fallback for silent stretches | ✅ | `protocol_segment` in `transcript.py`: "Ruf … zurück" opens an exercise, "Danke" closes it, "Beschreibe" / "Was siehst du noch" / "Was ist am deutlichsten" bound subsections; used when even 45 s holds no speech |
| Hallucinated tokens kept out of excerpts | ✅ | `drop_hallucinated_tokens` in `asr.py`; script-based, no hard-coded alphabet |
| Graceful degradation when Ollama is down | ✅ | `summary.py` catches `httpx.HTTPError`/`ValueError` → returns `None`; analysis completes without summaries |
| `summary` + `score` fields in response | ✅ | Schema defined; populated when Ollama is available |

---

## P5 – UX Hardening & Export

| Item | Status | Notes |
|------|--------|-------|
| Session result export to CSV | ✅ | Client-side Blob download in `EventTimeline.tsx` |
| Session result export to JSON | ✅ | Client-side Blob download in `EventTimeline.tsx` |
| Session result export to SRT / PDF | ✅ | SRT via Blob download; PDF via `window.print()` with print-only CSS |
| EventTimeline UI polish | ✅ | Rule badge, colored score, signed delta_kohm, "Jump to" seek button |
| Drag-and-drop file upload | ✅ | `UploadPanel.tsx` |
| Waveform visualisation (Wavesurfer.js) | ✅ | WaveSurfer v7 replaces `<audio>`; canvas waveform with playback, seek, and nav buttons |
| Plotly.js charts (from design doc) | ❌ | Using hand-rolled SVG charts instead |

---

## P6 – EEG Support

| Item | Status | Notes |
|------|--------|-------|
| EEG file ingestion pipeline | ❌ | Only GSR (single channel) supported |
| Multi-channel visualisation | ❌ | Not started |

---

## P7 – Packaging & Hardening

| Item | Status | Notes |
|------|--------|-------|
| PyInstaller desktop build (macOS) | ✅ | `packaging/neuronarrative.spec` + `scripts/build_desktop.sh` → `NeuroNarrative.app`, 328 MB with the ASR model bundled (253 MB with `--no-model`). Smoke-tested offline with no venv. |
| Desktop build: Windows / Linux | ❌ | Spec is cross-platform apart from the macOS `BUNDLE` step; untried |
| Code signing / notarization | ❌ | Unsigned; Gatekeeper blocks a downloaded copy |
| Native window (not a browser tab) | ✅ | pywebview → system WKWebView. +4 MB, no Node, no second binary to sign. Electron/Tauri not needed. |
| End-to-end tests (Playwright) | ✅ | `frontend/tests/e2e/preview_flow.spec.ts` – 3 tests, all pass. Needs dev server on **:5175** (config `baseURL`) and `npx playwright install chromium`. Not run in CI. |
| Backend unit tests | ✅ | `test_events.py` (4), `test_analysis.py` (7), `test_health.py` (1), `test_storage.py` (7), `test_upload.py` (5) – 24 total; skip gracefully when deps absent |
| ESLint configuration | ✅ | `frontend/.eslintrc.cjs` – ESLint 8 legacy format, `@typescript-eslint` + react + react-hooks + prettier. `npm run lint` is clean. |
| CI/CD pipeline | ✅ | `.github/workflows/ci.yml` – frontend lint + typecheck + build, backend pytest, parallel jobs |

---

## Known Issues / Tech Debt

| Issue | File | Priority |
|-------|------|----------|
| Pressing Analyze opened the app a second time in a browser | `backend/app/desktop.py` | ✅ Fixed – missing `multiprocessing.freeze_support()`: transcription spawns worker processes, and in a frozen bundle each re-executed the binary from the top, booting a fresh app that hit the single-instance guard. Also, that guard now focuses the running window instead of opening a browser. |
| Transcription crashed mid-run (window vanished, no error) | `asr.py`, `accelerator.py`, `analysis.py` | ✅ Three defects fixed: (1) the model was reloaded into GPU memory once per window — 107× on a 54-min recording; (2) `/api/health` re-probed Metal on the HTTP thread while inference ran on a worker; (3) transcription used an arbitrary pool thread. **Intermittent, so not provable** — two full runs on the real recording now pass and are ~2× faster (276 s → ~150 s). |
| Transcript word count varied run to run (1576–3234 words on one recording) | `asr.py` | ✅ Fixed – Whisper's temperature *fallback chain* re-decodes hard passages with random sampling. Per-window diff showed 17 of 107 windows differing, some returning 237 words in 30 s (~8 words/s). `temperature=0.0` plus a 6 words/s ceiling: two runs, 1589 words each, **0 differing windows, no loops**, and 40 % faster. |
| "No summary available" although Ollama was running | `hardware.py`, `summary.py`, `main.py` | ✅ Fixed – two causes: the GPU gate tested for CUDA only (false on all Apple silicon), and the configured model `qwen2.5:7b-instruct-q4_K_M` was not installed (`qwen2.5:7b` was). Metal now counts as a GPU, the model is resolved against `/api/tags`, and `/api/health` reports `summarizer_status`. |
| Summaries came back in English for German audio | `summary.py` | ✅ Fixed – prompt now pins the output language to the excerpt's. |
| "No summary available" persisted on most events even with Ollama healthy | `analysis.py`, `asr.py`, `EventTimeline.tsx` | ✅ Fixed – three causes: the 5 s/7 s window is empty for most events in a mostly-silent session (1589 words over 54 min), so `_context_words` widens to `summary_context_sec` = 45 s when it holds fewer than `summary_min_words`; Whisper's non-word hallucinations over room tone (`ლლლ`, `ʕ ʔ`) became the excerpt, now removed by `drop_hallucinated_tokens`; and the prompt returned `NONE` on any fragment. A later protocol-cue fallback (`protocol_segment`) covers events with no speech within 45 s. 6/23 → 21/23 summarised events on the reference recording. |
| A missing summary was reported as "Provide a transcript or enable the local LLM" even when the setup was fine | `EventTimeline.tsx` | ✅ Fixed – now distinguishes "No speech near this event", "Too little was said here to summarise", and the summariser actually being off (with `summarizer_status` from `/api/health`). |
| **Changepoint detection was O(n²) in memory.** `Pelt(model="rbf")` builds an n×n Gram matrix: ~2.6 GB at 10k samples, ~64 GB at 90k. A 30-minute recording froze the whole machine (32 GB RSS, all cores). `_changepoint_candidates` now decimates to `CHANGEPOINT_MAX_SAMPLES` (2000) and maps indices back. 90k samples: **0.12 s, +98 MB**. `KernelCPD` was evaluated and is quadratic too, so bounding the input is the fix, not the algorithm. | `backend/app/services/events.py` | ✅ Fixed |
| **Time-unit heuristic corrupted long recordings.** `max(time) > 1000 → milliseconds` silently compressed any session longer than ~16.7 min logged in seconds: 30 min became 1.8 s, wrecking event timing and the min-gap rule. Now decided by median sample interval (plus an explicit `ms` in the header), matching what `gsrParser.ts` already did. | `backend/app/services/analysis.py` | ✅ Fixed |
| Analysis ran inline on the event loop, so the API was unresponsive (health included) for the whole run | `backend/app/services/analysis.py` | ✅ Fixed – `asyncio.to_thread` for parsing and detection |
| **`/analyze` was synchronous, so long recordings failed with "timeout exceeded".** A 54-min recording needs ~9 min of transcription; WKWebView enforces a ~60 s per-request timeout the client cannot raise. Now `202 {job_id}` + `GET /api/analyze/{job_id}` polling, with stage and real progress (`segment.end / duration`), and a progress bar in the UI. | `backend/app/services/jobs.py`, `routes.py`, `frontend/src/App.tsx` | ✅ Fixed |
| Smoke test could silently attach to an already-running instance and test the *old* build | `scripts/smoke_desktop.sh` | ✅ Fixed – fails fast on "already running" |
| Transcription saturated every core, making the machine unusable during an analysis | `backend/app/utils/cpu.py` | ✅ Fixed – adaptive budget (P-cores only, half of them, affinity + cgroup aware). Measured on M1 Pro: 4 threads 29 s vs. 10 threads 70 s, so the limit is **2.4× faster**, not a trade-off. `NEURONARRATIVE_ASR_THREADS` overrides. |
| Overview chart emitted one SVG path command per sample (~1.5 MB path at 90k samples) | `frontend/src/components/SignalPreview.tsx` | ✅ Fixed – min/max decimation per pixel column, preserves spikes |
| Two independent GSR CSV parsers: frontend `gsrParser.ts` (scored column detection) for the preview, backend `_load_gsr` (substring match) for analysis. They **had already diverged** — the frontend used the correct interval-based time-unit heuristic while the backend used the broken max-based one. A CSV the preview renders can still be rejected by `/api/analyze`. | `frontend/src/utils/gsrParser.ts`, `backend/app/services/analysis.py` | **High** |
| Detail chart width is `duration × 80 px/s` — a 30-min recording produces a 144 000 px wide SVG. Scrolls, but heavy. Needs windowing to the visible range. | `frontend/src/components/SignalPreview.tsx` | Medium |
| `summarize_with_local_llm` raised on an unreachable Ollama, failing all of `/api/analyze` | `backend/app/services/summary.py` | ✅ Fixed – returns `None`, logs a warning |
| `save_temp_upload` used `async with upload`, which current Starlette no longer supports on `UploadFile` – **every upload returned 500** and no test covered the endpoint | `backend/app/services/storage.py` | ✅ Fixed – `test_upload.py` now covers the route |
| `/api/analyze` accepted arbitrary filesystem paths from the client (arbitrary file read) | `backend/app/api/routes.py` | ✅ Fixed – `_resolve_staged_path` confines paths to the upload dir |
| Uploads staged in a hardcoded `/tmp/neuronarrative`, never cleaned up, not a valid Windows path | `backend/app/api/routes.py` | ✅ Fixed – `platformdirs` cache dir + 24 h pruning |
| `gpu_is_available()` only detects CUDA (env vars + `/dev/nvidia*`); Apple Silicon / Metal always reports false | `backend/app/utils/hardware.py` | Low |
| `event_id` is derived from the sample index (`evt-{idx}`), so it is not stable across re-parses | `backend/app/services/events.py` | Low |
| Speaker diarisation not implemented | — | Medium |
| `docs/images/frontend-overview.png` predates the current UI (no status pill, Preview button, or signal preview) | `docs/images/` | Low |
| Ollama sidecar in compose requests an NVIDIA GPU – unusable on Apple Silicon; sits behind the `summarizer` profile so it is not started by default | `docker/compose.local.yml` | Low |
| `librosa` was a declared dependency but never imported, pulling in numba + llvmlite + scikit-learn (~196 MB) | `backend/pyproject.toml` | ✅ Removed |
| `openai-whisper` pulled in torch (~519 MB with sympy/networkx) and required the ffmpeg CLI | `backend/pyproject.toml`, `analysis.py` | ✅ Replaced with `faster-whisper` + soundfile decoding |
| `HealthResponse` used deprecated `datetime.utcnow()` | `backend/app/api/schemas.py` | ✅ Fixed – timezone-aware `datetime.now(timezone.utc)` |
| Backend validates WAV MIME as `audio/wav` / `audio/x-wav` / `audio/vnd.wave` / `audio/wave` / `""` + filename fallback | `backend/app/api/routes.py` | ✅ Fixed |
| Compose set `VITE_API_BASE_URL=http://backend:8000/api` while the client already prefixes `/api`, yielding `/api/api/...`; the Vite proxy target was also hardcoded to `localhost:8000`, unreachable from inside the container | `docker/compose.local.yml`, `frontend/vite.config.ts` | ✅ Fixed – now `VITE_PROXY_TARGET` |
| `npm run lint` was declared with no ESLint config present | `frontend/.eslintrc.cjs` | ✅ Fixed |
| Dead `trianglePath` variable and needless regex escape found by first lint run | `SignalPreview.tsx`, `gsrParser.ts` | ✅ Fixed |
| SRT / PDF export | — | ✅ Implemented |
| Transcript timeline viewer in UI | — | ✅ Implemented (`TranscriptTimeline.tsx`) |

---

## P7: Desktop packaging – detailed breakdown

Goal: ship NeuroNarrative as an app a non-technical user can install and launch without a
terminal, keeping the local-first guarantee.

**Estimates assume one developer familiar with this codebase.** They are calendar-day
estimates, not ideal-hours.

### Phase 0 – dependency diet ✅ DONE (2026-07-30)

The blocker was never the app shell; it was the Python dependency tail. Completed:

| Item | Result |
|------|--------|
| Drop unused `librosa` | −196 MB, and removes numba/llvmlite/`lazy_loader`, the three worst PyInstaller static-analysis offenders |
| `openai-whisper` → `faster-whisper` | −519 MB of torch/sympy/networkx; torch is the single most painful dependency to freeze |
| Decode WAV via `soundfile` + `scipy.signal.resample_poly` | No ffmpeg CLI to ship, and no LGPL/GPL audit against the Apache-2.0 licence |
| `platformdirs` upload dir + 24 h pruning | Valid on Windows; bounded disk use |
| `NEURONARRATIVE_FRONTEND_DIST` + `SpaStaticFiles` | Single-process mode: backend serves the SPA, so no dev server, proxy or CORS in a bundle |
| Ollama failure returns `None` | An unreachable LLM can't fail an analysis a user can't debug |
| Confine `/analyze` paths to the upload dir | Arbitrary file read closed before it ships as a local server |

**Measured:** venv 1.0 GB → 442 MB; runtime footprint ≈ 360 MB. Largest remaining:
scipy 97, onnxruntime 77, pandas 67, av 46, numpy 31 MB. `onnxruntime` (VAD) and `av`
are hard dependencies of faster-whisper even though we decode audio ourselves.

### Phase 1 – frozen backend, macOS ✅ DONE (2026-07-30)

| Item | Result |
|------|--------|
| PyInstaller spec | `packaging/neuronarrative.spec` – onedir + macOS `BUNDLE`. `collect_all` over faster_whisper, ctranslate2, onnxruntime, av, soundfile, tokenizers; `collect_submodules("uvicorn")` for its string-resolved loops/protocols. UPX off (corrupts signed dylibs). |
| Launcher | `backend/app/desktop.py`, exposed as the `neuronarrative` console script. Serves the SPA, logs to `~/Library/Logs/neuronarrative/`, opens the browser once healthy. |
| Ephemeral port | Socket bound *before* uvicorn starts and handed over via `server.run(sockets=[...])`, so nothing can race for the port. Written to a state file. |
| Single instance | A second launch finds the running instance via the state file + health probe and reopens that URL instead of starting a second server. |
| ASR model provisioning | **Both** supported: bundled by default (offline first run), `--no-model` for a leaner artifact that downloads on first use. Resolved decision 1 below. |
| Smoke test | `scripts/smoke_desktop.sh` – runs the bundle under `env -i` (no venv, no Python on PATH) with `HF_HUB_OFFLINE=1`, then health → SPA → SPA fallback → upload → analyze → path confinement → real transcription. |

**Measured:** 328 MB bundled-model `.app`, 253 MB with `--no-model`. Build takes ~1 min.

Verified in the frozen bundle, offline, with no Python environment: 4 events detected on the
synthetic fixture, and 20 words transcribed from `say`-synthesised speech with the excerpt
correctly aligned to an event window.

Two failures worth remembering:
- The entry script ran as `__main__`, so `from .main import app` raised `ImportError:
  attempted relative import with no known parent package`. Absolute imports only.
- `StaticFiles(html=True)` does **not** do SPA fallback (directory indexes only); needed the
  `SpaStaticFiles` subclass.

### Phase 2 – native window ✅ DONE (2026-07-30) via pywebview

Chosen over Electron (+150 MB Chromium, Node toolchain, two binaries to sign) and Tauri
(Rust toolchain, same per-OS webviews anyway). pywebview reuses the OS webview, so it is
**+4 MB** and the artifact stays a single signable `.app`.

| Item | Result |
|------|--------|
| Native window | 1440×940, min 1024×700, titled "NeuroNarrative"; verified via `CGWindowListCopyWindowInfo` on the frozen build |
| Thread model | GUI owns the main thread (mandatory on macOS); uvicorn moved to a worker thread |
| Lifecycle | Closing the window sets `server.should_exit` and joins the thread, so no orphaned server |
| Fallback | `NEURONARRATIVE_BROWSER=1` forces the browser; a missing/failing pywebview falls back automatically |
| Stale state file | AppKit termination skips the `finally`, so the instance file can outlive the process — it is health-probed and cleared on next launch (verified: relaunch got a fresh port) |

Remaining shell polish, if wanted: native menu bar, native file-open dialogs (currently the
HTML file input), app icon (`icon=None` in the spec today), auto-update.

### Phase 3 – distribution (~2 weeks)

| Item | Est. | Notes |
|------|------|-------|
| macOS signing + notarization | 1–2 d | Needs Apple Developer ($99/yr). Hardened runtime vs. a spawned subprocess needs the right entitlements. |
| Windows build + Authenticode | 1–2 d | Unsigned ⇒ SmartScreen warning on every download. Cert has an annual cost. |
| Linux AppImage | 1 d | |
| CI packaging matrix | 1–2 d | Three runners, multi-hundred-MB artifacts; expect cache-size pain |
| Cross-OS QA + buffer | 3–5 d | |

### Totals

| Scope | Estimate |
|-------|----------|
| macOS app with a native window, unsigned | ✅ **Done** – phases 0, 1 and 2 |
| Full (3 OSes, signed, in CI) | **~3 weeks** remaining (phase 3 only) |

### Open decisions

1. ~~**Bundle the ASR model or download on first run?**~~ ✅ Resolved: both, bundled by
   default, `--no-model` for a 75 MB smaller artifact.
2. ~~**Shell or no shell?**~~ ✅ Resolved: pywebview native window. Electron rejected on
   size/toolchain/signing cost; revisit only if identical cross-OS rendering or
   auto-update becomes a requirement.
3. **Drop `pandas` (67 MB)?** `_load_gsr` only needs `read_csv` + `sort_values`; stdlib `csv`
   + numpy would do. Worth it only if chasing installer size. **Still open.**
4. **Ollama stays external.** It cannot be bundled (separate daemon, multi-GB models). The
   backend degrades to no-summaries and the UI now says which of the three reasons applies
   (no speech near the event, too little said, or summariser off with the health status).
   ✅ Done.
5. **Windows path for `say`-based smoke testing.** The smoke test skips transcription
   verification where `say` is unavailable; a checked-in speech fixture would fix that.

### Risks

- **Signing is calendar time, not just effort**: notarization round-trips and certificate
  issuance can take days of waiting.
- **Windows/Linux are unproven.** The spec is portable apart from the macOS `BUNDLE` step,
  but ctranslate2/onnxruntime ship native libs that often need per-platform hook fixes.
- **CI artifact size**: a 328 MB bundle per OS per run will strain cache and artifact limits.
- Resolved: PyInstaller + native ML wheels was the big unknown, and dropping torch in phase 0
  is what made the spec straightforward — the first build worked apart from an import bug.

---

## Markdown ↔ Code Accuracy Audit

Last verified 2026-07-31, after the summary-coverage fixes (context widening + hallucinated-token
filtering, confirmed working in the packaged desktop app, then the protocol-cue fallback for
events with no speech within 45 s). The `*_FIX_SUMMARY.md` /
`IMPLEMENTATION_SUMMARY.md` files listed in earlier revisions of this table were deleted in
commit `4cd8d1a`.

| Doc | Matches Code? | Notes |
|-----|---------------|-------|
| `README.md` | ✅ Accurate | Covers drag-drop, event bubbles, export, CI, E2E, lint, license |
| `TODO.md` | ✅ Accurate | This file |
| `CLAUDE.md` | ✅ Accurate | Agent-facing architecture notes; commands verified by running them |
| `docs/system-design.md` | ⚠️ Aspirational by design | Carries a disclaimer + a divergence section. Not adopted: Plotly, Tailwind/shadcn, Zustand, SQLite/Postgres, Dramatiq/Redis, neurokit2, WebSockets, `/api/v1` routes, telemetry. |
