"""Runtime configuration for the LLM pipeline.

All settings can be overridden with environment variables so the backend
team can tune the pipeline without touching code, e.g.:

    export OLLAMA_MODEL=llama3.2:3b
    export LLM_MAX_RETRIES=3
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, using the default if it is missing or invalid."""
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float environment variable, using the default if it is missing or invalid."""
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable. Only 1, true, yes and on count as true."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMSettings:
    """Pipeline settings. Each one can be overridden by an environment variable."""
    # Ollama server + model
    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST_URL", "http://localhost:11434"))
    # qwen2.5:3b (~1.9 GB) is small enough for an 8 GB M1 MacBook Air and is
    # strong at following JSON instructions. llama3.2:3b is a good alternative.
    model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen2.5:3b"))

    # Sampling: low temperature => more deterministic, schema-following output.
    temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.2))
    num_ctx: int = field(default_factory=lambda: _env_int("LLM_NUM_CTX", 8192))
    num_predict: int = field(default_factory=lambda: _env_int("LLM_NUM_PREDICT", 4096))

    # Reliability
    # A 3B model on an M1 Air writes ~24 tokens/s, so a full 4096-token answer
    # takes ~175 s. The timeout must be comfortably above that.
    request_timeout_s: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT_SECONDS", 300.0))
    max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 2))  # 2 retries => 3 attempts
    # Targeted "fill these coverage gaps" requests after a usable draft exists.
    # Each is small (a few tests), so ~20-40 s on an M1 Air.
    max_supplement_rounds: int = field(default_factory=lambda: _env_int("LLM_MAX_SUPPLEMENT_ROUNDS", 3))

    # If true, send the full JSON schema to Ollama's `format` field
    # (constrained decoding, Ollama >= 0.5). If false, send `format: "json"`.
    use_json_schema_format: bool = field(default_factory=lambda: _env_bool("LLM_USE_JSON_SCHEMA", True))

    # How long Ollama keeps the model loaded in memory after a request.
    keep_alive: str = field(default_factory=lambda: os.getenv("OLLAMA_KEEP_ALIVE", "10m"))

    @property
    def max_attempts(self) -> int:
        """Total generation attempts: the first try plus the retries, and at least one."""
        return max(1, self.max_retries + 1)


def get_settings() -> LLMSettings:
    """Build the settings from the current environment."""
    return LLMSettings()
