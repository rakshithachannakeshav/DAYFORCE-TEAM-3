# Product Requirements-to-Test Assistant

Turns a product requirement into a first draft of its test plan: acceptance criteria, test scenarios (positive, negative, boundary, edge case), clarifying questions, requirement traceability and automation recommendations. It runs on a local model through Ollama, so requirements stay on your machine.

The web UI appears under the name **TestCraft AI**. A person still reviews the output: the tool gives testers a traceable draft and shows where a requirement needs a decision.

## How it works

```text
Browser (React)  -->  Backend (FastAPI)  -->  LLM pipeline  -->  Ollama (local model)
frontend/             backend/                llm_pipeline/      qwen2.5:3b
```

The model writes the tests, and ordinary code checks them:

1. **Analyse the requirement without the model:** find vague wording, parse numeric limits, and create one acceptance criterion per business rule clause.
2. **Generate:** ask the model for tests, with its output restricted to a JSON schema.
3. **Check:** reject invalid tests, mark invented values as assumptions, and add boundary tests in code for parsed limits.
4. **Repair:** retry unusable output, then request only the tests that are still missing, up to a fixed number of calls.
5. **Report:** return validated coverage and name any remaining gaps. A criterion blocked by a vague term is never reported as validated.

A rule-based baseline is included as a comparison point, so the evaluation can show what the LLM pipeline adds.

## Results

One full run of `python eval/run_eval.py` over the 12 requirements in `eval/sample_requirements.json`, on 9 November 2026, using `qwen2.5:3b` on a laptop.

| Metric | Baseline | LLM pipeline |
|---|---|---|
| Failed requirements | 0 of 12 | 0 of 12 |
| Rule coverage | 100.0% (41/41) | 92.7% (38/41) |
| Validated rule coverage, mean | n/a | 53.2% |
| Boundary-value coverage | 0.0% (0/11) | 100.0% (11/11) |
| Ambiguous requirements flagged | 0 of 3 | 3 of 3, with no clear requirement flagged |
| Edge-case checklist | 0.0% (0/113) | 10.6% (12/113) |
| Complete traceability | 100.0% | 83.3% (10 of 12) |
| Median time per requirement | under 1 ms | 5.9 min (longest 10.6 min) |

How to read these:

- **The baseline's 100% rule coverage is by construction.** It writes one template per rule, so compare boundaries, ambiguity and the checklist instead.
- **Boundary coverage reflects the system, not the model alone,** because code adds the boundary tests.
- **Edge cases are the main weakness.** Of the 12 checklist hits, 9 are boundary values, leaving 3 of 101 across the other categories.
- **Validated coverage is lower by design on vague requirements.** The 3 ambiguous requirements score 0% until they are clarified, and the 9 clear ones average 70.9%.
- **This is one run on a small dataset.** Treat the numbers as indications, because model results vary between runs.

Definitions and known limits are in [docs/EVALUATION.md](docs/EVALUATION.md).

## Quick start (Windows PowerShell)

Requires Python 3.13, Node.js 20.19 or newer, and [Ollama](https://ollama.com/download). On older Node versions, the frontend build fails with "Cannot find native binding".

```powershell
# Model, one time. Skip `ollama serve` if the Ollama app is already running.
ollama serve                                # separate terminal
ollama pull qwen2.5:3b

# Backend, from the repository root
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000   # API docs at http://localhost:8000/docs

# Frontend, in a second terminal
cd frontend
npm ci
npm run dev                                 # http://localhost:5173
```

On macOS or Linux, activate the environment with `source .venv/bin/activate` instead.

In the UI, put each business rule on its own line starting with `- `, so coverage can be traced back to it. Generation can take several minutes per requirement on a laptop.

### Frontend settings

Set these as environment variables before `npm run dev` or `npm run build`:

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend address |
| `VITE_USE_MOCK` | off | `true` shows built-in mock data instead of calling the backend |

## API

| Method and path | Purpose |
|---|---|
| `POST /api/llm/generate` | Generate with the LLM pipeline. This is the route the UI uses. |
| `GET /api/llm/health` | Check that Ollama and the model are available |
| `POST /api/generate` | Generate with the rule-based baseline, and save the run |
| `GET /api/history`, `GET /api/history/{run_id}` | Read saved baseline runs |
| `GET /api/samples` | List the sample requirements |
| `POST /api/validate` | Validate a requirement against the baseline schema |
| `GET /api/health` | Check that the backend is running |

## Project structure

| Path | Purpose |
|---|---|
| `backend/` | FastAPI app, rule-based baseline, traceability and SQLite storage |
| `llm_pipeline/` | LLM generation pipeline, described in [docs/LLM_PIPELINE.md](docs/LLM_PIPELINE.md) |
| `frontend/` | React, TypeScript and Vite UI, described in [frontend/README.md](frontend/README.md) |
| `eval/` | Evaluation harness, sample requirements and edge-case checklist |
| `tests/`, `backend/tests/` | Python tests |
| `examples/` | Sample inputs for the pipeline's command-line tool |

## Tests

```powershell
pytest                     # 254 Python tests, no Ollama needed
cd frontend
npm test                   # 29 frontend tests
npm run lint
npm run build
```

CI runs these on every pull request to `main`.

## Evaluation

```powershell
python eval/run_eval.py --baseline-only     # no Ollama needed, takes seconds
python eval/run_eval.py                     # baseline and LLM, about 70 minutes on a laptop
```

Results are written to `eval/results/`, which is generated output and not committed.

## Docs

- [docs/LLM_PIPELINE.md](docs/LLM_PIPELINE.md): pipeline design and API contract
- [docs/EVALUATION.md](docs/EVALUATION.md): running the harness, metric definitions and known limits
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md): 5-minute demo
- [CONTRIBUTING.md](CONTRIBUTING.md): team workflow
