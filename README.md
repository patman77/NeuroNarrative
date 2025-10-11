# NeuroNarrative

From biosignal spikes to meaning: align, detect, and summarize speech around GSR/EEG events.

## Project layout

```
.
├── backend/               # FastAPI service for ingestion, detection, and summaries
│   ├── app/
│   │   ├── api/           # HTTP routes and schemas
│   │   ├── core/          # Configuration helpers
│   │   └── services/      # Signal processing, storage, and summarisation helpers
│   ├── pyproject.toml     # Python project definition and dependencies
│   └── tests/             # Pytest suite
├── frontend/              # React + Vite single-page application
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
- `POST /api/analyze` – orchestrate signal ingestion, event detection, and local LLM summarisation.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies API calls to `http://localhost:8000` by default.

## Local LLM integration

By default the backend expects an [Ollama](https://ollama.com/) compatible endpoint available at `http://127.0.0.1:11434/api/generate`. You can tweak the URL, model name, or disable summaries entirely via environment variables:

```
NEURONARRATIVE_OLLAMA_URL=http://localhost:11434/api/generate
NEURONARRATIVE_OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
NEURONARRATIVE_SUMMARIZER_ENABLED=false
```

## Testing

Backend tests run with:

```bash
cd backend
pytest
```

The frontend currently focuses on manual QA while core analytics mature; add Vitest/Playwright in subsequent iterations.

## Next steps

- Integrate Whisper or Vosk for on-device transcription and diarisation.
- Expand event rules (SCR peaks, clustering) and expose a ruleset editor in the UI.
- Add waveform + chart visualisations and export formats (CSV/JSON/SRT/PDF).
- Wire EEG ingestion pipelines alongside GSR to extend multimodal coverage.
