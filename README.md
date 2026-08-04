# NeuroNarrative

> Align biosignals with conversation to surface emotion-linked summaries.

NeuroNarrative is an in-development, local-first web application that synchronises galvanic skin response (GSR) recordings with audio sessions to help surface physiologically significant moments in conversation. All data stays on your machine.

The recordings it is built for are **MindWalking** sittings: one person works through a scripted recall protocol while a *mindwalker* GSR device tracks their charge level. The app detects the phenomena that method names — Ausschlag, Blitzentladung, langsame Entladung and the rest — aligns them to what was said, and writes the session report the method requires by hand. See [docs/mindwalking-domain.md](docs/mindwalking-domain.md).

**Status: in development.** The pipeline works end to end and the MindWalking phenomenon
catalogue is detected, reviewed and reported. Nothing is yet validated against hand-made labels,
so every figure the app prints is a count rather than a measured accuracy — see
[docs/status.md](docs/status.md), which is explicit about what is unproven, and
[TODO.md](TODO.md) for feature status.

> The packaged desktop `.app` lags the browser build; rebuild with `./scripts/build_desktop.sh`.

---

## What works today

| Area | Status |
|------|--------|
| GSR CSV upload & parsing (column auto-detect) | ✅ |
| WAV audio upload with drag-and-drop | ✅ |
| Session preview: semicircular charge-level (LP) gauge | ✅ |
| Session preview: WaveSurfer.js waveform + playback | ✅ |
| Session preview: full-recording overview chart (click-to-seek) | ✅ |
| Session preview: zoomed detail chart | ✅ |
| Timeline navigation (Start / -10s / +10s / 25% / 50% / 75% / End) | ✅ |
| Event detection (derivative + changepoint via `ruptures`) | ✅ |
| Detection rulesets: Balanced / Sensitive / Strict (`default` / `sensitive` / `strict` on the wire) | ✅ |
| Configurable pre/post event context windows | ✅ |
| Event markers overlaid on overview and detail charts | ✅ |
| Event list with score, ΔkΩ, and jump-to buttons | ✅ |
| MindWalking phenomenon catalogue (A, T, BE, LPA, X, KVZ, KB) | ✅ |
| Analysis in the LP (charge level) domain, shared by both CSV parsers | ✅ |
| BK3 protocol parsing: procedure/exercise tree from the spoken cues | ✅ |
| Session narrative: time-segmented report with real timestamps, markdown export | ✅ |
| Phenomenon labelling (confirm / reject / reclassify / missed) with persistence | ✅ |
| Evaluation: per-kind precision, recall and F1 against labels | ✅ |
| Two-column review layout, resizable scrollable panes, cross-panel hover linking | ✅ |
| Audio transcription (`small` model, on-device, no ffmpeg, VAD, deterministic) | ✅ |
| Transcript timeline with word-level click-to-seek | ✅ |
| GPU acceleration, auto-detected (Apple Metal / NVIDIA CUDA / CPU) | ✅ |
| LLM summarisation per event (Ollama, auto-detected, answers in the transcript's language) | ✅ |
| Session export: CSV, JSON, SRT, PDF | ✅ |
| Backend health status pill with auto-retry | ✅ |
| Backend unit tests (pytest, 198 passing) | ✅ |
| Frontend E2E tests (Playwright, 24 passing) | ✅ |
| ESLint config (TypeScript + React rules) | ✅ |
| CI: GitHub Actions (frontend lint + typecheck + build, backend pytest) | ✅ |
| Speaker diarisation | ❌ deliberately not done — the corpus is solo, so there is nothing to separate; cue matching carries the role signal instead |
| `SN` / `FN` needle-state detection | ❌ needs labelled examples |
| Classifiers (BE vs KB, SN vs FN) | ❌ tooling ready, needs labels |
| EEG ingestion | ❌ not started |
| Desktop app: frozen macOS `.app` (PyInstaller), native window, offline-capable | ✅ |
| Desktop app: Windows / Linux builds via GitHub Actions on a `v*` tag | ✅ built and boot-checked; macOS Intel path untried |
| Desktop app: code signing / notarization | ❌ not started — Gatekeeper and SmartScreen will object |
| Build version shown in the header and About box, with copyright | ✅ |

---

## Repository layout

```
.
├── backend/                  # FastAPI service
│   ├── app/
│   │   ├── api/              # HTTP routes and request/response schemas
│   │   ├── core/             # Settings (pydantic-settings)
│   │   ├── services/         # Signal processing, transcription, summarisation, narrative, labels
│   │   │   └── phenomena/    # LP conditioning, primitives, detectors, calibration, evaluation
│   │   └── utils/
│   ├── tests/                # pytest suite
│   └── pyproject.toml
├── docker/                   # Compose stack for local development
│   ├── backend.Dockerfile
│   ├── frontend.Dockerfile
│   └── compose.local.yml
├── docs/
│   ├── images/               # frontend-overview.png — predates the current UI
│   ├── system-design.md      # Aspirational architecture reference
│   ├── mindwalking-domain.md            # The MindWalking method: device, phenomena, session protocol
│   ├── phenomena-detection-design.md    # Design + as-built: detecting A / T / BE / LPA / X / KVZ / KB
│   ├── session-narrative-design.md      # Design: BK3 protocol parsing + summaries
│   └── status.md             # Current state: what is built, measured, and unproven
├── frontend/                 # React + Vite + TypeScript
│   ├── src/
│   │   ├── components/       # SignalPreview, EventTimeline, TranscriptTimeline, UploadPanel, RuleSelector
│   │   ├── utils/            # gsrParser, logger
│   │   └── App.tsx
│   ├── tests/e2e/            # Playwright tests
│   ├── .eslintrc.cjs
│   └── vite.config.ts
├── packaging/                # PyInstaller spec for the desktop build
├── scripts/                  # build_desktop.sh, smoke_desktop.sh, dev helpers
├── CLAUDE.md                 # Architecture notes for AI coding agents
└── TODO.md                   # Detailed feature status
```

The repo-root `test_gsr.csv` / `test_audio.wav` fixtures are the synthetic session used by
the Playwright suite and `scripts/test_api.py`; regenerate them with
`python scripts/generate_synthetic_data.py`.

---

## Getting started

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev,asr,gpu]" # "gpu" adds MLX on Apple silicon; no-op elsewhere
uvicorn app.main:app --reload
```

The API runs on <http://localhost:8000>. Key endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Liveness check; reports `summarizer_status`, `cpu`, `asr_threads`, `gpu_available` |
| `POST` | `/api/upload` | Accept GSR CSV + WAV, stage them, return their paths |
| `POST` | `/api/analyze` | Start an analysis; returns `202 {job_id}` immediately |
| `GET` | `/api/analyze/{job_id}` | Poll status: `stage`, `progress` (0–1), and `result` when done |
| `GET` | `/api/labels/{recording_id}` | Labels made against a recording |
| `PUT` | `/api/labels/{recording_id}` | Record a verdict (confirmed / rejected / reclassified / missed) |
| `DELETE` | `/api/labels/{recording_id}/{phenomenon_id}` | Clear one verdict |
| `POST` | `/api/labels/{recording_id}/evaluate` | Per-kind precision, recall and F1 from the labels so far |

Analysis is a **background job**, not a long request. Transcribing a 54-minute recording
takes several minutes, and the desktop window enforces its own per-request timeout, so a
synchronous call would fail no matter what the client sets. The UI polls once per second and
shows a progress bar.

Uploads are staged in a per-user cache directory (`~/Library/Caches/neuronarrative/uploads`
on macOS, `%LOCALAPPDATA%` on Windows, `~/.cache` on Linux) and pruned after 24 h. `/analyze`
only accepts paths inside that directory.

Useful environment variables (all prefixed `NEURONARRATIVE_`, or use `backend/.env`):

| Variable | Default | Purpose |
|---|---|---|
| `UPLOAD_DIR` | per-user cache dir | Where uploads are staged |
| `UPLOAD_RETENTION_HOURS` | `24` | Age at which staged uploads are pruned; `0` disables |
| `ASR_BACKEND` | `auto` | `auto` picks MLX (Apple GPU) → CUDA → CPU. Force with `mlx`, `cuda`, `cpu` |
| `ASR_MODEL` | `small` | Model size — see the comparison below |
| `ASR_VAD` | `true` | Skip non-speech (faster on recordings with pauses, prevents hallucinated text over silence) |
| `ASR_TEMPERATURE` | `0.0` | Greedy decoding. Whisper's default fallback chain re-decodes hard passages with random sampling — see below |
| `ASR_MAX_WORDS_PER_SEC` | `6.0` | Windows exceeding this are hallucination loops and are dropped; `0` disables |
| `ASR_LANGUAGE` | unset | Force a language code (e.g. `de`); unset auto-detects |
| `ASR_THREADS` | `0` (auto) | Transcription threads. Auto = half the performance cores, so the machine stays usable. See below. |
| `ASR_MODEL_DIR` | per-user cache dir | Model download cache |
| `SUMMARY_CONTEXT_SEC` | `45.0` | Fallback radius when the pre/post window holds too little speech to summarise; `0` disables. Sessions are mostly silent, so a 12 s window is empty for most events |
| `SUMMARY_MIN_WORDS` | `4` | Excerpts shorter than this are not sent to the LLM |
| `LABEL_DIR` | per-user data dir | Where hand-made phenomenon labels are stored (user data, not cache) |
| `FRONTEND_DIST` | unset | When set, the backend serves the built SPA at `/` |

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs on <http://localhost:5173> (or the next free port) and proxies `/api/*` to the backend.

> **If Docker is running**, it binds `*:8000` over IPv6 and `localhost` resolves to `::1` first, so the proxy reaches Docker instead of the backend and every analysis fails with a 500 and nothing in the backend log. Start the dev server with `VITE_PROXY_TARGET=http://127.0.0.1:8000`, or stop Docker. CORS is configured to accept any `localhost` port, so port conflicts are handled automatically. Set `VITE_PROXY_TARGET` if the backend is not on `http://localhost:8000`.

Other frontend scripts: `npm run lint` (ESLint), `npm run typecheck` (`tsc --noEmit`), `npm run build`.

For a single-process setup with no dev server (and therefore no proxy or CORS involved),
build the frontend and point the backend at it:

```bash
cd frontend && npm run build
cd ../backend && NEURONARRATIVE_FRONTEND_DIST=../frontend/dist uvicorn app.main:app
# whole app on http://localhost:8000
```

### Docker (both services together)

```bash
docker compose --project-directory "$(pwd)" -f docker/compose.local.yml up --build
```

The frontend container runs the Vite dev server and reaches the backend through the proxy
via `VITE_PROXY_TARGET=http://backend:8000`. The Ollama sidecar sits behind the
`summarizer` compose profile and requests an NVIDIA GPU, so it is not started by default
and does not work on Apple Silicon — run Ollama natively there (see below).

---

## Desktop build (macOS)

Produces a double-clickable `NeuroNarrative.app` that needs no Python, no Node and no
terminal. It starts the API on an ephemeral port, serves the built UI itself, and shows it
in a **native window** (pywebview → system WKWebView, so no browser engine is bundled).

```bash
cd backend && pip install -e ".[asr,gpu,desktop,packaging]" && cd ..   # "gpu" is a no-op off Apple silicon
./scripts/build_desktop.sh              # ~721 MB, `small` ASR model bundled (works offline)
./scripts/build_desktop.sh --no-model   # ~257 MB, model downloads on first use
NEURONARRATIVE_ASR_MODEL=base ./scripts/build_desktop.sh   # ~400 MB, faster, lower accuracy
./scripts/smoke_desktop.sh              # verify the bundle with no venv, network offline
```

Output lands in `dist/` (both a `NeuroNarrative/` directory and a `NeuroNarrative.app`).

| Behaviour | Detail |
|---|---|
| Window | 1440×940 native window, min 1024×700. Closing it shuts the server down. |
| Port | Ephemeral — 8000 is often taken. The chosen URL is printed and logged. |
| Logs | `~/Library/Logs/neuronarrative/neuronarrative.log` |
| Uploads | `~/Library/Caches/neuronarrative/uploads`, pruned after 24 h |
| ASR model | Bundled build reads it from inside the `.app`; `--no-model` falls back to `~/Library/Caches/neuronarrative/models` and downloads on first use |
| Second launch | Detects the running instance and reopens it instead of starting a second server; a stale record is health-probed and cleared |
| `NEURONARRATIVE_BROWSER=1` | Use the system browser instead of the native window |
| `NEURONARRATIVE_NO_BROWSER=1` | Headless: serve only, open nothing (used by the smoke test) |

**Not yet done:** the bundle is unsigned and un-notarized, so macOS Gatekeeper will block it
if it's downloaded rather than built locally (right-click → Open, or
`xattr -dr com.apple.quarantine NeuroNarrative.app`). Windows and Linux builds are untried.
See [TODO.md](TODO.md#p7-desktop-packaging--detailed-breakdown).

---

## Local LLM (optional)

Event summaries are generated by a local Ollama model. At startup the app probes Ollama and
reports the outcome in `GET /api/health` as `summarizer_status`, so a missing summary always
has a stated reason rather than a silent shrug.

Summaries are written in the language of the excerpt, so a German session yields German
summaries.

Four things used to break this quietly — worth knowing, because none of them looked like
what they were:

* The GPU check tested for **CUDA only**, so every Apple silicon Mac reported "no GPU" and
  disabled summaries — with Ollama running happily on Metal next door. Metal now counts.
* The configured model name is easy to get wrong. `qwen2.5:7b-instruct-q4_K_M` looks
  plausible but Ollama may only have `qwen2.5:7b` pulled, and requesting a missing model
  fails per event with no clue why. The probe now falls back to an installed model of the
  same family and says so in `summarizer_status`.
* **The excerpt window was usually empty.** Sessions are mostly silent — a 54-minute
  recording held 1589 words — so the 5 s/7 s window around an event caught nothing for 17
  of 23 events. The search now widens to `SUMMARY_CONTEXT_SEC` (45 s) only when the tight
  window comes up short, so dense passages keep the more precise excerpt. When even that
  finds nothing, the facilitator's session cues take over: "Ruf … zurück" opens an
  exercise, "Danke" closes it, and "Beschreibe" / "Was siehst du noch" / "Was ist am
  deutlichsten" bound subsections — the event's excerpt becomes everything said in its
  exercise, which is the only context there is.
* **Whisper invents non-words over room tone** — runs like `ლლლლ`, `සිවිිිි` or `ʕ ʔ ʔ`.
  These are too few per window to look like the hallucination loops the word-rate check
  catches, but they became the text an event was summarised from. They are now filtered by
  script; numbers and punctuation survive, because spoken meter readings are real content.

An event with no summary now says which of these applies: no speech near it, too little
said to paraphrase, or the summariser being off.

```bash
# Install Ollama (https://ollama.com), then:
ollama pull qwen2.5:7b
ollama serve
```

Use `NEURONARRATIVE_SUMMARIZER_ENABLED=false` to switch summaries off entirely.

```bash
# Install Ollama (https://ollama.com), then:
ollama pull qwen2.5:7b-instruct-q4_K_M
ollama serve
```

Relevant environment variables:

```bash
NEURONARRATIVE_OLLAMA_URL=http://127.0.0.1:11434/api/generate
NEURONARRATIVE_OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
NEURONARRATIVE_SUMMARIZER_ENABLED=false          # disable entirely
NEURONARRATIVE_REQUIRE_GPU_FOR_SUMMARIZER=false  # skip GPU guard
```

On macOS with Apple Silicon, run Ollama natively (not inside Docker) and point the backend at `http://host.docker.internal:11434/api/generate` if using the compose stack.

---

## Audio transcription

Transcription uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2),
on-device, in a worker thread inside the backend process. WAV decoding and resampling to
16 kHz go through `soundfile` + `scipy`, so **no ffmpeg binary is required**.

### Hardware acceleration (automatic)

The backend is chosen at runtime from what the machine actually offers — nothing to
configure:

| Machine | Backend | Device |
|---|---|---|
| Apple silicon M1–M5 with the `gpu` extra | MLX | **Metal GPU** |
| Apple silicon without the extra | faster-whisper | CPU (int8) |
| NVIDIA GPU (Windows/Linux) | faster-whisper | **CUDA** (float16) |
| Intel Mac, GPU-less Windows/Linux | faster-whisper | CPU (int8) |

Every probe degrades rather than raises, so an unusable driver or a missing package falls
back to CPU instead of failing. Force a choice with `NEURONARRATIVE_ASR_BACKEND=mlx|cuda|cpu`.
`GET /api/health` reports what was picked.

Measured on an M1 Pro, German speech:

| Backend | Word error rate | Throughput | 54-min recording |
|---|---|---|---|
| **MLX (Metal GPU)** | **0.0 %** | **6.3× realtime** | **~8.5 min** |
| CPU int8 | 3.3 % | 1.6× realtime | ~33 min |

The GPU path is both faster *and* slightly more accurate, because MLX runs float16 where
the CPU path uses int8 quantisation.

### Choosing a model

Measured on noisy German speech (~10 dB SNR), CPU backend:

| Model | Word error rate | Size |
|---|---|---|
| `tiny` | 16.7 % | 75 MB |
| `base` | 6.7 % | 141 MB |
| **`small` (default)** | **3.3 %** | 464 MB |

`small` is the default because transcript quality drives everything downstream — excerpts
and summaries are only as good as the words. `NEURONARRATIVE_ASR_MODEL=base` trades accuracy
for speed; `large-v3-turbo` is available for maximum quality on the GPU path.

### Voice activity detection

Long silences are skipped before transcription. This both saves time and prevents Whisper's
worst failure mode: inventing text over quiet passages and repeating one phrase for minutes.

The two backends detect speech differently, and not by preference — **onnxruntime (which
Silero VAD needs) segfaults when loaded in the same process as MLX.** Verified: the crash
depends on initialisation order and `KMP_DUPLICATE_LIB_OK` does not help. So the MLX path
uses a self-contained energy detector in numpy (3 ms on a 41 s recording, versus 168 ms for
Silero, and it picked the same speech region), while the CPU/CUDA path keeps faster-whisper's
built-in Silero VAD. Disable either with `NEURONARRATIVE_ASR_VAD=false`.

faster-whisper reports a per-word probability, which populates `TranscribedWord.confidence`.
`align_transcript` drops words below `min_confidence` (0.5), so very uncertain words no
longer reach the summariser — that filter existed before but was inert while confidence was
always `None`.

---

## Testing

```bash
# Backend unit tests
cd backend && pytest tests/ -v

# Frontend static checks
cd frontend && npm run lint && npm run typecheck

# Frontend E2E. playwright.config.ts pins baseURL to port 5175,
# so the dev server must listen there rather than on the default 5173.
cd frontend
npx playwright install chromium   # once, or after a @playwright/test upgrade
npx vite --port 5175 &
npx playwright test
```

`.github/workflows/ci.yml` runs the frontend lint/typecheck/build and the backend pytest
suite on every push and PR to `main`. The E2E suite is **not** in CI — it needs a running
dev server and browser binaries, so run it locally when changing the preview UI. The
linked-view specs stub the analysis from a captured backend response, so they need only the
dev server.

### Releases

Pushing a `v*` tag builds the desktop app on macOS (Apple silicon and Intel), Windows and
Linux and attaches the archives to a GitHub release, together with a `SHA256SUMS` file:

```bash
git tag v0.2.0
git push origin v0.2.0
```

Each platform is gated on a boot check — the bundle is launched headless and must answer
`/api/health` and serve the SPA before it is packaged. Running the workflow manually
(*Actions → Release → Run workflow*) builds the same artifacts without publishing anything,
which is how to test a packaging change before committing to a tag.

The builds are **not code-signed**: macOS Gatekeeper and Windows SmartScreen will both
object, and the release notes explain how to get past them. On Linux the app has no bundled
GUI toolkit and opens your default browser instead of a native window.

---

## What's next

See [TODO.md](TODO.md) for the full breakdown. The most impactful gaps are:

- **Label a session** — the tooling exists but no labels have been made, so no accuracy figure in this project is measured rather than counted
- **Transcript timeline UX** — currently shows words but needs better visual design
- **EEG support** — no ingestion pipeline yet
- **Desktop packaging** — ship as a standalone app without requiring a terminal

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
