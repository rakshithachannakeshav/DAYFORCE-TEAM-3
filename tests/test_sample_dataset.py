"""Tests on the team's requirement dataset (examples/sample_requirements.json).

All deterministic (no LLM): input format, ambiguity detection against the dataset's own
``intentionally_ambiguous`` labels, rule clauses, and boundary values for every stated limit.
Plus pipeline/CLI runs with a fake LLM.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import ac, make_pipeline, run, tc
from llm_pipeline.ambiguity import blocking_terms, detect_ambiguities, parse_limits
from llm_pipeline.coverage import Context
from llm_pipeline.schemas import RequirementInput
from llm_pipeline.validation import validate_requirement

DATASET = json.loads((Path(__file__).parents[1] / "examples" / "sample_requirements.json").read_text())
BY_ID = {r["id"]: r for r in DATASET}


def req(rid: str) -> RequirementInput:
    return validate_requirement(RequirementInput.model_validate(BY_ID[rid]))


# --------------------------------------------------------------------------- #
# Input format
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw", DATASET, ids=lambda r: r["id"])
def test_dataset_fields_id_and_rules_are_read(raw):
    """Regression: 'id' and 'rules' used to be ignored silently (no ID, no business rules)."""
    r = RequirementInput.model_validate(raw)
    assert r.requirement_id == raw["id"]
    assert r.business_rules == raw["rules"]
    assert r.model_dump()["business_rules"] == raw["rules"]  # output keeps the contract's field names


def test_original_field_names_still_work():
    r = RequirementInput.model_validate({"requirement_id": "R-1", "description": "x", "business_rules": ["b"]})
    assert (r.requirement_id, r.business_rules) == ("R-1", ["b"])


# --------------------------------------------------------------------------- #
# Ambiguity detection vs. the dataset labels
# --------------------------------------------------------------------------- #
def _flagged(r: RequirementInput) -> bool:
    high = any(a.severity == "high" for a in detect_ambiguities(r))
    blocked = any(blocking_terms(s.text) for s in Context.from_requirement(r).seeds)
    return high or blocked


@pytest.mark.parametrize("raw", DATASET, ids=lambda r: r["id"])
def test_static_ambiguity_detection_matches_the_label(raw):
    """Clear requirements must not be flagged (passive rules like 'are classified' ARE outcomes);
    intentionally ambiguous ones must be."""
    assert _flagged(req(raw["id"])) == raw["intentionally_ambiguous"]


@pytest.mark.parametrize("rid", ["REQ-AMB-010", "REQ-AMB-011", "REQ-AMB-012"])
def test_vague_rules_block_their_seeded_criteria(rid):
    seeds = Context.from_requirement(req(rid)).seeds
    assert seeds and all(blocking_terms(s.text) for s in seeds)


def test_external_references_are_flagged():
    issues = " ".join(a.issue for a in detect_ambiguities(req("REQ-AMB-012")))
    assert "Refers to rules defined elsewhere (policy, law, standards)" in issues


def test_low_severity_word_in_a_concrete_rule_does_not_block():
    assert blocking_terms("An approved request deducts days from the employee's balance immediately.") == []


# --------------------------------------------------------------------------- #
# Limits and boundary values
# --------------------------------------------------------------------------- #
EXPECTED_LIMITS = {
    "REQ-TC-001": [("threshold", "after 16 hours", ["15 hours -> before the limit",
                    "16 hours -> exactly at the limit - expected behaviour must be clarified", "17 hours -> after the limit"])],
    "REQ-TC-002": [("xmin", "over 8", ["8 hours -> does not match 'over 8'", "9 hours -> matches 'over 8'"]),
                   ("xmin", "over 12", ["12 hours -> does not match 'over 12'", "13 hours -> matches 'over 12'"])],
    "REQ-TC-003": [("min", "38 or more", ["37 hours -> does not match '38 or more'", "38 hours -> matches '38 or more'",
                                          "39 hours -> matches '38 or more'"])],
    "REQ-PTO-004": [],
    "REQ-PTO-005": [("min", "at least 10 characters", ["9 characters -> rejected", "10 characters -> accepted",
                                                       "11 characters -> accepted"]),
                    ("threshold", "within 5 working days", ["4 working days -> before the limit",
                     "5 working days -> exactly at the limit - expected behaviour must be clarified",
                     "6 working days -> after the limit"])],
    "REQ-PTO-006": [("xmax", "under 2 years", ["1 year -> matches 'under 2 years'", "2 years -> does not match 'under 2 years'"]),
                    ("min", "2 or more years", ["1 year -> does not match '2 or more years'",
                                                "2 years -> matches '2 or more years'", "3 years -> matches '2 or more years'"]),
                    ("cap", "capped at 30 days", ["29 days -> below the cap", "30 days -> at the cap",
                                                  "31 days -> never reached - the value stays at the cap"])],
    "REQ-SW-007": [("xmin", "exceed 48 scheduled hours", ["48 scheduled hours -> does not match 'exceed 48 scheduled hours'",
                                                          "49 scheduled hours -> matches 'exceed 48 scheduled hours'"]),
                   ("xmax", "less than 11 hours rest", ["10 hours -> matches 'less than 11 hours rest'",
                                                        "11 hours -> does not match 'less than 11 hours rest'"])],
    "REQ-SW-008": [], "REQ-TC-009": [], "REQ-AMB-010": [], "REQ-AMB-011": [], "REQ-AMB-012": [],
}


@pytest.mark.parametrize("rid", list(EXPECTED_LIMITS))
def test_every_stated_limit_gets_exact_boundary_values(rid):
    got = [(lim.kind, lim.phrase, lim.test_values()) for lim in parse_limits(req(rid))]
    assert got == EXPECTED_LIMITS[rid]


def test_no_limit_is_invented_from_decimals_or_rates():
    """'accrue 1.5 days per month' used to produce a bogus '5 days' limit."""
    ctx = Context.from_requirement(req("REQ-PTO-006"))
    assert ctx.leftover_boundaries == []
    assert not any("5 days" in lim.phrase for lim in ctx.limits)


def test_negated_limits_are_marked_inverted():
    by_phrase = {lim.phrase: lim for lim in parse_limits(req("REQ-SW-007"))}
    assert by_phrase["exceed 48 scheduled hours"].inverted and by_phrase["less than 11 hours rest"].inverted
    assert not any(lim.inverted for lim in parse_limits(req("REQ-TC-002")))


# --------------------------------------------------------------------------- #
# Pipeline with a fake LLM
# --------------------------------------------------------------------------- #
def _t(rid, *a, **k):
    return {**tc(*a, **k), "requirement_id": rid}


def test_ambiguous_dataset_item_is_never_validated_even_with_tests():
    """REQ-AMB-010: the model happily writes tests for 'handled correctly' - they must not validate it."""
    rid = "REQ-AMB-010"
    out = {"ambiguities": [], "assumptions": [],
           "acceptance_criteria": [ac("AC-1", "Overtime should be handled correctly."),
                                   ac("AC-2", "Employees should be treated fairly.")],
           "test_scenarios": [_t(rid, "TC-001", "AC-1", "positive", "Overtime paid", expected="Overtime is paid"),
                              _t(rid, "TC-002", "AC-1", "negative", "No overtime", steps=["Work 7 hours"],
                                 expected="No overtime is paid"),
                              _t(rid, "TC-003", "AC-2", "positive", "Fair pay", expected="Pay is the same for everyone")],
           "not_applicable": []}
    pipeline, client = make_pipeline([out])
    r = run(pipeline.generate(RequirementInput.model_validate(BY_ID[rid])))
    assert [x.status for x in r.traceability] == ["needs_clarification", "needs_clarification"]
    assert r.coverage.coverage_percent == 0.0 and r.coverage.blocked_acceptance_criteria == 2
    assert r.needs_clarification is True
    assert len(client.calls) == 1  # nothing testable -> no supplements, no regeneration


def test_clear_dataset_item_gets_condition_boundary_tests_and_validates():
    rid = "REQ-TC-002"
    acs = [ac(f"AC-{i}", t) for i, t in enumerate(BY_ID[rid]["rules"], start=1)]
    tests = [
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
    ]
    out = {"ambiguities": [], "assumptions": [], "acceptance_criteria": acs, "test_scenarios": tests, "not_applicable": []}
    pipeline, _ = make_pipeline([out])
    r = run(pipeline.generate(RequirementInput.model_validate(BY_ID[rid])))
    bva = {t.acceptance_criterion_id: t.test_data for t in r.test_scenarios if t.test_type == "boundary"}
    assert bva == {"AC-1": ["8 hours -> does not match 'over 8'", "9 hours -> matches 'over 8'"],
                   "AC-2": ["12 hours -> does not match 'over 12'", "13 hours -> matches 'over 12'"]}
    assert r.coverage.coverage_percent == 100.0 and r.needs_clarification is False


def test_cli_batch_mode_writes_results_and_label_summary(tmp_path, monkeypatch):
    import llm_pipeline.__main__ as cli
    from llm_pipeline.errors import LLMTimeoutError

    items = [BY_ID["REQ-AMB-010"], BY_ID["REQ-TC-002"]]
    data = tmp_path / "reqs.json"
    data.write_text(json.dumps(items))
    rid = "REQ-AMB-010"
    good = {"ambiguities": [], "assumptions": [],
            "acceptance_criteria": [ac("AC-1", "Overtime should be handled correctly."),
                                    ac("AC-2", "Employees should be treated fairly.")],
            "test_scenarios": [_t(rid, "TC-001", "AC-1", "positive", "Overtime paid", expected="Overtime is paid")],
            "not_applicable": []}
    pipeline, _ = make_pipeline([good, LLMTimeoutError("x"), LLMTimeoutError("x"), LLMTimeoutError("x")])
    monkeypatch.setattr(cli, "GenerationPipeline", lambda: pipeline)
    monkeypatch.setattr(sys, "argv", ["llm_pipeline", str(data), "--out-dir", str(tmp_path / "out")])
    code = cli.main()
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert code == 1                                         # one requirement failed ...
    assert (tmp_path / "out" / "REQ-AMB-010.json").exists()   # ... but the batch continued
    assert summary[0]["ambiguity_label_matches"] is True and summary[0]["validated_coverage_percent"] == 0.0
    assert summary[1]["id"] == "REQ-TC-002" and summary[1]["error"].startswith("generation_failed")


# --------------------------------------------------------------------------- #
# Regressions from the real qwen2.5:3b batch run on this dataset
# --------------------------------------------------------------------------- #
def _tc002_with(extra_tests):
    rid = "REQ-TC-002"
    acs = [ac(f"AC-{i}", t) for i, t in enumerate(BY_ID[rid]["rules"], start=1)]
    return {"ambiguities": [], "assumptions": [], "acceptance_criteria": acs, "test_scenarios": extra_tests,
            "not_applicable": []}


def _warnings_for(test):
    valid = _t("REQ-TC-002", "TC-099", "AC-4", "positive", "Shift across local midnight",
               steps=["Record a shift across local midnight"], expected="Hours are split at local midnight")
    pipeline, _ = make_pipeline([_tc002_with([test, valid])], supplements=0)
    r = run(pipeline.generate(RequirementInput.model_validate(BY_ID["REQ-TC-002"])))
    return r, " | ".join(r.metadata.warnings)


def test_positive_test_contradicting_an_unconditional_rule_is_removed():
    """Real output: rule 'Unpaid break time is excluded', positive test expected it to be INCLUDED."""
    t = _t("REQ-TC-002", "TC-007", "AC-3", "positive", "Unpaid break",
           steps=["Process a workday with unpaid break time and expect worked hours to include the break time"],
           expected="Worked hours include the unpaid break time")
    r, w = _warnings_for(t)
    assert "TC-007 removed: contradicts its criterion - the rule says 'excluded' but it expects 'include'" in w
    assert not next(x for x in r.traceability if x.acceptance_criterion_id == "AC-3").has_positive


def test_restatement_without_concrete_input_is_removed():
    """Real output: 'Process a workday with hours over 8' -> 'Classify hours over 8 as overtime'."""
    t = _t("REQ-TC-002", "TC-001", "AC-1", "positive", "Over 8", steps=["Process a workday with hours over 8"],
           expected="Classify hours over 8 as overtime")
    _, w = _warnings_for(t)
    assert "TC-001 removed: its expected result only restates the criterion and the test uses no concrete input" in w


@pytest.mark.parametrize("steps, expected", [
    (["Record 9 hours with a 1 hour unpaid break"], "8 worked hours are counted"),          # consistent with 'excluded'
    (["Record a 10 hour workday"], "2 hours are classified as overtime"),                    # concrete + derived value
])
def test_consistent_concrete_tests_are_kept(steps, expected):
    t = _t("REQ-TC-002", "TC-001", "AC-3" if "break" in steps[0] else "AC-1", "positive", "Kept", steps=steps,
           expected=expected)
    r, _ = _warnings_for(t)
    assert "Kept" in {x.title for x in r.test_scenarios}


def test_conditional_rule_positive_expecting_acceptance_is_not_a_contradiction():
    rid = "REQ-PTO-004"
    acs = [ac(f"AC-{i}", t) for i, t in enumerate(BY_ID[rid]["rules"], start=1)]
    t = _t(rid, "TC-001", "AC-3", "positive", "Within balance", steps=["Request 3 days with a balance of 5 days"],
           expected="The request is accepted")
    out = {"ambiguities": [], "assumptions": [], "acceptance_criteria": acs, "test_scenarios": [t], "not_applicable": []}
    pipeline, _ = make_pipeline([out], supplements=0)
    r = run(pipeline.generate(RequirementInput.model_validate(BY_ID[rid])))
    assert "Within balance" in {x.title for x in r.test_scenarios}
