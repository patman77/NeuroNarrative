# NeuroNarrative – Project TODO

Status legend: ✅ Done · 🔧 Partial · ❌ Not started · 🧪 Stubbed

---

## P0 – Scaffold & Core Pipeline

| Item | Status | Notes |
|------|--------|-------|
| FastAPI backend (health, upload, analyze routes) | ✅ | `backend/app/api/routes.py` |
| React + Vite frontend shell | ✅ | `frontend/src/` |
| Docker Compose local stack | ✅ | `docker/compose.local.yml` – both services |
| Vite proxy → backend on :8000 | ✅ | `frontend/vite.config.ts` |
| CORS allow list for localhost:5173 | ✅ | `backend/app/main.py` |
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
| Backend health status pill in header | ✅ | Added in current session |
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
| Rule presets (default / sensitive / strict) | ✅ | `RuleSelector.tsx` + backend |
| Pre/post event window config | ✅ | Sliders in `RuleSelector.tsx` |
| Event list in `EventTimeline` component | ✅ | Polished cards: badge, score, delta_kohm color, seek-to button |
| Event bubbles overlaid on signal chart | ✅ | Orange markers on `OverviewChart` + `SignalChart` |

---

## P3 – Speech Processing

| Item | Status | Notes |
|------|--------|-------|
| Audio transcription (Whisper / Vosk) | ✅ | `openai-whisper==20250625` installed; `_transcribe_audio()` uses tiny model; graceful `[]` fallback if import fails |
| Speaker diarisation | ❌ | Not started |
| Transcript-to-event time alignment | ✅ | `align_transcript()` in `transcript.py` – runs when transcript is non-empty |
| Transcript timeline viewer in UI | ✅ | `TranscriptTimeline.tsx` – word-level click-to-seek; empty-state message when no transcript |

---

## P4 – LLM Summarisation

| Item | Status | Notes |
|------|--------|-------|
| Ollama HTTP client integration | ✅ | `backend/app/services/summary.py` |
| GPU guard / CPU fallback env var | ✅ | `NEURONARRATIVE_REQUIRE_GPU_FOR_SUMMARIZER` |
| Summarisation per detected event | ✅ | Works; Whisper now installed so transcripts populate when audio has speech |
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
| PyInstaller / Electron packaging | ❌ | Not started |
| End-to-end tests (Playwright) | ✅ | `frontend/tests/e2e/preview_flow.spec.ts` – 3 tests, all pass |
| Backend unit tests | ✅ | `test_events.py` (4 tests), `test_analysis.py` (5 tests) – skip gracefully when deps absent |
| CI/CD pipeline | ✅ | `.github/workflows/ci.yml` – frontend build + typecheck, backend pytest, parallel jobs |

---

## Known Issues / Tech Debt

| Issue | File | Priority |
|-------|------|----------|
| Whisper installed (`openai-whisper==20250625`); tiny model downloads on first use (~72 MB) | `backend/app/services/analysis.py` | ✅ Resolved |
| `EventTimeline` export bar only visible after analysis (correct) | `frontend/src/components/EventTimeline.tsx` | — |
| Speaker diarisation not implemented | — | Medium |
| Transcript timeline viewer in UI | — | ✅ Implemented (`TranscriptTimeline.tsx`) |
| Local venv deps installed; disk was full but user freed 1.8 GB | `backend/.venv` | ✅ Resolved |
| Backend validates WAV MIME as `audio/wav` / `audio/x-wav` / `audio/vnd.wave` / `audio/wave` / `""` + filename fallback | `backend/app/api/routes.py` | ✅ Fixed |
| Ollama sidecar in compose uses CUDA layers – breaks on Apple Silicon without native Ollama | `docker/compose.local.yml` | Low |
| SRT / PDF export | — | ✅ Implemented |

---

## Markdown ↔ Code Accuracy Audit

| Doc | Matches Code? | Gaps |
|-----|---------------|------|
| `README.md` | 🔧 Partially accurate | Doesn't mention drag-drop, event bubbles, export, CI/CD, E2E tests |
| `IMPLEMENTATION_SUMMARY.md` | ✅ Accurate | Describes implemented gauge + navigation correctly |
| `GAUGE_FIX_SUMMARY.md` | ✅ Accurate | All code references verified |
| `NEEDLE_FIX_SUMMARY.md` | ✅ Accurate | Baseline step-function, resistance interpolation confirmed |
| `TIMELINE_NAVIGATION_ENHANCEMENTS.md` | ✅ Accurate | 7 nav buttons confirmed in code |
| `docs/system-design.md` | ⚠️ Aspirational | P3–P7 largely unimplemented; Plotly/Wavesurfer/Zustand not adopted |
