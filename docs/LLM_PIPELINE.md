# LLM Generation Pipeline (Person 1 – LLM & Pipeline)

This module turns **one structured product requirement** into acceptance criteria,
positive/negative/boundary/edge-case test scenarios, ambiguity reports, a
traceability matrix, and automated-test recommendations, using a **local
open-weight LLM served by Ollama**.

It lives in [`llm_pipeline/`](../llm_pipeline) and is independent of the rest of
the backend: the backend mounts one FastAPI router or calls one async function.

---

## 1. Architecture

```
RequirementInput (JSON)
   │
   ▼
1. Requirement validation ── validation.py   reject empty/too short/garbage → HTTP 422 (no LLM call)
   │
   ▼
2. Static analysis ───────── ambiguity.py    vague terms, "etc.", TBD, and/or, missing actor/outcome,
   │                         coverage.py     numeric limits (+ unclear inclusivity), and
   │                                          business rules split into clauses → SEEDED criteria AC-1…n
   ▼
3. LLM generation ────────── prompts.py      fixed criteria + grounding rules + "do not write boundary tests"
   │                         llm_client.py   Ollama /api/chat, JSON-schema constrained output, timeout
   ▼
4. JSON parsing/recovery ─── parsing.py      fences/chatter/trailing commas, salvage of truncated output
   ▼
5. Schema validation ─────── schemas.py      Pydantic LLMOutput; a single invalid test is dropped, not everything
   ▼
6. Rule anchoring ────────── coverage.align_criteria    model criteria merged into the seeded rule criteria
   │  Grounding ──────────── coverage.ground_criteria   unstated values/concepts → assumption + ASM entry
   ▼
7. Validation + coverage ─── coverage.check_output      invalid references, duplicate IDs, mislabelled tests,
   │                                                    duplicates / mirror negatives / non-specific tests,
   │                                                    unsupported expected values, not_applicable claims,
   │                                                    deterministic boundary tests, per-criterion assessment
   │                                                    → precise TASKS ("AC-4 has no negative test …")
   ▼
8. Bounded repair
   │   unusable output → full regeneration with repair prompt   (LLM_MAX_RETRIES + 1 = 3 attempts)
   │   open tasks      → supplement requests, ≤ 4 tasks each     (LLM_MAX_SUPPLEMENT_ROUNDS = 3)
   │                     tasks the model failed are not re-asked; everything is re-validated after merging
   │   a usable draft is never discarded
   ▼
9. Final GenerationResult ── pipeline.py     traceability with per-criterion status, VALIDATED vs generated
                                              coverage, rule & boundary coverage, remaining gaps
```

### Measured on the target machine (M1 MacBook Air 8 GB, `qwen2.5:3b`, real Ollama runs)

`examples/password_reset.json` (4 business rules):

| | v1.2 | v1.3 (current) – 3 runs |
|---|---|---|
| Criteria | 7 – model fragmented one rule into test-case-shaped criteria, then a duplicate AC-7 was added | exactly the 5 rule clauses, verbatim |
| Tests TC-001…005 | identical titles and steps, only the expected result differed | removed as mirrors / re-requested |
| Boundary tests | 3 (values at/one side only); "expires 30 minutes" none | 4, below/at/above, each on the right criterion + an inclusivity ambiguity |
| Reported coverage | **100 %** (only "has ≥ 1 test") | validated **80 % / 100 % / 60 %** with the exact gaps named |
| Time / LLM calls | ~1:50 / 3 | 1:48 / 3 · 1:44 / 3 · 2:45 / 4 |

`examples/ambiguous_search.json` ("fast and user-friendly … relevant … etc."):

| | v1.2 | v1.3 (current) |
|---|---|---|
| Criterion | "returns relevant … within a reasonable time frame", marked **explicit** | same kind of wording → **needs_clarification**, blocked by AMB 'relevant' + AMB 'fast' |
| Duplicate ambiguities | 'fast' and 'user-friendly' reported twice (rule + LLM) | once each |
| Reported coverage | **100 %** | **0 %** validated (honest: nothing measurable until clarified) |
| Invented values | – | none ("2 seconds" would be reclassified as an assumption, see tests) |

The model is not deterministic: the same input can give a fully validated result on one run
and two remaining gaps on the next. The pipeline's job is to make that visible, not to hide it.

### Known limitations
* **Semantic correctness is not proven.** The checker verifies structure, grounding, and
  coverage; it cannot prove that a test's steps really exercise its criterion. Example seen:
  a "positive" expiry test whose steps are generic. Human review is still required.
* **Heuristics, not understanding.** Grounding uses numbers and word overlap; a reworded
  invented rule without numbers and with requirement vocabulary can pass as explicit.
  Conversely a legitimate criterion using new words can be flagged as an assumption.
* **Rule splitting** handles "…must X and Y" / "…and cannot Z"; complex sentences with
  "or", "unless", or nested conditions stay as one clause.
* **Limit parsing** covers between / at least / at most / more / less than / expires / within;
  other phrasings ("no later than 5 pm", "twice a day") become LLM boundary tasks or are missed.
* **Remaining gaps are possible** with a 3B model within the call budget (≤ 3 + 3 calls,
  ~1–3 min). A larger model (`qwen2.5:7b`) would likely close more gaps, at ~2× the time
  and with tight memory on 8 GB – not benchmarked here.
* Requirements **without `business_rules`** have no seeded criteria, so rule coverage is `null`
  and all criteria come from the model (still grounded and checked).

| File | Responsibility |
|---|---|
| `config.py` | All settings (model, host, timeout, retries, supplement rounds) via environment variables |
| `errors.py` | Typed exceptions → mapped to HTTP status codes |
| `schemas.py` | Input contract, LLM output contract, final response contract (Pydantic v2) |
| `validation.py` | Stage 1 input validation, auto-generates a requirement ID if missing |
| `ambiguity.py` | Rule-based ambiguity detection, numeric-limit parsing, ambiguity merge/de-duplication |
| `coverage.py` | **Coverage checker**: rule anchoring, grounding, test validity, boundary-value analysis, assessment |
| `prompts.py` | System prompt, user prompt, repair prompt, task-list supplement prompt |
| `llm_client.py` | `LLMClient` protocol + `OllamaClient` (async httpx) |
| `parsing.py` | Robust JSON extraction/repair |
| `pipeline.py` | `GenerationPipeline` orchestration: calls, retries, supplements, result assembly |
| `api.py` | FastAPI `APIRouter` (`/api/llm/generate`, `/api/llm/health`) |
| `server.py` | Standalone app for local demo (`uvicorn llm_pipeline.server:app`) |
| `__main__.py` | CLI: `python -m llm_pipeline examples/password_reset.json` |

---

## 2. Ollama integration

**Model choice:** `qwen2.5:3b` (≈1.9 GB download, ≈3 GB RAM while running).
The development machine is an **M1 MacBook Air with 8 GB RAM**, so 7B+ models
would compete with the OS, browser, and IDE for memory. Qwen2.5-3B is among the
best small models at following JSON instructions. Alternatives:

| Model | Size | Notes |
|---|---|---|
| `qwen2.5:3b` (default) | ~1.9 GB | Best JSON reliability at this size |
| `llama3.2:3b` | ~2.0 GB | Good alternative |
| `qwen2.5:7b` | ~4.7 GB | Better quality, but tight on 8 GB – close other apps |

Switch models without code changes: `export OLLAMA_MODEL=llama3.2:3b`.

**How the client calls Ollama** (`llm_client.py`): `POST /api/chat` with
`stream: false`, `temperature: 0.2` (more deterministic), `num_ctx: 8192`,
`num_predict: 4096`, and `format` set to the **JSON schema of `LLMOutput`**.
Ollama (≥ 0.5) uses this schema for *constrained decoding*, so the model
physically cannot emit tokens outside valid JSON structure. `$ref`s are inlined
first for compatibility. Set `LLM_USE_JSON_SCHEMA=false` to fall back to plain
`format: "json"`.

The pipeline depends only on the `LLMClient` protocol (`chat()` + `health()`),
so tests inject a fake and another provider could be added later.

| Env var | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Model tag |
| `LLM_TIMEOUT_SECONDS` | `300` | Per-call timeout (a full 4096-token answer takes ~175 s on an M1 Air) |
| `LLM_MAX_RETRIES` | `2` | Full-generation retries after the first attempt (→ 3 attempts) |
| `LLM_MAX_SUPPLEMENT_ROUNDS` | `3` | Targeted "fill these gaps" requests after a usable draft exists |
| `LLM_TEMPERATURE` | `0.2` | Sampling temperature |
| `LLM_NUM_CTX` / `LLM_NUM_PREDICT` | `8192` / `4096` | Context / max output tokens |
| `LLM_USE_JSON_SCHEMA` | `true` | Schema-constrained output |
| `OLLAMA_KEEP_ALIVE` | `10m` | Keep model loaded between requests |

---

## 3. Prompt engineering approach

The system prompt (`prompts.py`, `PROMPT_VERSION = "1.4"`) is organised in sections:

1. **Role** – "senior QA engineer and requirements analyst".
2. **Grounding rules** – use only stated information; *every number in a criterion or
   expected result must appear in the requirement*; vague words are **not** turned into
   numbers. The prompt contains the exact counter-example:
   "The search should be fast" → ambiguity + clarification question, **not** "within 2 seconds".
   If the model still writes a criterion for a vague term it must use a placeholder
   (`[response time to be confirmed - AMB-1]`) and `source: "assumption"`.
3. **Fixed acceptance criteria** – for every business-rule clause the code passes a
   criterion with ID and exact wording; the model must keep them and only writes
   Given/When/Then and tests. It may add at most 2 criteria, only for behaviour stated in
   the description.
4. **Test validity** – positive = valid input succeeds; negative = invalid input / violated
   rule / failure condition. *A negative test must use different input or conditions than
   the positive test – never a copy with the expected result reversed.* If no meaningful
   negative case exists, the model writes a `not_applicable` entry with a reason instead.
5. **Division of labour** – the user prompt lists the limits whose boundary tests the code
   generates ("do NOT write boundary tests for them"), saving output tokens. Limits without
   a clear direction ("after 5 attempts") are given to the model as explicit boundary tasks.
6. **Output budget** – ≤ 5 ambiguities/assumptions, criteria = seeds + 2, ≤ 16 tests,
   strings under 25 words; also enforced as `maxItems` in the decoding schema.
7. **Labelling example** – a two-line example from another domain (coupon codes)
   showing a valid negative test (different condition, not a reversed result).

The **supplement prompt** is a numbered task list for at most 4 tasks, each naming
the criterion, what is missing, and constraints, e.g.

```
1. AC-4 ('A user can request at most 3 reset emails per hour.') has no negative test: write ONE
   negative test that uses invalid input or a failure condition that violates it. Its steps or
   test_data must differ from TC-007. If no meaningful negative test can exist, add a
   not_applicable entry for AC-4 with the reason instead.
```

The **repair prompt** (only for unusable output) re-sends the bad output as an
`assistant` message plus the exact validation errors.

Preview the exact prompt without calling the model:
`python -m llm_pipeline examples/password_reset.json --show-prompt`

---

## 4. Validation, coverage checking and retries

### 4.1 Rule anchoring – explicit rules can't be dropped, reworded or fragmented
Each business rule is split into atomic clauses (`coverage.split_rule_clauses`):
"The new password must be between 8 and 64 characters **and** contain at least 1 digit"
→ `AC-2 …between 8 and 64 characters.` + `AC-3 …must contain at least 1 digit.`
After generation, `align_criteria` matches every model criterion to a seed (same numbers
**and** similar wording, so "at least 3 characters" never matches "at most 3 emails").
Matches – including test-case-shaped fragments such as "A valid 8-character password is
accepted" – are merged into the seed and their tests re-linked. The seed keeps the rule's
exact wording; model Given/When/Then that introduces an unstated value is replaced.
A rule the model skipped still gets its criterion. Remaining criteria are renumbered after
the seeds, and near-duplicates among them are merged.

### 4.2 Grounding – assumptions are never silently promoted
For criteria that are not rule seeds (`ground_criteria`):

| Detected | Result |
|---|---|
| a number not stated in the requirement (± 1 allowed for boundary neighbours; IDs ignored) | `source → "assumption"`, new `ASM-n` entry with the reason |
| more than half of its content words do not occur in the requirement | same (e.g. "PDF includes a company logo and watermark") |
| `source: "assumption"` without an assumption ID | an `ASM-n` entry is created and linked |
| an unresolved placeholder (`[response time to be confirmed - AMB-1]`, "within a specified response time", "the required limit", TBD) | `source → "assumption"` + `ASM-n` **and** status `needs_clarification` – never explicit |
| a vague term (fast, relevant, reasonable …) | status `needs_clarification`, `blocked_by` → the ambiguity ID |

For fixed (rule-seeded) criteria the `then` is always the rule text: the model's own outcome was
seen to add unstated behaviour ("the user is prompted to wait an hour").
`AMB-n` references written by the model are rewritten to the final ambiguity IDs after merging;
a reference to an undefined ambiguity becomes `AMB-?`, and a placeholder that references an
ambiguity about a different topic is corrected to the matching one (with a note).

A **test** whose `expected_result` asserts an unstated value (e.g. "within 5 minutes")
is kept but does not count towards validated coverage, and a warning names it.

### 4.3 Test validity (`check_output`)
| Problem | Action |
|---|---|
| Test linked to an unknown criterion | removed, listed in `coverage.invalid_references` (kept across supplement rounds) |
| Every model-written test invalid | full regeneration (repair prompt) |
| Duplicate test IDs | renumbered (not fatal) |
| "positive" test whose expected result is a rejection / error / expiry | relabelled `negative` |
| Exact duplicate | removed |
| **Mirror test**: same steps + data as another test of the same criterion, only the expected result differs | removed ("only the expected result is reversed") – the gap is re-requested |
| Same steps + data as a test for a *different* criterion | removed as not specific |
| Near-duplicate (same criterion & type, ≥ 85 % word overlap) | removed |
| `not_applicable` claim for a criterion that has numbers or constraint words (not, only, at most, expire, equal …), with no real reason, or whose reason only restates the criterion | rejected – a negative test is still required |
| **Negative test with only valid input** ("clicks the link *within* 30 minutes" → expects "no longer valid") | removed – never relabelled into coverage |
| **Positive test with valid input that expects a rejection** | removed as contradictory (previously relabelled to "negative", which created fake negative coverage) |
| Negative test that expects success, or exactly the same result as a positive test of its criterion | removed |
| **Concrete value contradicting the stated limit** ("wait 29 minutes" → "link not usable" when the limit is 30) – values from steps/test data only, comparatives like "fewer than 8" ignored | removed |
| **Tautology** – expected result restates the criterion, or repeats one of the test's own steps | removed (it observes nothing) |
| Expected result with an unstated number (`429`, "5 minutes") or a quoted message the requirement does not contain | removed (previously kept but not counted, which made traceability and coverage disagree) |
| Model-written boundary test for a limit the code already covers | removed – boundary tests for stated limits come only from code |
| Item copied from the prompt's JSON template ("exact unclear phrase", "why unclear") | removed |
| Wrong `requirement_id`, `ac2` vs `AC-2`, "Happy Path", "HIGH" | normalised |

### 4.4 Boundary-value analysis (in code)
`ambiguity.parse_limits` reads the limits stated in the requirement – nothing is invented:

| Phrase | Kind | Generated `test_data` |
|---|---|---|
| between 8 and 64 characters | range | 7 rejected · 8 accepted · 64 accepted · 65 rejected |
| at least 1 digit | min | 0 rejected · 1 accepted · 2 accepted |
| at most 3 reset emails | max | 2 accepted · 3 accepted · 4 rejected |
| more than 5 / less than 10 | exclusive | 5 / 6 and 9 / 10 (satisfies / does not satisfy) |
| expires 30 minutes after / within 2 hours | threshold | 29 before · 30 *must be clarified* · 31 after – **plus an ambiguity** asking whether exactly 30 is inside the limit |

Each limit is attached to the criterion whose text contains its numbers and best matches
the sentence it came from. Numeric phrases without a direction ("after 5 attempts") become
a boundary **task** for the model.

### 4.5 Per-criterion assessment and status
| Status | Meaning |
|---|---|
| `validated` | explicit, measurable, has a valid positive test, a valid negative test (or an accepted not-applicable reason), and boundary tests for each of its limits |
| `partial` | explicit and tested, but something above is missing (listed in `missing`) |
| `untested` | explicit with no tests |
| `needs_clarification` | blocked by an unresolved ambiguity (vague term / placeholder) – **never validated**, whatever its source |
| `assumption` | not a stated requirement and not blocked – excluded from the validated-coverage scope |

**Validated coverage** (`coverage.coverage_percent`) = validated criteria ÷ (explicit criteria +
criteria blocked by an ambiguity). Blocked criteria are in the denominator but never in the
numerator, so "1 placeholder + 1 validated" is 50 %, not 100 %. **Generated coverage**
(`generated_coverage_percent`) = criteria with at least one linked test. Counts:
`validated_acceptance_criteria`, `blocked_acceptance_criteria`, `assumption_criteria`.
For every blocked criterion, `traceability[].missing`, `blocked_by` and `coverage.gaps` name the
same ambiguity IDs ("AC-1 cannot be validated until AMB-3 (performance target) is clarified").

### 4.6 Retry and supplement loop
1. **Full generation** – retried (≤ 3 attempts) only for unusable output: invalid/empty
   JSON, schema errors, timeouts, or no valid model-written tests while some criterion is testable.
   The repair prompt lists *why* each test was removed. If the last attempt still has no valid
   tests but usable criteria, it is kept and tests are requested per criterion (no HTTP 502).
2. **Supplements** – while tasks remain (≤ 3 rounds): send ≤ 4 tasks; accept only tests
   whose type + criterion match a requested task; renumber IDs; merge; then
   **re-validate the whole draft** (a supplement test can itself be a mirror or invalid).
   Tasks the model failed are not asked again; the loop stops early when nothing new is left.
3. Ollama down / timeout during supplements → the current draft is returned.
4. Anything unresolved appears in `coverage.gaps`, per criterion in `traceability[].missing`,
   and in `metadata.warnings` as `remaining gap: …`.

If no usable draft was ever produced, `GenerationFailedError` (HTTP 502) is returned with
one reason per call.

---

## 5. Ambiguity detection

Two layers, merged and de-duplicated (`merge_ambiguities`), renumbered `AMB-1…n`:

* **Rule-based** (`source: "rule"`):
  * ~45 vague terms (fast, user-friendly, relevant, secure, instantly, many …) with a tailored question and severity
  * open-ended lists (`etc.`), placeholders (`TBD`), `and/or`, weak modals (`may/might/could`)
  * completeness: no actor, no expected outcome, performance without a number, very brief requirement
  * time limits whose inclusivity is unstated ("expires 30 minutes after …")
* **LLM-based** (`source: "llm"`) – semantic gaps rules can't see. An LLM finding about a
  vague term the rules already reported is dropped as a duplicate.
* **From criteria** – if a criterion uses a vague term no ambiguity covers, one is created and linked via `blocked_by`.

`needs_clarification` is `true` if any ambiguity is `high` severity or any criterion is `needs_clarification`.

---

## 6. Output schema

### Request – `POST /api/llm/generate`
```json
{
  "requirement_id": "REQ-101",          // optional – auto "REQ-<hash>" if omitted
  "title": "Password reset via email",   // optional
  "description": "As a registered user, I want to …",   // required
  "actor": "registered user",            // optional
  "business_rules": ["The reset link expires 30 minutes after it is sent."],
  "context": null,                       // optional
  "priority": "high"                     // optional: high | medium | low
}
```

### Response – `200 OK` (`GenerationResult`)
```jsonc
{
  "requirement_id": "REQ-101",
  "title": "Password reset via email",
  "original_requirement": "…full text…",
  "needs_clarification": false,
  "ambiguities": [{"id":"AMB-1","text":"…","issue":"…","clarification_question":"…","severity":"medium","source":"llm"}],
  "assumptions": [{"id":"ASM-1","statement":"…","reason":"…"}],
  "acceptance_criteria": [{"id":"AC-1","description":"…","given":"…","when":"…","then":"…","source":"explicit","assumption_ids":[]}],
  "test_scenarios": [{
    "test_case_id": "TC-001", "title": "…",
    "requirement_id": "REQ-101", "acceptance_criterion_id": "AC-1",
    "test_type": "positive",              // positive | negative | boundary | edge_case
    "preconditions": ["…"], "test_steps": ["…"], "test_data": ["…"],
    "expected_result": "…", "priority": "high",
    "automation": {"automatable": true, "level": "api", "suggested_tool": "pytest", "rationale": "…"}
  }],
  "edge_cases": [{"test_case_id":"TC-004","acceptance_criterion_id":"AC-2","test_type":"boundary","description":"…","expected_result":"…"}],
  "traceability": [{
    "requirement_id":"REQ-101","acceptance_criterion_id":"AC-2","acceptance_criterion":"The new password must be between 8 and 64 characters.",
    "test_case_ids":["TC-003","TC-004","TC-014"],"test_types":["boundary","negative","positive"],"covered":true,
    "business_rules":["The new password must be between 8 and 64 characters and contain at least 1 digit."],   // v1.3 ↓
    "has_positive":true,"has_negative":true,"boundary_required":true,"has_boundary":true,
    "not_applicable":[],"blocked_by":[],"status":"validated","missing":[]
  }],
  "coverage": {
    "total_acceptance_criteria":6,"covered_acceptance_criteria":6,
    "coverage_percent":80.0,                 // VALIDATED explicit criteria (changed meaning in v1.3)
    "scenarios_by_type":{"positive":5,"negative":5,"boundary":4,"edge_case":1},
    "generated_coverage_percent":100.0,      // criteria with ≥ 1 linked test (old meaning)   v1.3 ↓
    "validated_acceptance_criteria":4,"assumption_criteria":1,
    "rule_coverage_percent":75.0,
    "rule_coverage":[{"rule":"…","acceptance_criterion_ids":["AC-2","AC-3"],"status":"partial"}],
    "boundary_coverage":[{"limit":"between 8 and 64 characters","acceptance_criterion_id":"AC-2","test_case_ids":["TC-014"],"covered":true}],
    "invalid_references":[],
    "gaps":["AC-3 ('The new password must contain at least 1 digit.') has no negative test: …"]
  },
  "automation_recommendations": {"automatable_count":7,"manual_count":1,"by_level":{"api":6,"integration":1,"manual":1},"suggested_tools":["pytest"],"recommendation":"Automate 7 of 8 scenarios (…) using pytest; keep 1 as manual/exploratory checks."},
  "metadata": {"model":"qwen2.5:3b","prompt_version":"1.3","attempts":1,"duration_ms":41234,"warnings":[]}
}
```

`edge_cases`, `traceability`, `coverage`, and `automation_recommendations` are
**computed by code** from the LLM's scenarios, so they are always internally
consistent – the LLM never has to produce the same information twice.

**Contract changes in v1.3** – all additive except one:
* New optional fields on `traceability[]` and `coverage` (marked `v1.3` above); older clients can ignore them.
* `coverage.coverage_percent` now means **validated** coverage (explicit criteria that are measurable
  and have positive, negative and boundary tests). The previous meaning – "has at least one test" –
  is now `coverage.generated_coverage_percent`. This was changed on purpose: the old number showed
  100 % for outputs that skipped business rules or had no negative tests.
* `metadata.attempts` counts all LLM calls (full generations + supplements).

### Errors – `{"error": "<code>", "message": "…", "details": ["…"]}`
| HTTP | `error` | When |
|---|---|---|
| 422 | `invalid_requirement` | Input failed validation (or FastAPI body validation) |
| 502 | `generation_failed` | All attempts produced invalid output |
| 503 | `llm_unavailable` | Ollama not running / model not pulled |
| 504 | `llm_timeout` | (reserved; timeouts are normally retried, then reported as 502) |

---

## 7. Running

```bash
# one-time: install Ollama and the model
brew install ollama            # or download the app from https://ollama.com/download
ollama serve                   # leave running in its own terminal (not needed if you use the Ollama app)
ollama pull qwen2.5:3b

# one-time: Python environment
cd "/Users/shachitas/Product Requirements-to-Test Assistant"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# CLI demo
python -m llm_pipeline examples/password_reset.json -o output.json
python -m llm_pipeline examples/ambiguous_search.json

# API demo
uvicorn llm_pipeline.server:app --reload --port 8001
# open http://localhost:8001/docs
curl http://localhost:8001/api/llm/health
curl -X POST http://localhost:8001/api/llm/generate -H "Content-Type: application/json" -d @examples/password_reset.json
```

On an M1 Air `qwen2.5:3b` writes about 24 tokens/s; measured v1.3 runs on
`examples/password_reset.json` took 1:44–2:45 (3–4 LLM calls) and on
`examples/ambiguous_search.json` 30–75 s (1–2 calls). The first request after
starting Ollama is slower because the model is loaded into memory.

For higher quality at the cost of speed, try `OLLAMA_MODEL=qwen2.5:7b` (≈4.7 GB; close
other apps on an 8 GB machine, and raise `LLM_TIMEOUT_SECONDS`). Not benchmarked here.

## 8. Testing

```bash
source .venv/bin/activate
pytest -v                       # 121 tests, all with mocked LLM responses (no Ollama needed)
pytest tests/test_pipeline.py -v -k "vague or boundary or coverage"   # a focused subset for a demo
```

| Required scenario | Test(s) |
|---|---|
| 1. Explicit business rules | `test_rule_fragments_and_rewording_are_merged_into_the_seeded_criterion`, `test_rule_the_model_skipped_is_still_a_criterion_and_gets_tests`, `test_seeded_criterion_with_invented_value_in_then_is_replaced`, `test_split_rule_clauses` |
| 2. Vague terms (fast, user-friendly) | `test_vague_terms_are_not_turned_into_requirements`, `test_placeholder_criterion_is_an_assumption_with_an_assumption_entry`, `test_vague_term_ambiguities_are_deduplicated_across_rule_and_llm` |
| 3. Numeric boundaries | `test_boundary_tests_use_exact_values_for_every_stated_limit`, `test_parse_limits_and_boundary_values` (6 kinds), `test_limit_without_parsable_direction_becomes_a_precise_llm_task`, `test_no_limits_are_invented_when_requirement_has_none`, `test_threshold_limit_creates_inclusivity_ambiguity` |
| 4. Missing details | `test_brief_requirement_flags_missing_details_and_invented_criteria`, `test_unusable_requirement_is_rejected_before_the_llm` |
| 5. Positive / negative coverage | `test_missing_negative_test_is_requested_precisely_and_filled`, `test_not_applicable_negative_is_accepted_with_a_reason`, `test_not_applicable_is_rejected_when_the_criterion_has_a_constraint`, `test_positive_test_expecting_an_error_is_relabelled` |
| 6. Unsupported business-rule assumptions | `test_extra_criterion_with_unstated_value_becomes_an_assumption`, `test_test_asserting_unstated_value_does_not_count` |
| 7. Duplicate scenarios | `test_mirror_negative_with_same_steps_is_removed_and_re_requested`, `test_exact_near_and_cross_criterion_duplicates_are_removed`, `test_duplicate_test_ids_are_renumbered_not_fatal` |
| 8. Invalid traceability references | `test_test_linked_to_unknown_criterion_is_removed_and_reported`, `test_all_tests_invalid_triggers_full_regeneration`, `test_loose_id_formats_are_normalised` |
| 9. Retry and supplement | `test_supplements_are_batched_and_failed_tasks_are_not_re_asked`, `test_supplement_output_is_filtered_and_previous_output_preserved`, `test_supplement_results_are_revalidated_like_everything_else`, `test_draft_is_kept_when_supplements_time_out_or_ollama_goes_down`, `test_supplement_rounds_are_bounded` |
| 10. Coverage calculation | `test_coverage_distinguishes_generated_from_validated`, `test_coverage_is_never_100_when_criteria_are_untested`, `test_good_answer_is_fully_validated_in_one_call` |
| Robustness | invalid / fenced / empty / truncated JSON, schema errors, missing ACs, retry exhaustion, timeouts, Ollama down, enum normalisation (`tests/test_pipeline.py`, bottom) |
| Components | JSON parsing, Ollama client over mocked HTTP, FastAPI routes (`tests/test_components.py`) |
| Regressions from real `qwen2.5:3b` runs | `tests/test_regressions.py` – incl. **replays** of real model answers in `tests/data/` |
| Internal consistency | every pipeline test runs `conftest.assert_consistent`: traceability ↔ tests ↔ coverage ↔ gaps ↔ warnings |

## 9. Integration with the backend

```python
# in the backend's main.py
from llm_pipeline.api import router as llm_router
app.include_router(llm_router)          # exposes /api/llm/generate and /api/llm/health
```
or from a backend service:
```python
from llm_pipeline import GenerationPipeline, RequirementInput, PipelineError
result = await GenerationPipeline().generate(RequirementInput(description="…"))
db_row = result.model_dump()            # plain JSON-serialisable dict
```
`RequirementInput` / `GenerationResult` in `schemas.py` are the proposed
contract. If the backend already has its own requirement model, map its fields
onto `RequirementInput` (only `description` is required).
