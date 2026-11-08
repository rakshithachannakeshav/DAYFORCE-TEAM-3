"""Shared test fixtures. No test here needs Ollama running."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_pipeline.config import LLMSettings  # noqa: E402
from llm_pipeline.llm_client import ChatMessage, LLMResponse  # noqa: E402
from llm_pipeline.pipeline import GenerationPipeline  # noqa: E402
from llm_pipeline.schemas import RequirementInput  # noqa: E402


class FakeLLMClient:
    """Replays a scripted list of responses.

    Each item is either a ``str`` (model content), an ``LLMResponse``, a dict
    (JSON-encoded for you), or an ``Exception`` instance (raised).
    """

    model = "fake-model"

    def __init__(self, script: list[Any]):
        self.script = list(script)
        self.calls: list[list[ChatMessage]] = []

    async def chat(self, messages, *, json_schema=None) -> LLMResponse:
        self.calls.append(list(messages))
        if not self.script:
            raise AssertionError("FakeLLMClient: no more scripted responses")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResponse):
            return item
        if isinstance(item, dict):
            item = json.dumps(item)
        return LLMResponse(content=item)

    async def health(self):
        return {"ollama_reachable": True, "model": self.model, "model_available": True}


def make_pipeline(script: list[Any], max_retries: int = 2, supplements: int = 3) -> tuple[GenerationPipeline, FakeLLMClient]:
    """Pipeline with a scripted fake LLM. Every result it returns is checked by
    ``assert_consistent`` - so ALL pipeline tests also test internal consistency."""
    client = FakeLLMClient(script)
    settings = LLMSettings(max_retries=max_retries, request_timeout_s=5, max_supplement_rounds=supplements)
    pipeline = GenerationPipeline(client=client, settings=settings)
    original = pipeline.generate

    async def checked_generate(req):
        result = await original(req)
        assert_consistent(result)
        return result

    pipeline.generate = checked_generate  # type: ignore[method-assign]
    return pipeline, client


def assert_consistent(r) -> None:
    """Traceability, coverage, gaps and warnings must tell the same story."""
    acs = {a.id: a for a in r.acceptance_criteria}
    tests = {t.test_case_id: t for t in r.test_scenarios}
    amb_ids = {a.id for a in r.ambiguities}
    asm_ids = {a.id for a in r.assumptions}
    assert len(acs) == len(r.acceptance_criteria), "duplicate AC ids"
    assert len(tests) == len(r.test_scenarios), "duplicate test ids"
    assert [x.acceptance_criterion_id for x in r.traceability] == list(acs), "one link per AC, same order"

    for t in r.test_scenarios:
        assert t.acceptance_criterion_id in acs, f"{t.test_case_id} links to unknown AC"
        assert t.requirement_id == r.requirement_id

    for link in r.traceability:
        ac = acs[link.acceptance_criterion_id]
        mine = [t for t in r.test_scenarios if t.acceptance_criterion_id == ac.id]
        assert link.test_case_ids == [t.test_case_id for t in mine], f"{ac.id}: test ids disagree"
        assert link.test_types == sorted({t.test_type for t in mine}), f"{ac.id}: test types disagree"
        assert link.covered == bool(mine)
        assert link.has_positive == any(t.test_type == "positive" for t in mine), f"{ac.id}: has_positive"
        assert link.has_negative == any(t.test_type == "negative" for t in mine), f"{ac.id}: has_negative"
        assert set(link.blocked_by) <= amb_ids, f"{ac.id}: blocked_by unknown ambiguity"
        assert set(ac.assumption_ids) <= asm_ids, f"{ac.id}: unknown assumption id"
        for ref in __import__("re").findall(r"AMB-\d+", f"{ac.description} {ac.then}"):
            assert ref in amb_ids, f"{ac.id} text references unknown {ref}"
        if link.status == "validated":
            assert ac.source == "explicit" and not link.missing and not link.blocked_by
            assert link.has_positive and (link.has_negative or link.not_applicable)
            assert link.has_boundary or not link.boundary_required
        if link.status == "needs_clarification":
            assert link.blocked_by and len(link.missing) == len(link.blocked_by), f"{ac.id}: blocked w/o reason"
            for amb in link.blocked_by:
                assert any(amb in m for m in link.missing)
                assert any(g.startswith(ac.id) and amb in g for g in r.coverage.gaps), f"{ac.id}: no gap names {amb}"
        if ac.source == "assumption":
            assert ac.assumption_ids, f"{ac.id}: assumption without assumption entry"
            assert link.status in ("assumption", "needs_clarification")
        if ac.source == "explicit" and link.status in ("partial", "untested"):
            assert link.missing, f"{ac.id}: not validated but nothing missing"
            assert any(g.startswith(ac.id) for g in r.coverage.gaps), f"{ac.id}: not validated but no gap"

    c = r.coverage
    explicit = [x for x in r.traceability if acs[x.acceptance_criterion_id].source == "explicit"]
    scope = [x for x in r.traceability
             if acs[x.acceptance_criterion_id].source == "explicit" or x.status == "needs_clarification"]
    validated = [x for x in scope if x.status == "validated"]
    assert c.total_acceptance_criteria == len(acs)
    assert c.covered_acceptance_criteria == sum(x.covered for x in r.traceability)
    assert c.validated_acceptance_criteria == len(validated) == sum(x.status == "validated" for x in r.traceability)
    assert c.blocked_acceptance_criteria == sum(x.status == "needs_clarification" for x in r.traceability)
    assert c.assumption_criteria == len(acs) - len(explicit)
    assert c.coverage_percent == (round(100 * len(validated) / len(scope), 1) if scope else 0.0)
    assert all(x.status != "validated" for x in r.traceability if x.blocked_by), "blocked criterion counted as validated"
    assert c.generated_coverage_percent == (round(100 * c.covered_acceptance_criteria / len(acs), 1) if acs else 0.0)
    for g in c.gaps:  # every gap is about a criterion that is NOT validated (or an unmapped limit)
        ac_id = g.split(" ", 1)[0]
        if ac_id in acs:
            assert next(x for x in r.traceability if x.acceptance_criterion_id == ac_id).status != "validated", g
    remaining = [w[len("remaining gap: "):] for w in r.metadata.warnings if w.startswith("remaining gap: ")]
    assert remaining == c.gaps, "warnings and coverage.gaps disagree"
    for rule in c.rule_coverage:
        statuses = [x.status for x in r.traceability if x.acceptance_criterion_id in rule.acceptance_criterion_ids]
        assert (rule.status == "validated") == (bool(statuses) and all(s == "validated" for s in statuses)), rule.rule
    for b in c.boundary_coverage:
        assert b.covered == bool(b.test_case_ids)
        for tid in b.test_case_ids:
            assert tests[tid].test_type == "boundary" and tests[tid].acceptance_criterion_id == b.acceptance_criterion_id
    assert {e.test_case_id for e in r.edge_cases} == {t.test_case_id for t in r.test_scenarios
                                                      if t.test_type in ("boundary", "edge_case")}
    assert r.needs_clarification == (any(a.severity == "high" for a in r.ambiguities)
                                     or any(x.status == "needs_clarification" for x in r.traceability))


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Canned data: the password-reset requirement and a GOOD model answer for it
# --------------------------------------------------------------------------- #

PASSWORD_RULES = [
    "The reset link expires 30 minutes after it is sent.",
    "The new password must be between 8 and 64 characters and contain at least 1 digit.",
    "A user can request at most 3 reset emails per hour.",
    "The new password must not equal the current password.",
]
# Seeded criteria the pipeline derives from those rules (one per clause):
#   AC-1 expires 30 minutes | AC-2 8-64 characters | AC-3 at least 1 digit
#   AC-4 at most 3 per hour | AC-5 must not equal current password


def tc(tc_id, ac_id, test_type, title, level="api", priority="high", data=None, expected=None, steps=None):
    return {
        "test_case_id": tc_id,
        "title": title,
        "requirement_id": "REQ-101",
        "acceptance_criterion_id": ac_id,
        "test_type": test_type,
        "preconditions": ["A registered user exists"],
        "test_steps": steps or ["Open the reset page", f"Perform: {title}"],
        "test_data": data or [],
        "expected_result": expected or f"Outcome verified: {title}",
        "priority": priority,
        "automation": {"automatable": True, "level": level, "suggested_tool": "pytest", "rationale": "API-testable"},
    }


def ac(ac_id, description, source="explicit", assumption_ids=None):
    return {"id": ac_id, "description": description, "given": "a registered user with a reset link",
            "when": "the rule is exercised", "then": description, "source": source,
            "assumption_ids": assumption_ids or []}


VALID_OUTPUT: dict[str, Any] = {
    "ambiguities": [{
        "id": "AMB-1", "text": "reset link",
        "issue": "Behaviour of previously issued links after a new one is requested is not stated.",
        "clarification_question": "Are older reset links invalidated when a new one is sent?", "severity": "medium",
    }],
    "assumptions": [{"id": "ASM-1", "statement": "Older links are invalidated when a new link is issued.", "reason": "AMB-1"}],
    "acceptance_criteria": [
        ac("AC-1", "The reset link expires 30 minutes after it is sent."),
        ac("AC-2", "The new password must be between 8 and 64 characters."),
        ac("AC-3", "The new password must contain at least 1 digit."),
        ac("AC-4", "A user can request at most 3 reset emails per hour."),
        ac("AC-5", "The new password must not equal the current password."),
        ac("AC-6", "Older reset links stop working after a new link is issued.", "assumption", ["ASM-1"]),
    ],
    "test_scenarios": [
        tc("TC-001", "AC-1", "positive", "Fresh link opens the reset form"),
        tc("TC-002", "AC-1", "negative", "Expired link is rejected"),
        tc("TC-003", "AC-2", "positive", "Twelve-character password accepted"),
        tc("TC-004", "AC-2", "negative", "Seventy-character password rejected"),
        tc("TC-005", "AC-3", "positive", "Password with a digit accepted"),
        tc("TC-006", "AC-3", "negative", "Password without digits rejected"),
        tc("TC-007", "AC-4", "positive", "Third request in an hour sends an email"),
        tc("TC-008", "AC-4", "negative", "Fourth request in an hour is refused"),
        tc("TC-009", "AC-5", "positive", "Password different from current accepted"),
        tc("TC-010", "AC-5", "negative", "Password equal to current rejected"),
        tc("TC-011", "AC-6", "negative", "Old link rejected after a new request", level="integration"),
        tc("TC-012", "AC-1", "edge_case", "Visual check of reset email", level="manual", priority="low"),
    ],
    "not_applicable": [],
}


@pytest.fixture
def valid_output() -> dict[str, Any]:
    out = copy.deepcopy(VALID_OUTPUT)
    out["test_scenarios"][-1]["automation"]["automatable"] = False
    return out


@pytest.fixture
def password_requirement() -> RequirementInput:
    return RequirementInput(
        requirement_id="REQ-101",
        title="Password reset via email",
        description=(
            "As a registered user, I want to reset my password using a link sent to my email "
            "so that I can regain access to my account."
        ),
        actor="registered user",
        business_rules=list(PASSWORD_RULES),
    )


def scenarios(out: dict, *, drop: tuple[str, ...] = ()) -> list[dict]:
    """Copy of the scenarios without the given test IDs."""
    return [copy.deepcopy(s) for s in out["test_scenarios"] if s["test_case_id"] not in drop]
