"""Pydantic models: the input contract, the LLM output contract, and the
final API response contract.

Two output layers are used on purpose:

* ``LLMOutput`` - the *small* structure the model must produce. Keeping it
  small makes a 3B-parameter local model far more reliable.
* ``GenerationResult`` - the final response returned to the backend/frontend.
  The pipeline adds fields the model should NOT be trusted to produce
  (requirement ID, original text, traceability matrix, coverage, metadata),
  computing them deterministically from the LLM output.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #

TestType = Literal["positive", "negative", "boundary", "edge_case"]
Priority = Literal["high", "medium", "low"]
Severity = Literal["high", "medium", "low"]
CriterionSource = Literal["explicit", "assumption"]
AutomationLevel = Literal["unit", "api", "integration", "ui", "manual"]
AmbiguitySource = Literal["rule", "llm"]

_TEST_TYPE_ALIASES = {
    "positive": "positive",
    "happy path": "positive",
    "happy_path": "positive",
    "functional": "positive",
    "negative": "negative",
    "error": "negative",
    "invalid": "negative",
    "boundary": "boundary",
    "boundary value": "boundary",
    "boundary_value": "boundary",
    "bva": "boundary",
    "edge": "edge_case",
    "edge case": "edge_case",
    "edge-case": "edge_case",
    "edge_case": "edge_case",
    "corner case": "edge_case",
}

_LEVEL_ALIASES = {
    "unit": "unit",
    "api": "api",
    "service": "api",
    "integration": "integration",
    "e2e": "ui",
    "end-to-end": "ui",
    "ui": "ui",
    "gui": "ui",
    "manual": "manual",
    "exploratory": "manual",
}


def _norm_enum(value: Any, aliases: dict[str, str] | None = None) -> Any:
    """Lower-case / alias-map loosely formatted enum values from the LLM."""
    if not isinstance(value, str):
        return value
    v = value.strip().lower()
    if aliases:
        return aliases.get(v, aliases.get(v.replace("-", " ").replace("_", " "), v))
    return v


def _as_list(value: Any) -> Any:
    """Small models sometimes emit a single string where a list is expected."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip(" -*\t") for p in re.split(r"\n|;\s*(?=\S)", value)]
        return [p for p in parts if p]
    return value


class _Lenient(BaseModel):
    # Ignore unknown keys the model may add rather than failing the request.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Input contract
# --------------------------------------------------------------------------- #


class RequirementInput(_Lenient):
    """A structured product requirement, as sent by the backend."""

    # Accepts both this contract's names and the dataset format used in
    # eval/sample_requirements.json ("id", "rules"). Output always uses the names below.
    requirement_id: str | None = Field(
        default=None,
        max_length=64,
        validation_alias=AliasChoices("requirement_id", "id"),
        description="Backend ID of the requirement, e.g. 'REQ-101'. Generated if omitted. Alias: 'id'.",
    )
    title: str | None = Field(default=None, max_length=200)
    description: str = Field(..., description="The requirement text / user story.")
    actor: str | None = Field(default=None, max_length=100, description="Primary user role, e.g. 'registered user'.")
    business_rules: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("business_rules", "rules"),
        description="Explicitly stated rules / constraints. Alias: 'rules'.",
    )
    context: str | None = Field(default=None, max_length=2000, description="Optional domain / system context.")
    priority: Priority | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def _p(cls, v: Any) -> Any:
        return _norm_enum(v)

    @field_validator("business_rules", mode="before")
    @classmethod
    def _br(cls, v: Any) -> Any:
        return _as_list(v)

    def full_text(self) -> str:
        """All requirement text concatenated - used for ambiguity scans."""
        parts = [self.title or "", self.description, *self.business_rules]
        return "\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# LLM output contract (what the model must return)
# --------------------------------------------------------------------------- #


class Ambiguity(_Lenient):
    id: str = Field(..., description="AMB-1, AMB-2, ...")
    text: str = Field(..., description="The exact phrase from the requirement that is unclear (or 'N/A' if missing info).")
    issue: str = Field(..., description="Why it is ambiguous or what is missing.")
    clarification_question: str = Field(..., description="Question to ask the product owner.")
    severity: Severity = "medium"
    source: AmbiguitySource = "llm"

    @field_validator("severity", mode="before")
    @classmethod
    def _s(cls, v: Any) -> Any:
        return _norm_enum(v)


class Assumption(_Lenient):
    id: str = Field(..., description="ASM-1, ASM-2, ...")
    statement: str
    reason: str = Field(..., description="Which ambiguity / gap this assumption fills.")


class AcceptanceCriterion(_Lenient):
    id: str = Field(..., description="AC-1, AC-2, ...")
    description: str = Field(..., description="One measurable, testable statement.")
    given: str
    when: str
    then: str
    source: CriterionSource = Field(
        "explicit", description="'explicit' if stated in the requirement, 'assumption' if derived from an assumption."
    )
    assumption_ids: list[str] = Field(default_factory=list)

    @field_validator("source", mode="before")
    @classmethod
    def _src(cls, v: Any) -> Any:
        v = _norm_enum(v)
        if isinstance(v, str) and v.startswith("assum"):
            return "assumption"
        if isinstance(v, str) and v in {"stated", "requirement", "explicitly stated"}:
            return "explicit"
        return v

    @field_validator("assumption_ids", mode="before")
    @classmethod
    def _aids(cls, v: Any) -> Any:
        return _as_list(v)


class AutomationRecommendation(_Lenient):
    automatable: bool = True
    level: AutomationLevel = Field("api", description="Lowest test level that can verify this scenario.")
    suggested_tool: str = Field("pytest", description="e.g. pytest, Playwright, Postman/Newman, JUnit.")
    rationale: str = ""

    @field_validator("level", mode="before")
    @classmethod
    def _lvl(cls, v: Any) -> Any:
        return _norm_enum(v, _LEVEL_ALIASES)


class TestScenario(_Lenient):
    __test__ = False  # stop pytest from trying to collect this class

    test_case_id: str = Field(..., description="TC-001, TC-002, ...")
    title: str
    requirement_id: str = Field(..., description="Always the input requirement ID (normalised by the pipeline).")
    acceptance_criterion_id: str = Field(..., description="ID of the AC this test verifies, e.g. AC-1.")
    test_type: TestType
    preconditions: list[str] = Field(default_factory=list)
    test_steps: list[str] = Field(..., min_length=1)
    test_data: list[str] = Field(default_factory=list)
    expected_result: str
    priority: Priority = "medium"
    automation: AutomationRecommendation = Field(default_factory=AutomationRecommendation)

    @field_validator("test_type", mode="before")
    @classmethod
    def _tt(cls, v: Any) -> Any:
        return _norm_enum(v, _TEST_TYPE_ALIASES)

    @field_validator("priority", mode="before")
    @classmethod
    def _pr(cls, v: Any) -> Any:
        return _norm_enum(v)

    @field_validator("preconditions", "test_steps", "test_data", mode="before")
    @classmethod
    def _lists(cls, v: Any) -> Any:
        return _as_list(v)


class LLMOutput(_Lenient):
    """Exactly what the model is asked to return."""

    ambiguities: list[Ambiguity] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(..., min_length=1)
    test_scenarios: list[TestScenario] = Field(..., min_length=1)
    not_applicable: list["NotApplicable"] = Field(default_factory=list)


class NotApplicable(_Lenient):
    """The model's explanation of why a test type cannot exist for a criterion
    (instead of inventing an artificial test). Only accepted for 'negative'
    tests, and only when the criterion has no constraint a test could violate."""

    acceptance_criterion_id: str
    test_type: Literal["negative"] = "negative"
    reason: str

    @field_validator("test_type", mode="before")
    @classmethod
    def _tt(cls, v: Any) -> Any:
        return _norm_enum(v, _TEST_TYPE_ALIASES)


class SupplementOutput(_Lenient):
    """Response to a targeted 'fill exactly these coverage tasks' request."""

    test_scenarios: list[TestScenario] = Field(default_factory=list)
    not_applicable: list[NotApplicable] = Field(default_factory=list)


LLMOutput.model_rebuild()


# --------------------------------------------------------------------------- #
# Final response contract (returned by the API)
# --------------------------------------------------------------------------- #


class EdgeCase(BaseModel):
    """Convenience view of boundary / edge-case scenarios for the UI."""

    test_case_id: str
    acceptance_criterion_id: str
    test_type: Literal["boundary", "edge_case"]
    description: str
    expected_result: str


CriterionStatus = Literal["validated", "partial", "untested", "needs_clarification", "assumption"]


class TraceabilityLink(BaseModel):
    requirement_id: str
    acceptance_criterion_id: str
    acceptance_criterion: str
    test_case_ids: list[str]
    test_types: list[TestType]
    covered: bool = Field(..., description="Generated coverage: at least one test is linked.")
    # --- validated coverage (added in v1.3; all fields optional for older clients) ---
    business_rules: list[str] = Field(default_factory=list, description="Explicit business rules this AC traces to.")
    has_positive: bool = False
    has_negative: bool = False
    boundary_required: bool = False
    has_boundary: bool = False
    not_applicable: list[str] = Field(default_factory=list, description="e.g. 'negative: <reason>'")
    blocked_by: list[str] = Field(default_factory=list, description="Ambiguity IDs that make this AC unmeasurable.")
    status: CriterionStatus = "untested"
    missing: list[str] = Field(default_factory=list, description="What is still needed for this AC to be validated.")


class RuleCoverage(BaseModel):
    rule: str
    acceptance_criterion_ids: list[str]
    status: CriterionStatus | Literal["missing"]


class BoundaryCoverage(BaseModel):
    limit: str
    acceptance_criterion_id: str | None
    test_case_ids: list[str]
    covered: bool


class CoverageSummary(BaseModel):
    total_acceptance_criteria: int
    covered_acceptance_criteria: int
    coverage_percent: float = Field(
        ..., description="VALIDATED coverage: validated criteria / (explicit criteria + criteria blocked by an "
                         "ambiguity). Assumption-only criteria are excluded; blocked criteria are never validated."
    )
    scenarios_by_type: dict[str, int]
    # --- added in v1.3 ---
    generated_coverage_percent: float = Field(0.0, description="Share of criteria with at least one linked test.")
    validated_acceptance_criteria: int = 0
    blocked_acceptance_criteria: int = Field(0, description="Criteria blocked by an unresolved ambiguity (never validated).")
    assumption_criteria: int = Field(0, description="Criteria based on assumptions (not counted as requirements).")
    rule_coverage_percent: float | None = Field(None, description="Share of business rules whose criteria are validated.")
    rule_coverage: list[RuleCoverage] = Field(default_factory=list)
    boundary_coverage: list[BoundaryCoverage] = Field(default_factory=list)
    invalid_references: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, description="Remaining coverage gaps, one sentence each.")


class AutomationSummary(BaseModel):
    automatable_count: int
    manual_count: int
    by_level: dict[str, int]
    suggested_tools: list[str]
    recommendation: str


class GenerationMetadata(BaseModel):
    model: str
    prompt_version: str
    attempts: int
    duration_ms: int
    warnings: list[str] = Field(default_factory=list)


class GenerationResult(BaseModel):
    requirement_id: str
    title: str | None = None
    original_requirement: str
    needs_clarification: bool = Field(
        ..., description="True if any high-severity ambiguity was found or a criterion is blocked by one.")
    ambiguities: list[Ambiguity]
    assumptions: list[Assumption]
    acceptance_criteria: list[AcceptanceCriterion]
    test_scenarios: list[TestScenario]
    edge_cases: list[EdgeCase]
    traceability: list[TraceabilityLink]
    coverage: CoverageSummary
    automation_recommendations: AutomationSummary
    metadata: GenerationMetadata


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: list[str] = Field(default_factory=list)
