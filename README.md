# Product Requirements-to-Test Assistant

Converts a structured product requirement into acceptance criteria, test
scenarios (positive / negative / boundary / edge case), ambiguity reports,
requirement traceability, and automated-test recommendations.

## Modules

| Module | Status |
|---|---|
| `llm_pipeline/` – LLM & generation pipeline (Ollama) | Implemented – see [docs/LLM_PIPELINE.md](docs/LLM_PIPELINE.md) |
| `backend/` – FastAPI | Implemented. Serves the baseline at `POST /api/generate` and mounts the LLM pipeline at `POST /api/llm/generate` |
| `frontend/` – React + TypeScript + Vite | Implemented. Consumes `POST /api/llm/generate` |
| `eval/` – Evaluation harness | Implemented. Compares baseline and LLM – see [docs/EVALUATION.md](docs/EVALUATION.md) |

Tests: 254 Python tests (`pytest`, no Ollama needed) and 29 frontend tests (`npm test`).

## Quick start (Windows PowerShell)

Requires Python 3.13 and Node.js 20.19 or newer. On older Node versions the frontend build fails with "Cannot find native binding". Install Ollama from https://ollama.com/download.

```powershell
# Model, one time. Skip `ollama serve` if the Ollama app is already running.
ollama serve                                # separate terminal
ollama pull qwen2.5:3b

# Backend, from the repository root
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest                                      # no Ollama needed
uvicorn backend.main:app --reload --port 8000   # http://localhost:8000/docs

# Frontend, in a second terminal
cd frontend
npm ci
npm run dev                                 # http://localhost:5173
```

On macOS or Linux, activate the environment with `source .venv/bin/activate` instead.

In the UI, put each business rule on its own line starting with `- `, so coverage can be traced back to it.

### Frontend settings

Set these as environment variables before `npm run dev` or `npm run build`:

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend address |
| `VITE_USE_MOCK` | off | `true` shows built-in mock data instead of calling the backend |

## Evaluation

```powershell
python eval/run_eval.py --baseline-only     # no Ollama needed
python eval/run_eval.py                     # baseline and LLM
```

Results are written to `eval/results/`.

## Docs

- [docs/LLM_PIPELINE.md](docs/LLM_PIPELINE.md) – pipeline design and API contract
- [docs/EVALUATION.md](docs/EVALUATION.md) – running the harness, metric definitions, known limits
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) – 5-minute demo
- [CONTRIBUTING.md](CONTRIBUTING.md) – team workflow
