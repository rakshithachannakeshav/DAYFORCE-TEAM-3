"""Traceability Matrix Engine.

Computes and validates test coverage across atomic requirement rules,
acceptance criteria, and test scenarios.
"""
from schemas import AcceptanceCriterion, Requirement, Scenario, TraceabilityRow


def build_traceability_matrix(
    requirement: Requirement,
    criteria: list[AcceptanceCriterion],
    scenarios: list[Scenario],
) -> list[TraceabilityRow]:
    """Builds a deterministic traceability matrix for a requirement.

    For every atomic rule in requirement.rules (by index clause_ref):
    - Identifies all criteria that reference this clause_ref.
    - Identifies all scenarios that reference any of those criteria.
    - Marks covered=True only if there is at least one criterion AND at least one scenario.
    """
    rows: list[TraceabilityRow] = []

    # Group criterion IDs by the rule clause they cover
    criteria_by_clause: dict[int, list[str]] = {}
    for criterion in criteria:
        criteria_by_clause.setdefault(criterion.clause_ref, []).append(criterion.id)

    for clause_idx in range(len(requirement.rules)):
        criterion_ids = sorted(set(criteria_by_clause.get(clause_idx, [])))

        # Find scenarios that mention any of these criterion IDs
        scenario_ids = sorted(
            {
                scenario.id
                for scenario in scenarios
                if any(cid in scenario.criterion_ids for cid in criterion_ids)
            }
        )

        covered = len(criterion_ids) > 0 and len(scenario_ids) > 0

        rows.append(
            TraceabilityRow(
                requirement_id=requirement.id,
                clause_ref=clause_idx,
                criterion_ids=criterion_ids,
                scenario_ids=scenario_ids,
                covered=covered,
            )
        )

    return rows


def calculate_coverage_summary(rows: list[TraceabilityRow]) -> dict:
    """Calculates summary coverage metrics for the traceability matrix."""
    total_clauses = len(rows)
    if total_clauses == 0:
        return {
            "total_clauses": 0,
            "covered_clauses": 0,
            "uncovered_clauses": 0,
            "coverage_percentage": 100.0,
        }

    covered_count = sum(1 for row in rows if row.covered)
    uncovered_count = total_clauses - covered_count
    coverage_percentage = round((covered_count / total_clauses) * 100.0, 2)

    return {
        "total_clauses": total_clauses,
        "covered_clauses": covered_count,
        "uncovered_clauses": uncovered_count,
        "coverage_percentage": coverage_percentage,
    }
