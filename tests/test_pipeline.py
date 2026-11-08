"""End-to-end pipeline tests with a mocked LLM (no Ollama needed).

Grouped by the behaviours the pipeline must guarantee:
  1 explicit business rules       6 unsupported business-rule assumptions
  2 vague terms                   7 duplicate test detection
  3 numeric boundaries            8 invalid traceability references
  4 missing details               9 retry and supplement behaviour
  5 positive / negative coverage 10 coverage calculation
  + robustness (invalid/empty/truncated JSON, timeouts, Ollama down, normalisation)
"""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from conftest import ac, make_pipeline, run, scenarios, tc
from llm_pipeline.errors import GenerationFailedError, InvalidRequirementError, LLMTimeoutError, LLMUnavailableError
from llm_pipeline.llm_client import LLMResponse
from llm_pipeline.schemas import RequirementInput


def link(result, ac_id):
    return next(x for x in result.traceability if x.acceptance_criterion_id == ac_id)


def supplement(*tests, na=None):
    return {"test_scenarios": list(tests), "not_applicable": na or []}


# =========================================================================== #
# Baseline: a good model answer
# =========================================================================== #
def test_good_answer_is_fully_validated_in_one_call(password_requirement, valid_output):
    pipeline, client = make_pipeline([valid_output])
    result = run(pipeline.generate(password_requirement))

    assert len(client.calls) == 1 and result.metadata.attempts == 1
    assert [a.id for a in result.acceptance_criteria] == ["AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6"]
    assert all(link(result, f"AC-{i}").status == "validated" for i in range(1, 6))
    assert link(result, "AC-6").status == "assumption"
    assert result.coverage.coverage_percent == 100.0
    assert result.coverage.rule_coverage_percent == 100.0
    assert result.coverage.gaps == []
    assert not any(w.startswith("remaining gap") for w in result.metadata.warnings)
    json.loads(result.model_dump_json())  # frontend can consume it


def test_prompt_lists_fixed_criteria_and_grounding_rules(password_requirement, valid_output):
    pipeline, client = make_pipeline([valid_output])
    run(pipeline.generate(password_requirement))
    system, user = client.calls[0]
    assert "Do NOT invent business rules" in system.content
    assert 'NOT "within 2 seconds"' in system.content
    assert "Never copy a positive test and just reverse its expected result" in system.content
    assert "AC-2: The new password must be between 8 and 64 characters." in user.content
    assert "AC-3: The new password must contain at least 1 digit." in user.content
    assert "generated automatically - do NOT write boundary tests" in user.content


# =========================================================================== #
# 1. Requirement with explicit business rules
# =========================================================================== #
def test_rule_fragments_and_rewording_are_merged_into_the_seeded_criterion(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    # the model fragments rule 2 into test-case-shaped criteria (seen in a real qwen2.5:3b run)
    out["acceptance_criteria"][1] = ac("AC-2", "A valid 8-character password is accepted.")
    out["acceptance_criteria"].append(ac("AC-7", "A password with more than 64 characters is rejected."))
    out["test_scenarios"][3]["acceptance_criterion_id"] = "AC-7"
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(password_requirement))

    ac2 = next(a for a in result.acceptance_criteria if a.id == "AC-2")
    assert ac2.description == "The new password must be between 8 and 64 characters."  # rule wording kept
    assert ac2.source == "explicit"
    assert link(result, "AC-2").test_case_ids[:2] == ["TC-003", "TC-004"]  # fragment's test re-linked
    assert [a.id for a in result.acceptance_criteria] == ["AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6"]
    assert any("described the same rule and were merged" in w for w in result.metadata.warnings)


def test_rule_the_model_skipped_is_still_a_criterion_and_gets_tests(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    del out["acceptance_criteria"][4]  # AC-5 "must not equal the current password"
    out["test_scenarios"] = scenarios(out, drop=("TC-009", "TC-010"))
    fill = supplement(
        tc("X1", "AC-5", "positive", "Different password accepted", steps=["Enter a different password"]),
        tc("X2", "AC-5", "negative", "Current password reused", steps=["Enter the current password"],
           expected="Rejected: new password equals current"),
    )
    pipeline, client = make_pipeline([out, fill])
    result = run(pipeline.generate(password_requirement))

    ac5 = next(a for a in result.acceptance_criteria if a.id == "AC-5")
    assert ac5.description == "The new password must not equal the current password."
    assert any("did not write a criterion" in w for w in result.metadata.warnings)
    assert link(result, "AC-5").status == "validated"
    assert len(client.calls) == 2
    assert result.coverage.rule_coverage_percent == 100.0


def test_seeded_criterion_with_invented_value_in_then_is_replaced(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["acceptance_criteria"][0]["then"] = "the link stops working after 45 minutes"
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(password_requirement))
    ac1 = result.acceptance_criteria[0]
    assert ac1.then == "The reset link expires 30 minutes after it is sent."
    assert any("unsupported value(s) ['45']" in w for w in result.metadata.warnings)


# =========================================================================== #
# 2. Requirement with vague terms ("fast", "user-friendly")
# =========================================================================== #
SEARCH = RequirementInput(
    requirement_id="REQ-202", title="Product search",
    description="The search should be fast and user-friendly and return relevant products, categories, brands etc.",
)


def _search_output():
    def t(*a, **k):
        return {**tc(*a, **k), "requirement_id": "REQ-202"}

    return {
        "ambiguities": [{"id": "AMB-1", "text": "fast", "issue": "speed undefined",
                         "clarification_question": "How fast?", "severity": "high"}],
        "assumptions": [],
        "acceptance_criteria": [
            ac("AC-1", "Search results are returned within 2 seconds."),
            ac("AC-2", "The search returns relevant products, categories and brands."),
            ac("AC-3", "Search results include categories and brands, not only products."),
        ],
        "test_scenarios": [
            t("TC-001", "AC-1", "positive", "Search is fast", expected="Results appear in under 2 seconds"),
            t("TC-002", "AC-2", "positive", "Relevant products found"),
            t("TC-003", "AC-3", "positive", "Brand appears in results"),
            t("TC-004", "AC-3", "negative", "Unknown term shows no-results message",
              expected="An empty-results message is shown, no error"),
        ],
        "not_applicable": [],
    }


def test_vague_terms_are_not_turned_into_requirements():
    pipeline, client = make_pipeline([_search_output()])
    result = run(pipeline.generate(SEARCH))

    # invented "2 seconds" -> assumption with an explicit assumption entry, not a requirement
    ac1 = result.acceptance_criteria[0]
    assert ac1.source == "assumption" and ac1.assumption_ids
    asm = next(a for a in result.assumptions if a.id == ac1.assumption_ids[0])
    assert "['2']" in asm.reason
    assert any("reclassified as assumption" in w for w in result.metadata.warnings)
    # "relevant" makes AC-2 unmeasurable -> blocked by the 'relevant' ambiguity
    l2 = link(result, "AC-2")
    assert l2.status == "needs_clarification" and l2.blocked_by
    blocker = next(a for a in result.ambiguities if a.id == l2.blocked_by[0])
    assert "relevant" in (blocker.text + blocker.issue).lower()
    # the test asserting "under 2 seconds" is removed, not kept as coverage
    assert any("TC-001 removed: expects value(s) ['2']" in w for w in result.metadata.warnings)
    assert "TC-001" not in {t.test_case_id for t in result.test_scenarios}
    # rules + LLM both found "fast" -> reported once
    assert sum("'fast'" in a.issue or a.text == "fast" for a in result.ambiguities) == 1
    assert result.needs_clarification is True
    # of the explicit criteria AC-2 and AC-3 only AC-3 is validated
    assert result.coverage.coverage_percent == 50.0
    assert result.coverage.generated_coverage_percent == 66.7  # AC-1 lost its only (invented) test
    # nothing was requested for blocked / assumption criteria
    assert len(client.calls) == 1


def test_blocked_criterion_links_to_the_ambiguity_that_names_the_term():
    """Real run: AC said 'relevant ... within a specified response time'; it was linked to the
    'user-friendly' ambiguity because that excerpt happened to contain the word 'relevant'."""
    out = _search_output()
    out["acceptance_criteria"] = [ac("AC-1", "The search returns relevant products within a specified response time.")]
    out["test_scenarios"] = [{**tc("TC-001", "AC-1", "positive", "Search works"), "requirement_id": "REQ-202"}]
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(SEARCH))
    blockers = {a.id: a.issue for a in result.ambiguities if a.id in link(result, "AC-1").blocked_by}
    assert any("'relevant'" in i for i in blockers.values())
    assert any("'fast'" in i for i in blockers.values())  # "response time" without a number -> the 'fast' ambiguity
    assert not any("'user-friendly'" in i for i in blockers.values())


def test_real_search_output_is_not_reported_as_validated():
    """Exact criteria qwen2.5:3b produced for examples/ambiguous_search.json."""
    out = _search_output()
    out["ambiguities"] = [{"id": "AMB-1", "text": "open-ended list", "issue": "the list of items is open-ended",
                           "clarification_question": "Which items?", "severity": "high"}]
    out["acceptance_criteria"] = [
        ac("AC-1", "The search returns relevant products, categories, and brands within a specified time."),
        ac("AC-2", "The search does not return irrelevant products, categories, and brands."),
    ]
    out["test_scenarios"] = [
        {**tc("TC-001", "AC-1", "positive", "Relevant results"), "requirement_id": "REQ-202"},
        {**tc("TC-002", "AC-2", "negative", "Irrelevant results hidden"), "requirement_id": "REQ-202"},
        {**tc("TC-003", "AC-2", "positive", "Valid results"), "requirement_id": "REQ-202"},
    ]
    pipeline, client = make_pipeline([out])
    result = run(pipeline.generate(SEARCH))
    assert [link(result, i).status for i in ("AC-1", "AC-2")] == ["needs_clarification", "needs_clarification"]
    relevant = next(a.id for a in result.ambiguities if "'relevant'" in a.issue)
    assert relevant in link(result, "AC-2").blocked_by                       # 'irrelevant' -> 'relevant'
    assert any("'fast'" in a.issue for a in result.ambiguities if a.id in link(result, "AC-1").blocked_by)
    assert sum("open-ended" in (a.text + a.issue).lower() for a in result.ambiguities) == 1
    assert result.coverage.coverage_percent == 0.0 and len(client.calls) == 1


def test_llm_restating_a_rule_ambiguity_is_deduplicated(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["ambiguities"].append({"id": "AMB-2", "text": "30 minutes", "issue": "whether the 30 minutes limit is inclusive or exclusive",
                               "clarification_question": "Is exactly 30 minutes still valid?", "severity": "high"})
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(password_requirement))
    assert sum("30" in a.issue for a in result.ambiguities) == 1


def test_placeholder_criterion_is_an_assumption_with_an_assumption_entry():
    out = _search_output()
    out["acceptance_criteria"] = [
        ac("AC-1", "Search results are returned within [response time to be confirmed - AMB-1].", "assumption"),
        out["acceptance_criteria"][2],
    ]
    out["test_scenarios"] = [s for s in out["test_scenarios"] if s["acceptance_criterion_id"] == "AC-3"]
    for s in out["test_scenarios"]:
        s["acceptance_criterion_id"] = "AC-2"
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(SEARCH))
    a1 = result.acceptance_criteria[0]
    assert a1.source == "assumption" and a1.assumption_ids
    l1 = link(result, "AC-1")
    fast = next(a.id for a in result.ambiguities if "'fast'" in a.issue)
    # the model's own AMB-1 ('fast') was merged into the rule finding -> reference rewritten to the final id
    assert l1.status == "needs_clarification" and l1.blocked_by == [fast]
    assert f"- {fast}]" in a1.description


# =========================================================================== #
# 3. Requirement with numeric boundaries
# =========================================================================== #
def test_boundary_tests_use_exact_values_for_every_stated_limit(password_requirement, valid_output):
    pipeline, _ = make_pipeline([valid_output])
    result = run(pipeline.generate(password_requirement))
    tests = {t.test_case_id: t for t in result.test_scenarios}
    data = {b.limit: tests[b.test_case_ids[0]].test_data for b in result.coverage.boundary_coverage}
    assert data["between 8 and 64 characters"] == [
        "7 characters -> rejected", "8 characters -> accepted", "64 characters -> accepted", "65 characters -> rejected"]
    assert data["at least 1 digit"] == ["0 digits -> rejected", "1 digit -> accepted", "2 digits -> accepted"]
    assert data["at most 3 reset emails"] == [
        "2 reset emails -> accepted", "3 reset emails -> accepted", "4 reset emails -> rejected"]
    assert data["expires 30 minutes"][1].startswith("30 minutes -> exactly at the limit")
    assert all(b.covered for b in result.coverage.boundary_coverage)
    # each limit is linked to the criterion whose rule contains it
    by_limit = {b.limit: b.acceptance_criterion_id for b in result.coverage.boundary_coverage}
    assert by_limit == {"expires 30 minutes": "AC-1", "between 8 and 64 characters": "AC-2",
                        "at least 1 digit": "AC-3", "at most 3 reset emails": "AC-4"}
    # inclusivity at exactly 30 minutes is unstated -> an ambiguity, not an invented answer
    assert any("exactly 30 minutes" in a.issue for a in result.ambiguities)


def test_limit_without_parsable_direction_becomes_a_precise_llm_task():
    req = RequirementInput(requirement_id="REQ-9", description="The account is locked after 5 attempts with a wrong password.",
                           business_rules=["The account is locked after 5 attempts."])

    def t(*a, **k):
        return {**tc(*a, **k), "requirement_id": "REQ-9"}

    out = {"ambiguities": [], "assumptions": [],
           "acceptance_criteria": [ac("AC-1", "The account is locked after 5 attempts.")],
           "test_scenarios": [t("TC-001", "AC-1", "positive", "Correct password logs in"),
                              t("TC-002", "AC-1", "negative", "Locked account cannot log in")],
           "not_applicable": []}
    fill = supplement(t("X", "AC-1", "boundary", "Attempts 4, 5, 6", data=["4 attempts", "5 attempts", "6 attempts"]))
    pipeline, client = make_pipeline([out, fill])
    result = run(pipeline.generate(req))
    assert "AC-1 has no boundary test for '5 attempts'" in client.calls[1][1].content
    assert result.coverage.boundary_coverage[0].covered
    assert link(result, "AC-1").status == "validated"


def test_no_limits_are_invented_when_requirement_has_none():
    req = RequirementInput(requirement_id="REQ-101", description="A registered user can log out from any page of the app.")
    out = {"ambiguities": [], "assumptions": [],
           "acceptance_criteria": [ac("AC-1", "A registered user can log out from any page.")],
           "test_scenarios": [tc("TC-001", "AC-1", "positive", "Logout from settings page")],
           "not_applicable": [{"acceptance_criterion_id": "AC-1", "test_type": "negative",
                               "reason": "Logging out has no invalid input a user could provide."}]}
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(req))
    assert result.coverage.boundary_coverage == []
    assert not any(t.test_type == "boundary" for t in result.test_scenarios)


# =========================================================================== #
# 4. Requirement with missing details
# =========================================================================== #
def test_brief_requirement_flags_missing_details_and_invented_criteria():
    req = RequirementInput(description="Export the monthly report to PDF format.")
    out = {
        "ambiguities": [], "assumptions": [],
        "acceptance_criteria": [
            ac("AC-1", "The monthly report can be exported to PDF format."),
            ac("AC-2", "Exported files include a company logo, watermark and page numbering."),
        ],
        "test_scenarios": [tc("TC-001", "AC-1", "positive", "Export current month"),
                           tc("TC-002", "AC-1", "negative", "Export with no report data", expected="An error message is shown"),
                           tc("TC-003", "AC-2", "positive", "Logo visible in PDF")],
        "not_applicable": [],
    }
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(req))
    issues = " ".join(a.issue for a in result.ambiguities)
    assert "No user role" in issues and "very brief" in issues
    assert result.acceptance_criteria[1].source == "assumption"  # logo / watermark were never requested
    assert "introduces concepts not in the requirement" in result.assumptions[-1].reason
    assert link(result, "AC-1").status == "validated"
    assert result.requirement_id.startswith("REQ-")


def test_unusable_requirement_is_rejected_before_the_llm():
    pipeline, client = make_pipeline([])
    for bad in ["", "   ", "Login", "!!! ??? ###", "a b c"]:
        with pytest.raises(InvalidRequirementError):
            run(pipeline.generate(RequirementInput(description=bad)))
    assert client.calls == []


# =========================================================================== #
# 5. Positive and negative test coverage
# =========================================================================== #
def test_missing_negative_test_is_requested_precisely_and_filled(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"] = scenarios(out, drop=("TC-008",))  # AC-4 loses its negative test
    fill = supplement(tc("X", "AC-4", "negative", "Fourth email in the hour", steps=["Request a 4th email"],
                         expected="Request refused with a rate-limit error"))
    pipeline, client = make_pipeline([out, fill])
    result = run(pipeline.generate(password_requirement))
    prompt = client.calls[1][1].content
    assert "1. AC-4 ('A user can request at most 3 reset emails per hour.') has no negative test" in prompt
    assert "must differ from TC-007" in prompt
    assert link(result, "AC-4").has_negative and link(result, "AC-4").status == "validated"


def test_not_applicable_negative_is_accepted_with_a_reason():
    req = RequirementInput(requirement_id="REQ-5", description="The dashboard shows the user's name in the header.")
    out = {"ambiguities": [], "assumptions": [],
           "acceptance_criteria": [ac("AC-1", "The dashboard shows the user's name in the header.")],
           "test_scenarios": [{**tc("TC-001", "AC-1", "positive", "Name shown after login"), "requirement_id": "REQ-5"}],
           "not_applicable": [{"acceptance_criterion_id": "AC-1", "test_type": "negative",
                               "reason": "Displaying the name involves no user input that could be invalid."}]}
    pipeline, client = make_pipeline([out])
    result = run(pipeline.generate(req))
    l1 = link(result, "AC-1")
    assert l1.status == "validated" and l1.not_applicable[0].startswith("negative: Displaying")
    assert len(client.calls) == 1


def test_not_applicable_is_rejected_when_the_criterion_has_a_constraint(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"] = scenarios(out, drop=("TC-010",))
    out["not_applicable"] = [{"acceptance_criterion_id": "AC-5", "test_type": "negative", "reason": "Not needed here really."}]
    pipeline, _ = make_pipeline([out], supplements=0)
    result = run(pipeline.generate(password_requirement))
    assert link(result, "AC-5").status == "partial"
    assert any("not applicable' for AC-5 rejected" in w for w in result.metadata.warnings)


def test_positive_test_expecting_an_error_is_relabelled(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"].append(tc("TC-013", "AC-2", "positive", "65-char password", expected="An error says it is too long"))
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(password_requirement))
    assert next(t for t in result.test_scenarios if t.title == "65-char password").test_type == "negative"


# =========================================================================== #
# 6. Unsupported business-rule assumptions
# =========================================================================== #
def test_extra_criterion_with_unstated_value_becomes_an_assumption(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["acceptance_criteria"].append(ac("AC-7", "The reset email arrives within 5 minutes."))
    out["test_scenarios"].append(tc("TC-013", "AC-7", "positive", "Email arrives quickly"))
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(password_requirement))
    ac7 = result.acceptance_criteria[-1]
    assert ac7.source == "assumption" and ac7.assumption_ids
    assert link(result, ac7.id).status == "assumption"
    assert result.coverage.assumption_criteria == 2
    assert result.coverage.coverage_percent == 100.0  # assumptions do not count as requirements


def test_test_asserting_unstated_value_does_not_count(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"][6]["expected_result"] = "The email arrives within 5 minutes"  # TC-007, AC-4 positive
    fill = supplement(tc("X", "AC-4", "positive", "Second request in the hour", steps=["Request a second email"]))
    pipeline, client = make_pipeline([out, fill])
    result = run(pipeline.generate(password_requirement))
    assert any("TC-007 removed: expects value(s) ['5']" in w for w in result.metadata.warnings)
    assert "AC-4" in client.calls[1][1].content and "no positive test" in client.calls[1][1].content
    assert link(result, "AC-4").status == "validated"


# =========================================================================== #
# 7. Duplicate test scenario detection
# =========================================================================== #
def test_mirror_negative_with_same_steps_is_removed_and_re_requested(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"][1]["test_steps"] = out["test_scenarios"][0]["test_steps"]  # TC-002 copies TC-001's steps
    fill = supplement(tc("X", "AC-1", "negative", "Link opened after expiry", steps=["Wait past expiry", "Open link"],
                         expected="Link rejected as expired"))
    pipeline, _ = make_pipeline([out, fill])
    result = run(pipeline.generate(password_requirement))
    assert any("TC-002 removed: same steps and data as TC-001; only the expected result is reversed" in w
               for w in result.metadata.warnings)
    assert link(result, "AC-1").has_negative


def test_exact_near_and_cross_criterion_duplicates_are_removed(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    s = out["test_scenarios"]
    s.append({**s[2], "test_case_id": "TC-013"})                                     # exact duplicate of TC-003
    s.append({**s[2], "test_case_id": "TC-014", "acceptance_criterion_id": "AC-3"})  # same steps, other AC
    s.append({**s[2], "test_case_id": "TC-015", "title": s[2]["title"] + " again",
              "test_steps": [*s[2]["test_steps"], "Again"]})                         # near-duplicate
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(password_requirement))
    ids = {t.test_case_id for t in result.test_scenarios}
    w = " | ".join(result.metadata.warnings)
    assert "TC-013 removed: duplicate of TC-003" in w
    assert "TC-014 removed: same steps and data as TC-003 (for AC-2); not specific" in w
    assert "TC-015 removed: near-duplicate of TC-003" in w
    assert "TC-003" in ids


def test_duplicate_test_ids_are_renumbered_not_fatal(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"][3]["test_case_id"] = "TC-003"
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(password_requirement))
    ids = [t.test_case_id for t in result.test_scenarios]
    assert len(ids) == len(set(ids))
    assert any("duplicate test ID TC-003 renumbered" in w for w in result.metadata.warnings)


# =========================================================================== #
# 8. Invalid traceability references
# =========================================================================== #
def test_test_linked_to_unknown_criterion_is_removed_and_reported(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"][2]["acceptance_criterion_id"] = "AC-99"  # TC-003 (AC-2 positive)
    fill = supplement(tc("X", "AC-2", "positive", "Ten-character password accepted", steps=["Enter ten chars"]))
    pipeline, _ = make_pipeline([out, fill])
    result = run(pipeline.generate(password_requirement))
    assert result.coverage.invalid_references == ["TC-003 referenced unknown acceptance criterion 'AC-99' and was removed"]
    assert link(result, "AC-2").status == "validated"


def test_all_tests_invalid_triggers_full_regeneration(password_requirement, valid_output):
    bad = copy.deepcopy(valid_output)
    for s in bad["test_scenarios"]:
        s["acceptance_criterion_id"] = "AC-99"
    pipeline, client = make_pipeline([bad, valid_output])
    result = run(pipeline.generate(password_requirement))
    assert result.metadata.attempts == 2
    assert "no valid test scenarios remain" in client.calls[1][-1].content


def test_loose_id_formats_are_normalised(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"][3]["acceptance_criterion_id"] = "ac2"
    out["test_scenarios"][2]["requirement_id"] = "R-1"
    pipeline, _ = make_pipeline([out])
    result = run(pipeline.generate(password_requirement))
    t = {x.test_case_id: x for x in result.test_scenarios}
    assert t["TC-004"].acceptance_criterion_id == "AC-2" and t["TC-003"].requirement_id == "REQ-101"
    assert result.coverage.invalid_references == []


# =========================================================================== #
# 9. Retry and supplement behaviour
# =========================================================================== #
def _no_negatives(valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"] = [s for s in out["test_scenarios"] if s["test_type"] != "negative"]
    return out


def test_supplements_are_batched_prioritised_and_bounded(password_requirement, valid_output):
    nothing = supplement()
    pipeline, client = make_pipeline([_no_negatives(valid_output), nothing, nothing, nothing])
    result = run(pipeline.generate(password_requirement))
    rounds = [c[1].content.split("Tasks:\n", 1)[1] for c in client.calls[1:]]
    assert rounds[0].count("has no negative test") == 4           # max 4 tasks per request: AC-1..AC-4
    assert rounds[1].startswith("1. AC-5")                       # never-asked task goes first
    assert "Previous attempt rejected: no usable test was returned" in rounds[1]  # retried tasks get feedback
    assert "AC-1" not in rounds[2] and "AC-4" in rounds[2]       # each task is asked at most twice
    assert len(client.calls) == 4                                 # 1 generation + max 3 supplement rounds
    remaining = [w for w in result.metadata.warnings if w.startswith("remaining gap")]
    assert len(remaining) == 5 and all("no valid negative test" in w for w in remaining)


def test_rejected_supplement_test_is_explained_when_the_task_is_retried(password_requirement, valid_output):
    """Real qwen2.5:3b run: asked for a positive expiry test, it wrote one expecting 'link expired'."""
    out = copy.deepcopy(valid_output)
    out["test_scenarios"] = scenarios(out, drop=("TC-001",))  # AC-1 has no positive test
    wrong = supplement(tc("X", "AC-1", "positive", "Link after expiry", steps=["Wait", "Open link"],
                          expected="The link is expired and cannot be used"))
    right = supplement(tc("Y", "AC-1", "positive", "Link opened within the limit", steps=["Open link soon after sending"],
                          expected="The reset form opens"))
    pipeline, client = make_pipeline([out, wrong, right])
    result = run(pipeline.generate(password_requirement))
    first, retry = client.calls[1][1].content, client.calls[2][1].content
    assert "must be a success, not an error or rejection" in first and "inside the limit (expires 30 minutes)" in first
    assert "Previous attempt rejected: your test 'Link after expiry' expected an error or rejection" in retry
    assert link(result, "AC-1").status == "validated"


def test_supplement_output_is_filtered_and_previous_output_preserved(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"] = scenarios(out, drop=("TC-006",))
    fill = supplement(
        tc("X1", "AC-3", "positive", "Padding positive", steps=["pad"]),           # not requested
        tc("X2", "AC-9", "negative", "Unknown criterion", steps=["x"]),              # invalid reference
        tc("X3", "AC-3", "negative", "Letters-only password", steps=["Enter letters only"],
           expected="Rejected: a digit is required"),                                 # the task
    )
    pipeline, _ = make_pipeline([out, fill])
    result = run(pipeline.generate(password_requirement))
    titles = [t.title for t in result.test_scenarios]
    assert "Letters-only password" in titles and "Padding positive" not in titles
    assert all(t in titles for t in [s["title"] for s in out["test_scenarios"]])  # nothing valid was lost
    assert any("did not match a requested task" in w for w in result.metadata.warnings)
    added = next(t for t in result.test_scenarios if t.title == "Letters-only password")
    assert added.test_case_id == "TC-017"  # numbered after TC-013..016 (boundary tests)


def test_supplement_results_are_revalidated_like_everything_else(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"] = scenarios(out, drop=("TC-002",))
    mirror = supplement(tc("X", "AC-1", "negative", "Mirror", steps=out["test_scenarios"][0]["test_steps"],
                           expected="Link rejected"))
    pipeline, client = make_pipeline([out, mirror, supplement()])
    result = run(pipeline.generate(password_requirement))
    assert not any(t.title == "Mirror" for t in result.test_scenarios)
    assert link(result, "AC-1").status == "partial"
    assert "Previous attempt rejected: your test removed: same steps and data as TC-001" in client.calls[2][1].content


def test_draft_is_kept_when_supplements_time_out_or_ollama_goes_down(password_requirement, valid_output):
    pipeline, _ = make_pipeline([_no_negatives(valid_output), LLMTimeoutError("slow"), LLMUnavailableError("down")])
    result = run(pipeline.generate(password_requirement))
    assert len(result.test_scenarios) >= 6
    assert result.coverage.coverage_percent == 0.0  # honest: no criterion has a negative test


def test_supplement_rounds_are_bounded(password_requirement, valid_output):
    pipeline, client = make_pipeline([_no_negatives(valid_output), supplement()], supplements=1)
    run(pipeline.generate(password_requirement))
    assert len(client.calls) == 2


# =========================================================================== #
# 10. Coverage calculation
# =========================================================================== #
def test_coverage_distinguishes_generated_from_validated(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"] = scenarios(out, drop=("TC-006",))  # AC-3 (digit clause of rule 2) has no negative
    pipeline, _ = make_pipeline([out], supplements=0)
    result = run(pipeline.generate(password_requirement))
    c = result.coverage
    assert c.generated_coverage_percent == 100.0  # every AC has some test...
    assert c.coverage_percent == 80.0             # ...but only 4 of 5 explicit ACs are validated
    assert c.validated_acceptance_criteria == 4
    rule2 = next(r for r in c.rule_coverage if r.rule.startswith("The new password must be between"))
    assert rule2.acceptance_criterion_ids == ["AC-2", "AC-3"] and rule2.status == "partial"
    assert c.rule_coverage_percent == 75.0
    assert link(result, "AC-3").missing == ["negative test"]
    assert "AC-3 ('The new password must contain at least 1 digit.') has no valid negative test" in c.gaps


def test_coverage_is_never_100_when_criteria_are_untested(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    out["test_scenarios"] = scenarios(out, drop=("TC-009", "TC-010"))
    pipeline, _ = make_pipeline([out], supplements=0)
    result = run(pipeline.generate(password_requirement))
    assert link(result, "AC-5").status == "untested"
    assert result.coverage.coverage_percent == 80.0
    assert next(r for r in result.coverage.rule_coverage if "current password" in r.rule).status == "untested"


# =========================================================================== #
# Robustness
# =========================================================================== #
def test_invalid_json_triggers_repair_and_recovers(password_requirement, valid_output):
    pipeline, client = make_pipeline(["Sure! Here are your tests: {acceptance_criteria: [", valid_output])
    result = run(pipeline.generate(password_requirement))
    assert result.metadata.attempts == 2
    assert client.calls[1][-2].role == "assistant" and "not valid JSON" in client.calls[1][-1].content


def test_json_in_markdown_fence_is_recovered_without_retry(password_requirement, valid_output):
    wrapped = "Here you go:\n```json\n" + json.dumps(valid_output) + "\n```\nHope this helps!"
    pipeline, _ = make_pipeline([wrapped])
    assert run(pipeline.generate(password_requirement)).metadata.attempts == 1


def test_empty_response_is_retried(password_requirement, valid_output):
    pipeline, client = make_pipeline(["   ", valid_output])
    assert run(pipeline.generate(password_requirement)).metadata.attempts == 2
    assert "empty" in client.calls[1][-1].content


def test_schema_error_is_retried_with_field_level_errors(password_requirement, valid_output):
    broken = copy.deepcopy(valid_output)
    del broken["acceptance_criteria"][0]["then"]
    pipeline, client = make_pipeline([broken, valid_output])
    assert run(pipeline.generate(password_requirement)).metadata.attempts == 2
    assert "acceptance_criteria.0.then" in client.calls[1][-1].content


def test_missing_acceptance_criteria_is_retried_then_fails(password_requirement, valid_output):
    no_ac = copy.deepcopy(valid_output)
    no_ac["acceptance_criteria"] = []
    pipeline, client = make_pipeline([no_ac, valid_output])
    assert run(pipeline.generate(password_requirement)).metadata.attempts == 2
    assert "acceptance_criteria" in client.calls[1][-1].content
    pipeline, _ = make_pipeline([no_ac] * 3)
    with pytest.raises(GenerationFailedError):
        run(pipeline.generate(password_requirement))


def test_retry_exhaustion_raises_with_history(password_requirement):
    pipeline, client = make_pipeline(["not json", "", "{still not json"])
    with pytest.raises(GenerationFailedError) as exc:
        run(pipeline.generate(password_requirement))
    assert exc.value.attempts == 3 and len(client.calls) == 3 and len(exc.value.details) == 3
    assert "invalid JSON" in exc.value.details[0] and "empty" in exc.value.details[1]


def test_timeout_then_success(password_requirement, valid_output):
    pipeline, _ = make_pipeline([LLMTimeoutError("slow"), valid_output])
    assert run(pipeline.generate(password_requirement)).metadata.attempts == 2


def test_hanging_client_hits_outer_timeout(password_requirement, valid_output):
    pipeline, client = make_pipeline([valid_output], max_retries=0)

    async def hang(messages, *, json_schema=None):
        await asyncio.sleep(60)

    client.chat = hang
    object.__setattr__(pipeline.settings, "request_timeout_s", 0.01)
    with pytest.raises(GenerationFailedError) as exc:
        run(pipeline.generate(password_requirement))
    assert "timed out" in exc.value.details[0]


def test_ollama_down_fails_fast(password_requirement):
    pipeline, client = make_pipeline([LLMUnavailableError("down"), "unused"])
    with pytest.raises(LLMUnavailableError):
        run(pipeline.generate(password_requirement))
    assert len(client.calls) == 1


def test_truncated_output_is_salvaged(password_requirement, valid_output):
    text = json.dumps({k: v for k, v in valid_output.items() if k != "not_applicable"})
    cut = text.rfind('{"test_case_id": "TC-012"') + 40
    pipeline, _ = make_pipeline([LLMResponse(content=text[:cut], truncated=True)])
    result = run(pipeline.generate(password_requirement))
    assert result.metadata.attempts == 1
    assert "Visual check of reset email" not in {t.title for t in result.test_scenarios}  # the cut-off item
    assert len([t for t in result.test_scenarios if t.test_type != "boundary"]) == 11
    assert any("token limit" in w for w in result.metadata.warnings)


def test_single_invalid_scenario_is_dropped_not_regenerated(password_requirement, valid_output):
    out = copy.deepcopy(valid_output)
    del out["test_scenarios"][11]["expected_result"]  # TC-012 (edge case, not needed for validation)
    pipeline, client = make_pipeline([out])
    result = run(pipeline.generate(password_requirement))
    assert len(client.calls) == 1
    assert any("dropped invalid test scenario TC-012" in w for w in result.metadata.warnings)


def test_loose_enum_formatting_is_normalised(password_requirement, valid_output):
    messy = copy.deepcopy(valid_output)
    messy["test_scenarios"][0]["test_type"] = "Happy Path"
    messy["test_scenarios"][1]["priority"] = "HIGH"
    messy["test_scenarios"][4]["test_steps"] = "Open page\nEnter a password with a digit\nSubmit"
    messy["test_scenarios"][10]["automation"]["level"] = "E2E"
    messy["unexpected_key"] = "ignored"
    pipeline, _ = make_pipeline([messy])
    t = {x.test_case_id: x for x in run(pipeline.generate(password_requirement)).test_scenarios}
    assert t["TC-001"].test_type == "positive" and t["TC-002"].priority == "high"
    assert t["TC-005"].test_steps == ["Open page", "Enter a password with a digit", "Submit"]
    assert t["TC-011"].automation.level == "ui"
