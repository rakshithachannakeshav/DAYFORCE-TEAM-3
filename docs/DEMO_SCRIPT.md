# 5-minute demo script

The demo uses three requirements from `eval/sample_requirements.json`: one clear, one with limits and an open question, and one intentionally ambiguous.

> **Before presenting:** every value marked `[LLM-TBD]` is a placeholder. Run `python eval/run_eval.py` with Ollama running, then copy the values from `eval/results/REPORT.md`. Do not quote a placeholder or estimate one. The baseline numbers below come from a real run of `python eval/run_eval.py --baseline-only`.

## Before the demo

A local model can take minutes per requirement, so prepare ahead of time.

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
3. Run all three requirements once beforehand. This loads the model and shows how long each one takes on your machine.
4. **Have a backup.** If generation is slow, submit Requirement 1 before you start talking and use the time for the intro. If Ollama fails, restart the frontend with `$env:VITE_USE_MOCK="true"; npm run dev` to show the UI, and say clearly that it is mock data.

## Timeline

### 0:00 to 0:30: The problem

"Turning a requirement into test cases is manual, and the gaps show up late: the boundary nobody tested, the vague rule nobody questioned. This tool generates acceptance criteria, test scenarios and traceability from a requirement, and it says when a requirement is too vague to test."

### 0:30 to 1:45: Requirement 1, a clear one (REQ-TC-002)

Type this into the box. Lines starting with `- ` are sent as business rules.

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

```text
Managers approve or reject leave requests from their direct reports.
- Only the employee's direct manager can approve or reject the request.
- A rejection requires a reason of at least 10 characters.
- An approved request deducts days from the employee's balance immediately.
- A request not actioned within 5 working days is escalated to the next-level manager.
```

Point out:

- **Boundary values:** 9, 10 and 11 characters, and 4, 5 and 6 working days.
- **Ambiguities & Clarifications:** the tool asks whether exactly 5 working days is inside or outside the limit. The rule does not say, and this is a question a tester would raise.
- Open the **Traceability** page. Each criterion maps to its tests and has a status. Explain the two numbers: how many criteria have a test, and how many are validated.

### 2:45 to 3:45: Requirement 3, an ambiguous one (REQ-AMB-011)

```text
Timecard approval should be quick and easy for managers.
- Approvals should happen in a reasonable time.
- The approval screen should be user friendly.
```

Point out:

- The **clarification banner** appears on the Results page.
- **Ambiguities & Clarifications** names the vague words and asks a specific question for each: what time limit defines "quick", what value is "reasonable".
- On **Traceability**, criteria show **Needs Clarification** and validated coverage is low even though tests exist. "This is the behaviour we want. It will not report a vague requirement as fully covered just because it could write tests for it."

### 3:45 to 4:45: The numbers

Show `eval/results/REPORT.md`.

"We ran all 12 requirements through a rule-based baseline and through the LLM pipeline."

| Metric | Baseline | LLM |
|---|---|---|
| Rule coverage | 100.0% (41/41) | `[LLM-TBD]` |
| Boundary-value coverage | 0.0% (0/11) | `[LLM-TBD]` |
| Ambiguity recall, clarification flag | 0.0 (0 of 3) | `[LLM-TBD]` |
| Ambiguity precision, clarification flag | n/a (never flags) | `[LLM-TBD]` |
| Edge-case checklist | 0.0% (0/113) | `[LLM-TBD]` |
| Scenario types | 41 untyped | `[LLM-TBD]` |
| Validated rule coverage | n/a | `[LLM-TBD]` |
| Failed requirements | 0 of 12 | `[LLM-TBD]` |
| Median latency per requirement | under 1 ms | `[LLM-TBD]` |

Say this, because someone may ask:

- "The baseline's 100% rule coverage is by construction. It writes one template per rule, which is why we also measure boundaries, ambiguity and edge cases."
- "Boundary tests come partly from deterministic code, so that number reflects the system and not the model alone."
- "It is 12 requirements, so these are indications, not statistics."

Mention one item from the LLM's worst 3 list in the report, to show you know where it falls short: `[LLM-TBD]`.

### 4:45 to 5:00: Close

"It runs entirely on a local model, so requirements stay on your machine. It gives testers a traceable first draft and tells them where a requirement needs a decision. A person still reviews the output."

## If something goes wrong

| What you see | What to do |
|---|---|
| "Cannot reach the backend" | Start uvicorn on port 8000 |
| "Cannot connect to Ollama" | Run `ollama serve` |
| "Model ... is not available" | Run `ollama pull qwen2.5:3b` |
| "Could not generate valid output" | Submit again, since results vary between runs. Mention that the system reports failure instead of showing an invalid result. |
| Results differ from the rehearsal | This is expected from a model. Explain it instead of hiding it. |
