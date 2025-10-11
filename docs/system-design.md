# NeuroNarrative Web Application – System Architecture & Development Plan

## 1. Product Vision
NeuroNarrative is a local-first web application that aligns speech audio with biosignals (initially galvanic skin response, later EEG) to surface what was being said whenever physiology changes. Users upload a synchronized WAV recording and CSV/TSV biosignal export, configure event-detection rules, and receive interactive plots with transcript snippets and LLM-generated summaries anchored to signal spikes or drops. The solution must run completely on the user's machine or a self-hosted node so that sensitive recordings never leave the local environment.

### Core Goals
- **Multimodal alignment** – keep audio, transcript, and biosignals in sync at millisecond precision, including optional manual offsets.
- **Event intelligence** – detect significant physiological changes (peaks, drops, change points, tonic/phasic shifts) with configurable rules.
- **Narrative insight** – extract transcript segments around events, remove filler words, and summarize them via a local LLM into compact "bubble" annotations.
- **Explainability** – let users audit the raw transcript and signal traces that produced each summary.
- **Extensibility** – add additional biosignal channels (EEG bands, heart rate) without rewriting the pipeline.

## 2. Target Users & Use Cases
- **Researchers / psychologists** running small lab studies who need to correlate GSR/EEG with speech content.
- **Therapists / coaches** who review sessions to identify emotionally charged moments.
- **Qualitative UX researchers** who annotate interviews with physiological cues.

Primary use cases:
1. Upload paired WAV + GSR CSV to explore arousal events and hearing what was spoken then.
2. Configure custom rules (e.g., derivative threshold, change-point penalty) and preview detections.
3. Export event tables, annotated transcripts, or PDF reports for collaboration.

## 3. Success Metrics & Constraints
- Accurate alignment tolerance ≤ ±40 ms between audio and biosignal timeline.
- Event detection latency < 10 s for a 60-minute session on a modern laptop.
- Summaries stay local; no external API calls required.
- UI remains responsive when plotting ≥ 1-hour session sampled at 50 Hz (180k points).

## 4. Development Roadmap
| Phase | Scope | Key Deliverables |
| --- | --- | --- |
| **P0 – Project Scaffold** | Repository setup, lint/test tooling, base license, end-to-end smoke script with synthetic data. | FastAPI skeleton with `/healthz`, React/Vite app with Tailwind + shadcn/ui, Docker Compose, CI (lint + unit tests). |
| **P1 – Data Ingestion & Alignment** | File upload, storage, baseline preprocessing. | WAV/CSV upload API, CSV schema inference, resampling utilities, manual/automatic offset estimation, local persistence (SQLite/PostgreSQL), baseline visualization. |
| **P2 – Event Detection Engine** | Configurable rules and evaluation. | Rule definition schema, derivative & amplitude thresholds, change-point detection (ruptures), SCR peak detection (NeuroKit2), unit-tested synthetic scenarios. |
| **P3 – Speech Processing** | Local ASR + transcript cleaning. | Whisper.cpp/Whisper (user choice) integration, diarization-ready schema, filler removal, sentence segmentation, searchable transcript viewer. |
| **P4 – Summaries & Insight Layer** | Local LLM summaries and scoring. | Ollama/llama.cpp connector, summary prompt templates, interestingness scoring (physiology + speech features), event bubble metadata. |
| **P5 – UI/UX Completion** | Narrative explorer, rule builder, exports. | Zoomable Plotly.js chart with annotation bubbles, waveform lane, transcript timeline, rule editor modal, data export (CSV/JSON/SRT/PDF). |
| **P6 – EEG & Multi-Channel Extensibility** | Generalize pipelines for additional sensors. | Channel abstraction, EEG preprocessing presets (band-pass, PSD), UI channel selector, documentation updates. |
| **P7 – Hardening & Packaging** | Observability, packaging, documentation. | App telemetry (OpenTelemetry), error logging, offline installer (PyInstaller / Electron shell), user guide & sample datasets. |

## 5. Recommended Tech Stack

### Frontend
- **Framework**: React 18 + Vite + TypeScript.
- **UI Library**: shadcn/ui (Radix primitives) with Tailwind CSS for consistent theming.
- **State Management**: Zustand for lightweight global state (selection, rule presets, playback state).
- **Data Visualization**: Plotly.js for time-series zooming, annotations, and multi-channel overlays; Wavesurfer.js for waveform rendering; React Flow for optional timeline graph view.
- **Media Playback**: HTML5 Audio element synchronized with charts; Web Audio API for waveform extraction.

### Backend
- **Language/Framework**: Python 3.11 + FastAPI.
- **Data Processing**: pandas, numpy, scipy, neurokit2, ruptures, librosa/pydub.
- **ASR**: Whisper (OpenAI) or whisper.cpp for CPU/GPU local inference. Optionally integrate Vosk for lower resource usage.
- **Summarization**: Ollama or llama.cpp server clients for local LLMs (Qwen2.5 7B, Llama 3.1 8B, Mistral Nemo 12B).
- **Storage**: SQLite for local single-user deployments, PostgreSQL for multi-user; store uploads on filesystem or S3-compatible bucket (MinIO).
- **Task Processing**: Dramatiq (Redis broker) or FastAPI background tasks for ingestion jobs.
- **Packaging**: Poetry/uv for dependency management, Docker for reproducible builds, PyInstaller/Electron wrapper for desktop bundles.

### Tooling & Quality
- **Testing**: Pytest (backend), Vitest + Testing Library (frontend), Playwright (E2E).
- **Linting/Formatting**: Ruff + Black + isort; ESLint + Prettier.
- **CI/CD**: GitHub Actions (lint, test, build, packaging smoke test).
- **Observability**: Prometheus metrics, OpenTelemetry traces, Sentry (optional) for error capture (can be disabled offline).

### Licensing Strategy
- **Code**: Apache License 2.0 recommended for contributor patent safety and enterprise adoption.
- **Models / Prompts / Documentation**: Creative Commons Attribution 4.0 (CC BY 4.0).

## 6. High-Level Architecture
```
+-----------------------+      WebSocket/REST      +--------------------------+
|  React Frontend       | <---------------------> | FastAPI Gateway          |
| - Upload & Rule UI    |                         | - Auth & Session Mgmt    |
| - Plotly Timeline     |                         | - File Orchestration     |
| - Transcript Viewer   |                         | - Job Dispatch           |
+-----------+-----------+                         +-----------+--------------+
            |                                                     |
            |                                      Background Jobs | (Dramatiq)
            |                                                     v
            |                                       +-------------------------+
            |                                       | Processing Workers      |
            |                                       | - Signal Preprocess     |
            |                                       | - Event Detection       |
            |                                       | - ASR & Cleaning        |
            |                                       | - Summarization (LLM)   |
            |                                       +-------------------------+
            |                                                     |
            v                                                     v
+---------------------+      +--------------------+      +--------------------+
| Object Storage      |      | Relational DB      |      | Local LLM Runtime  |
| (uploads, cache)    |      | (projects, events) |      | (Ollama/llama.cpp) |
+---------------------+      +--------------------+      +--------------------+
```

### Component Responsibilities
- **FastAPI Gateway** – Handles uploads, orchestrates preprocessing jobs, streams progress via WebSockets, serves transcript/event data.
- **Processing Workers** – Perform CPU-intensive tasks (resampling, detection, ASR) asynchronously, persisting results and artifacts.
- **Local LLM Runtime** – Exposed via HTTP (Ollama) or gRPC for low-latency summarization requests with deterministic prompts.
- **Storage Layer** – Maintains raw files, derived data (resampled signal, transcripts), and metadata in normalized schema.

## 7. Data & Processing Pipelines
1. **Upload & Validation**
   - Accept single-session package (WAV + CSV + optional metadata JSON). Validate sampling rate, channel presence, header names.
   - Compute checksum, store files, and create a processing job entry.

2. **Signal Preprocessing**
   - Normalize timestamps to seconds, resample to user-selected Hz (default 10 Hz for detection, keep original for visualization).
   - Remove artifacts (median filter, Savitzky–Golay smoothing), z-score normalization.
   - Optional EDA decomposition (tonic vs phasic) via neurokit2, with caching per parameter set.

3. **Event Detection**
   - Rule schema supports derivative z-threshold, absolute delta, percentage change, SCR peaks, change-point (ruptures PELT/RBF).
   - Merge overlapping detections using configurable refractory window.
   - Compute metrics per event (ΔkΩ, slope, area under curve, baseline value) for scoring.

4. **ASR & Transcript Cleaning**
   - Run Whisper (configurable model size) with word timestamps.
   - Remove filler tokens using locale-specific lists, merge duplicates, maintain timestamps.
   - Segment transcript into clauses/sentences using pause thresholds (≥500 ms) and punctuation from ASR.

5. **Event Window Extraction**
   - For each event time t*, gather transcript words within `[t*−pre, t*+post]` (default 5 s before, 7 s after).
   - Calculate speech features (word count, speaking rate, confidence, keyword density).

6. **Summarization**
   - Guard conditions (min tokens, ASR confidence). If satisfied, call local LLM with strict prompt returning JSON summary ≤20 words.
   - Combine physiological metrics and speech features into `interestingness_score` for bubble ranking.

7. **Packaging Outputs**
   - Persist event objects with references to transcripts, audio segments, and summary metadata.
   - Generate downloadable assets: CSV/JSON event tables, SRT/VTT caption exports, PDF report with embedded plots (WeasyPrint).

## 8. Data Model Sketch
- `project`: id, name, created_at, locale, sampling_rate, timezone.
- `session`: id, project_id, title, recording_started_at, duration, status, offsets, notes.
- `media_asset`: id, session_id, type (wav/csv/json), path, checksum, metadata.
- `signal_channel`: id, session_id, name (GSR, EEG_Fp1, etc.), raw_sample_rate, units.
- `signal_sample`: timeseries storage (chunked tables or compressed parquet) for resampled data.
- `event_rule`: id, session_id, type, parameters JSON, enabled flag.
- `event`: id, session_id, rule_id, timestamp, metrics JSON, score.
- `transcript_segment`: id, session_id, start_s, end_s, text, confidence, speaker.
- `event_summary`: id, event_id, summary_text, llm_model, window_start, window_end, interestingness.

## 9. API Design Overview
- `POST /api/v1/sessions` – Create session and initiate upload.
- `POST /api/v1/sessions/{id}/files` – Upload WAV/CSV files (multipart) or zipped bundle.
- `POST /api/v1/sessions/{id}/process` – Trigger (re-)processing with specified rule set.
- `GET /api/v1/sessions/{id}` – Session metadata, processing status.
- `GET /api/v1/sessions/{id}/signals` – Stream downsampled signal data for plotting.
- `POST /api/v1/sessions/{id}/rules` – Save or test detection rules (dry-run returns preview events).
- `GET /api/v1/sessions/{id}/events` – Paginated events with metrics, transcripts, summaries.
- `WS /api/v1/sessions/{id}/progress` – Job updates.
- `POST /api/v1/sessions/{id}/exports` – Generate requested export (CSV/JSON/SRT/PDF).
- `POST /api/v1/summarize` – Internal endpoint to proxy to local LLM runtime (optional if direct client access allowed).

## 10. UI/UX Design System

### Design Principles
- **Time-synchronized clarity** – Always show where the audio playhead is across all visualizations.
- **Configurable detail** – Users can adjust summary density (top K events, word limits) and rule sensitivities.
- **Progressive disclosure** – Start with high-level event markers; expand into transcripts and raw numbers on demand.
- **Accessibility** – WCAG 2.1 AA contrast, keyboard navigation, screen-reader-friendly labeling.

### Global Layout
- **Shell**: Top app bar (project selector, session dropdown, play/pause, export menu). Left rail for navigation (Sessions, Rule Presets, Reports, Settings).
- **Main Workspace**: Three resizable panes in a grid layout:
  1. **Signal Panel** (top) – Stacked Plotly charts for GSR and additional channels; overlays event markers and summary bubbles. Includes zoom brush and channel toggles.
  2. **Transcript Panel** (middle) – Scrollable timeline with word or sentence chips aligned to time; clicking centers the playhead.
  3. **Insight Panel** (right) – Event table with sortable columns (time, delta, score, summary). Selecting a row highlights marker on charts.
- **Playback Footer**: Transport controls, playback speed, offset adjustment slider, and event navigation buttons (prev/next interesting event).

### Component-Level Designs
1. **Upload & Session Setup Dialog**
   - Drag-and-drop area accepting WAV + CSV simultaneously or zipped bundle.
   - Metadata form: session title, participant code, baseline notes, default offset.
   - Validation checklist with immediate feedback (missing columns, sampling mismatch).

2. **Rule Builder Drawer**
   - Tabs per rule type (Derivative Spike, Change Point, SCR Peak, Custom Script).
   - Parameter controls (sliders/input fields) with inline descriptions and unit hints.
   - Preview button runs detection on a selected time window and overlays tentative markers on the chart before saving.
   - Preset templates (e.g., "High sensitivity interview", "Calm baseline").

3. **Signal Timeline**
   - Plotly charts with shared x-axis; each event bubble is an annotation with truncated summary text.
   - Hover reveals tooltip containing raw metrics, summary, and quick actions (play audio, open transcript snippet).
   - Channel legend toggles visibility; additional EEG channels appear as separate traces or heatmap (spectrogram).

4. **Transcript Explorer**
   - Sentence chips color-coded by interestingness score.
   - Option to expand into raw word-level view with filler words greyed out or removed.
   - Search bar to locate keywords and highlight matching moments on the timeline.

5. **Summary Bubble Configurator**
   - Slider for max words (8–25) and toggle for "Only show top N events".
   - Dropdown to choose summarization model (Qwen2.5, Llama3.1) and temperature.
   - Confidence indicator if LLM returned "NONE" or low-quality response.

6. **Exports Modal**
   - Checkboxes for Event CSV, Transcript w/ annotations, Audio snippets, PDF report.
   - Option to include/exclude physiological metrics or LLM summaries.

### Responsiveness
- Desktop-first with min width 1280px; for tablets, stack panels vertically and provide dedicated navigation via tabs.
- Provide simplified read-only report view for mobile (list of events and audio snippets) but limit editing functions.

## 11. Security, Privacy & Compliance
- Local-first deployments store data on disk; secure directories with OS permissions.
- Optional user authentication for multi-user nodes (FastAPI JWT + hashed passwords).
- Support encryption-at-rest (PostgreSQL + filesystem encryption) and TLS for remote access.
- Provide data retention and deletion tools (wipe session, scrub derived artifacts).
- Logging avoids storing raw transcript text unless explicitly enabled.

## 12. Deployment & Operations
- **Local Development**: `docker compose up` starts FastAPI, PostgreSQL, Redis, Ollama (optional), and Vite dev server.
- **Packaging**: Provide scripts to build standalone desktop app (Electron shell pointing to bundled FastAPI) and CLI utilities for headless batch processing.
- **Monitoring**: Lightweight metrics endpoint (`/metrics`) for CPU usage, job durations; optional integration with Grafana.
- **Backups**: Document file system backup procedure for session data and exports.

## 13. Future Enhancements (EEG & Beyond)
- Expand channel parser to recognize EEG file formats (e.g., EDF, BDF). Provide conversion tooling.
- Add preprocessing presets: band-pass filters per EEG band, artifact rejection (ICA), feature extraction (alpha/beta power).
- Visualize EEG as stacked band-power plots or scalp heatmaps synchronized with events.
- Introduce multi-modal event correlation (e.g., co-occurring GSR and EEG changes) and cluster events by physiological signature.
- Explore diarization (Pyannote) for multi-speaker transcripts and speaker-specific summaries.

## 14. Documentation & Community
- Maintain `/docs` site (Docusaurus or VitePress) with tutorials: data preparation, rule tuning, model setup.
- Provide sample datasets and synthetic generators for testing.
- Encourage contributions via CODE_OF_CONDUCT.md, CONTRIBUTING.md, and issue templates.
- Showcase research references and validation benchmarks to build credibility.

---
This plan reflects a true web application tailored to GSR/EEG + speech analysis, emphasizing local deployment, configurable signal intelligence, and explainable summaries for emotionally salient events.
