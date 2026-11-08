"""Tests for the evaluation harness (eval/). No Ollama: the LLM path uses the fake client.

Expected values are computed by hand in the comments, not taken from a harness run.
"""

from __future__ import annotations

import copy
import csv
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import ac, make_pipeline, tc
from generator import generate_baseline_test_suite
from schemas import Requirement

from eval import run_eval
from eval.metrics import (
    RequirementScore,
    aggregate,
    ambiguity_outcome,
    ambiguity_summary,
    baseline_rule_coverage,
    check_traceability,
    explain,
    limit_values,
    llm_boundary_coverage,
    llm_rule_coverage,
    pct,
    precision_recall_f1,
    requirement_echoes,
    score_baseline,
    score_checklist,
    strip_echoes,
    text_boundary_coverage,
    worst_requirements,
)
from llm_pipeline.ambiguity import parse_limits
from llm_pipeline.errors import LLMTimeoutError
from llm_pipeline.schemas import RequirementInput

ROOT = Path(__file__).parents[1]
DATASET = json.loads((ROOT / "eval" / "sample_requirements.json").read_text(encoding="utf-8"))
BY_ID = {r["id"]: r for r in DATASET}
CHECKLIST = json.loads((ROOT / "eval" / "edge_case_checklist.json").read_text(encoding="utf-8"))
REQUIRED_CATEGORIES = {"boundary_values", "time_zones_dst", "empty_null_input", "duplicate_submissions",
                       "permission_role_violations", "concurrency", "date_time_rollover", "rounding", "large_input"}


def limits_of(rid: str):
    return parse_limits(RequirementInput.model_validate(BY_ID[rid]))


def baseline_of(rid: str):
    return generate_baseline_test_suite(Requirement.model_validate(BY_ID[rid]))


def _t(rid, *a, **k):
    return {**tc(*a, **k), "requirement_id": rid}


def tc002_output() -> dict:
    """A good model answer for REQ-TC-002 (4 rules, limits 'over 8' and 'over 12')."""
    rid = "REQ-TC-002"
    return {
        "ambiguities": [], "assumptions": [], "not_applicable": [],
        "acceptance_criteria": [ac(f"AC-{i}", t) for i, t in enumerate(BY_ID[rid]["rules"], start=1)],
        "test_scenarios": [
            _t(rid, "TC-001", "AC-1", "positive", "Ten hours worked", steps=["Record a 10 hour workday"],
               expected="2 hours are classified as overtime"),
            _t(rid, "TC-002", "AC-1", "negative", "Seven hours worked", steps=["Record a 7 hour workday"],
               expected="No hours are classified as overtime"),
            _t(rid, "TC-003", "AC-2", "positive", "Thirteen hours", steps=["Record a 13 hour workday"],
               expected="1 hour is classified as double time"),
            _t(rid, "TC-004", "AC-2", "negative", "Eleven hours", steps=["Record an 11 hour workday"],
               expected="No hours are classified as double time"),
            _t(rid, "TC-005", "AC-3", "positive", "Unpaid break excluded", steps=["Record 9 hours with a 1 hour unpaid break"],
               expected="8 worked hours are counted"),
            _t(rid, "TC-006", "AC-3", "negative", "Paid break kept", steps=["Record 9 hours with a paid break"],
               expected="9 worked hours are counted"),
            _t(rid, "TC-007", "AC-4", "positive", "Local midnight split", steps=["Record a shift across local midnight"],
               expected="Hours are split at local midnight"),
            _t(rid, "TC-008", "AC-4", "negative", "UTC is not used", steps=["Record a shift in a UTC+5 time zone"],
               expected="Hours are not split at UTC midnight"),
        ],
    }


def amb010_output() -> dict:
    """The model writes tests for 'handled correctly'; the pipeline must still block both criteria."""
    rid = "REQ-AMB-010"
    return {
        "ambiguities": [], "assumptions": [], "not_applicable": [],
        "acceptance_criteria": [ac("AC-1", "Overtime should be handled correctly."),
                                ac("AC-2", "Employees should be treated fairly.")],
        "test_scenarios": [
            _t(rid, "TC-001", "AC-1", "positive", "Overtime paid", expected="Overtime is paid"),
            _t(rid, "TC-002", "AC-2", "positive", "Fair pay", expected="Pay is the same for everyone"),
        ],
    }


# --------------------------------------------------------------------------- #
# Ambiguity math
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label, predicted, expected", [
    (True, True, "TP"), (True, False, "FN"), (False, True, "FP"), (False, False, "TN"),
])
def test_ambiguity_outcome(label, predicted, expected):
    assert ambiguity_outcome(label, predicted) == expected


@pytest.mark.parametrize("tp, fp, fn, expected", [
    # P = 2/3, R = 2/3, F1 = 2*(2/3)*(2/3) / (4/3) = 2/3
    (2, 1, 1, {"precision": 0.667, "recall": 0.667, "f1": 0.667}),
    # P = 3/4, R = 3/3, F1 = 2*0.75*1 / 1.75 = 0.857
    (3, 1, 0, {"precision": 0.75, "recall": 1.0, "f1": 0.857}),
    # all correct on the dataset's three ambiguous requirements
    (3, 0, 0, {"precision": 1.0, "recall": 1.0, "f1": 1.0}),
    # nothing predicted: precision is undefined, not 0 or 1
    (0, 0, 3, {"precision": None, "recall": 0.0, "f1": 0.0}),
    # no positive labels (a --only run on clear requirements): recall is undefined
    (0, 2, 0, {"precision": 0.0, "recall": None, "f1": 0.0}),
    (0, 0, 0, {"precision": None, "recall": None, "f1": 0.0}),
])
def test_precision_recall_f1(tp, fp, fn, expected):
    assert precision_recall_f1(tp, fp, fn) == expected


def test_ambiguity_summary_counts_outcomes():
    # TP 2, FP 1, FN 1, TN 8 -> P 2/3, R 2/3
    outcomes = ["TP", "TP", "FP", "FN"] + ["TN"] * 8
    assert ambiguity_summary(outcomes) == {"TP": 2, "FP": 1, "FN": 1, "TN": 8,
                                           "precision": 0.667, "recall": 0.667, "f1": 0.667}


# --------------------------------------------------------------------------- #
# Rule coverage
# --------------------------------------------------------------------------- #
def test_pct():
    assert pct(1, 3) == 33.3
    assert pct(0, 0) is None


def test_baseline_rule_coverage_reuses_the_backend_summary():
    result = baseline_of("REQ-TC-002")
    assert baseline_rule_coverage(result.traceability, BY_ID["REQ-TC-002"]["rules"]) == (4, 4, [])

    result.traceability[2].covered = False  # 3 of 4 rows covered
    covered, total, uncovered = baseline_rule_coverage(result.traceability, BY_ID["REQ-TC-002"]["rules"])
    assert (covered, total) == (3, 4)
    assert uncovered == ["Unpaid break time is excluded from worked hours."]


def _rule(rule, ids):
    return SimpleNamespace(rule=rule, acceptance_criterion_ids=ids)


def _link(ac_id, covered):
    return SimpleNamespace(acceptance_criterion_id=ac_id, covered=covered)


def test_llm_rule_coverage_requires_a_scenario_for_every_clause():
    coverage = SimpleNamespace(rule_coverage=[
        _rule("r1", ["AC-1"]),            # covered
        _rule("r2", ["AC-2", "AC-3"]),    # AC-3 has no scenario -> not covered
        _rule("r3", []),                  # no criterion at all -> not covered
    ])
    links = [_link("AC-1", True), _link("AC-2", True), _link("AC-3", False)]
    assert llm_rule_coverage(coverage, links) == (1, 3, ["r2", "r3"])


# --------------------------------------------------------------------------- #
# Boundary coverage
# --------------------------------------------------------------------------- #
def test_limit_values_come_from_the_pipelines_own_parser():
    assert [limit_values(lim) for lim in limits_of("REQ-TC-002")] == [[8, 9], [12, 13]]
    assert [limit_values(lim) for lim in limits_of("REQ-PTO-005")] == [[9, 10, 11], [4, 5, 6]]


@pytest.mark.parametrize("texts, covered", [
    (["Reasons of 9, 10 and 11 characters", "4, 5 and 6 working days"], 2),
    (["Reasons of 9, 10 and 11 characters"], 1),
    (["A rejection requires at least 10 characters"], 0),  # restating the limit is not a boundary test
])
def test_text_boundary_coverage_needs_every_value(texts, covered):
    assert text_boundary_coverage(limits_of("REQ-PTO-005"), texts)[:2] == (covered, 2)


def test_text_boundary_coverage_ignores_decimals_references_and_step_numbers():
    # 'under 2 years' needs 1 and 2. None of these is the value 1.
    limit = [lim for lim in limits_of("REQ-PTO-006") if lim.phrase == "under 2 years"]
    assert text_boundary_coverage(limit, ["accrue 1.5 days", "rule #1", "1. Setup state", "2 years"])[0] == 0
    assert text_boundary_coverage(limit, ["1 year of service", "2 years of service"])[0] == 1


def test_llm_boundary_coverage_reuses_the_result():
    coverage = SimpleNamespace(boundary_coverage=[SimpleNamespace(limit="over 8", covered=True),
                                                  SimpleNamespace(limit="over 12", covered=False)])
    assert llm_boundary_coverage(coverage) == (1, 2, ["over 12"])


# --------------------------------------------------------------------------- #
# Traceability
# --------------------------------------------------------------------------- #
def test_traceability_complete():
    check = check_traceability(["AC-1", "AC-2"], {"TS-1": ["AC-1"], "TS-2": ["AC-2"]}, [True, True])
    assert check.complete and check.orphan_criteria == [] and check.orphan_scenarios == []


def test_traceability_finds_orphans_in_both_directions():
    check = check_traceability(["AC-1", "AC-2"], {"TS-1": ["AC-1"], "TS-2": ["AC-9"], "TS-3": []}, [True, False])
    assert check.orphan_criteria == ["AC-2"]
    assert check.orphan_scenarios == ["TS-2", "TS-3"]
    assert (check.rows_covered, check.rows_total) == (1, 2)
    assert not check.complete


def test_uncovered_row_alone_makes_traceability_incomplete():
    assert not check_traceability(["AC-1"], {"TS-1": ["AC-1"]}, [False]).complete


# --------------------------------------------------------------------------- #
# Checklist
# --------------------------------------------------------------------------- #
def test_checklist_file_has_the_required_categories_and_valid_regexes():
    assert {c["id"] for c in CHECKLIST["categories"]} == REQUIRED_CATEGORIES
    ids = [item["id"] for c in CHECKLIST["categories"] for item in c["items"]]
    assert len(ids) == len(set(ids))
    for category in CHECKLIST["categories"]:
        for item in category["items"]:
            assert item["patterns"], item["id"]
            for pattern in [*item["patterns"], *([item["applies_if"]] if item["applies_if"] else [])]:
                re.compile(pattern)


TINY_CHECKLIST = {"categories": [
    {"id": "a", "items": [
        {"id": "a1", "applies_if": None, "patterns": ["\\bempty\\b"]},
        {"id": "a2", "applies_if": "\\bpassword\\b", "patterns": ["\\bdst\\b"]},   # not applicable below
    ]},
    {"id": "b", "items": [
        {"id": "b1", "applies_if": "\\bhours\\b", "patterns": ["\\bunused\\b", "\\bmidnight\\b"]},
        {"id": "b2", "applies_if": "\\bhours\\b", "patterns": ["\\bleap year\\b"]},
    ]},
]}
TINY_REQ = {"id": "R", "title": "T", "description": "Hours are recorded.", "rules": ["Hours are empty on a holiday."]}


def test_checklist_score_counts_applicable_and_matched_items():
    # Applicable: a1, b1, b2 (a2 needs 'password'). Matched: a1, b1. The score is 2/3.
    score = score_checklist(TINY_CHECKLIST, TINY_REQ, ["An EMPTY value", "A shift across midnight"])
    assert (score["matched"], score["applicable"], score["missed"]) == (2, 3, ["b2"])
    assert score["by_category"] == {"a": {"applicable": 1, "matched": 1}, "b": {"applicable": 2, "matched": 1}}


def test_repeating_the_requirement_does_not_score():
    # 'empty' appears only inside the rule's own text.
    score = score_checklist(TINY_CHECKLIST, TINY_REQ, ["Verify: Hours are empty on a holiday."])
    assert score["matched"] == 0


def test_strip_echoes_is_case_insensitive():
    assert strip_echoes("Check HOURS ARE RECORDED. now", ["Hours are recorded."]).split() == ["Check", "now"]


def test_echoes_include_the_prefix_used_in_baseline_titles():
    raw = BY_ID["REQ-PTO-006"]
    assert raw["rules"][0][:60] in requirement_echoes(raw)


@pytest.mark.parametrize("rid", list(BY_ID))
def test_baseline_template_words_do_not_score_on_the_checklist(rid):
    """'Boundary/null test for rule' contains the words 'boundary' and 'null' but tests nothing."""
    raw = BY_ID[rid]
    score = score_baseline(raw, baseline_of(rid), 0.1, CHECKLIST, schema_valid=True)
    assert score.checklist_matched == 0
    assert score.checklist_applicable > 0


def test_checklist_recognises_real_model_output():
    """Sanity check against a recorded qwen2.5:3b answer: the patterns can match real text."""
    out = json.loads((ROOT / "tests" / "data" / "qwen_password_reset_run.json").read_text())
    pipeline, _ = make_pipeline([out], supplements=0)
    raw = {**json.loads((ROOT / "examples" / "password_reset.json").read_text()), "id": "REQ-101",
           "rules": json.loads((ROOT / "examples" / "password_reset.json").read_text())["business_rules"],
           "intentionally_ambiguous": False}
    score = run_eval.run_llm(raw, pipeline, CHECKLIST)
    assert score.error is None
    assert score.checklist_by_category["boundary_values"]["matched"] == 2
    assert 0 < score.checklist_matched < score.checklist_applicable


# --------------------------------------------------------------------------- #
# Scoring whole results
# --------------------------------------------------------------------------- #
def test_baseline_on_a_clear_requirement():
    run = run_eval.run_baseline(BY_ID["REQ-TC-002"], CHECKLIST)
    assert run.schema_valid_first_try and run.traceability_complete
    assert run.rule_coverage_pct == 100.0
    assert (run.limits_covered, run.limits_total) == (0, 2)     # 'over 8' is stated, 9 is never tested
    assert run.boundary_coverage_pct == 0.0
    assert run.scenario_types == {"untyped": 4}
    assert run.ambiguity_outcome == "TN"
    assert run.validated_rule_coverage_pct is None              # the baseline does not validate anything


def test_baseline_misses_every_ambiguous_requirement():
    run = run_eval.run_baseline(BY_ID["REQ-AMB-011"], CHECKLIST)
    assert run.ambiguity_outcome == "FN"
    assert run.boundary_coverage_pct is None                    # no limits: not applicable, not 0


def test_llm_on_a_clear_requirement():
    pipeline, _ = make_pipeline([tc002_output()], supplements=0)
    run = run_eval.run_llm(BY_ID["REQ-TC-002"], pipeline, CHECKLIST)
    assert run.error is None and run.schema_valid_first_try and run.llm_calls == 1
    assert run.rule_coverage_pct == 100.0 and run.validated_rule_coverage_pct == 100.0
    assert run.boundary_coverage_pct == 100.0                   # both limits, added by the pipeline's own BVA
    assert run.validated_criteria_coverage_pct == 100.0
    assert run.traceability_complete and run.orphan_criteria == [] and run.orphan_scenarios == []
    assert run.ambiguity_outcome == "TN"
    # 8 scenarios written by the model + 2 boundary scenarios added by code
    assert run.scenario_types == {"positive": 4, "negative": 4, "boundary": 2}
    assert run.scenarios == 10
    # 'UTC+5' and 'local midnight' match; '8 hours -> does not match' is outside the limit.
    assert "tz_different_zone" not in run.checklist_missed
    assert "roll_midnight" not in run.checklist_missed
    assert "bv_outside_limit" not in run.checklist_missed
    assert "tz_dst" in run.checklist_missed


def test_llm_on_an_ambiguous_requirement():
    pipeline, _ = make_pipeline([amb010_output()])
    run = run_eval.run_llm(BY_ID["REQ-AMB-010"], pipeline, CHECKLIST)
    assert run.ambiguity_flagged and run.ambiguity_outcome == "TP" and run.ambiguity_any_outcome == "TP"
    assert run.clarifying_questions > 0
    assert run.validated_criteria_coverage_pct == 0.0           # blocked criteria are never validated
    assert run.validated_rule_coverage_pct == 0.0
    assert run.rule_coverage_pct == 100.0                       # but both rules do have a criterion and a test


def test_a_medium_question_on_a_clear_requirement_differs_between_the_two_ambiguity_definitions():
    """A clear requirement with an open question: not flagged for clarification (TN), but a
    question was raised, which counts as a false positive under 'any question raised'."""
    out = tc002_output()
    out["ambiguities"] = [{"id": "AMB-1", "text": "double time", "issue": "The pay rate is not stated.",
                           "clarification_question": "What rate applies to double time?", "severity": "medium"}]
    pipeline, _ = make_pipeline([out], supplements=0)
    run = run_eval.run_llm(BY_ID["REQ-TC-002"], pipeline, CHECKLIST)
    assert run.ambiguity_outcome == "TN"
    assert run.ambiguity_any_outcome == "FP"
    assert run.clarifying_questions == 1


def test_schema_first_try_is_false_when_the_first_answer_is_not_json():
    pipeline, _ = make_pipeline(["this is not json", tc002_output()], supplements=0)
    run = run_eval.run_llm(BY_ID["REQ-TC-002"], pipeline, CHECKLIST)
    assert run.error is None and not run.schema_valid_first_try and run.llm_calls == 2


def test_schema_first_try_is_false_when_one_scenario_is_invalid():
    """The pipeline drops the bad scenario and carries on, but the first answer was not valid."""
    out = tc002_output()
    del out["test_scenarios"][0]["test_steps"]
    pipeline, _ = make_pipeline([out, {"test_scenarios": [], "not_applicable": []}], supplements=1)
    assert not run_eval.run_llm(BY_ID["REQ-TC-002"], pipeline, CHECKLIST).schema_valid_first_try


def test_schema_first_try_is_not_confused_by_coverage_supplements():
    """metadata.attempts also counts supplements, so attempts == 1 would be the wrong test."""
    out = tc002_output()
    out["test_scenarios"] = out["test_scenarios"][:-1]          # AC-4 now lacks its negative test
    pipeline, _ = make_pipeline([out, {"test_scenarios": [], "not_applicable": []}], supplements=1)
    run = run_eval.run_llm(BY_ID["REQ-TC-002"], pipeline, CHECKLIST)
    assert run.schema_valid_first_try and run.llm_calls == 2


@pytest.mark.parametrize("response, expected", [
    (json.dumps(tc002_output()), True),
    ("```json\n" + json.dumps(tc002_output()) + "\n```", True),   # recoverable formatting is allowed
    ('{"acceptance_criteria": []}', False),
    ("", False),
    (None, False),
])
def test_is_schema_valid(response, expected):
    assert run_eval.is_schema_valid(response) is expected


def test_a_failed_generation_scores_zero_not_missing():
    errors = [LLMTimeoutError("x"), LLMTimeoutError("x"), LLMTimeoutError("x")]
    pipeline, _ = make_pipeline(errors, max_retries=2)
    run = run_eval.run_llm(BY_ID["REQ-TC-002"], pipeline, CHECKLIST)
    assert run.error.startswith("generation_failed")
    assert (run.rules_covered, run.rules_total) == (0, 4)
    assert (run.limits_covered, run.limits_total) == (0, 2)
    assert run.checklist_matched == 0 and run.checklist_applicable > 0
    assert not run.traceability_complete and not run.schema_valid_first_try
    assert run.llm_calls == 3
    assert "generation failed" in explain(run)[0]


def test_a_failed_generation_on_an_ambiguous_requirement_is_a_false_negative():
    pipeline, _ = make_pipeline([LLMTimeoutError("x")], max_retries=0)
    assert run_eval.run_llm(BY_ID["REQ-AMB-010"], pipeline, CHECKLIST).ambiguity_outcome == "FN"


def test_run_llm_restores_the_client():
    pipeline, client = make_pipeline([tc002_output()], supplements=0)
    run_eval.run_llm(BY_ID["REQ-TC-002"], pipeline, CHECKLIST)
    assert pipeline.client is client


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _score(rid, label, flagged, any_raised, **kw) -> RequirementScore:
    return RequirementScore(pipeline="llm", requirement_id=rid, title=rid, intentionally_ambiguous=label,
                            ambiguity_flagged=flagged, ambiguity_any_raised=any_raised, **kw)


@pytest.fixture
def three_scores() -> list[RequirementScore]:
    return [
        _score("A", True, True, True, latency_ms=100.0, schema_valid_first_try=True, rules_covered=3, rules_total=4,
               limits_covered=1, limits_total=2, checklist_matched=2, checklist_applicable=4, traceability_complete=True,
               scenario_types={"positive": 2, "negative": 1}, validated_rule_coverage_pct=50.0,
               checklist_by_category={"x": {"applicable": 4, "matched": 2}}),
        _score("B", False, True, True, latency_ms=300.0, rules_covered=2, rules_total=2, checklist_matched=1,
               checklist_applicable=2, scenario_types={"positive": 1, "boundary": 1}, validated_rule_coverage_pct=100.0,
               checklist_by_category={"x": {"applicable": 2, "matched": 1}}),
        _score("C", True, False, True, latency_ms=200.0, error="boom", rules_covered=1, rules_total=4,
               limits_covered=1, limits_total=1, checklist_matched=0, checklist_applicable=4,
               checklist_by_category={"x": {"applicable": 4, "matched": 0}}),
    ]


def test_aggregate_pools_counts_by_hand(three_scores):
    agg = aggregate(three_scores)
    assert (agg["requirements"], agg["failed"]) == (3, 1)
    assert agg["schema_valid_first_try_pct"] == 33.3            # 1 of 3
    assert agg["rule_coverage_pct"] == 60.0                     # (3+2+1) / (4+2+4)
    assert agg["boundary_coverage_pct"] == 66.7                 # (1+0+1) / (2+0+1)
    assert agg["checklist_score_pct"] == 30.0                   # (2+1+0) / (4+2+4)
    assert agg["checklist_by_category"]["x"] == {"applicable": 10, "matched": 3, "score_pct": 30.0}
    assert agg["traceability_complete_pct"] == 33.3             # A only
    assert agg["validated_rule_coverage_pct"] == 75.0           # mean(50, 100); C has none
    assert agg["scenario_type_mix"] == {"positive": 3, "negative": 1, "boundary": 1, "edge_case": 0, "untyped": 0}
    assert agg["latency_ms"] == {"mean": 200.0, "median": 200.0, "max": 300.0, "total": 600.0}


def test_aggregate_ambiguity_by_hand(three_scores):
    agg = aggregate(three_scores)
    # A = TP, B = FP, C = FN -> P 1/2, R 1/2, F1 1/2
    assert agg["ambiguity_flag"] == {"TP": 1, "FP": 1, "FN": 1, "TN": 0, "precision": 0.5, "recall": 0.5, "f1": 0.5}
    # all raise something: A, C = TP, B = FP -> P 2/3, R 1, F1 = 2*(2/3)/(5/3) = 0.8
    assert agg["ambiguity_any_raised"] == {"TP": 2, "FP": 1, "FN": 0, "TN": 0, "precision": 0.667, "recall": 1.0, "f1": 0.8}


def test_aggregate_of_nothing_is_undefined_not_a_crash():
    agg = aggregate([])
    assert agg["rule_coverage_pct"] is None and agg["latency_ms"]["mean"] is None


def test_quality_score_and_worst_ranking_by_hand(three_scores):
    a, b, c = three_scores
    assert a.quality_score == 75.0    # (75 rule + 50 boundary + 50 checklist + 100 trace + 100 ambiguity) / 5
    assert b.quality_score == 37.5    # (100 + 50 + 0 + 0) / 4; no limits, so boundary is left out
    assert c.quality_score == 25.0    # (25 + 100 + 0 + 0 + 0) / 5
    worst = worst_requirements(three_scores, count=2)
    assert [w["requirement_id"] for w in worst] == ["C", "B"]
    assert any("generation failed: boom" in r for r in worst[0]["reasons"])
    assert any("clear requirement, but flagged" in r for r in worst[1]["reasons"])


def test_explain_a_clean_requirement():
    assert explain(_score("A", False, False, False, latency_ms=1.0, traceability_complete=True)) == ["no problems found"]


# --------------------------------------------------------------------------- #
# CLI and outputs
# --------------------------------------------------------------------------- #
def test_baseline_only_writes_the_three_outputs(tmp_path):
    assert run_eval.main(["--baseline-only", "--out-dir", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["REPORT.md", "per_requirement.csv", "summary.json"]

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["pipelines"] == ["baseline"]
    agg = summary["aggregate"]["baseline"]
    assert agg["requirements"] == 12 and agg["failed"] == 0
    assert agg["rules_total"] == sum(len(r["rules"]) for r in DATASET)
    assert agg["limits_total"] == 11                             # the limits listed in test_sample_dataset.py
    # the baseline never asks anything: 3 ambiguous requirements missed, 9 clear ones "correct"
    assert agg["ambiguity_flag"] == {"TP": 0, "FP": 0, "FN": 3, "TN": 9, "precision": None, "recall": 0.0, "f1": 0.0}

    with (tmp_path / "per_requirement.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["requirement_id"] for r in rows] == [r["id"] for r in DATASET]
    assert {r["pipeline"] for r in rows} == {"baseline"}

    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "| Rule coverage | 100.0% (41/41) | not run |" in report
    assert "Worst 3 requirements: Baseline" in report
    assert report.count("### REQ-") == 3


def test_both_pipelines_side_by_side(tmp_path, monkeypatch):
    pipeline, _ = make_pipeline([amb010_output()])
    monkeypatch.setattr(run_eval, "build_llm_pipeline", lambda: pipeline)
    assert run_eval.main(["--only", "REQ-AMB-010", "--out-dir", str(tmp_path)]) == 0

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["pipelines"] == ["baseline", "llm"] and summary["llm_model"] == "fake-model"
    assert summary["aggregate"]["baseline"]["ambiguity_flag"]["recall"] == 0.0
    assert summary["aggregate"]["llm"]["ambiguity_flag"]["recall"] == 1.0
    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "Worst 3 requirements: LLM" in report and "not run" not in report
    with (tmp_path / "per_requirement.csv").open(encoding="utf-8", newline="") as fh:
        assert [r["pipeline"] for r in csv.DictReader(fh)] == ["baseline", "llm"]


def _unhealthy(pipeline, **health):
    async def fake_health():
        return health
    pipeline.client.health = fake_health
    return pipeline


def test_unreachable_ollama_falls_back_to_the_baseline(tmp_path, monkeypatch, capsys):
    pipeline, _ = make_pipeline([])
    monkeypatch.setattr(run_eval, "build_llm_pipeline",
                        lambda: _unhealthy(pipeline, ollama_reachable=False, model_available=False))
    assert run_eval.main(["--only", "REQ-TC-001", "--out-dir", str(tmp_path)]) == 0
    assert "Ollama is not reachable" in capsys.readouterr().out
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["pipelines"] == ["baseline"]
    assert "not reachable" in summary["llm_skipped_reason"]
    assert "not reachable" in (tmp_path / "REPORT.md").read_text(encoding="utf-8")


def test_missing_model_names_the_pull_command(tmp_path, monkeypatch, capsys):
    pipeline, _ = make_pipeline([])
    monkeypatch.setattr(run_eval, "build_llm_pipeline",
                        lambda: _unhealthy(pipeline, ollama_reachable=True, model_available=False))
    assert run_eval.main(["--only", "REQ-TC-001", "--out-dir", str(tmp_path)]) == 0
    assert "ollama pull fake-model" in capsys.readouterr().out


def test_llm_only_with_no_ollama_stops_without_overwriting_results(tmp_path, monkeypatch):
    pipeline, _ = make_pipeline([])
    monkeypatch.setattr(run_eval, "build_llm_pipeline",
                        lambda: _unhealthy(pipeline, ollama_reachable=False, model_available=False))
    assert run_eval.main(["--llm-only", "--out-dir", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == []


def test_only_rejects_unknown_ids(tmp_path, capsys):
    assert run_eval.main(["--baseline-only", "--only", "REQ-NOPE", "--out-dir", str(tmp_path)]) == 2
    assert "REQ-NOPE" in capsys.readouterr().err


def test_baseline_only_and_llm_only_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        run_eval.parse_args(["--baseline-only", "--llm-only"])


def test_one_failed_llm_requirement_does_not_stop_the_batch(tmp_path, monkeypatch):
    script = [LLMTimeoutError("x"), copy.deepcopy(amb010_output())]
    pipeline, _ = make_pipeline(script, max_retries=0)
    monkeypatch.setattr(run_eval, "build_llm_pipeline", lambda: pipeline)
    assert run_eval.main(["--llm-only", "--only", "REQ-AMB-010,REQ-AMB-011", "--out-dir", str(tmp_path)]) == 0
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["aggregate"]["llm"]["failed"] == 1
    assert summary["aggregate"]["llm"]["requirements"] == 2
