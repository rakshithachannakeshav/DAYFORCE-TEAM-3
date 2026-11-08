"""Exception hierarchy for the generation pipeline.

The API layer maps these to HTTP status codes (see api.py), so the backend
and frontend get a predictable error shape.
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base class for every error raised by the pipeline."""

    code: str = "pipeline_error"

    def __init__(self, message: str, *, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class InvalidRequirementError(PipelineError):
    """The input requirement is empty, too short, or otherwise unusable."""

    code = "invalid_requirement"


class LLMError(PipelineError):
    """Base class for problems talking to / getting output from the LLM."""

    code = "llm_error"


class LLMUnavailableError(LLMError):
    """Ollama is not running, unreachable, or the model is not pulled."""

    code = "llm_unavailable"


class LLMTimeoutError(LLMError):
    """The LLM did not respond within the configured timeout."""

    code = "llm_timeout"


class EmptyResponseError(LLMError):
    """The LLM returned an empty or whitespace-only response."""

    code = "empty_response"


class OutputParseError(LLMError):
    """The LLM response could not be parsed as JSON, even after recovery."""

    code = "invalid_json"


class OutputValidationError(LLMError):
    """The JSON parsed but violates the schema or traceability rules."""

    code = "schema_validation_failed"


class GenerationFailedError(PipelineError):
    """All attempts were exhausted without a valid result."""

    code = "generation_failed"

    def __init__(self, message: str, *, attempts: int, details: list[str] | None = None):
        super().__init__(message, details=details)
        self.attempts = attempts
