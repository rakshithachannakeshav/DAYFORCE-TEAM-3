import pytest
from pydantic import ValidationError
from schemas import GenerationResult, Requirement, Scenario


def test_requirement_accepts_valid_input():
    req = Requirement(
        id="REQ-1",
        title="Example",
        description="Example requirement",
        actor="Employee",
        rules=["Rule one"],
    )
    assert req.priority.value == "medium"


def test_scenario_requires_at_least_one_criterion():
    with pytest.raises(ValidationError):
        Scenario(
            id="TS-1",
            title="No criteria",
            criterion_ids=[],
            steps=["do something"],
            expected_result="something happens",
        )


def test_generation_result_minimal():
    result = GenerationResult(
        requirement_id="REQ-1",
        criteria=[],
        edge_cases=[],
        scenarios=[],
        automation=[],
        traceability=[],
        model_name="test-model",
    )
    assert result.schema_valid_on_first_try is True
