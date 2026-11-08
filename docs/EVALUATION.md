# Evaluation

The harness runs the 12 requirements in `eval/sample_requirements.json` through two pipelines and compares them:

- **Baseline**: the rule-based generator, `generate_baseline_test_suite` in `backend/generator.py`.
- **LLM**: `GenerationPipeline` from `llm_pipeline`, against local Ollama. The model comes from `llm_pipeline/config.py` (`OLLAMA_MODEL`).

## Running it

Run these from the repository root, in PowerShell or any other shell. Only the Python packages in `requirements.txt` are needed.

```powershell
python eval/run_eval.py --baseline-only                  # no Ollama needed, takes seconds
python eval/run_eval.py                                  # baseline and LLM
python eval/run_eval.py --llm-only
python eval/run_eval.py --only REQ-TC-002,REQ-AMB-010    # a subset
python eval/run_eval.py --out-dir some/other/folder
```

For the LLM path, Ollama must be running with the model pulled: `ollama serve`, then `ollama pull qwen2.5:3b`. A full run can take a long time on a laptop, so results are saved after each requirement.

| Situation | What happens |
|---|---|
| Ollama unreachable or model not pulled | Prints what to do, then continues with the baseline. `REPORT.md` says the LLM was not run. |
| The same with `--llm-only` | Prints the message, exits with code 2, and writes nothing, so existing results are kept. |
| One requirement fails on the LLM path | It is recorded and scored as a failure, and the run continues. |
| Unknown ID in `--only` | Prints the ID and exits with code 2. |

## Outputs

All three are written to `eval/results/`, which is generated output and ignored by git.

| File | Contents |
|---|---|
| `REPORT.md` | Baseline vs LLM table, checklist by category, worst 3 requirements with reasons |
| `summary.json` | The same aggregates, plus per-requirement detail such as which rules, limits and checklist items were missed |
| `per_requirement.csv` | One row per pipeline and requirement, for a spreadsheet |

## Metrics

Each metric is computed per requirement and in aggregate. Coverage metrics are pooled in the aggregate: rule coverage is all covered rules divided by all rules, not an average of per-requirement percentages.

| Metric | Baseline | LLM |
|---|---|---|
| **Schema valid on first try** | The result validates against `backend/schemas.py`, and `schema_valid_on_first_try` is true | The first raw model response parses and fully validates against `LLMOutput`. Fenced JSON and other formatting the parser recovers still counts as valid. |
| **Rule coverage** | Covered clauses from `calculate_coverage_summary` in `backend/traceability.py` | A rule is covered when each of its clause criteria has at least one scenario, read from `coverage.rule_coverage` and `traceability` |
| **Validated rule coverage** | n/a | `coverage.rule_coverage_percent` as returned, averaged. This is stricter: the criteria must be measurable, with the required positive, negative and boundary tests. |
| **Validated criteria coverage** | n/a | `coverage.coverage_percent` as returned, averaged |
| **Boundary-value coverage** | Limits come from `parse_limits`. A limit is covered only if all its boundary values appear in the generated text: "at least 10 characters" needs 9, 10 and 11. | `coverage.boundary_coverage` as returned |
| **Traceability completeness** | Complete means no criterion without a scenario, no scenario without a valid criterion, and every traceability row covered | Same |
| **Ambiguity detection** | Predicts ambiguous if it asks any clarifying question. It never does. | See below |
| **Edge-case checklist** | See [eval/README.md](../eval/README.md) | Same |
| **Scenario type mix** | The contract has no scenario type, so every scenario is `untyped` | `coverage.scenarios_by_type` |
| **Latency** | Wall-clock time per requirement | Wall-clock time per requirement, including retries and supplements |

Why the first raw response for the LLM's schema metric: `metadata.attempts` also counts coverage supplements, so `attempts == 1` would mark a perfectly valid first answer as a failure whenever a coverage gap was filled afterwards.

### Ambiguity precision, recall and F1

The labels are `intentionally_ambiguous` in the dataset. The LLM path is reported under two definitions, because they answer different questions:

| Definition | Predicted ambiguous when | Question it answers |
|---|---|---|
| **Clarification flag** (use this as the headline) | `needs_clarification` is true: a high-severity ambiguity, or a criterion blocked by one | Does the system refuse to treat this requirement as ready? |
| **Any question raised** | The flag is true, or `ambiguities` is not empty | Does the system ask anything at all? |

A good question about a clear requirement ("is exactly 16 hours inside the limit?") is useful, but counts as a false positive under the second definition. Expect lower precision there.

With TP, FP and FN counted across requirements:

- Precision = TP / (TP + FP)
- Recall = TP / (TP + FN)
- F1 = 2 x precision x recall / (precision + recall)

Precision is `n/a` when nothing was predicted ambiguous, and recall is `n/a` when the run has no ambiguous requirements. F1 is 0 in those cases. Treat `n/a` as "not measurable", not as a good score.

### Failed generations

A requirement that fails on the LLM path scores zero wherever a metric applies: no rules covered, no limits covered, no checklist items, and not flagged, which is a false negative if it was labelled ambiguous. Averages therefore cannot improve because a hard requirement failed. The failure count is shown next to the results.

## Reading REPORT.md

1. **Check the header and the `Requirements (failed)` row first.** If the LLM was not run or requirements failed, the comparison is partial.
2. **Compare the metrics that can tell the pipelines apart:** boundary coverage, ambiguity, and the checklist. The baseline scores 100% on schema, rule coverage and traceability by construction, because it emits one templated criterion and scenario per rule. Those numbers show the structure exists, not that the tests are useful.
3. **Do not read low validated coverage on `REQ-AMB-*` as a failure.** Those criteria are blocked until someone clarifies them, so 0% is the correct result.
4. **Use the worst 3 lists to find what to fix.** They rank by quality score, the mean of rule coverage, boundary coverage, checklist score, traceability (100 or 0) and ambiguity correctness (100 or 0), leaving out metrics that do not apply. The score only ranks requirements and is not a headline number.

## Known limits

- **The dataset is small.** With 12 requirements and 3 ambiguous ones, one requirement moves recall by 33 points. Treat differences as indications, not statistics.
- **LLM results vary.** Temperature is 0.2 and the pipeline retries, so numbers and latency change between runs and machines. Quote the model and date with any number.
- **Boundary coverage partly reflects code, not the model.** The pipeline adds boundary tests deterministically for limits it can parse, as long as a criterion carries the limit's numbers. High LLM boundary coverage is a result of the system, not of the model alone.
- **The limits are the parser's limits.** Boundary metrics count only limits `parse_limits` recognises. For example, "accrue 1.5 days per month" is deliberately not a limit.
- **The checklist detects topics, not correctness.** A scenario can mention "UTC" and still be a poor test. A pattern can also match by coincidence, for instance "at the same time" in a shift-overlap test. Patterns can miss valid wording as well.
- **The two boundary methods differ.** The baseline has no boundary data, so it is scored by searching its text, while the LLM's own record is reused. The search can credit a number that appears for an unrelated reason.
- **The requirement text is removed only when copied exactly.** A paraphrased rule can still match a pattern.
- **Baseline ambiguity precision is `n/a` by design,** because it never asks a question.
- **The UI sends less than the harness.** The harness sends each requirement's ID, title, actor and priority. The UI sends only the description and rules, so a demo run can differ slightly from the evaluated run.
- **Latency depends on the machine.** Compare runs from the same machine, and note that the first request is slower while the model loads.
