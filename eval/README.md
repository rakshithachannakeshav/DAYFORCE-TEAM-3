# Evaluation data and harness

## How the edge-case checklist is scored

`edge_case_checklist.json` lists categories of edge cases. Each category holds items, and each item has:

| Field | Meaning |
|---|---|
| `id`, `description` | What the item checks |
| `applies_if` | A regular expression run over the requirement's title, description and rules. `null` means the item always applies. |
| `patterns` | Regular expressions run over the generated text. Any one match satisfies the item. |

For one requirement and one pipeline:

1. Collect the generated text: edge cases and scenarios (titles, steps, test data, expected results).
2. Remove anything copied from the requirement: its description, its rules, and the 60-character rule prefix the baseline puts in scenario titles. Repeating a rule never scores.
3. An item is **applicable** if `applies_if` is null or matches the requirement.
4. An applicable item is **matched** if any pattern matches the remaining text. Matching ignores case.
5. Score = matched items / applicable items. The aggregate pools the counts across all requirements.

Scoring is deterministic: the same text always gets the same score. The score shows that a topic is mentioned, not that the test is correct. See "Known limits" in [docs/EVALUATION.md](../docs/EVALUATION.md).

To add an item, add it to the JSON with a unique `id`. `tests/test_eval_harness.py` checks that IDs are unique and every regular expression compiles.

## Files

| File | Purpose |
|---|---|
| `sample_requirements.json` | The dataset: 12 requirements, 3 labelled `intentionally_ambiguous`. This is the only copy. |
| `edge_case_checklist.json` | The checklist described above |
| `metrics.py` | Metric functions, with no I/O or LLM calls |
| `run_eval.py` | The command-line runner and the report writers |
| `results/` | Generated output, ignored by git |

Run it with `python eval/run_eval.py --baseline-only`. [docs/EVALUATION.md](../docs/EVALUATION.md) has the full guide.
