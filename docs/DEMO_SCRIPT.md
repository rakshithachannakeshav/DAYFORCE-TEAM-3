# 5-minute demo script

The demo shows three pre-generated requirements from `eval/sample_requirements.json`: one clear, one with limits and an open question, and one intentionally ambiguous. A fourth, ambiguous requirement runs live.

> **About the numbers:** all values below come from one full run of `python eval/run_eval.py` on 9 November 2026, using `qwen2.5:3b` on a laptop. They change between runs. `eval/results/` is not in the repository, so keep your copy of `REPORT.md`. To rerun without overwriting it, pass `--out-dir`. If you present numbers from a newer run, update the table.

## Before the demo

Generating three requirements live would not fit in five minutes. In the evaluation run, the requirements used here took:

| Requirement | Time | Used for |
|---|---|---|
| REQ-TC-002 | about 4 min | Pre-generated |
| REQ-PTO-005 | about 8 min | Pre-generated |
| REQ-AMB-011 | about 2 min | Pre-generated |
| REQ-AMB-010 | about 1 min | Live |

```powershell
# Terminal 1
ollama serve

# Terminal 2, from the repository root
.venv\Scripts\Activate.ps1
uvicorn backend.main:app --port 8000

# Terminal 3
cd frontend
npm run dev
```

1. Open http://localhost:5173.
2. Check http://localhost:8000/api/llm/health shows `"model_available": true`.
3. Open one browser tab per requirement and generate Requirements 1, 2 and 3 in their own tabs, one at a time. Allow about 15 minutes.
4. Leave each tab on its **Results** page. **Do not refresh these tabs.** Results are held only in the page and a refresh loses them.
5. Generate the live requirement once in a fourth tab, to load the model and check the timing on your machine. Then go back to the input page in that tab and paste the text again, ready to submit.
6. **Have a backup.** If Ollama fails, restart the frontend with `$env:VITE_USE_MOCK="true"; npm run dev` to show the UI, and say clearly that it is mock data.

## Timeline

### 0:00 to 0:30: The problem

Submit the live requirement in the fourth tab as you start talking, then switch to the first tab. Its text is:

```text
The system should handle overtime properly for all employees.
- Overtime should be handled correctly.
- Employees should be treated fairly.
```

"Turning a requirement into test cases is manual, and the gaps show up late: the boundary nobody tested, the vague rule nobody questioned. This tool generates acceptance criteria, test scenarios and traceability from a requirement, and it says when a requirement is too vague to test. A local model takes minutes per requirement, so these results were generated beforehand. One more is running live now, and we will come back to it."

### 0:30 to 1:45: Requirement 1, a clear one (REQ-TC-002)

Pre-generated from this text. Lines starting with `- ` are sent as business rules.

```text
Hours worked beyond the daily threshold are calculated as overtime and paid at a higher rate.
- Hours over 8 in a single workday are classified as overtime.
- Hours over 12 in a single workday are classified as double time.
- Unpaid break time is excluded from worked hours.
- Overtime is calculated per workday, using the employee's local time zone.
```

Point out, on the **Results** page:

- There is no clarification banner. The requirement is concrete, so it is treated as ready.
- The **Type** column labels each scenario as positive, negative, boundary or edge case. The exact mix varies between runs.
- A **boundary** scenario lists its values under the title, for example `8 hours -> does not match 'over 8'` and `9 hours -> matches 'over 8'`. When the model has not written a test for a limit, the pipeline adds one in code from the rule.

Then click **Export CSV** and mention that it opens in a spreadsheet.

### 1:45 to 2:45: Requirement 2, limits and an open question (REQ-PTO-005)

Pre-generated from this text:

```text
Managers approve or reject leave requests from their direct reports.
- Only the employee's direct manager can approve or reject the request.
- A rejection requires a reason of at least 10 characters.
- An approved request deducts days from the employee's balance immediately.
- A request not actioned within 5 working days is escalated to the next-level manager.
```

Point out:

- **Boundary values:** 9, 10 and 11 characters, and 4, 5 and 6 working days.
- **Ambiguities & Clarifications:** the tool may ask whether exactly 5 working days is inside or outside the limit. The rule does not say, and this is a question a tester would raise. Check what your pre-generated result asks, and describe that.
- Open the **Traceability** page. Each criterion maps to its tests and has a status. Explain the two numbers: how many criteria have a test, and how many are validated.

### 2:45 to 3:45: Requirement 3, an ambiguous one (REQ-AMB-011), then the live run

Pre-generated from this text:

```text
Timecard approval should be quick and easy for managers.
- Approvals should happen in a reasonable time.
- The approval screen should be user friendly.
```

Point out:

- The **clarification banner** appears on the Results page.
- **Ambiguities & Clarifications** names the vague words and asks a specific question for each: what time limit defines "quick", what value is "reasonable".
- On **Traceability**, criteria show **Needs Clarification** and validated coverage is low even though tests exist. "This is the behaviour we want. It will not report a vague requirement as fully covered just because it could write tests for it."

Then switch to the fourth tab. In the evaluation run this requirement raised 5 clarifying questions and wrote no tests, but the result can differ. "This is the one we started at the beginning. 'Handle overtime properly' gives it nothing to test against, so it asks." If it has not finished, say so, leave it running and move on.

### 3:45 to 4:45: The numbers

Show `eval/results/REPORT.md`.

"We ran all 12 requirements through a rule-based baseline and through the LLM pipeline."

| Metric | Baseline | LLM |
|---|---|---|
| Rule coverage | 100.0% (41/41) | 92.7% (38/41) |
| Boundary-value coverage | 0.0% (0/11) | 100.0% (11/11) |
| Ambiguity recall, clarification flag | 0.0 (0 of 3) | 1.0 (3 of 3) |
| Ambiguity precision, clarification flag | n/a (never flags) | 1.0 (no clear requirement flagged) |
| Ambiguity precision, any question raised | n/a (never asks) | 0.6 (questions on 2 clear requirements) |
| Edge-case checklist | 0.0% (0/113) | 10.6% (12/113) |
| Scenario types | 41 untyped | 30 positive, 31 negative, 11 boundary, 0 edge case |
| Validated rule coverage | n/a | 53.2% (70.9% on the 9 clear requirements) |
| Traceability complete | 100.0% | 83.3% (10 of 12) |
| Failed requirements | 0 of 12 | 0 of 12 |
| Median latency per requirement | under 1 ms | 5.9 min (longest 10.6 min) |

Say this, because someone may ask:

- "The baseline's 100% rule coverage is by construction. It writes one template per rule, which is why we also measure boundaries, ambiguity and edge cases."
- "Boundary tests come partly from deterministic code, so that number reflects the system and not the model alone."
- "Edge cases are the biggest weakness. Of the 12 checklist hits, 9 are boundary values, so everything else is 3 of 101. A person still has to add most edge cases."
- "It is 12 requirements and one run, so these are indications, not statistics. Results vary: validated coverage on one requirement was 50% in an earlier partial run and 25% in this one."

Mention one item from the LLM's worst 3 list, to show you know where it falls short: "On REQ-TC-001, a clear requirement, one rule ended up with no test, and the criterion that a flagged shift is shown to the manager has no valid positive test. A reviewer has to catch that."

### 4:45 to 5:00: Close

"It runs entirely on a local model, so requirements stay on your machine. It gives testers a traceable first draft and tells them where a requirement needs a decision. A person still reviews the output."

## If something goes wrong

| What you see | What to do |
|---|---|
| "Cannot reach the backend" | Start uvicorn on port 8000 |
| "Cannot connect to Ollama" | Run `ollama serve` |
| "Model ... is not available" | Run `ollama pull qwen2.5:3b` |
| "Could not generate valid output" | Submit again, since results vary between runs. Mention that the system reports failure instead of showing an invalid result. |
| The live run is still going | Do not wait for it. Say it is still running and continue with the numbers. |
| A pre-generated tab lost its results | Continue with the other tabs. Generating it again takes too long during the demo. |
| Results differ from the rehearsal | This is expected from a model. Explain it instead of hiding it. |
