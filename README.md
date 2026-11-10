# Product Requirements-to-Test Assistant

Turns a product requirement into a first draft of its test plan: acceptance criteria, test scenarios (positive, negative, boundary, edge case), clarifying questions, requirement traceability and automation recommendations. It runs on a local model through Ollama, so requirements stay on your machine.

The web UI appears under the name **TestCraft AI**. A person still reviews the output: the tool gives testers a traceable draft and shows where a requirement needs a decision.

## Demo video

▶️ **[Watch the demo (8 min, Google Drive)](https://drive.google.com/file/d/1TBqckkQ6dBuDz6dUYggC3rUQQAac9eeu/view?usp=sharing)**

The demo shows the end-to-end workflow on a clear requirement, one with numeric limits and a vague one, followed by the evaluation results.

## The problem

Testers turn each requirement into test cases by hand. It is slow, and the gaps show up late: a limit nobody tested at its boundary, or a vague rule ("quick", "reasonable") that nobody questioned until a defect was found. Coverage is also hard to show, because the link between a business rule and the tests that check it usually lives in someone's head.

This tool gives the tester a first draft in minutes, links every test back to the rule it checks, and stops to ask when a requirement is too vague to test.

## User journey

1. **Enter the requirement.** A tester or product owner pastes a requirement into the input page. Each business rule goes on its own line starting with `- `, so the tool can trace tests back to it.
2. **Generate.** The tool runs the pipeline described below. This takes a few minutes on a laptop.
3. **Check for questions.** If the requirement is vague, a clarification banner appears, and **Ambiguities & Clarifications** names each vague phrase with a specific question. The affected criteria show **Needs Clarification** and do not count as validated.
4. **Review the draft.** The Results page lists the acceptance criteria, test scenarios (positive, negative, boundary, edge case) with their test values, edge cases, assumptions the model made, and how each scenario could be automated.
5. **Check coverage.** The Traceability page maps each criterion to its tests, gives it a status, and lists what is still missing.
6. **Resolve and export.** The tester answers the open questions with the product owner, edits the requirement and generates again, then exports the reviewed draft as CSV (for a spreadsheet or test management tool) or JSON (the complete result).

The tester stays responsible for the final test plan. The tool drafts tests and shows gaps, and it does not decide what is correct.

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

## Key technical decisions

| Decision | Why |
|---|---|
| **A local open-weight model through Ollama** | Requirements can be confidential. Running locally keeps them on the machine and needs no API keys or paid service. |
| **`qwen2.5:3b` as the default model** | It runs on an 8 GB laptop and follows JSON instructions well. It is slow (minutes per requirement) and weak at edge cases, as the results below show. Set `OLLAMA_MODEL` to use another model. |
| **Code handles everything that can be decided without the model** | Finding vague wording, parsing numeric limits, creating one criterion per rule, adding boundary tests and computing coverage are all deterministic. The model writes test content, and it never decides whether coverage is complete. |
| **Two layers of output validation** | Ollama restricts the output to a JSON schema (constrained decoding), and Pydantic then validates it. Tests that fail checks are removed with a reason, and values the requirement does not state are marked as assumptions. Temperature is 0.2 so output varies less between runs. |
| **No retrieval or vector store** | For this use case, the requirement and its business rules *are* the trusted source. Every test must link to a criterion created from them. Retrieving other documents would bring in values the requirement does not state, which is the kind of invented detail the pipeline is built to flag. Extra domain context can be passed in the API's optional `context` field. Retrieval over an approved glossary or specification is a possible next step. |
| **Fail clearly instead of guessing** | Each model call has a timeout, retries are capped, and gap-filling rounds are limited. If no valid output remains, the API returns an error rather than an invalid result. |
| **Vague requirements are never reported as validated** | A criterion blocked by a vague term stays at **Needs Clarification** even when tests exist, so a person has to make the decision. |
| **A plain Python pipeline, without LangChain** | The flow is a fixed sequence of steps, so an orchestration framework would add dependencies without adding value. |
| **A rule-based baseline** | Comparing against a simple template generator shows what the LLM actually adds, instead of reporting LLM numbers on their own. |

### Model licence

`qwen2.5:3b` is released under the **Qwen Research License**, which allows **non-commercial use only** (research and evaluation). That covers this prototype. A commercial deployment would need a licence from Alibaba Cloud or a different model. For example, `qwen2.5:7b` is released under Apache 2.0. To switch, set `OLLAMA_MODEL`, pull the model, and run the evaluation again, because results will change. Run `ollama show <model> --license` to read a model's licence.

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
npm test                   # 30 frontend tests
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
