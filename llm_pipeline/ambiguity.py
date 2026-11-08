"""Stage 2 - Rule-based ambiguity detection.

Why rules *and* the LLM?
* Rules are deterministic, instant, and never hallucinate - they reliably
  catch classic requirement smells (vague adjectives, "etc.", "TBD", ...).
* The LLM catches semantic gaps rules can't see (e.g. "what happens to
  existing sessions after a password reset?").

The rule findings are (1) sent to the LLM as hints and (2) merged with the
LLM's own findings in the final response, de-duplicated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import Ambiguity, RequirementInput


@dataclass(frozen=True)
class _Rule:
    pattern: str
    issue: str
    question: str
    severity: str


# Vague / unmeasurable words -> not testable without a number or definition.
_VAGUE_TERMS: dict[str, tuple[str, str]] = {
    "fast": ("high", "What is the maximum acceptable response time (e.g. in ms/seconds)?"),
    "quick": ("high", "What exact time limit defines 'quick'?"),
    "quickly": ("high", "What exact time limit defines 'quickly'?"),
    "slow": ("medium", "What threshold defines 'slow'?"),
    "responsive": ("medium", "What response-time target defines 'responsive'?"),
    "user-friendly": ("medium", "What measurable usability criteria apply?"),
    "user friendly": ("medium", "What measurable usability criteria apply?"),
    "easy": ("medium", "How will 'easy' be measured (steps, time, success rate)?"),
    "easily": ("medium", "How will 'easily' be measured?"),
    "simple": ("low", "What makes the behaviour 'simple' in measurable terms?"),
    "intuitive": ("medium", "What measurable usability criteria define 'intuitive'?"),
    "efficient": ("medium", "What resource or time limit defines 'efficient'?"),
    "appropriate": ("medium", "What exactly is 'appropriate' here?"),
    "adequate": ("medium", "What exactly is 'adequate' here?"),
    "reasonable": ("medium", "What value is 'reasonable'?"),
    "sufficient": ("medium", "What value is 'sufficient'?"),
    "robust": ("medium", "Which failure conditions must be handled?"),
    "secure": ("medium", "Which specific security controls are required (e.g. hashing, rate limiting, MFA)?"),
    "securely": ("medium", "Which specific security controls are required?"),
    "scalable": ("medium", "What load (users / requests per second) must be supported?"),
    "seamless": ("low", "What observable behaviour defines 'seamless'?"),
    "flexible": ("low", "Which variations must be supported?"),
    "large": ("medium", "What size/count counts as 'large'?"),
    "small": ("low", "What size/count counts as 'small'?"),
    "many": ("medium", "What exact number is meant by 'many'?"),
    "several": ("medium", "What exact number is meant by 'several'?"),
    "few": ("medium", "What exact number is meant by 'few'?"),
    "some": ("low", "Which ones exactly?"),
    "various": ("low", "Which ones exactly?"),
    "often": ("medium", "What frequency is meant?"),
    "soon": ("medium", "What deadline/time is meant?"),
    "approximately": ("low", "What tolerance is acceptable?"),
    "minimal": ("medium", "What is the exact limit?"),
    "optimal": ("medium", "What measurable target defines 'optimal'?"),
    "as needed": ("medium", "Who decides when it is needed, and based on what?"),
    "as appropriate": ("medium", "What rule decides what is appropriate?"),
    "if possible": ("medium", "Is this mandatory or optional? Under what conditions?"),
    "where possible": ("medium", "Is this mandatory or optional? Under what conditions?"),
    "normally": ("low", "What happens in the non-normal case?"),
    "properly": ("medium", "What observable result counts as 'properly'?"),
    "correctly": ("low", "What observable result counts as 'correct'?"),
    "relevant": ("medium", "What makes a result 'relevant', and how should results be ranked?"),
    "irrelevant": ("medium", "What makes a result 'relevant', and how should results be ranked?"),
    "accurate": ("medium", "What accuracy is required, and how is it measured?"),
    "timely": ("medium", "What exact time limit is meant by 'timely'?"),
    "instantly": ("high", "What exact time limit is meant by 'instantly'?"),
    "immediately": ("medium", "What exact time limit is meant by 'immediately'?"),
    "real-time": ("high", "What maximum delay counts as 'real-time'?"),
    "acceptable": ("medium", "What value is 'acceptable'?"),
}

VAGUE_TERMS = frozenset(_VAGUE_TERMS)  # public: used by the coverage checker for measurability

_PATTERN_RULES: list[_Rule] = [
    _Rule(r"\b(etc\.?|and so on|and more)\b", "Open-ended list - the full set of items is not defined.",
          "What is the complete list of items?", "high"),
    _Rule(r"\b(TBD|TBC|to be (determined|decided|confirmed))\b", "Requirement contains an undecided placeholder.",
          "What is the decided value / behaviour?", "high"),
    _Rule(r"\band/or\b", "'and/or' makes it unclear whether both or either condition applies.",
          "Should both conditions apply, or is either one sufficient?", "medium"),
    _Rule(r"\b(may|might|could|optionally)\b", "Weak modal verb - unclear whether behaviour is mandatory.",
          "Is this behaviour mandatory (must) or optional?", "low"),
]

_ACTOR_WORDS = re.compile(
    r"\b(user|users|customer|customers|admin|administrator|manager|guest|visitor|member|client|"
    r"operator|employee|staff|student|teacher|seller|buyer|owner|system|service|api|app|application)\b",
    re.IGNORECASE,
)
_OUTCOME_WORDS = re.compile(
    r"\b(must|shall|should|will|can|cannot|able to|is displayed|is shown|returns?|receives?|redirect|"
    r"so that|then)\b",
    re.IGNORECASE,
)
_PERF_WORDS = re.compile(r"\b(performance|load|response time|latency|throughput|concurrent)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d")


def _excerpt(text: str, start: int, end: int, pad: int = 30) -> str:
    s, e = max(0, start - pad), min(len(text), end + pad)
    snippet = text[s:e].replace("\n", " ").strip()
    return ("..." if s > 0 else "") + snippet + ("..." if e < len(text) else "")


def detect_ambiguities(req: RequirementInput) -> list[Ambiguity]:
    """Return rule-based ambiguity findings for a requirement."""
    text = req.full_text()
    found: list[Ambiguity] = []
    seen_terms: set[str] = set()

    def add(term: str, issue: str, question: str, severity: str) -> None:
        key = term.lower()
        if key in seen_terms:
            return
        seen_terms.add(key)
        found.append(
            Ambiguity(
                id=f"AMB-R{len(found) + 1}",
                text=term,
                issue=issue,
                clarification_question=question,
                severity=severity,  # type: ignore[arg-type]
                source="rule",
            )
        )

    # 1) vague words (longest phrases first so "user-friendly" wins over "user")
    for term in sorted(_VAGUE_TERMS, key=len, reverse=True):
        m = re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text, re.IGNORECASE)
        if m:
            severity, question = _VAGUE_TERMS[term]
            add(_excerpt(text, m.start(), m.end()), f"Vague, unmeasurable term '{m.group(0)}'.", question, severity)

    # 2) structural patterns
    for rule in _PATTERN_RULES:
        m = re.search(rule.pattern, text, re.IGNORECASE)
        if m:
            add(_excerpt(text, m.start(), m.end()), rule.issue, rule.question, rule.severity)

    # 3) missing information (completeness checks)
    if not req.actor and not _ACTOR_WORDS.search(text):
        add("N/A (actor)", "No user role / actor is identified.", "Who performs this action?", "medium")
    if not _OUTCOME_WORDS.search(text):
        add("N/A (expected outcome)", "No expected outcome or obligation is stated.",
            "What should the system do, and what result should the user observe?", "high")
    if _PERF_WORDS.search(text) and not _NUMBER.search(text):
        add("N/A (performance target)", "Performance is mentioned without a numeric target.",
            "What are the numeric performance targets?", "high")
    if len(re.findall(r"\w+", req.description)) < 12 and not req.business_rules:
        add("N/A (detail)", "Requirement is very brief; validation rules and error handling are not specified.",
            "What are the validation rules, limits, and error behaviours?", "medium")

    # 4) time limits / thresholds whose inclusivity is not stated
    for lim in parse_limits(req):
        if lim.kind == "threshold":
            add(lim.phrase, f"It is not stated whether exactly {lim.high} {lim.unit} is inside or outside the limit.",
                f"At exactly {lim.high} {lim.unit}, does the old behaviour still apply or the new one?", "medium")

    return found


_TERM_IN_ISSUE = re.compile(r"term '([^']+)'")


def _vague_terms_in(text: str) -> set[str]:
    return {t for t in VAGUE_TERMS if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", text, re.IGNORECASE)}


def merge_ambiguities(rule_found: list[Ambiguity], llm_found: list[Ambiguity]) -> list[Ambiguity]:
    """Combine rule + LLM findings, drop duplicates, and renumber AMB-1..n."""
    return merge_ambiguities_with_map(rule_found, llm_found)[0]


def merge_ambiguities_with_map(
    rule_found: list[Ambiguity], llm_found: list[Ambiguity]
) -> tuple[list[Ambiguity], dict[str, str]]:
    """Combine rule + LLM findings, drop duplicates, and renumber AMB-1..n.

    Two findings are duplicates if their text+question normalise to the same
    string, OR if an LLM finding is about a vague term the rules already
    flagged (e.g. rule "Vague term 'fast'" and LLM "fast: speed undefined").

    Also returns ``llm_id -> final_id`` so references the model wrote elsewhere
    (e.g. a placeholder "[... - AMB-1]") can be rewritten; an LLM finding that
    was dropped as a duplicate maps to the finding that replaced it.
    """
    merged: list[Ambiguity] = []
    by_key: dict[str, int] = {}          # key -> index in merged
    llm_to_index: dict[str, int] = {}    # original LLM id -> index in merged
    rule_terms = {m.group(1).lower(): i for i, a in enumerate(rule_found) if (m := _TERM_IN_ISSUE.search(a.issue))}

    def key(a: Ambiguity) -> str:
        return re.sub(r"[^a-z0-9]", "", (a.text + a.clarification_question).lower())[:60]

    def nums(a: Ambiguity) -> set[str]:
        return set(re.findall(r"\d+", f"{a.text} {a.issue}"))

    def words(a: Ambiguity) -> set[str]:
        return {w for w in re.findall(r"[a-z]{4,}", f"{a.text} {a.issue} {a.clarification_question}".lower())}

    def rule_twin(a: Ambiguity) -> int | None:
        """Index (in rule_found == merged prefix) of the rule finding this LLM finding duplicates."""
        terms = _vague_terms_in(a.text)
        if terms and all(t in rule_terms for t in terms):
            return rule_terms[sorted(terms)[0]]
        for i, r in enumerate(rule_found):
            # same number + overlapping wording ("is exactly 30 minutes inclusive?")
            if nums(a) & nums(r) and len(words(a) & words(r)) / max(1, len(words(a) | words(r))) >= 0.15:
                return i
            # the LLM's phrase is literally the rule finding's issue ("open-ended list")
            short = re.sub(r"[^a-z0-9]", "", a.text.lower())
            if len(short) >= 6 and short in re.sub(r"[^a-z0-9]", "", r.issue.lower()):
                return i
        return None

    for a in rule_found:
        by_key.setdefault(key(a), len(merged))
        merged.append(a)
    for a in llm_found:
        k = key(a)
        idx = by_key.get(k)
        if idx is None:
            idx = rule_twin(a)
        if idx is None:
            idx = len(merged)
            by_key[k] = idx
            merged.append(a)
        llm_to_index.setdefault(a.id, idx)

    final = [a.model_copy(update={"id": f"AMB-{i}"}) for i, a in enumerate(merged, start=1)]
    return final, {old: final[i].id for old, i in llm_to_index.items()}


@dataclass(frozen=True)
class Limit:
    """A numeric limit stated in the requirement, used for boundary-value analysis.

    kinds:
      range      "between 8 and 64 characters"   (inclusive)
      min / max  "at least 1 digit", "at most 3"  (inclusive)
      xmin/xmax  "more than 5", "less than 10"   (exclusive)
      threshold  "expires 30 minutes after", "within 2 hours" - direction is
                 clear but inclusivity at exactly N is not stated
    """

    kind: str
    low: int | None
    high: int | None
    unit: str
    phrase: str
    source: str = ""  # the sentence/rule the limit was found in

    @property
    def numbers(self) -> set[str]:
        return {str(n) for n in (self.low, self.high) if n is not None}

    def test_values(self) -> list[str]:
        lo, hi = self.low, self.high
        if self.kind == "range":
            vals = [(lo - 1, "rejected"), (lo, "accepted"), (hi, "accepted"), (hi + 1, "rejected")]
        elif self.kind == "max":
            vals = [(hi - 1, "accepted"), (hi, "accepted"), (hi + 1, "rejected")]
        elif self.kind == "min":
            vals = [(lo - 1, "rejected"), (lo, "accepted"), (lo + 1, "accepted")]
        elif self.kind == "xmin":  # "more than N": N does not satisfy, N+1 does
            vals = [(lo, "does not satisfy the condition"), (lo + 1, "satisfies the condition")]
        elif self.kind == "xmax":  # "less than N"
            vals = [(hi - 1, "satisfies the condition"), (hi, "does not satisfy the condition")]
        else:  # threshold
            vals = [(hi - 1, "before the limit"), (hi, "exactly at the limit - expected behaviour must be clarified"),
                    (hi + 1, "after the limit")]
        return [f"{v}{self._unit_for(v)} -> {outcome}" for v, outcome in vals if v >= 0]

    def _unit_for(self, v: int) -> str:
        """'1 digit' / '0 digits', '1 minute' / '31 minutes'."""
        if not self.unit:
            return ""
        words = self.unit.split()
        last = words[-1]
        if not (last.isalpha() and last.islower() and len(last) > 2):
            return " " + self.unit  # abbreviations such as "MB", "%" are never pluralised
        if v == 1 and last.endswith("s") and not last.endswith("ss"):
            last = last[:-1]
        elif v != 1 and not last.endswith("s"):
            last += "s"
        return " " + " ".join([*words[:-1], last])


# Up to two words after the number form the unit ("3 reset emails", "64 characters"),
# but never a verb or connector ("5 failures ARE flagged", "3 items PER hour").
_NOT_UNIT = (r"(?!(?:and|or|per|after|within|in|of|to|the|a|an|is|are|be|was|were|must|can|cannot|will|should|"
             r"get|gets|has|have|may|for|from|before|since)\b)")
_UNIT = rf"(?:\s+({_NOT_UNIT}[A-Za-z]+(?:\s+{_NOT_UNIT}[a-z]+)?))?"
_TIME_UNIT = r"(seconds?|minutes?|hours?|days?|weeks?|months?)"


def _sentences(req: RequirementInput) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+|\n", req.description)
    return [p.strip() for p in [*parts, *req.business_rules] if p and p.strip()]


def parse_limits(req: RequirementInput) -> list[Limit]:
    """Parse numeric limits whose direction is unambiguous. Bare numbers with
    no direction ("5 attempts") are left to the LLM."""
    limits: list[Limit] = []
    seen: set[tuple] = set()

    def add(kind: str, low: int | None, high: int | None, unit: str | None, phrase: str, source: str) -> None:
        key = (kind, low, high)
        if key not in seen:
            seen.add(key)
            limits.append(Limit(kind, low, high, (unit or "").strip(), phrase.strip(), source))

    flags = re.IGNORECASE
    for s in _sentences(req):
        for m in re.finditer(r"\bbetween\s+(\d+)\s*(?:and|to|-)\s*(\d+)" + _UNIT, s, flags):
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo < hi:
                add("range", lo, hi, m.group(3), m.group(0), s)
        for m in re.finditer(r"\b(?:at most|maximum of|max\.?|up to|no more than)\s+(\d+)" + _UNIT, s, flags):
            add("max", None, int(m.group(1)), m.group(2), m.group(0), s)
        for m in re.finditer(r"\b(?:at least|minimum of|min\.?|no fewer than|no less than)\s+(\d+)" + _UNIT, s, flags):
            add("min", int(m.group(1)), None, m.group(2), m.group(0), s)
        for m in re.finditer(r"\b(?:more than|greater than|over|exceeds?)\s+(\d+)" + _UNIT, s, flags):
            add("xmin", int(m.group(1)), None, m.group(2), m.group(0), s)
        for m in re.finditer(r"\b(?:less than|fewer than|under|below)\s+(\d+)" + _UNIT, s, flags):
            add("xmax", None, int(m.group(1)), m.group(2), m.group(0), s)
        for m in re.finditer(rf"\b(?:expires?|expiring)\s+(?:after\s+|in\s+)?(\d+)\s+{_TIME_UNIT}", s, flags):
            add("threshold", None, int(m.group(1)), m.group(2), m.group(0), s)
        for m in re.finditer(rf"\b(?:valid for|within)\s+(\d+)\s+{_TIME_UNIT}", s, flags):
            add("threshold", None, int(m.group(1)), m.group(2), m.group(0), s)
    return limits


def extract_boundaries(req: RequirementInput) -> list[str]:
    """Find numeric limits/ranges in the requirement - these REQUIRE boundary tests."""
    text = req.full_text()
    patterns = [
        r"\b(at least|minimum( of)?|min\.?|no (fewer|less) than|more than|greater than|over|above)\s+\d+[\w%]*",
        r"\b(at most|maximum( of)?|max\.?|up to|no more than|less than|fewer than|under|below|within)\s+\d+[\w%]*",
        r"\b(minimum|maximum|min|max)\s+[a-z ]{1,25}?\s+(of|is)\s+\d+[\w%]*",  # "minimum age of 18"
        r"\bbetween\s+\d+\s*(and|-|to)\s*\d+(\s*(characters|chars|digits|items|years|days|minutes|seconds|mb|gb|kb|%))?",
        r"\b\d+\s*(-|to)\s*\d+\s*(characters|chars|digits|items|years|days|minutes|seconds|attempts|mb|gb|kb|%)",
        r"\b\d+\s*(characters|chars|digits|attempts|tries|minutes|seconds|hours|days|mb|gb|kb|items|%)",
    ]
    hits: list[str] = []
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            h = m.group(0).strip()
            if not any(h.lower() in x.lower() or x.lower() in h.lower() for x in hits):
                hits.append(h)
    return hits
