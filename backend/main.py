import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Ensure backend directory is in sys.path regardless of where uvicorn is launched
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db import (
    get_generation_history,
    get_generation_run,
    init_db,
    save_generation_run,
    save_requirement,
)
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from generator import generate_baseline_test_suite
from schemas import GenerationResult, Requirement

SAMPLE_REQUIREMENTS_PATH = (
    Path(__file__).resolve().parent.parent / "eval" / "sample_requirements.json"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database tables exist at application startup
    init_db()
    yield


# Ensure database tables exist at import/startup
init_db()

app = FastAPI(
    title="Requirements-to-Test Assistant API",
    description="API for converting product requirements into acceptance criteria, scenarios, edge cases, and traceability matrices.",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow React frontend (running locally on Vite or standard React ports) to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check():
    """Health check endpoint to verify backend service status."""
    return {
        "status": "ok",
        "service": "Requirements-to-Test Assistant API",
    }


@app.get("/api/samples", response_model=list[Requirement])
def get_sample_requirements():
    """Returns sample requirements from the evaluation dataset for frontend testing."""
    if not SAMPLE_REQUIREMENTS_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="Sample requirements file not found.",
        )

    try:
        data = json.loads(SAMPLE_REQUIREMENTS_PATH.read_text(encoding="utf-8"))
        samples = []
        for item in data:
            item_clean = {k: v for k, v in item.items() if k != "intentionally_ambiguous"}
            samples.append(Requirement(**item_clean))
        return samples
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load sample requirements: {exc}",
        ) from exc


@app.post("/api/validate")
def validate_requirement(requirement: Requirement):
    """Validates a product requirement against the schema contract."""
    return {
        "valid": True,
        "requirement_id": requirement.id,
        "rule_count": len(requirement.rules),
    }


@app.post("/api/generate", response_model=GenerationResult)
def generate_tests(requirement: Requirement):
    """Generates criteria, edge cases, scenarios, and a traceability matrix for a requirement."""
    # Persist input requirement in SQLite
    save_requirement(requirement)

    # Generate test suite with deterministic traceability
    result = generate_baseline_test_suite(requirement)

    # Persist generated run in SQLite
    save_generation_run(result)

    return result


@app.get("/api/history", response_model=list[dict[str, Any]])
def list_history(limit: int = Query(default=20, ge=1, le=100)):
    """Retrieves summaries of previous test generation runs."""
    return get_generation_history(limit=limit)


@app.get("/api/history/{run_id}", response_model=GenerationResult)
def get_history_run(run_id: int):
    """Retrieves the full GenerationResult of a specific historical run."""
    run = get_generation_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=f"Generation run #{run_id} not found.",
        )
    return run
