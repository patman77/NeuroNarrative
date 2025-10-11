# NeuroNarrative
From biosignal spikes to meaning: align, detect, and summarize speech around GSR/EEG events

## Overview
NeuroNarrative is an open-source playground for synchronising physiological recordings with spoken language.
The current prototype focuses on galvanic skin response (GSR) CSV exports aligned with WAV audio files.
Uploaded sessions are processed locally: the backend validates inputs, extracts basic signal metadata,
performs rule-based event detection, and prepares transcript windows for later summarisation.

> **Project status:** early prototype. Audio transcription is stubbed, and the frontend only offers a minimal
> workflow for uploading files and reviewing detected events.

## Repository layout
```
.
├── backend/               # FastAPI service for ingestion, event detection, and summaries
│   ├── app/
│   │   ├── api/           # HTTP routes and schemas
│   │   ├── core/          # Configuration helpers
│   │   └── services/      # Signal processing, storage, and summarisation helpers
│   ├── pyproject.toml     # Python project definition and dependencies
│   └── tests/             # Pytest suite
├── frontend/              # React + Vite single-page application shell
│   ├── src/               # Components, hooks, and styles
│   ├── package.json       # Node project definition
│   └── vite.config.ts     # Vite bundler configuration
└── docs/                  # Architecture and design documentation
```

## Getting started

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

The API exposes:
- `GET /api/health` – service availability check.
- `POST /api/upload` – accept a GSR CSV + aligned WAV audio and store them in a temporary directory.
- `POST /api/analyze` – orchestrate signal ingestion, event detection, and (optional) local LLM summarisation.

### Frontend
```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies API calls to `http://localhost:8000` by default.

## Local LLM integration (optional)
By default the backend expects an [Ollama](https://ollama.com/) compatible endpoint available at
`http://127.0.0.1:11434/api/generate`. Configure via environment variables:
```bash
NEURONARRATIVE_OLLAMA_URL=http://localhost:11434/api/generate
NEURONARRATIVE_OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
NEURONARRATIVE_SUMMARIZER_ENABLED=false  # disable summarisation when no local model is running
```

## Testing
Backend tests run with:
```bash
cd backend
pytest
```

Frontend tests are not yet wired; add Vitest/Playwright once the UI hardens.

## Roadmap
- Integrate Whisper or Vosk for on-device transcription and diarisation.
- Expand event rules (SCR peaks, clustering) and expose a ruleset editor in the UI.
- Add waveform + chart visualisations and export formats (CSV/JSON/SRT/PDF).
- Wire EEG ingestion pipelines alongside GSR to extend multimodal coverage.
