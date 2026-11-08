"""Metric functions for the evaluation harness. No I/O and no LLM calls.

Both result shapes (backend ``GenerationResult`` and llm_pipeline ``GenerationResult``)
are reduced to one ``RequirementScore``. Coverage numbers the results already carry are
reused; only what they do not carry is computed here. See docs/EVALUATION.md.
"""

from __future__ import annotations

import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT), str(ROOT / "backend")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from traceability import calculate_coverage_summary

from llm_pipeline.ambiguity import Limit, parse_limits
from llm_pipeline.schemas import RequirementInput

SCENARIO_TYPES = ("positive", "negative", "boundary", "edge_case", "untyped")


def pct(part: float, whole: float) -> float | None:
    """Percentage rounded to 1 decimal, or None when there is nothing to measure."""
    return round(100.0 * part / whole, 1) if whole else None


# --------------------------------------------------------------------------- #
# Ambiguity detection
# --------------------------------------------------------------------------- #
def ambiguity_outcome(label: bool, predicted: bool) -> str:
    if label:
        return "TP" if predicted else "FN"
    return "FP" if predicted else "TN"


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    """Precision or recall is None when undefined (nothing predicted / no positive labels)."""
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    return {
        "precision": None if precision is None else round(precision, 3),
        "recall": None if recall is None else round(recall, 3),
        "f1": round(f1, 3),
    }


def ambiguity_summary(outcomes: list[str]) -> dict[str, Any]:
    counts = {k: outcomes.count(k) for k in ("TP", "FP", "FN", "TN")}
    return {**counts, **precision_recall_f1(counts["TP"], counts["FP"], counts["FN"])}


# --------------------------------------------------------------------------- #
# Rule / clause coverage
# --------------------------------------------------------------------------- #
def baseline_rule_coverage(traceability: list[Any], rules: list[str]) -> tuple[int, int, list[str]]:
    """(covered, total, uncovered rule texts), from the backend's own coverage summary."""
    summary = calculate_coverage_summary(traceability)
    uncovered = [rules[row.clause_ref] for row in traceability if not row.covered]
    return summary["covered_clauses"], summary["total_clauses"], uncovered


def llm_rule_coverage(coverage: Any, traceability: list[Any]) -> tuple[int, int, list[str]]:
    """A rule is covered when each of its clause criteria has at least one linked scenario.

    Deliberately not ``coverage.rule_coverage_percent``, which also requires the criteria to
    be validated. That number is reported separately as validated rule coverage.
    """
    with_tests = {link.acceptance_criterion_id for link in traceability if link.covered}
    uncovered = [r.rule for r in coverage.rule_coverage
                 if not r.acceptance_criterion_ids or not set(r.acceptance_criterion_ids) <= with_tests]
    total = len(coverage.rule_coverage)
    return total - len(uncovered), total, uncovered


# --------------------------------------------------------------------------- #
# Boundary-value coverage
# --------------------------------------------------------------------------- #
def limit_values(limit: Limit) -> list[int]:
    """The integers a boundary test must use, e.g. 'at least 10 characters' -> [9, 10, 11]."""
    return [int(value.split()[0]) for value in limit.test_values()]


def _mentions_number(text: str, number: int) -> bool:
    # not part of a decimal ("1.5") or a reference ("rule #1")
    return re.search(rf"(?<![\d.#]){number}(?!\d|\.\d)", text) is not None


def text_boundary_coverage(limits: list[Limit], texts: list[str]) -> tuple[int, int, list[str]]:
    """For results with no boundary data of their own: a limit is covered only when every one
    of its boundary values appears. Restating the limit itself is not a boundary test."""
    # a numbered step ("1. Setup") is not a test value
    text = "\n".join(re.sub(r"^\d+\.\s+", "", t) for t in texts)
    missed = [lim.phrase for lim in limits if not all(_mentions_number(text, v) for v in limit_values(lim))]
    return len(limits) - len(missed), len(limits), missed


def llm_boundary_coverage(coverage: Any) -> tuple[int, int, list[str]]:
    missed = [b.limit for b in coverage.boundary_coverage if not b.covered]
    total = len(coverage.boundary_coverage)
    return total - len(missed), total, missed


# --------------------------------------------------------------------------- #
# Traceability completeness
# --------------------------------------------------------------------------- #
@dataclass
class TraceabilityCheck:
    orphan_criteria: list[str]
    orphan_scenarios: list[str]
    rows_total: int
    rows_covered: int

    @property
    def complete(self) -> bool:
        return not self.orphan_criteria and not self.orphan_scenarios and self.rows_covered == self.rows_total


def check_traceability(criterion_ids: list[str], scenario_links: dict[str, list[str]],
                       row_covered: list[bool]) -> TraceabilityCheck:
    """``scenario_links`` maps a scenario ID to the criterion IDs it references."""
    known = set(criterion_ids)
    linked = {cid for cids in scenario_links.values() for cid in cids}
    return TraceabilityCheck(
        orphan_criteria=[cid for cid in criterion_ids if cid not in linked],
        orphan_scenarios=[sid for sid, cids in scenario_links.items() if not cids or not set(cids) <= known],
        rows_total=len(row_covered),
        rows_covered=sum(row_covered),
    )


# --------------------------------------------------------------------------- #
# Edge-case checklist
# --------------------------------------------------------------------------- #
def requirement_text(raw: dict[str, Any]) -> str:
    return "\n".join([raw.get("title") or "", raw["description"], *raw.get("rules", [])])


def requirement_echoes(raw: dict[str, Any]) -> list[str]:
    """Strings copied from the requirement. They are removed before matching, so repeating a
    rule never scores. The 60-character prefix is the form the baseline puts in scenario titles."""
    rules = raw.get("rules", [])
    return sorted({raw["description"], *rules, *(r[:60] for r in rules)}, key=len, reverse=True)


def strip_echoes(text: str, echoes: list[str]) -> str:
    for echo in echoes:
        text = re.sub(re.escape(echo), " ", text, flags=re.IGNORECASE)
    return text


def score_checklist(checklist: dict[str, Any], raw: dict[str, Any], generated: list[str]) -> dict[str, Any]:
    """An item applies when ``applies_if`` is null or matches the requirement text. An applicable
    item is matched when any of its ``patterns`` matches the generated text (case-insensitive)."""
    req_text = requirement_text(raw)
    text = "\n".join(strip_echoes(t, requirement_echoes(raw)) for t in generated)
    applicable, matched = 0, 0
    missed: list[str] = []
    by_category: dict[str, dict[str, int]] = {}
    for category in checklist["categories"]:
        tally = {"applicable": 0, "matched": 0}
        for item in category["items"]:
            if item.get("applies_if") and not re.search(item["applies_if"], req_text, re.IGNORECASE):
                continue
            tally["applicable"] += 1
            if any(re.search(p, text, re.IGNORECASE) for p in item["patterns"]):
                tally["matched"] += 1
            else:
                missed.append(item["id"])
        by_category[category["id"]] = tally
        applicable += tally["applicable"]
        matched += tally["matched"]
    return {"applicable": applicable, "matched": matched, "missed": missed, "by_category": by_category}


# --------------------------------------------------------------------------- #
# One requirement, one pipeline
# --------------------------------------------------------------------------- #
@dataclass
class RequirementScore:
    pipeline: str
    requirement_id: str
    title: str
    intentionally_ambiguous: bool
    latency_ms: float
    error: str | None = None
    schema_valid_first_try: bool = False
    llm_calls: int | None = None
    rules_covered: int = 0
    rules_total: int = 0
    uncovered_rules: list[str] = field(default_factory=list)
    validated_rule_coverage_pct: float | None = None
    validated_criteria_coverage_pct: float | None = None
    limits_covered: int = 0
    limits_total: int = 0
    uncovered_limits: list[str] = field(default_factory=list)
    criteria: int = 0
    scenarios: int = 0
    orphan_criteria: list[str] = field(default_factory=list)
    orphan_scenarios: list[str] = field(default_factory=list)
    traceability_rows: int = 0
    traceability_rows_covered: int = 0
    traceability_complete: bool = False
    ambiguity_flagged: bool = False
    ambiguity_any_raised: bool = False
    clarifying_questions: int = 0
    checklist_applicable: int = 0
    checklist_matched: int = 0
    checklist_missed: list[str] = field(default_factory=list)
    checklist_by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    scenario_types: dict[str, int] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)

    @property
    def rule_coverage_pct(self) -> float | None:
        return pct(self.rules_covered, self.rules_total)

    @property
    def boundary_coverage_pct(self) -> float | None:
        return pct(self.limits_covered, self.limits_total)

    @property
    def checklist_score_pct(self) -> float | None:
        return pct(self.checklist_matched, self.checklist_applicable)

    @property
    def ambiguity_outcome(self) -> str:
        return ambiguity_outcome(self.intentionally_ambiguous, self.ambiguity_flagged)

    @property
    def ambiguity_any_outcome(self) -> str:
        return ambiguity_outcome(self.intentionally_ambiguous, self.ambiguity_any_raised)

    @property
    def quality_score(self) -> float:
        """Used only to rank the worst requirements: the mean of the metrics that apply."""
        parts = [self.rule_coverage_pct, self.boundary_coverage_pct, self.checklist_score_pct,
                 100.0 if self.traceability_complete else 0.0,
                 100.0 if self.ambiguity_outcome in ("TP", "TN") else 0.0]
        known = [p for p in parts if p is not None]
        return round(sum(known) / len(known), 1)


def _identity(raw: dict[str, Any]) -> dict[str, Any]:
    return {"requirement_id": raw["id"], "title": raw.get("title") or "",
            "intentionally_ambiguous": bool(raw["intentionally_ambiguous"])}


def baseline_generated_texts(result: Any) -> list[str]:
    texts = [e.description for e in result.edge_cases]
    for s in result.scenarios:
        texts += [s.title, *s.steps, s.expected_result]
    return texts


def llm_generated_texts(result: Any) -> list[str]:
    texts = [f"{e.description} {e.expected_result}" for e in result.edge_cases]
    for s in result.test_scenarios:
        texts += [s.title, *s.test_steps, *s.test_data, s.expected_result]
    return texts


def score_baseline(raw: dict[str, Any], result: Any, latency_ms: float, checklist: dict[str, Any],
                   schema_valid: bool) -> RequirementScore:
    rules = raw.get("rules", [])
    rules_covered, rules_total, uncovered_rules = baseline_rule_coverage(result.traceability, rules)
    texts = baseline_generated_texts(result)
    limits = parse_limits(RequirementInput.model_validate(raw))
    limits_covered, limits_total, uncovered_limits = text_boundary_coverage(limits, texts)
    trace = check_traceability([c.id for c in result.criteria],
                               {s.id: list(s.criterion_ids) for s in result.scenarios},
                               [row.covered for row in result.traceability])
    cl = score_checklist(checklist, raw, texts)
    asked = bool(result.clarifying_questions)
    return RequirementScore(
        pipeline="baseline", **_identity(raw), latency_ms=latency_ms,
        schema_valid_first_try=schema_valid and result.schema_valid_on_first_try,
        rules_covered=rules_covered, rules_total=rules_total, uncovered_rules=uncovered_rules,
        limits_covered=limits_covered, limits_total=limits_total, uncovered_limits=uncovered_limits,
        criteria=len(result.criteria), scenarios=len(result.scenarios),
        orphan_criteria=trace.orphan_criteria, orphan_scenarios=trace.orphan_scenarios,
        traceability_rows=trace.rows_total, traceability_rows_covered=trace.rows_covered,
        traceability_complete=trace.complete,
        ambiguity_flagged=asked, ambiguity_any_raised=asked,
        clarifying_questions=len(result.clarifying_questions),
        checklist_applicable=cl["applicable"], checklist_matched=cl["matched"], checklist_missed=cl["missed"],
        checklist_by_category=cl["by_category"],
        # the backend contract has no scenario type
        scenario_types={"untyped": len(result.scenarios)},
    )


def score_llm(raw: dict[str, Any], result: Any, latency_ms: float, checklist: dict[str, Any],
              schema_valid_first_try: bool) -> RequirementScore:
    c = result.coverage
    rules_covered, rules_total, uncovered_rules = llm_rule_coverage(c, result.traceability)
    limits_covered, limits_total, uncovered_limits = llm_boundary_coverage(c)
    trace = check_traceability([a.id for a in result.acceptance_criteria],
                               {s.test_case_id: [s.acceptance_criterion_id] for s in result.test_scenarios},
                               [link.covered for link in result.traceability])
    cl = score_checklist(checklist, raw, llm_generated_texts(result))
    return RequirementScore(
        pipeline="llm", **_identity(raw), latency_ms=latency_ms,
        schema_valid_first_try=schema_valid_first_try, llm_calls=result.metadata.attempts,
        rules_covered=rules_covered, rules_total=rules_total, uncovered_rules=uncovered_rules,
        validated_rule_coverage_pct=c.rule_coverage_percent, validated_criteria_coverage_pct=c.coverage_percent,
        limits_covered=limits_covered, limits_total=limits_total, uncovered_limits=uncovered_limits,
        criteria=c.total_acceptance_criteria, scenarios=len(result.test_scenarios),
        orphan_criteria=trace.orphan_criteria, orphan_scenarios=trace.orphan_scenarios,
        traceability_rows=trace.rows_total, traceability_rows_covered=trace.rows_covered,
        traceability_complete=trace.complete,
        ambiguity_flagged=result.needs_clarification,
        ambiguity_any_raised=result.needs_clarification or bool(result.ambiguities),
        clarifying_questions=len(result.ambiguities),
        checklist_applicable=cl["applicable"], checklist_matched=cl["matched"], checklist_missed=cl["missed"],
        checklist_by_category=cl["by_category"],
        scenario_types=dict(c.scenarios_by_type), gaps=list(c.gaps),
    )


def score_failure(pipeline: str, raw: dict[str, Any], error: str, latency_ms: float, checklist: dict[str, Any],
                  schema_valid_first_try: bool = False, llm_calls: int | None = None) -> RequirementScore:
    """A failed generation scores zero wherever the metric applies, so that averages
    cannot improve by a requirement failing."""
    rules = raw.get("rules", [])
    limits = parse_limits(RequirementInput.model_validate(raw))
    cl = score_checklist(checklist, raw, [])
    return RequirementScore(
        pipeline=pipeline, **_identity(raw), latency_ms=latency_ms, error=error,
        schema_valid_first_try=schema_valid_first_try, llm_calls=llm_calls,
        rules_total=len(rules), uncovered_rules=list(rules),
        validated_rule_coverage_pct=0.0 if rules else None, validated_criteria_coverage_pct=0.0,
        limits_total=len(limits), uncovered_limits=[lim.phrase for lim in limits],
        checklist_applicable=cl["applicable"], checklist_missed=cl["missed"], checklist_by_category=cl["by_category"],
    )


# --------------------------------------------------------------------------- #
# Aggregates and the worst requirements
# --------------------------------------------------------------------------- #
def _mean(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return round(sum(known) / len(known), 1) if known else None


def aggregate(scores: list[RequirementScore]) -> dict[str, Any]:
    """Coverage metrics are pooled over all rules / limits / items rather than averaged per
    requirement, so a requirement with one rule does not weigh as much as one with five."""
    categories: dict[str, dict[str, int]] = {}
    for s in scores:
        for cat, tally in s.checklist_by_category.items():
            total = categories.setdefault(cat, {"applicable": 0, "matched": 0})
            total["applicable"] += tally["applicable"]
            total["matched"] += tally["matched"]
    mix = {t: sum(s.scenario_types.get(t, 0) for s in scores) for t in SCENARIO_TYPES}
    latencies = [s.latency_ms for s in scores]
    return {
        "requirements": len(scores),
        "failed": sum(s.error is not None for s in scores),
        "schema_valid_first_try_pct": pct(sum(s.schema_valid_first_try for s in scores), len(scores)),
        "rules_covered": sum(s.rules_covered for s in scores),
        "rules_total": sum(s.rules_total for s in scores),
        "rule_coverage_pct": pct(sum(s.rules_covered for s in scores), sum(s.rules_total for s in scores)),
        "validated_rule_coverage_pct": _mean([s.validated_rule_coverage_pct for s in scores]),
        "validated_criteria_coverage_pct": _mean([s.validated_criteria_coverage_pct for s in scores]),
        "limits_covered": sum(s.limits_covered for s in scores),
        "limits_total": sum(s.limits_total for s in scores),
        "boundary_coverage_pct": pct(sum(s.limits_covered for s in scores), sum(s.limits_total for s in scores)),
        "traceability_complete_pct": pct(sum(s.traceability_complete for s in scores), len(scores)),
        "orphan_criteria": sum(len(s.orphan_criteria) for s in scores),
        "orphan_scenarios": sum(len(s.orphan_scenarios) for s in scores),
        "ambiguity_flag": ambiguity_summary([s.ambiguity_outcome for s in scores]),
        "ambiguity_any_raised": ambiguity_summary([s.ambiguity_any_outcome for s in scores]),
        "checklist_matched": sum(s.checklist_matched for s in scores),
        "checklist_applicable": sum(s.checklist_applicable for s in scores),
        "checklist_score_pct": pct(sum(s.checklist_matched for s in scores), sum(s.checklist_applicable for s in scores)),
        "checklist_by_category": {cat: {**t, "score_pct": pct(t["matched"], t["applicable"])}
                                  for cat, t in categories.items()},
        "scenarios": sum(mix.values()),
        "scenario_type_mix": mix,
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 3) if latencies else None,
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
            "total": round(sum(latencies), 3),
        },
    }


def explain(score: RequirementScore) -> list[str]:
    """Why a requirement scored as it did, one short reason per problem."""
    reasons: list[str] = []
    if score.error:
        reasons.append(f"generation failed: {score.error}")
    if score.uncovered_rules:
        reasons.append(f"{len(score.uncovered_rules)} of {score.rules_total} rules have no criterion with a scenario")
    if score.uncovered_limits:
        reasons.append("boundary values missing for: " + ", ".join(score.uncovered_limits))
    if score.orphan_criteria or score.orphan_scenarios:
        reasons.append(f"{len(score.orphan_criteria)} criteria without a scenario, "
                       f"{len(score.orphan_scenarios)} scenarios without a valid criterion")
    if score.ambiguity_outcome == "FN":
        reasons.append("intentionally ambiguous, but not flagged for clarification")
    if score.ambiguity_outcome == "FP":
        reasons.append("clear requirement, but flagged for clarification")
    if score.checklist_applicable and score.checklist_matched < score.checklist_applicable:
        reasons.append(f"edge-case checklist {score.checklist_matched}/{score.checklist_applicable}; "
                       f"missed: {', '.join(score.checklist_missed)}")
    if score.gaps:
        reasons.append(f"{len(score.gaps)} remaining coverage gap(s), first: {score.gaps[0]}")
    return reasons or ["no problems found"]


def worst_requirements(scores: list[RequirementScore], count: int = 3) -> list[dict[str, Any]]:
    ranked = sorted(scores, key=lambda s: (s.quality_score, s.requirement_id))[:count]
    return [{"requirement_id": s.requirement_id, "title": s.title, "quality_score": s.quality_score,
             "reasons": explain(s)} for s in ranked]
