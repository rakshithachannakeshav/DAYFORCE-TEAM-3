"""FastAPI integration.

The backend team mounts this router into their app:

    from llm_pipeline.api import router as llm_router
    app.include_router(llm_router)

Or calls the pipeline directly from their own route/service:

    from llm_pipeline import GenerationPipeline, RequirementInput
    result = await GenerationPipeline().generate(RequirementInput(...))
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .errors import (
    GenerationFailedError,
    InvalidRequirementError,
    LLMTimeoutError,
    LLMUnavailableError,
    PipelineError,
)
from .pipeline import GenerationPipeline
from .schemas import ErrorResponse, GenerationResult, RequirementInput

router = APIRouter(prefix="/api/llm", tags=["llm-pipeline"])

_STATUS = {
    InvalidRequirementError: 422,
    LLMUnavailableError: 503,
    LLMTimeoutError: 504,
    GenerationFailedError: 502,
}


@lru_cache(maxsize=1)
def get_pipeline() -> GenerationPipeline:
    """Dependency - override in tests with app.dependency_overrides[get_pipeline]."""
    return GenerationPipeline()


def _error(exc: PipelineError) -> JSONResponse:
    """Convert a pipeline error to its HTTP status and JSON error body."""
    status = next((code for cls, code in _STATUS.items() if isinstance(exc, cls)), 500)
    body = ErrorResponse(error=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(status_code=status, content=body.model_dump())


@router.post(
    "/generate",
    response_model=GenerationResult,
    responses={422: {"model": ErrorResponse}, 502: {"model": ErrorResponse},
               503: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
    summary="Generate acceptance criteria, test scenarios and traceability for one requirement",
)
async def generate(req: RequirementInput, pipeline: GenerationPipeline = Depends(get_pipeline)):
    """Generate acceptance criteria, tests, ambiguities and traceability for one requirement."""
    try:
        return await pipeline.generate(req)
    except PipelineError as exc:
        return _error(exc)


@router.get("/health", summary="Check that Ollama is reachable and the model is pulled")
async def health(pipeline: GenerationPipeline = Depends(get_pipeline)):
    """Report whether Ollama and the model are available, and the retry and timeout settings."""
    info = await pipeline.client.health()
    info["max_attempts"] = pipeline.settings.max_attempts
    info["timeout_seconds"] = pipeline.settings.request_timeout_s
    return info
