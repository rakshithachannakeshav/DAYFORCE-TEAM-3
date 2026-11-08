# Product Requirements-to-Test Assistant

Converts a structured product requirement into acceptance criteria, test
scenarios (positive / negative / boundary / edge case), ambiguity reports,
requirement traceability, and automated-test recommendations.

## Modules
| Module | Status |
|---|---|---|
| `llm_pipeline/` – LLM & generation pipeline (Ollama) |  Implemented, 121 tests – see [docs/LLM_PIPELINE.md](docs/LLM_PIPELINE.md) |
| Backend (FastAPI) |  Mount `llm_pipeline.api.router` |
| Frontend |  Consume `POST /api/llm/generate` |

## Quick start
```bash
brew install ollama && ollama serve        # separate terminal
ollama pull qwen2.5:3b
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -v                                   # no Ollama needed
uvicorn llm_pipeline.server:app --reload --port 8001   # http://localhost:8001/docs
```
