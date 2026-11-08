import pytest
from schemas import AcceptanceCriterion, Requirement, Scenario
from traceability import build_traceability_matrix, calculate_coverage_summary


@pytest.fixture
def sample_requirement():
    return Requirement(
        id="REQ-TC-001",
        title="Missed punch detection",
        description="Detect shifts with clock-in and no clock-out.",
        actor="Employee",
        rules=[
            "A shift with clock-in and no clock-out after 16 hours is flagged.",
            "Flagged shift is shown to manager for review.",
            "Employee can submit correction request.",
        ],
    )


def test_full_traceability_coverage(sample_requirement):
    criteria = [
        AcceptanceCriterion(
            id="AC-1", clause_ref=0, given="Shift open", when="16 hrs pass", then="Flagged"
        ),
        AcceptanceCriterion(
            id="AC-2", clause_ref=1, given="Shift flagged", when="Manager views", then="Visible"
        ),
        AcceptanceCriterion(
            id="AC-3", clause_ref=2, given="Shift flagged", when="Employee edits", then="Submitted"
        ),
    ]

    scenarios = [
        Scenario(
            id="TS-1",
            title="Auto-flag test",
            criterion_ids=["AC-1"],
            steps=["Clock in", "Wait 16h"],
            expected_result="Flagged",
        ),
        Scenario(
            id="TS-2",
            title="Manager & employee actions",
            criterion_ids=["AC-2", "AC-3"],
            steps=["View dashboard", "Submit edit"],
            expected_result="Corrected",
        ),
    ]

    matrix = build_traceability_matrix(sample_requirement, criteria, scenarios)

    assert len(matrix) == 3
    assert all(row.covered for row in matrix)
    assert matrix[0].criterion_ids == ["AC-1"]
    assert matrix[0].scenario_ids == ["TS-1"]
    assert matrix[1].criterion_ids == ["AC-2"]
    assert matrix[1].scenario_ids == ["TS-2"]
    assert matrix[2].criterion_ids == ["AC-3"]
    assert matrix[2].scenario_ids == ["TS-2"]

    summary = calculate_coverage_summary(matrix)
    assert summary["coverage_percentage"] == 100.0
    assert summary["covered_clauses"] == 3
    assert summary["uncovered_clauses"] == 0


def test_partial_coverage_missing_scenario(sample_requirement):
    # Clause 0 has criterion and scenario -> covered
    # Clause 1 has criterion but NO scenario -> not covered
    # Clause 2 has neither -> not covered
    criteria = [
        AcceptanceCriterion(
            id="AC-1", clause_ref=0, given="G", when="W", then="T"
        ),
        AcceptanceCriterion(
            id="AC-2", clause_ref=1, given="G", when="W", then="T"
        ),
    ]
    scenarios = [
        Scenario(
            id="TS-1",
            title="Test for AC-1 only",
            criterion_ids=["AC-1"],
            steps=["Do something"],
            expected_result="Result",
        )
    ]

    matrix = build_traceability_matrix(sample_requirement, criteria, scenarios)

    assert len(matrix) == 3
    assert matrix[0].covered is True
    assert matrix[1].covered is False  # Criterion exists, but no scenario
    assert matrix[2].covered is False  # No criterion, no scenario

    summary = calculate_coverage_summary(matrix)
    assert summary["covered_clauses"] == 1
    assert summary["uncovered_clauses"] == 2
    assert summary["coverage_percentage"] == pytest.approx(33.33, rel=1e-2)


def test_empty_rules_requirement():
    req = Requirement(
        id="REQ-EMPTY",
        title="Empty rules",
        description="No rules specified",
        actor="System",
        rules=[],
    )

    matrix = build_traceability_matrix(req, [], [])
    assert matrix == []

    summary = calculate_coverage_summary(matrix)
    assert summary["coverage_percentage"] == 100.0
    assert summary["total_clauses"] == 0

