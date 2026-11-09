"""Evaluate the rule-based baseline and the LLM pipeline on the 12-requirement dataset.

    python eval/run_eval.py --baseline-only             # no Ollama needed
    python eval/run_eval.py                             # baseline + LLM
    python eval/run_eval.py --llm-only --only REQ-TC-002,REQ-AMB-010

Writes summary.json, per_requirement.csv and REPORT.md to --out-dir (default eval/results).
See docs/EVALUATION.md.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT), str(ROOT / "backend")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from generator import generate_baseline_test_suite
from pydantic import ValidationError
from schemas import GenerationResult as BaselineResult
from schemas import Requirement

from eval.metrics import (
    SCENARIO_TYPES,
    RequirementScore,
    aggregate,
    score_baseline,
    score_failure,
    score_llm,
    worst_requirements,
)
from llm_pipeline.errors import PipelineError
from llm_pipeline.parsing import parse_llm_json
from llm_pipeline.pipeline import GenerationPipeline
from llm_pipeline.schemas import LLMOutput, RequirementInput

DATASET_PATH = ROOT / "eval" / "sample_requirements.json"
CHECKLIST_PATH = ROOT / "eval" / "edge_case_checklist.json"
DEFAULT_OUT_DIR = ROOT / "eval" / "results"

CSV_COLUMNS = [
    "pipeline", "requirement_id", "title", "intentionally_ambiguous", "error", "schema_valid_first_try", "llm_calls",
    "rules_covered", "rules_total", "rule_coverage_pct", "validated_rule_coverage_pct",
    "validated_criteria_coverage_pct", "limits_covered", "limits_total", "boundary_coverage_pct",
    "criteria", "scenarios", "orphan_criteria", "orphan_scenarios", "traceability_rows",
    "traceability_rows_covered", "traceability_complete", "ambiguity_flagged", "ambiguity_outcome",
    "ambiguity_any_raised", "ambiguity_any_outcome", "clarifying_questions", "checklist_matched",
    "checklist_applicable", "checklist_score_pct", *(f"n_{t}" for t in SCENARIO_TYPES), "latency_ms",
    "gaps", "quality_score",
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Running the two pipelines
# --------------------------------------------------------------------------- #
def run_baseline(raw: dict[str, Any], checklist: dict[str, Any]) -> RequirementScore:
    started = time.perf_counter()
    try:
        result = generate_baseline_test_suite(Requirement.model_validate(raw))
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        BaselineResult.model_validate(result.model_dump())
    except ValidationError as exc:
        return score_failure("baseline", raw, f"ValidationError: {exc}",
                             round((time.perf_counter() - started) * 1000, 3), checklist)
    return score_baseline(raw, result, latency_ms, checklist, schema_valid=True)


class RecordingClient:
    """Wraps an LLM client and keeps every raw response. The pipeline repairs and retries
    internally and ``metadata.attempts`` also counts coverage supplements, so the first
    raw response is the only way to tell whether the model got the schema right first."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.model = inner.model
        self.responses: list[str] = []
        self.calls = 0

    async def chat(self, messages, *, json_schema=None):
        self.calls += 1
        response = await self.inner.chat(messages, json_schema=json_schema)
        self.responses.append(response.content)
        return response

    async def health(self):
        return await self.inner.health()


def is_schema_valid(raw_response: str | None) -> bool:
    """True when the response parses and every part of it satisfies the LLM output schema."""
    if raw_response is None:
        return False
    try:
        LLMOutput.model_validate(parse_llm_json(raw_response))
    except (PipelineError, ValidationError):
        return False
    return True


def run_llm(raw: dict[str, Any], pipeline: GenerationPipeline, checklist: dict[str, Any]) -> RequirementScore:
    inner = pipeline.client
    recorder = RecordingClient(inner)
    pipeline.client = recorder
    started = time.perf_counter()
    result, error = None, None
    try:
        result = asyncio.run(pipeline.generate(RequirementInput.model_validate(raw)))
    except PipelineError as exc:  # one failing requirement must not stop the batch
        error = f"{exc.code}: {exc.message}"
    except Exception as exc:  # noqa: BLE001 - e.g. an unexpected transport error
        error = f"{type(exc).__name__}: {exc}"
    finally:
        pipeline.client = inner
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    first_valid = is_schema_valid(recorder.responses[0] if recorder.responses else None)
    if result is None:
        return score_failure("llm", raw, error or "unknown error", latency_ms, checklist, first_valid, recorder.calls)
    return score_llm(raw, result, latency_ms, checklist, first_valid)


def build_llm_pipeline() -> GenerationPipeline:
    return GenerationPipeline()


def llm_unavailable_reason(pipeline: GenerationPipeline) -> str | None:
    """None when the configured model can be used, otherwise what to do about it."""
    health = asyncio.run(pipeline.client.health())
    if not health.get("ollama_reachable"):
        return f"Ollama is not reachable at {pipeline.settings.ollama_host}. Start it with: ollama serve"
    if not health.get("model_available"):
        return f"Model '{pipeline.client.model}' is not pulled. Run: ollama pull {pipeline.client.model}"
    return None


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #
def score_row(score: RequirementScore) -> dict[str, Any]:
    row = {name: getattr(score, name, None) for name in CSV_COLUMNS}
    row["orphan_criteria"] = len(score.orphan_criteria)
    row["orphan_scenarios"] = len(score.orphan_scenarios)
    row["gaps"] = len(score.gaps)
    for scenario_type in SCENARIO_TYPES:
        row[f"n_{scenario_type}"] = score.scenario_types.get(scenario_type, 0)
    return row


def build_summary(scores: dict[str, list[RequirementScore]], *, model: str | None,
                  llm_skipped_reason: str | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pipelines": list(scores),
        "llm_model": model,
        "llm_skipped_reason": llm_skipped_reason,
        "aggregate": {},
        "worst_requirements": {},
        "per_requirement": {},
    }
    for name, rows in scores.items():
        summary["aggregate"][name] = aggregate(rows)
        summary["worst_requirements"][name] = worst_requirements(rows)
        summary["per_requirement"][name] = [
            {**score_row(s), "uncovered_rules": s.uncovered_rules, "uncovered_limits": s.uncovered_limits,
             "checklist_missed": s.checklist_missed, "coverage_gaps": s.gaps}
            for s in rows
        ]
    return summary


def write_csv(path: Path, scores: dict[str, list[RequirementScore]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for rows in scores.values():
            writer.writerows(score_row(s) for s in rows)


def _fmt(value: Any, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value}{suffix}"


def _report_rows(agg: dict[str, Any]) -> list[tuple[str, str]]:
    flag, any_raised = agg["ambiguity_flag"], agg["ambiguity_any_raised"]
    mix = agg["scenario_type_mix"]
    latency = agg["latency_ms"]

    def ambiguity(a: dict[str, Any]) -> str:
        return (f"P {_fmt(a['precision'])} / R {_fmt(a['recall'])} / F1 {_fmt(a['f1'])} "
                f"(TP {a['TP']}, FP {a['FP']}, FN {a['FN']}, TN {a['TN']})")

    return [
        ("Requirements (failed)", f"{agg['requirements']} ({agg['failed']})"),
        ("Schema valid on first try", _fmt(agg["schema_valid_first_try_pct"], "%")),
        ("Rule coverage", f"{_fmt(agg['rule_coverage_pct'], '%')} ({agg['rules_covered']}/{agg['rules_total']})"),
        ("Validated rule coverage (mean)", _fmt(agg["validated_rule_coverage_pct"], "%")),
        ("Validated criteria coverage (mean)", _fmt(agg["validated_criteria_coverage_pct"], "%")),
        ("Boundary-value coverage", f"{_fmt(agg['boundary_coverage_pct'], '%')} ({agg['limits_covered']}/{agg['limits_total']})"),
        ("Traceability complete", _fmt(agg["traceability_complete_pct"], "%")),
        ("Orphan criteria / scenarios", f"{agg['orphan_criteria']} / {agg['orphan_scenarios']}"),
        ("Ambiguity, clarification flag", ambiguity(flag)),
        ("Ambiguity, any question raised", ambiguity(any_raised)),
        ("Edge-case checklist", f"{_fmt(agg['checklist_score_pct'], '%')} ({agg['checklist_matched']}/{agg['checklist_applicable']})"),
        ("Scenarios: positive / negative / boundary / edge case / untyped",
         f"{mix['positive']} / {mix['negative']} / {mix['boundary']} / {mix['edge_case']} / {mix['untyped']}"),
        ("Latency per requirement: mean / median / max (ms)",
         f"{_fmt(latency['mean'])} / {_fmt(latency['median'])} / {_fmt(latency['max'])}"),
    ]


def build_report(summary: dict[str, Any]) -> str:
    aggregates = summary["aggregate"]
    lines = ["# Evaluation report", "",
             f"Generated {summary['generated_at']}. Metric definitions are in docs/EVALUATION.md.", ""]
    if summary["llm_model"]:
        lines += [f"LLM model: `{summary['llm_model']}`", ""]
    if summary["llm_skipped_reason"]:
        lines += [f"**The LLM pipeline was not run:** {summary['llm_skipped_reason']}", ""]
    lines += [("**Reading the baseline:** it maps each rule to one templated criterion and scenario, so its schema, "
               "rule coverage and traceability numbers are high by construction. They show that the structure "
               "exists, not that the tests are useful. Compare boundary, ambiguity and checklist numbers instead."), ""]

    names = {"baseline": "Baseline", "llm": "LLM"}
    empty = dict.fromkeys(("baseline", "llm"), None)
    table = {name: dict(_report_rows(agg)) for name, agg in aggregates.items()}
    metrics = [label for label, _ in _report_rows(next(iter(aggregates.values())))] if aggregates else []
    lines += ["## Baseline vs LLM", "", "| Metric | Baseline | LLM |", "|---|---|---|"]
    for metric in metrics:
        cells = {**empty, **{name: table[name][metric] for name in table}}
        lines.append(f"| {metric} | {cells['baseline'] or 'not run'} | {cells['llm'] or 'not run'} |")

    lines += ["", "## Edge-case checklist by category", "", "| Category | Baseline | LLM |", "|---|---|---|"]
    if aggregates:
        for category in next(iter(aggregates.values()))["checklist_by_category"]:
            cells = dict(empty)
            for name, agg in aggregates.items():
                c = agg["checklist_by_category"][category]
                cells[name] = f"{_fmt(c['score_pct'], '%')} ({c['matched']}/{c['applicable']})"
            lines.append(f"| {category} | {cells['baseline'] or 'not run'} | {cells['llm'] or 'not run'} |")

    for name, worst in summary["worst_requirements"].items():
        lines += ["", f"## Worst 3 requirements: {names[name]}", ""]
        for item in worst:
            lines.append(f"### {item['requirement_id']}: {item['title']} (quality score {item['quality_score']})")
            lines += ["", *[f"- {reason}" for reason in item["reasons"]], ""]
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(out_dir: Path, scores: dict[str, list[RequirementScore]], *, model: str | None,
                  llm_skipped_reason: str | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = build_summary(scores, model=model, llm_skipped_reason=llm_skipped_reason)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_csv(out_dir / "per_requirement.csv", scores)
    (out_dir / "REPORT.md").write_text(build_report(summary), encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the baseline and the LLM pipeline on the dataset.")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--baseline-only", action="store_true", help="Run only the rule-based baseline (no Ollama needed)")
    which.add_argument("--llm-only", action="store_true", help="Run only the LLM pipeline")
    parser.add_argument("--only", help="Comma-separated requirement IDs to run")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory (default: eval/results)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dataset = load_json(DATASET_PATH)
    checklist = load_json(CHECKLIST_PATH)

    if args.only:
        wanted = [x.strip() for x in args.only.split(",") if x.strip()]
        known = {r["id"] for r in dataset}
        unknown = [x for x in wanted if x not in known]
        if unknown:
            print(f"Unknown requirement ID(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        dataset = [r for r in dataset if r["id"] in wanted]

    pipeline = None
    llm_skipped_reason = "--baseline-only was used." if args.baseline_only else None
    if not args.baseline_only:
        pipeline = build_llm_pipeline()
        llm_skipped_reason = llm_unavailable_reason(pipeline)
        if llm_skipped_reason:
            pipeline = None
            print(f"LLM pipeline skipped: {llm_skipped_reason}")
            if args.llm_only:
                print("Nothing to run with --llm-only; no results were written.", file=sys.stderr)
                return 2
            print("Continuing with the baseline only.")

    scores: dict[str, list[RequirementScore]] = {}
    if not args.llm_only:
        scores["baseline"] = [run_baseline(raw, checklist) for raw in dataset]
        print(f"Baseline: {len(dataset)} requirement(s) scored.")

    model = pipeline.client.model if pipeline else None
    if pipeline:
        scores["llm"] = []
        for i, raw in enumerate(dataset, start=1):
            print(f"LLM [{i}/{len(dataset)}] {raw['id']} ...", flush=True)
            score = run_llm(raw, pipeline, checklist)
            scores["llm"].append(score)
            print(f"  {'FAILED: ' + score.error if score.error else 'done'} in {score.latency_ms / 1000:.1f} s", flush=True)
            # A full run takes a long time, so finished requirements are saved as it goes.
            write_outputs(args.out_dir, scores, model=model, llm_skipped_reason=None)

    write_outputs(args.out_dir, scores, model=model, llm_skipped_reason=llm_skipped_reason)
    print(f"Results written to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
