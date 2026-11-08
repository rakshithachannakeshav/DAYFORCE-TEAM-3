"""Unit tests for parsing, ambiguity detection, the Ollama client and the API."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import VALID_OUTPUT, make_pipeline, run
from llm_pipeline.ambiguity import detect_ambiguities, extract_boundaries
from llm_pipeline.api import get_pipeline, router
from llm_pipeline.config import LLMSettings
from llm_pipeline.errors import EmptyResponseError, LLMTimeoutError, LLMUnavailableError, OutputParseError
from llm_pipeline.llm_client import ChatMessage, OllamaClient
from llm_pipeline.parsing import parse_llm_json
from llm_pipeline.pipeline import LLM_OUTPUT_JSON_SCHEMA
from llm_pipeline.schemas import RequirementInput


# --- parsing ----------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1, "acceptance_criteria": []}',
        '```json\n{"a": 1, "acceptance_criteria": []}\n```',
        'Here it is: {"a": 1, "acceptance_criteria": [],} thanks',
        '{"result": {"acceptance_criteria": [], "test_scenarios": []}}',
        '{"a": "brace } inside string", "acceptance_criteria": []}',
    ],
)
def test_parse_recovers_common_problems(raw):
    assert "acceptance_criteria" in parse_llm_json(raw)


def test_parse_rejects_garbage_and_truncation():
    with pytest.raises(OutputParseError):
        parse_llm_json("no json here")
    with pytest.raises(OutputParseError) as exc:
        parse_llm_json('{"acceptance_criteria": [{"id": "AC-1"')
    assert "truncated" in exc.value.details[0]
    with pytest.raises(OutputParseError):
        parse_llm_json("[1, 2, 3]")
    with pytest.raises(EmptyResponseError):
        parse_llm_json("")


# --- ambiguity / boundaries ---------------------------------------------------
def test_clear_requirement_has_few_rule_ambiguities():
    req = RequirementInput(
        actor="registered user",
        description="A registered user must be able to log in with email and password and is redirected to the dashboard.",
        business_rules=["The account is locked after 5 failed attempts within 15 minutes."],
    )
    assert [a for a in detect_ambiguities(req) if a.severity == "high"] == []


def test_ambiguity_rules():
    req = RequirementInput(description="The page could load quickly and show reports, charts etc. TBD for admins and/or managers.")
    issues = " ".join(a.issue for a in detect_ambiguities(req))
    assert "quickly" in issues
    assert "Open-ended list" in issues
    assert "placeholder" in issues
    assert "and/or" in issues
    assert "Weak modal" in issues


def test_extract_boundaries():
    req = RequirementInput(
        description="Usernames must be between 3 and 20 characters.",
        business_rules=["Upload at most 10 MB", "Lock after 5 attempts", "Minimum age of 18"],
    )
    found = " | ".join(extract_boundaries(req)).lower()
    assert "between 3 and 20" in found
    assert "at most 10" in found
    assert "5 attempts" in found
    assert "minimum age of 18" in found
    assert extract_boundaries(RequirementInput(description="Users can log out from any page.")) == []


# --- Ollama client (HTTP mocked with httpx.MockTransport) -----------------------
def _ollama(handler) -> OllamaClient:
    return OllamaClient(LLMSettings(model="qwen2.5:3b"), transport=httpx.MockTransport(handler))


def test_ollama_client_sends_schema_and_parses_reply():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"x":1}'}, "done": True,
                                         "done_reason": "stop"})

    resp = run(_ollama(handler).chat([ChatMessage("user", "hi")], json_schema=LLM_OUTPUT_JSON_SCHEMA))
    assert resp.content == '{"x":1}' and resp.truncated is False
    assert seen["model"] == "qwen2.5:3b" and seen["stream"] is False
    assert seen["format"]["type"] == "object" and "$defs" not in json.dumps(seen["format"])
    assert seen["options"]["temperature"] == 0.2


def test_ollama_client_errors():
    def empty(_):
        return httpx.Response(200, json={"message": {"content": ""}, "done": True})

    def missing_model(_):
        return httpx.Response(404, json={"error": "model not found"})

    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    msgs = [ChatMessage("user", "hi")]
    with pytest.raises(EmptyResponseError):
        run(_ollama(empty).chat(msgs))
    with pytest.raises(LLMUnavailableError, match="ollama pull"):
        run(_ollama(missing_model).chat(msgs))
    with pytest.raises(LLMTimeoutError):
        run(_ollama(timeout).chat(msgs))
    with pytest.raises(LLMUnavailableError, match="ollama serve"):
        run(_ollama(refused).chat(msgs))


def test_ollama_truncation_flag():
    def handler(_):
        return httpx.Response(200, json={"message": {"content": '{"a":'}, "done": True, "done_reason": "length"})

    assert run(_ollama(handler).chat([ChatMessage("user", "hi")])).truncated is True


def test_ollama_health():
    def handler(_):
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]})

    info = run(_ollama(handler).health())
    assert info["ollama_reachable"] and info["model_available"]


# --- FastAPI router -------------------------------------------------------------
def _api(script):
    pipeline, _ = make_pipeline(script)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    return TestClient(app)


def test_api_generate_success(password_requirement):
    body = password_requirement.model_dump(exclude_none=True)
    r = _api([VALID_OUTPUT]).post("/api/llm/generate", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ["requirement_id", "original_requirement", "ambiguities", "assumptions", "acceptance_criteria",
                "test_scenarios", "edge_cases", "traceability", "coverage", "automation_recommendations", "metadata"]:
        assert key in data
    assert data["requirement_id"] == "REQ-101"


def test_api_error_mapping():
    assert _api([]).post("/api/llm/generate", json={"description": "hi"}).status_code == 422
    r = _api(["bad", "bad", "bad"]).post("/api/llm/generate", json={"description": "Users can reset their password by email."})
    assert r.status_code == 502 and r.json()["error"] == "generation_failed"
    r = _api([LLMUnavailableError("down")]).post("/api/llm/generate", json={"description": "Users can reset their password by email."})
    assert r.status_code == 503 and r.json()["error"] == "llm_unavailable"


def test_api_health():
    r = _api([]).get("/api/llm/health")
    assert r.status_code == 200 and r.json()["max_attempts"] == 3
