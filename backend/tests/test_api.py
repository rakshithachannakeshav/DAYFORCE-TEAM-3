"""Tests for the baseline API routes."""
from fastapi.testclient import TestClient
from main import app
from schemas import GenerationResult, Requirement

client = TestClient(app)


def test_health_check_returns_200():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data


def test_get_samples_returns_requirements():
    response = client.get("/api/samples")
    assert response.status_code == 200
    samples = response.json()
    assert isinstance(samples, list)
    assert len(samples) > 0

    # Ensure each sample adheres to the Requirement model
    for item in samples:
        req = Requirement(**item)
        assert req.id.startswith("REQ-")
        assert len(req.rules) > 0


def test_validate_requirement_endpoint():
    payload = {
        "id": "REQ-VAL-001",
        "title": "Validate endpoint test",
        "description": "Checking validate endpoint behavior",
        "actor": "Admin",
        "rules": ["Rule A", "Rule B"],
        "priority": "high",
    }
    response = client.post("/api/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["requirement_id"] == "REQ-VAL-001"
    assert data["rule_count"] == 2


def test_validate_requirement_rejects_missing_fields():
    # Missing required 'actor' and 'id'
    invalid_payload = {
        "title": "Incomplete requirement",
        "description": "Missing required fields",
    }
    response = client.post("/api/validate", json=invalid_payload)
    assert response.status_code == 422


def test_generate_and_retrieve_history():
    payload = {
        "id": "REQ-HIST-001",
        "title": "Historical Run Test",
        "description": "Verifying persistence in SQLite",
        "actor": "Manager",
        "rules": [
            "Rule 1 for history test",
            "Rule 2 for history test",
        ],
        "priority": "medium",
    }
    gen_response = client.post("/api/generate", json=payload)
    assert gen_response.status_code == 200
    gen_data = gen_response.json()
    result = GenerationResult(**gen_data)
    assert result.requirement_id == "REQ-HIST-001"

    # Query history list
    hist_response = client.get("/api/history?limit=10")
    assert hist_response.status_code == 200
    history_items = hist_response.json()
    assert len(history_items) > 0

    latest_run = history_items[0]
    assert latest_run["requirement_id"] == "REQ-HIST-001"
    assert latest_run["requirement_title"] == "Historical Run Test"
    run_id = latest_run["run_id"]

    # Query specific run by ID
    run_response = client.get(f"/api/history/{run_id}")
    assert run_response.status_code == 200
    retrieved_result = GenerationResult(**run_response.json())
    assert retrieved_result.requirement_id == "REQ-HIST-001"
    assert len(retrieved_result.criteria) == 2


def test_get_nonexistent_history_run_returns_404():
    response = client.get("/api/history/999999")
    assert response.status_code == 404


def test_llm_pipeline_routes_are_mounted():
    paths = app.openapi()["paths"]
    assert "/api/llm/generate" in paths
    assert "/api/llm/health" in paths
