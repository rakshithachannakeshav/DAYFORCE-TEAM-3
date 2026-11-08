"""Command-line demo.

    python -m llm_pipeline examples/password_reset.json
    python -m llm_pipeline --text "Users must be able to reset their password via email."
    python -m llm_pipeline examples/password_reset.json --show-prompt

Batch mode (the file holds a JSON LIST of requirements, e.g. eval/sample_requirements.json):

    python -m llm_pipeline eval/sample_requirements.json --out-dir results
    python -m llm_pipeline eval/sample_requirements.json --only REQ-TC-002,REQ-AMB-010
    python -m llm_pipeline eval/sample_requirements.json --show-prompt --only REQ-TC-002

Each result goes to <out-dir>/<requirement id>.json, plus <out-dir>/summary.json. If the
dataset carries an "intentionally_ambiguous" label, the summary checks needs_clarification
against it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from .ambiguity import detect_ambiguities
from .coverage import Context
from .errors import PipelineError
from .pipeline import GenerationPipeline
from .prompts import prompt_debug_dump
from .schemas import GenerationResult, RequirementInput
from .validation import validate_requirement


def _summary_row(raw: dict[str, Any], result: GenerationResult | None, error: str | None, seconds: float) -> dict:
    row: dict[str, Any] = {"id": raw.get("requirement_id") or raw.get("id"), "title": raw.get("title")}
    if "intentionally_ambiguous" in raw:
        row["intentionally_ambiguous"] = raw["intentionally_ambiguous"]
    if result is None:
        return {**row, "error": error, "seconds": round(seconds)}
    c = result.coverage
    row.update({
        "needs_clarification": result.needs_clarification,
        "criteria": c.total_acceptance_criteria,
        "validated": c.validated_acceptance_criteria,
        "blocked": c.blocked_acceptance_criteria,
        "assumptions": c.assumption_criteria,
        "validated_coverage_percent": c.coverage_percent,
        "generated_coverage_percent": c.generated_coverage_percent,
        "tests": len(result.test_scenarios),
        "gaps": c.gaps,
        "llm_calls": result.metadata.attempts,
        "seconds": round(seconds),
    })
    if "intentionally_ambiguous" in raw:
        row["ambiguity_label_matches"] = result.needs_clarification == bool(raw["intentionally_ambiguous"])
    return row


def _print_table(rows: list[dict]) -> None:
    print(f"\n{'id':<13} {'label':<9} {'clarify?':<9} {'valid%':>6} {'gen%':>6} {'crit':>4} {'ok/blk/asm':>10} "
          f"{'gaps':>4} {'calls':>5} {'sec':>5}")
    for r in rows:
        label = ("ambig" if r.get("intentionally_ambiguous") else "clear") if "intentionally_ambiguous" in r else "-"
        if "error" in r:
            print(f"{r['id']:<13} {label:<9} ERROR: {r['error'][:80]}")
            continue
        mark = "" if r.get("ambiguity_label_matches", True) else " (label mismatch)"
        print(f"{r['id']:<13} {label:<9} {str(r['needs_clarification']):<9} {r['validated_coverage_percent']:>6} "
              f"{r['generated_coverage_percent']:>6} {r['criteria']:>4} "
              f"{str(r['validated']) + '/' + str(r['blocked']) + '/' + str(r['assumptions']):>10} "
              f"{len(r['gaps']):>4} {r['llm_calls']:>5} {r['seconds']:>5}{mark}")
    labelled = [r for r in rows if "ambiguity_label_matches" in r]
    if labelled:
        print(f"\nambiguity detection agrees with the dataset label: "
              f"{sum(r['ambiguity_label_matches'] for r in labelled)}/{len(labelled)}")


def _run_batch(items: list[dict], args) -> int:
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        items = [r for r in items if (r.get("requirement_id") or r.get("id")) in wanted]
        if not items:
            print(f"no requirement matches --only {args.only}", file=sys.stderr)
            return 1
    if args.show_prompt:
        for raw in items:
            v = validate_requirement(RequirementInput.model_validate(raw))
            print(prompt_debug_dump(v, detect_ambiguities(v), Context.from_requirement(v)))
        return 0

    out_dir = Path(args.out_dir or "results")
    out_dir.mkdir(parents=True, exist_ok=True)
    pipeline = GenerationPipeline()
    rows = []
    for i, raw in enumerate(items, start=1):
        rid = raw.get("requirement_id") or raw.get("id") or f"item-{i}"
        logging.info("[%d/%d] %s - %s", i, len(items), rid, raw.get("title", ""))
        started = time.perf_counter()
        result, error = None, None
        try:
            result = asyncio.run(pipeline.generate(RequirementInput.model_validate(raw)))
            (out_dir / f"{rid}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        except PipelineError as exc:  # one failing requirement must not stop the batch
            error = f"{exc.code}: {exc.message}"
        except Exception as exc:  # noqa: BLE001 - e.g. input validation of a malformed item
            error = f"{type(exc).__name__}: {exc}"
        rows.append(_summary_row(raw, result, error, time.perf_counter() - started))
        (out_dir / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")  # saved as we go
    _print_table(rows)
    print(f"\nResults saved to {out_dir}/")
    return 0 if all("error" not in r for r in rows) else 1


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m llm_pipeline", description="Generate tests from a requirement.")
    p.add_argument("file", nargs="?", help="JSON file with one requirement, or a JSON list of requirements")
    p.add_argument("--text", help="Plain requirement text instead of a file")
    p.add_argument("--show-prompt", action="store_true", help="Print the prompt instead of calling the model")
    p.add_argument("-o", "--output", help="Write result JSON to this file (single requirement)")
    p.add_argument("--out-dir", help="Batch mode: directory for per-requirement results (default: results)")
    p.add_argument("--only", help="Batch mode: comma-separated requirement IDs to run")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.text:
        data: Any = {"description": args.text}
    elif args.file:
        with open(args.file, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        p.error("provide a JSON file or --text")

    if isinstance(data, list):
        return _run_batch(data, args)

    req = RequirementInput.model_validate(data)
    try:
        if args.show_prompt:
            v = validate_requirement(req)
            print(prompt_debug_dump(v, detect_ambiguities(v), Context.from_requirement(v)))
            return 0
        result = asyncio.run(GenerationPipeline().generate(req))
    except PipelineError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message, "details": exc.details}, indent=2),
              file=sys.stderr)
        return 1

    text = result.model_dump_json(indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Saved to {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
