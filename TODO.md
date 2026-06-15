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

---

## P2 – Event Detection

| Item | Status | Notes |
|------|--------|-------|
| Derivative-based event detection | ✅ | `backend/app/services/analysis.py` |
| Changepoint detection (ruptures) | ✅ | Uses `ruptures` library |
| Rule presets (default / sensitive / strict) | ✅ | `RuleSelector.tsx` + backend |
| Pre/post event window config | ✅ | Sliders in `RuleSelector.tsx` |
| Event list in `EventTimeline` component | 🔧 | Component exists; styling/display needs polish |
| Event bubbles overlaid on signal chart | ❌ | Designed in system-design.md; not implemented |

---

## P3 – Speech Processing

| Item | Status | Notes |
|------|--------|-------|
| Audio transcription (Whisper / Vosk) | 🧪 | `_transcribe_audio()` returns `[]` – stub only |
| Speaker diarisation | ❌ | Not started |
| Transcript-to-event time alignment | ❌ | Depends on P3 transcription |
| Transcript timeline viewer in UI | ❌ | Designed; not implemented |

---

## P4 – LLM Summarisation

| Item | Status | Notes |
|------|--------|-------|
| Ollama HTTP client integration | ✅ | `backend/app/services/summary.py` |
| GPU guard / CPU fallback env var | ✅ | `NEURONARRATIVE_REQUIRE_GPU_FOR_SUMMARIZER` |
| Summarisation per detected event | 🔧 | Works but receives empty transcripts (blocked by P3) |
| `summary` + `score` fields in response | ✅ | Schema defined; populated when Ollama is available |

---

## P5 – UX Hardening & Export

| Item | Status | Notes |
|------|--------|-------|
| Session result export to CSV | ❌ | Not implemented |
| Session result export to JSON | ❌ | Not implemented |
| Session result export to SRT / PDF | ❌ | Not implemented |
| EventTimeline UI polish | ❌ | Renders empty state; needs real event cards |
| Drag-and-drop file upload | ❌ | File picker works; D&D not wired |
| Waveform visualisation (Wavesurfer.js) | ❌ | Currently using custom SVG audio proxy |
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
| End-to-end tests (Playwright) | ❌ | Manual Playwright script exists at `/tmp/verify_buttons.cjs` |
| Backend unit tests beyond pytest stub | 🔧 | `backend/tests/` exists; coverage unknown |
| CI/CD pipeline | ❌ | No GitHub Actions workflow file |

---

## Known Issues / Tech Debt

| Issue | File | Priority |
|-------|------|----------|
| `_transcribe_audio()` is a stub – analysis always returns empty transcripts | `backend/app/services/analysis.py:70` | High |
| `EventTimeline` component shows nothing useful without events | `frontend/src/components/EventTimeline.tsx` | Medium |
| No retry / error-recovery on upload failures | `App.tsx` | Medium |
| CSV parsing assumes time column contains "time" in header name | `gsrParser.ts:180` | Medium |
| Backend validates WAV MIME as `audio/wav` / `audio/x-wav` / `audio/vnd.wave` only – mismatches cause 422 errors | `backend/app/api/routes.py` | Low |
| Ollama sidecar in compose uses CUDA layers – breaks on Apple Silicon without native Ollama | `docker/compose.local.yml` | Low |

---

## Markdown ↔ Code Accuracy Audit

| Doc | Matches Code? | Gaps |
|-----|---------------|------|
| `README.md` | ✅ Mostly accurate | Doesn't mention baseline/resistance CSV columns or health pill |
| `IMPLEMENTATION_SUMMARY.md` | ✅ Accurate | Describes implemented gauge + navigation correctly |
| `GAUGE_FIX_SUMMARY.md` | ✅ Accurate | All code references verified |
| `NEEDLE_FIX_SUMMARY.md` | ✅ Accurate | Baseline step-function, resistance interpolation confirmed |
| `TIMELINE_NAVIGATION_ENHANCEMENTS.md` | ✅ Accurate | 7 nav buttons confirmed in code |
| `docs/system-design.md` | ⚠️ Aspirational | P3–P7 largely unimplemented; Plotly/Wavesurfer/Zustand not adopted |
