"""Stage 4 - JSON parsing with recovery.

Small local models sometimes wrap JSON in markdown fences, add commentary,
leave trailing commas, or nest the object under an extra key. We repair the
common, *safe* cases here; anything else raises ``OutputParseError`` so the
pipeline can retry with a correction prompt.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import EmptyResponseError, OutputParseError

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_EXPECTED_KEYS = {"acceptance_criteria", "test_scenarios"}


def _extract_balanced_object(text: str) -> str | None:
    """Return the first complete top-level {...} block, respecting strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth, in_str, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None  # unbalanced -> probably truncated


def _unwrap(obj: Any) -> Any:
    """Handle ``{"result": {...}}`` / ``{"output": {...}}`` style wrapping."""
    if isinstance(obj, dict) and not (_EXPECTED_KEYS & obj.keys()) and len(obj) == 1:
        inner = next(iter(obj.values()))
        if isinstance(inner, dict) and (_EXPECTED_KEYS & inner.keys()):
            return inner
    return obj


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Parse model output into a dict, applying safe repairs."""
    if raw is None or not raw.strip():
        raise EmptyResponseError("The model returned an empty response")

    candidates: list[str] = [raw.strip()]
    fence = _FENCE_RE.search(raw)
    if fence:
        candidates.append(fence.group(1).strip())
    block = _extract_balanced_object(raw)
    if block:
        candidates.append(block)

    last_err: Exception | None = None
    for cand in candidates:
        for variant in (cand, _TRAILING_COMMA_RE.sub(r"\1", cand)):
            try:
                obj = _unwrap(json.loads(variant))
            except json.JSONDecodeError as exc:
                last_err = exc
                continue
            if not isinstance(obj, dict):
                last_err = ValueError(f"top-level JSON must be an object, got {type(obj).__name__}")
                continue
            return obj

    hint = "output appears truncated (unbalanced braces)" if raw.count("{") > raw.count("}") else str(last_err)
    raise OutputParseError("Model output is not valid JSON", details=[hint])


def salvage_truncated_json(raw: str) -> dict[str, Any]:
    """Recover the complete part of output that was cut off at the token limit.

    Finds the last point where a *whole* item of a top-level array (e.g. one
    complete test scenario) has just been closed, cuts there, and closes the
    open brackets. Partially written items are dropped, never half-kept, so the
    result still passes schema validation.
    """
    start = raw.find("{")
    if start == -1:
        raise OutputParseError("Model output is not valid JSON", details=["no JSON object found"])

    stack: list[str] = []
    cut_points: list[int] = []  # indices just after a complete top-level array item
    in_str = escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            if stack == ["{", "["]:  # closed one item of an array directly under the root
                cut_points.append(i + 1)

    for cut in reversed(cut_points[-50:]):
        try:
            obj = _unwrap(json.loads(raw[start:cut] + "]}"))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise OutputParseError("Model output was truncated and could not be salvaged",
                           details=["output appears truncated (unbalanced braces)"])
