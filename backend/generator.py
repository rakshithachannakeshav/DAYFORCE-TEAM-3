"""Generation service interface.

Provides test suite generation and contract enforcement. Includes a baseline
generator so backend, frontend, and CI workflows can run deterministically
before or alongside the Ollama LLM integration.
"""
from schemas import (
    AcceptanceCriterion,
    AutomationRecommendation,
    EdgeCase,
    EdgeCaseCategory,
    GenerationResult,
    Requirement,
    Scenario,
)
from traceability import build_traceability_matrix


def generate_baseline_test_suite(
    requirement: Requirement,
    model_name: str = "baseline-rule-mapper-v1",
) -> GenerationResult:
    """Generates criteria, scenarios, edge cases, and traceability for a requirement.

    This ensures every atomic rule clause in the requirement receives at least one
    acceptance criterion and scenario, resulting in 100% initial traceability coverage.
    """
    criteria: list[AcceptanceCriterion] = []
    edge_cases: list[EdgeCase] = []
    scenarios: list[Scenario] = []
    automation: list[AutomationRecommendation] = []

    for idx, rule in enumerate(requirement.rules):
        criterion_id = f"AC-{idx + 1}"
        edge_case_id = f"EC-{idx + 1}"
        scenario_id = f"TS-{idx + 1}"

        # 1. Acceptance Criterion
        criteria.append(
            AcceptanceCriterion(
                id=criterion_id,
                clause_ref=idx,
                given=f"Given an actor '{requirement.actor}' with valid system access",
                when=f"When action governed by rule '{rule}' is executed",
                then="Then the expected business outcome is enforced according to specification",
            )
        )

        # 2. Edge Case
        edge_cases.append(
            EdgeCase(
                id=edge_case_id,
                category=EdgeCaseCategory.boundary,
                description=f"Boundary/null test for rule: {rule}",
                clause_ref=idx,
            )
        )

        # 3. Test Scenario
        scenarios.append(
            Scenario(
                id=scenario_id,
                title=f"Verify rule #{idx + 1}: {rule[:60]}...",
                criterion_ids=[criterion_id],
                edge_case_ids=[edge_case_id],
                steps=[
                    f"1. Setup state for {requirement.actor}",
                    f"2. Execute trigger corresponding to rule: {rule}",
                    "3. Validate resulting system state and response",
                ],
                expected_result="Operation completes adhering to business rules and constraints.",
            )
        )

        # 4. Automation Recommendation
        automation.append(
            AutomationRecommendation(
                scenario_id=scenario_id,
                level="unit" if idx % 2 == 0 else "integration",
                rationale=f"Automate rule {idx + 1} at unit/integration boundary for fast regression feedback.",
                code_stub=f"""def test_rule_{idx + 1}_{requirement.id.lower().replace('-', '_')}():
    # Setup test actor: {requirement.actor}
    # Trigger rule: {rule}
    assert True
""",
            )
        )

    # 5. Deterministic Traceability Matrix
    traceability_matrix = build_traceability_matrix(requirement, criteria, scenarios)

    return GenerationResult(
        requirement_id=requirement.id,
        criteria=criteria,
        edge_cases=edge_cases,
        scenarios=scenarios,
        automation=automation,
        clarifying_questions=[],
        traceability=traceability_matrix,
        model_name=model_name,
        schema_valid_on_first_try=True,
    )

