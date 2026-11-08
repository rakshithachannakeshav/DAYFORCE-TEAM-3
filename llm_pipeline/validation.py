"""Stage 1 - Requirement validation (runs BEFORE calling the LLM).

Rejects input that cannot produce meaningful tests, so we never waste an
expensive LLM call on empty or garbage text. Merely *incomplete* requirements
are NOT rejected here - they pass through and are flagged by ambiguity
detection instead.
"""

from __future__ import annotations

import hashlib
import re

from .errors import InvalidRequirementError
from .schemas import RequirementInput

MIN_CHARS = 15
MIN_WORDS = 4
MAX_CHARS = 6000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def make_requirement_id(req: RequirementInput) -> str:
    """Deterministic fallback ID so the same text always gets the same ID."""
    digest = hashlib.sha1(req.full_text().encode("utf-8")).hexdigest()[:6].upper()
    return f"REQ-{digest}"


def validate_requirement(req: RequirementInput) -> RequirementInput:
    """Return a normalised copy of ``req`` or raise ``InvalidRequirementError``."""
    problems: list[str] = []
    text = (req.description or "").strip()

    if not text:
        problems.append("description is empty")
    else:
        if len(text) < MIN_CHARS:
            problems.append(f"description is too short ({len(text)} chars, minimum {MIN_CHARS})")
        words = re.findall(r"[A-Za-z]{2,}", text)
        if len(words) < MIN_WORDS:
            problems.append(f"description must contain at least {MIN_WORDS} real words")
        letters = sum(c.isalpha() for c in text)
        if letters / max(len(text), 1) < 0.5:
            problems.append("description does not look like natural-language text")

    if len(req.full_text()) > MAX_CHARS:
        problems.append(f"requirement is too long (max {MAX_CHARS} chars); split it into smaller requirements")

    if req.requirement_id and not _ID_RE.match(req.requirement_id):
        problems.append("requirement_id may only contain letters, digits, '-', '_' and '.'")

    if problems:
        raise InvalidRequirementError("Requirement failed validation", details=problems)

    rules = [r.strip() for r in req.business_rules if r and r.strip()]
    normalised = req.model_copy(update={"description": text, "business_rules": rules})
    if not normalised.requirement_id:
        normalised = normalised.model_copy(update={"requirement_id": make_requirement_id(normalised)})
    return normalised
