"""Shared contract for the Requirements-to-Test Assistant.

Agree on this file as a team first. Backend validates against it, the frontend
mirrors it, the LLM prompts target it, and the eval scripts score against it.
"""
from enum import Enum

from pydantic import BaseModel, Field


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Requirement(BaseModel):
    id: str = Field(..., examples=["REQ-TC-014"])
    title: str
    description: str
    actor: str = Field(..., examples=["Employee", "Manager", "Payroll admin"])
    rules: list[str] = Field(
        default_factory=list,
        description="Atomic rule clauses. Each clause must be covered by at least one criterion.",
    )
    priority: Priority = Priority.medium


class AcceptanceCriterion(BaseModel):
    id: str = Field(..., examples=["AC-1"])
    clause_ref: int = Field(..., description="Index into Requirement.rules this criterion covers")
    given: str
    when: str
    then: str


class EdgeCaseCategory(str, Enum):
    boundary = "boundary"
    null_or_empty = "null_or_empty"
    permission = "permission"
    duplicate = "duplicate"
    concurrency = "concurrency"
    timezone_or_date = "timezone_or_date"
    invalid_input = "invalid_input"
    other = "other"


class EdgeCase(BaseModel):
    id: str
    category: EdgeCaseCategory
    description: str
    clause_ref: int | None = None


class Scenario(BaseModel):
    id: str = Field(..., examples=["TS-1"])
    title: str
    criterion_ids: list[str] = Field(..., min_length=1)
    edge_case_ids: list[str] = Field(default_factory=list)
    steps: list[str]
    expected_result: str


class AutomationRecommendation(BaseModel):
    scenario_id: str
    level: str = Field(..., pattern="^(unit|integration|api_contract|e2e)$")
    rationale: str
    code_stub: str | None = Field(None, description="pytest or Jest skeleton")


class ClarifyingQuestion(BaseModel):
    clause_ref: int | None = None
    question: str


class TraceabilityRow(BaseModel):
    requirement_id: str
    clause_ref: int
    criterion_ids: list[str]
    scenario_ids: list[str]
    covered: bool


class GenerationResult(BaseModel):
    requirement_id: str
    criteria: list[AcceptanceCriterion]
    edge_cases: list[EdgeCase]
    scenarios: list[Scenario]
    automation: list[AutomationRecommendation]
    clarifying_questions: list[ClarifyingQuestion] = Field(
        default_factory=list,
        description="Filled when the requirement is ambiguous instead of inventing rules.",
    )
    traceability: list[TraceabilityRow]
    model_name: str
    schema_valid_on_first_try: bool = True
