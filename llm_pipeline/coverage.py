"""Coverage checker and grounding validation (deterministic - no LLM).

Responsibilities
----------------
1. Rule anchoring    - every explicit business rule is split into atomic clauses
                       and each clause becomes a *seeded* acceptance criterion
                       with the rule's exact wording (``seed_criteria``,
                       ``align_criteria``). The LLM writes Given/When/Then and
                       tests, but it cannot drop, reword, or fragment a rule.
2. Grounding         - criteria/tests may not contain values or concepts that
                       are not in the requirement; such criteria become
                       *assumptions* with an explicit assumption entry
                       (``ground_criteria``). Vague words make a criterion
                       "needs_clarification" instead of "validated".
3. Test validity     - invalid references, duplicate IDs, mislabelled tests,
                       duplicates, and "mirror" negatives (same steps as a
                       positive, only the expected result flipped).
4. Boundary analysis - exact boundary values for every stated limit.
5. Assessment        - per criterion: positive / negative / boundary coverage,
                       status, and the precise *tasks* still needed. These
                       tasks drive the supplement requests in pipeline.py.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .ambiguity import Limit, blocking_terms, extract_boundaries, parse_limits
from .schemas import (
    AcceptanceCriterion,
    Assumption,
    AutomationRecommendation,
    LLMOutput,
    RequirementInput,
    TestScenario,
)

# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #

_STOP = {
    "must", "should", "shall", "will", "with", "that", "this", "their", "they", "them", "from", "into", "when",
    "then", "given", "have", "been", "after", "before", "each", "only", "than", "able", "user", "users", "system",
    "which", "there", "these", "those", "also", "such", "being", "does", "were", "what", "your",
}
_ID_RE = re.compile(r"\b(?:AC|TC|AMB|ASM|REQ|EC)[-_ ]?[A-Za-z0-9]*\d+\b", re.IGNORECASE)


def norm_text(s: str) -> str:
    """Lowercase the text and keep only letters and digits, for loose comparison."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def content_words(s: str) -> set[str]:
    """Lower-case content words with a crude plural strip ('categories' -> 'category')."""
    out = set()
    for w in re.findall(r"[a-z]{4,}", s.lower()):
        if w in _STOP:
            continue
        if (w.endswith("ies") or w.endswith("ied")) and len(w) > 5:
            w = w[:-3] + "y"  # categories -> category, classified -> classify
        elif w.endswith("es") and len(w) > 5 and w[-3] in "sxz":
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 4:
            w = w[:-1]
        out.add(w)
    return out


def _fmt(x: float) -> str:
    """Format a number without a trailing .0."""
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def numbers(s: str) -> set[str]:
    """Numbers in a text ("1.5" stays one number), ignoring IDs such as AC-1, TC-004, REQ-101."""
    return {_fmt(float(n)) for n in re.findall(r"(?<![\d.])\d+(?:\.\d+)?", _ID_RE.sub(" ", s or ""))}


def derived_numbers(inputs: set[str], stated: set[str]) -> set[str]:
    """Values a tester can legitimately compute: the test's own input numbers, and the difference
    between an input and a number STATED in the requirement (a 10-hour day with "over 8 is
    overtime" -> 2 overtime hours). Kept deliberately narrow so invented values stay invented."""
    out = set(inputs)
    for a in (float(x) for x in inputs):
        for b in (float(x) for x in stated):
            out.add(_fmt(abs(a - b)))
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    """Return the overlap of two sets from 0 to 1. Two empty sets score 0."""
    return len(a & b) / len(a | b) if a | b else 0.0


def canon_id(id_: str) -> str:
    """'ac 1', 'AC1', 'AC-01' -> 'AC1' for tolerant ID matching."""
    m = re.match(r"^\s*([A-Za-z]+)[\s_\-]*0*(\d+)\s*$", id_ or "")
    return f"{m.group(1).upper()}{m.group(2)}" if m else (id_ or "").strip().upper()


def id_number(id_: str) -> int:
    """Return the number at the end of an ID such as TC-007, or 0 if there is none."""
    m = re.search(r"(\d+)\s*$", id_ or "")
    return int(m.group(1)) if m else 0


_PLACEHOLDER_RE = re.compile(
    r"\[[^\]]*(confirm|tbd|tbc|defin|clarif)[^\]]*\]|\bto be (confirmed|defined|determined)\b|\bTB[DC]\b"
    # an unnamed value standing in for a number: "within a specified response time", "the required limit"
    r"|\b(?:a|an|the)\s+(?:specified|defined|agreed|required|given|certain|predefined|configured|set|target)\s+"
    r"(?:response time|time|limit|threshold|value|period|duration|number|amount|time frame)\b",
    re.IGNORECASE,
)

# Strings copied from the JSON shape in the prompt instead of real content.
_TEMPLATE_ECHOES = {
    "exactunclearphrase", "whyunclear", "questionfortheproductowner", "whatyouassumed", "whichgapitfills",
    "measurablestatement", "", "reqid", "acn", "whynonegativetestcanexist",
}


def is_template_echo(*texts: str) -> bool:
    """True if any text is copied from the example shape shown in the prompt."""
    return any(norm_text(t) in _TEMPLATE_ECHOES for t in texts if t is not None)


# Wording that says the test's INPUT is valid / invalid (used to judge negative tests).
_VALID_INPUT_RE = re.compile(
    r"\b(valid|correct|correctly|allowed|permitted|meets?|satisf(?:y|ies)|different from|acceptable|"
    r"within (?:the )?(?:allowed|limit|permitted|time)|within \d+|before (?:the )?(?:limit|expiry|expiration))\b",
    re.IGNORECASE,
)
_INVALID_INPUT_RE = re.compile(
    r"\b(invalid|incorrect|wrong|without|missing|empty|blank|no digits?|fewer than|less than|shorter|longer|"
    r"more than|exceed\w*|too (?:short|long|many)|same as|equal to|equals|identical|reuse\w*|expired|"
    r"after (?:the )?(?:limit|expiry|expiration|\d+)|already|again|second time|fourth|4th|non[- ]?existent|"
    r"unregistered|unknown|not registered|beyond|outside|violat\w*|above|below|over the|limit reached)\b",
    re.IGNORECASE,
)
_SUCCESS_RE = re.compile(
    r"\b(is applied|applied|succeeds?|successful(?:ly)?|accepted|is sent|are sent|works|opens|is reset|"
    r"is updated|logged in|granted|is saved|is displayed)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"\b(not|no longer|never|cannot|can't|isn't|aren't|doesn't|won't)\b", re.IGNORECASE)
# quoted message text; single quotes only when not an apostrophe inside a word ("user's", "can't")
_QUOTED_RE = re.compile(r"[\"“]([^\"”]{12,})[\"”]|(?<!\w)'([^']{12,})'(?!\w)")

_PERF_RE = re.compile(
    r"\b(response time|load time|latency|speed|quickly|fast|performance|throughput|time frame|time limit|"
    r"within (?:a|an|the)?\s*(?:\w+\s+)?(?:time|period|duration))\b",  # "within a specified time"
    re.IGNORECASE,
)
PERFORMANCE_TERM = "performance target"
# ambiguity issues that a "performance target" gap maps to
PERFORMANCE_WORDS = ("'fast'", "'quick'", "'quickly'", "'slow'", "'responsive'", "'instantly'", "'real-time'",
                     "performance", "response time")

# A "positive" test whose expected result is a rejection is really a negative test.
REJECTION_RE = re.compile(
    r"\b(error|errors|rejected|rejects|reject|rejection|denied|denies|refused|fails?|failed|not allowed|invalid|"
    r"too (long|short|many)|blocked|prevented|cannot|can't|is not (accepted|saved|sent|applied)|unable|"
    r"no longer valid|not valid|expired|not successful|unsuccessful|(?:prompted|asked|required) to wait|must wait|"
    r"not usable|unusable|no longer usable|does not work|doesn't work|not accessible|inaccessible)\b",
    re.IGNORECASE,
)

# Words that mean a criterion has a constraint a negative test could violate.
_CONSTRAINT_RE = re.compile(
    r"\b(not|only|never|at most|at least|between|limit|limited|maximum|minimum|expire|expires|expired|invalid|"
    r"valid|required|requires|equal|unique|exceed|exceeds|within|allowed|reject|rejected|cannot)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# Request context
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Seed:
    """An acceptance criterion fixed by code from an explicit business rule."""

    id: str
    text: str
    rule: str


_MODAL = r"(?:must not|must|should not|should|shall not|shall|will not|will|cannot|can not|can|may not|may)"
_SPLIT_RE = re.compile(
    r",?\s+and\s+(?=(?:must|should|shall|can|cannot|contain|contains|be|not|never|have|has|include|includes|"
    r"only|use|uses|expire|expires|match|matches)\b)",
    re.IGNORECASE,
)


def split_rule_clauses(rule: str) -> list[str]:
    """'The new password must be between 8 and 64 characters and contain at least 1 digit.'
    -> ['The new password must be between 8 and 64 characters.',
        'The new password must contain at least 1 digit.']"""
    rule = rule.strip()
    parts = [p.strip(" .") for p in _SPLIT_RE.split(rule) if p and p.strip(" .")]
    if len(parts) <= 1:
        return [rule if rule.endswith(".") else rule + "."]
    head = re.match(rf"^(.*?)\s*\b({_MODAL})\b", parts[0], re.IGNORECASE)  # subject + modal of the first clause
    clauses = [parts[0] + "."]
    for p in parts[1:]:
        if head and re.match(rf"^{_MODAL}\b", p, re.IGNORECASE):        # "cannot contain spaces"
            p = f"{head.group(1)} {p}"
        elif head and not re.match(r"^(the|a|an|each|every|all)\b", p, re.IGNORECASE):  # "contain at least 1 digit"
            p = f"{head.group(1)} {head.group(2)} {p}"
        clauses.append(p[0].upper() + p[1:] + ".")
    return clauses


def seed_criteria(rules: list[str]) -> list[Seed]:
    """Create one fixed acceptance criterion per rule clause, numbered AC-1 onwards."""
    seeds: list[Seed] = []
    for rule in rules:
        for clause in split_rule_clauses(rule):
            seeds.append(Seed(id=f"AC-{len(seeds) + 1}", text=clause, rule=rule))
    return seeds


@dataclass
class Context:
    """Everything the checker needs to know about the requirement."""

    requirement_id: str
    actor: str
    rules: list[str]
    seeds: list[Seed]
    limits: list[Limit]
    leftover_boundaries: list[str]  # numeric phrases with no parsable direction -> LLM must write the test
    allowed_numbers: set[str]       # numbers stated in the requirement, +/- 1 (boundary neighbours)
    requirement_words: set[str]
    stated_numbers: set[str] = field(default_factory=set)  # exactly the numbers in the requirement text

    @classmethod
    def from_requirement(cls, req: RequirementInput) -> "Context":
        """Analyse a requirement: seed criteria, parse limits, and collect the numbers it allows."""
        text = req.full_text()
        limits = parse_limits(req)
        covered_nums = set().union(*(lim.numbers for lim in limits)) if limits else set()
        leftover = [b for b in extract_boundaries(req) if not numbers(b) <= covered_nums]
        stated = numbers(text)
        allowed = set(stated)
        for n in stated:
            if "." not in n:  # boundary neighbours only for whole numbers
                allowed |= {str(int(n) - 1), str(int(n) + 1)}
        return cls(
            requirement_id=req.requirement_id or "",
            actor=req.actor or "user",
            rules=list(req.business_rules),
            seeds=seed_criteria(req.business_rules),
            limits=limits,
            leftover_boundaries=leftover,
            allowed_numbers=allowed,
            stated_numbers=stated,
            requirement_words=content_words(text),
        )

    @property
    def seed_ids(self) -> set[str]:
        """IDs of the criteria seeded from business rules."""
        return {s.id for s in self.seeds}


# --------------------------------------------------------------------------- #
# 1. Rule anchoring
# --------------------------------------------------------------------------- #


def _seed_score(ac: AcceptanceCriterion, seed: Seed) -> float:
    """How well an LLM criterion matches a seeded rule clause (0 = no match)."""
    sn, an = numbers(seed.text), numbers(f"{ac.description} {ac.then}")
    w = jaccard(content_words(ac.description), content_words(seed.text))
    if sn:
        # Same rule if it uses the rule's numbers AND talks about the same thing
        # (stops "at least 3 characters" matching "at most 3 emails").
        if not (an & sn) or w < 0.15:
            return 0.0
        return 1.0 + len(an & sn) / len(sn) + w
    return w if w >= 0.3 else 0.0


def same_criterion(a: str, b: str) -> bool:
    """Near-duplicate test for two criterion descriptions."""
    if norm_text(a) == norm_text(b):
        return True
    return numbers(a) == numbers(b) and jaccard(content_words(a), content_words(b)) >= 0.8


def align_criteria(out: LLMOutput, ctx: Context, notes: list[str]) -> None:
    """Replace the LLM's criteria for business rules with the seeded ones.

    * An LLM criterion that matches a seed (even a fragment such as "a valid
      8-character password is accepted") is merged into that seed; its tests
      are re-linked. The seed keeps the rule's exact wording.
    * LLM criteria that match no seed are kept as extra criteria (they must
      come from the description - checked by ``ground_criteria``).
    * A seed the model did not write is still created from the rule text.
    * Extra criteria that duplicate each other are merged; all extras are
      renumbered after the seeds, and every test link is remapped.
    """
    by_seed: dict[str, list[tuple[float, AcceptanceCriterion]]] = {s.id: [] for s in ctx.seeds}
    remap: dict[str, str] = {}
    extras: list[AcceptanceCriterion] = []
    for ac in out.acceptance_criteria:
        scored = [(_seed_score(ac, s) + (0.01 if canon_id(ac.id) == canon_id(s.id) else 0), s) for s in ctx.seeds]
        score, best = max(scored, key=lambda x: x[0]) if scored else (0.0, None)
        if best is not None and score > 0:
            by_seed[best.id].append((score, ac))
            remap[canon_id(ac.id)] = best.id
        else:
            extras.append(ac)

    final: list[AcceptanceCriterion] = []
    for seed in ctx.seeds:
        matches = sorted(by_seed[seed.id], key=lambda x: -x[0])
        base = matches[0][1] if matches else None
        if len(matches) > 1:
            notes.append(f"{seed.id}: {len(matches)} model criteria described the same rule and were merged")
        given, when, then = (base.given, base.when, base.then) if base else ("", "", "")
        if base is None:
            notes.append(f"{seed.id}: the model did not write a criterion for rule '{seed.text}'; created from the rule text")
        bad = numbers(f"{given} {when} {then}") - ctx.allowed_numbers
        if bad:
            notes.append(f"{seed.id}: model Given/When/Then used unsupported value(s) {sorted(bad)}; replaced with the rule text")
            given = when = ""
        if then and norm_text(then) != norm_text(seed.text):
            # The outcome of a fixed criterion IS the rule. Model-written outcomes were seen to add
            # behaviour the requirement never states ("the user is prompted to wait an hour").
            notes.append(f"{seed.id}: model-written 'then' replaced with the rule text (fixed criterion)")
        final.append(AcceptanceCriterion(
            id=seed.id,
            description=seed.text,
            given=given or f"a {ctx.actor} is using the feature described in the requirement",
            when=when or "the behaviour governed by this rule is exercised",
            then=seed.text,
            source="explicit",
            assumption_ids=[],
        ))

    # Extra (non-rule) criteria: merge near-duplicates, then number after the seeds.
    next_n = len(ctx.seeds) + 1
    kept: list[tuple[AcceptanceCriterion, str]] = []
    for ac in extras:
        twin = next((new_id for k, new_id in kept if same_criterion(k.description, ac.description)), None)
        if twin:
            remap[canon_id(ac.id)] = twin
            notes.append(f"criterion '{ac.description[:60]}' duplicated {twin} and was merged into it")
            continue
        new_id = f"AC-{next_n}"
        next_n += 1
        remap[canon_id(ac.id)] = new_id
        kept.append((ac, new_id))
        final.append(ac.model_copy(update={"id": new_id}))

    seed_canon = {canon_id(s.id): s.id for s in ctx.seeds}
    for tc in out.test_scenarios:
        c = canon_id(tc.acceptance_criterion_id)
        tc.acceptance_criterion_id = remap.get(c) or seed_canon.get(c) or tc.acceptance_criterion_id
    for na in out.not_applicable:
        c = canon_id(na.acceptance_criterion_id)
        na.acceptance_criterion_id = remap.get(c) or seed_canon.get(c) or na.acceptance_criterion_id
    out.acceptance_criteria = final


# --------------------------------------------------------------------------- #
# 2. Grounding of criteria
# --------------------------------------------------------------------------- #


def _add_assumption(out: LLMOutput, statement: str, reason: str) -> str:
    """Append an assumption with the next free ASM number and return its ID."""
    n = max((id_number(a.id) for a in out.assumptions), default=0) + 1
    asm = Assumption(id=f"ASM-{n}", statement=statement, reason=reason)
    out.assumptions.append(asm)
    return asm.id


def ground_criteria(out: LLMOutput, ctx: Context, notes: list[str]) -> None:
    """Never let an unstated value or concept pass as an explicit requirement."""
    asm_ids = {a.id for a in out.assumptions}
    for ac in out.acceptance_criteria:
        if ac.id in ctx.seed_ids:
            continue  # seeded: wording is the rule itself, G/W/T already checked
        ac.assumption_ids = [a for a in ac.assumption_ids if a in asm_ids]
        text = f"{ac.description} {ac.given} {ac.when} {ac.then}"
        reasons = []
        bad_nums = numbers(text) - ctx.allowed_numbers
        if bad_nums:
            reasons.append(f"uses value(s) {sorted(bad_nums, key=float)} that the requirement does not state")
        words = content_words(ac.description)
        new_words = sorted(words - ctx.requirement_words)
        if len(words) >= 3 and len(new_words) / len(words) > 0.5:
            reasons.append(f"introduces concepts not in the requirement ({', '.join(new_words[:4])})")
        if _PLACEHOLDER_RE.search(f"{ac.description} {ac.then}"):
            reasons.append("contains an unresolved placeholder instead of a stated value")
        if reasons:
            asm = _add_assumption(out, f"{ac.id}: {ac.description}", "Not stated in the requirement: " + "; ".join(reasons))
            if ac.source == "explicit":
                notes.append(f"{ac.id} was marked explicit but {' and '.join(reasons)}; reclassified as assumption {asm}")
            ac.source = "assumption"
            ac.assumption_ids = sorted({*ac.assumption_ids, asm})
        elif ac.assumption_ids and ac.source != "assumption":
            ac.source = "assumption"
        elif ac.source == "assumption" and not ac.assumption_ids:
            asm = _add_assumption(out, f"{ac.id}: {ac.description}", "The model marked this criterion as assumed")
            ac.assumption_ids = [asm]


def drop_template_echoes(out: LLMOutput, notes: list[str]) -> None:
    """Remove items the model copied from the prompt's JSON shape ("exact unclear phrase",
    "why unclear", "..."). Seen in a real run: an echoed ambiguity had severity 'high' and
    wrongly set needs_clarification."""
    before = (len(out.ambiguities), len(out.assumptions), len(out.acceptance_criteria), len(out.test_scenarios))
    out.ambiguities = [a for a in out.ambiguities if not is_template_echo(a.text, a.issue, a.clarification_question)]
    out.assumptions = [a for a in out.assumptions if not is_template_echo(a.statement, a.reason)]
    kept_ac = [a for a in out.acceptance_criteria if not is_template_echo(a.description)]
    if kept_ac:  # never empty the list here; schema validation already guaranteed >= 1
        out.acceptance_criteria = kept_ac
    out.test_scenarios = [t for t in out.test_scenarios if not is_template_echo(t.title, t.expected_result)]
    after = (len(out.ambiguities), len(out.assumptions), len(out.acceptance_criteria), len(out.test_scenarios))
    for name, b, a in zip(("ambiguities", "assumptions", "acceptance criteria", "test scenarios"), before, after):
        if b > a:
            notes.append(f"{b - a} {name} removed: copied from the prompt template instead of real content")


# --------------------------------------------------------------------------- #
# 3-5. Check report
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Task:
    """One precise piece of missing coverage."""

    kind: str  # "positive" | "negative" | "boundary"
    ac_id: str
    text: str        # full instruction sent to the model
    detail: str = ""
    summary: str = ""  # short sentence for people (coverage.gaps / warnings)

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity of the task, used to count how often it has been requested."""
        return (self.kind, self.ac_id, self.detail)


@dataclass
class Assessment:
    """What the coverage check found for one acceptance criterion."""
    ac_id: str
    tests: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    has_positive: bool = False
    has_negative: bool = False
    boundary_required: bool = False
    has_boundary: bool = False
    not_applicable: list[str] = field(default_factory=list)
    blocked_terms: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    status: str = "untested"
    missing: list[str] = field(default_factory=list)


@dataclass
class BoundaryStatus:
    """Whether one numeric limit has a boundary test."""
    limit: str
    ac_id: str | None
    tests: list[str]
    covered: bool


@dataclass
class CheckReport:
    """Everything one coverage check found, including the tasks still open."""
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    other_gaps: list[str] = field(default_factory=list)  # gaps the LLM cannot fix with a test
    invalid_references: list[str] = field(default_factory=list)
    unsupported_tests: dict[str, str] = field(default_factory=dict)  # tc id -> reason
    assessments: dict[str, Assessment] = field(default_factory=dict)
    boundaries: list[BoundaryStatus] = field(default_factory=list)

    @property
    def gaps(self) -> list[str]:
        """Every remaining gap: open tasks and gaps a test cannot fix."""
        return [t.summary or t.text for t in self.tasks] + self.other_gaps


def _limit_ac(out: LLMOutput, nums: set[str], source: str) -> AcceptanceCriterion | None:
    """Pick the criterion that carries the limit's numbers and is worded closest to its source."""
    cands = [a for a in out.acceptance_criteria if nums and nums <= numbers(f"{a.description} {a.then}")]
    if not cands:
        return None
    return max(cands, key=lambda a: jaccard(content_words(a.description), content_words(source)))


def add_boundary_tests(out: LLMOutput, ctx: Context, notes: list[str]) -> None:
    """Boundary-value analysis in code: exact values for every stated limit."""
    next_n = max((id_number(tc.test_case_id) for tc in out.test_scenarios), default=0) + 1
    for limit in ctx.limits:
        ac = _limit_ac(out, limit.numbers, limit.source)
        if ac is None:
            continue
        if any(tc.acceptance_criterion_id == ac.id and tc.test_type == "boundary"
               and limit.numbers <= numbers(" ".join(tc.test_data) + " " + tc.title) for tc in out.test_scenarios):
            continue
        tc_id = f"TC-{next_n:03d}"
        next_n += 1
        out.test_scenarios.append(TestScenario(
            test_case_id=tc_id,
            title=f"Boundary values for '{limit.phrase}'",
            requirement_id=ctx.requirement_id,
            acceptance_criterion_id=ac.id,
            test_type="boundary",
            preconditions=[f"Preconditions of {ac.id}: {ac.given}"],
            test_steps=[
                "Prepare one input for each value in test_data",
                f"Perform the action under test: {ac.when}",
                "Record the behaviour observed for each value",
            ],
            test_data=limit.test_values(),
            expected_result=f"Each value behaves as listed in test_data (limit: {limit.phrase})",
            priority="high",
            automation=AutomationRecommendation(
                automatable=True, level="unit", suggested_tool="pytest (parametrize)",
                rationale=f"{_BVA_RATIONALE}; one parametrized case per value",
            ),
        ))
        notes.append(f"{tc_id} generated by deterministic boundary-value analysis of '{limit.phrase}'")


def _sig(tc: TestScenario) -> str:
    """Normalised steps and test data, to compare tests by what they do and not by title."""
    return norm_text(" ".join(tc.test_steps) + "|" + " ".join(tc.test_data))


_COMPARATIVE_BEFORE = re.compile(
    r"(?:(?:fewer|less|more|greater|longer|shorter) than|over|under|above|below|exceed\w*|up to|at most|at least|"
    r"maximum of|minimum of|max\.?|min\.?|between|and|to|or|-|–)\s*$",
    re.IGNORECASE,
)


def _inside_limit(lim: Limit, v: int) -> bool | None:
    """Is value v ALLOWED by the limit? None = the limit is not an accept/reject decision
    (category thresholds, caps, non-negated "more than N" conditions) or v is exactly at an
    unclear threshold."""
    if not lim.validity or lim.kind == "cap":
        return None
    if lim.kind == "range":
        return lim.low <= v <= lim.high
    if lim.kind == "max":
        return v <= lim.high
    if lim.kind == "min":
        return v >= lim.low
    if lim.kind == "threshold":
        return None if v == lim.high else v < lim.high
    if lim.kind in ("xmin", "xmax"):
        if not lim.inverted:
            return None  # "Hours over 8 are overtime" classifies; it does not accept or reject
        matches = v > lim.low if lim.kind == "xmin" else v < lim.high
        return not matches  # "must not exceed 48 hours": 49 matches the forbidden condition
    return None


def _limit_contradiction(inputs: str, exp: str, criterion: str, ctx: Context) -> str | None:
    """A concrete value in the test vs the stated limit of its criterion.
    Real output: "Wait 29 minutes ... use the link" -> expected "the link is not usable" (limit: 30 minutes)."""
    rejects = bool(REJECTION_RE.search(exp))
    succeeds = bool(_SUCCESS_RE.search(exp)) and not rejects and not _NEGATION_RE.search(exp)
    if not (rejects or succeeds):
        return None
    for lim in ctx.limits:
        if not lim.unit or not lim.numbers <= numbers(criterion):
            continue  # only limits that belong to this test's criterion
        stem = lim.unit.split()[-1].lower()
        stem = stem[:-1] if stem.endswith("s") and not stem.endswith("ss") else stem
        if len(stem) < 3:
            continue
        for m in re.finditer(rf"\b(\d+)\s+(?:[a-z]+\s+)?{re.escape(stem)}s?\b", inputs, re.IGNORECASE):
            if _COMPARATIVE_BEFORE.search(inputs[max(0, m.start() - 25):m.start()]):
                continue  # "fewer than 8 characters", "more than 3 emails": not a concrete value
            v = int(m.group(1))
            inside = _inside_limit(lim, v)
            if inside is True and rejects:
                return f"contradictory - {v} {lim.unit} is inside the stated limit ({lim.phrase}) but it expects a rejection"
            if inside is False and succeeds:
                return f"contradictory - {v} {lim.unit} is outside the stated limit ({lim.phrase}) but it expects success"
    return None


_CONDITIONAL_RE = re.compile(r"\b(if|when|unless|only|whenever|until|except)\b", re.IGNORECASE)
# (word in the rule, its opposite) - only checked against UNCONDITIONAL rules, because for
# "a request is rejected IF ..." a positive test legitimately expects acceptance.
_OPPOSITES = [
    (r"\bexclud\w*", r"\binclud\w*"), (r"\binclud\w*", r"\bexclud\w*"),
    (r"\bnot counted\b", r"\b(?<!not )counted\b"), (r"\bcannot be edited\b", r"\b(?<!not )(?:can be|is) edited\b"),
    (r"\blocked\b", r"\bunlocked\b"), (r"\bdeduct\w*", r"\b(?:add|credit)\w*"),
]


def _invalid_test_reason(tc: TestScenario, ctx: Context, allowed_in_results: set[str],
                         criterion: str = "") -> str | None:
    """Why a model-written test must not be kept (None = keep)."""
    exp = tc.expected_result
    # Tautology: the "expected result" is the rule itself or one of the test's own steps
    # (real output: step "The password is between 8 and 64 characters" -> expected the same).
    exp_words = content_words(exp)
    states_outcome = bool(REJECTION_RE.search(exp) or _SUCCESS_RE.search(exp))  # "Rejected: password equals current"
    if (criterion and not states_outcome and len(exp_words) >= 2
            and jaccard(exp_words, content_words(criterion)) >= 0.75):
        return "its expected result only restates the criterion; it must describe an observable outcome"
    if any(norm_text(step) == norm_text(exp) for step in tc.test_steps):
        return "its expected result repeats one of its own steps; it must describe an observable outcome"
    # Opposite of an unconditional rule: rule "break time is EXCLUDED", positive test expects "INCLUDED".
    if tc.test_type == "positive" and criterion and not _CONDITIONAL_RE.search(criterion):
        for rule_word, opposite in _OPPOSITES:
            if (re.search(rule_word, criterion, re.I) and not re.search(opposite, criterion, re.I)
                    and re.search(opposite, exp, re.I) and not re.search(rule_word, exp, re.I)):
                return f"contradicts its criterion - the rule says '{re.search(rule_word, criterion, re.I).group(0)}' " \
                       f"but it expects '{re.search(opposite, exp, re.I).group(0)}'"
    # Restatement without a concrete input: "Process a workday with hours over 8" -> "Classify hours
    # over 8 as overtime". Every expected word is in the rule and the test uses no value of its own.
    crit_words = content_words(criterion)
    own_values = numbers(" ".join([*tc.test_steps, *tc.test_data])) - ctx.stated_numbers
    if (criterion and not states_outcome and len(exp_words) >= 3 and not own_values
            and len(exp_words & crit_words) / len(exp_words) >= 0.8):
        return "its expected result only restates the criterion and the test uses no concrete input"
    input_nums = numbers(" ".join([*tc.test_steps, *tc.test_data]))
    bad = numbers(exp) - allowed_in_results - derived_numbers(input_nums, ctx.stated_numbers)
    if bad:
        return f"expects value(s) {sorted(bad, key=float)} that the requirement does not state"
    stated = norm_text(" ".join(ctx.rules))
    quoted = [q for pair in _QUOTED_RE.findall(exp) for q in pair if q and norm_text(q) not in stated]
    if quoted:
        return f"expects a message the requirement does not specify ('{quoted[0][:40]}')"
    inputs = " ".join([tc.title, *tc.test_steps, *tc.test_data])
    # concrete values only: steps and test data (titles usually restate the rule's range)
    contradiction = _limit_contradiction(" ".join([*tc.test_steps, *tc.test_data]), exp, criterion, ctx)
    if contradiction:
        return contradiction
    valid_input = bool(_VALID_INPUT_RE.search(inputs)) and not _INVALID_INPUT_RE.search(inputs)
    rejects = bool(REJECTION_RE.search(exp)) or bool(_NEGATION_RE.search(exp))
    if tc.test_type == "positive" and REJECTION_RE.search(exp) and valid_input:
        return "contradictory - it uses valid input but expects a rejection"
    if tc.test_type == "negative":
        if valid_input:
            return "uses only valid input; a negative test must use invalid input or violate the rule"
        if _SUCCESS_RE.search(exp) and not rejects:
            return "expects the same successful behaviour as a positive test; a negative test must expect rejection"
    return None


def check_output(out: LLMOutput, ctx: Context) -> CheckReport:
    """Validate references and tests in place, then assess coverage."""
    rep = CheckReport()
    ac_by_id = {ac.id: ac for ac in out.acceptance_criteria}
    canon_to_ac = {canon_id(i): i for i in ac_by_id}

    # --- references ---------------------------------------------------------
    kept: list[TestScenario] = []
    for tc in out.test_scenarios:
        if tc.requirement_id != ctx.requirement_id:
            rep.notes.append(f"{tc.test_case_id}: requirement_id '{tc.requirement_id}' corrected to '{ctx.requirement_id}'")
            tc.requirement_id = ctx.requirement_id
        if tc.acceptance_criterion_id not in ac_by_id:
            fixed = canon_to_ac.get(canon_id(tc.acceptance_criterion_id))
            if not fixed:
                rep.invalid_references.append(
                    f"{tc.test_case_id} referenced unknown acceptance criterion '{tc.acceptance_criterion_id}' and was removed")
                continue
            tc.acceptance_criterion_id = fixed
        kept.append(tc)

    # --- duplicate test IDs -> renumber, never fail ---------------------------
    seen_ids: set[str] = set()
    next_n = max((id_number(t.test_case_id) for t in kept), default=0) + 1
    for tc in kept:
        if tc.test_case_id in seen_ids:
            new_id = f"TC-{next_n:03d}"
            next_n += 1
            rep.notes.append(f"duplicate test ID {tc.test_case_id} renumbered to {new_id}")
            tc.test_case_id = new_id
        seen_ids.add(tc.test_case_id)

    # --- test validity: type must agree with input and expected result --------
    kept = [tc for tc in kept if not is_template_echo(tc.title, tc.expected_result)]
    allowed_in_results = ctx.allowed_numbers | {"0"}
    valid_kept: list[TestScenario] = []
    for tc in kept:
        if is_generated(tc):
            valid_kept.append(tc)
            continue
        crit = ac_by_id[tc.acceptance_criterion_id].description if tc.acceptance_criterion_id in ac_by_id else ""
        reason = _invalid_test_reason(tc, ctx, allowed_in_results, crit)
        if reason:
            rep.notes.append(f"{tc.test_case_id} removed: {reason}")
            continue
        if tc.test_type == "positive" and REJECTION_RE.search(tc.expected_result):
            tc.test_type = "negative"
            rep.notes.append(f"{tc.test_case_id} relabelled positive -> negative (invalid input, expected result is a rejection)")
        valid_kept.append(tc)
    positive_results = {(tc.acceptance_criterion_id, norm_text(tc.expected_result))
                        for tc in valid_kept if tc.test_type == "positive"}
    kept = []
    for tc in valid_kept:
        if tc.test_type == "negative" and (tc.acceptance_criterion_id, norm_text(tc.expected_result)) in positive_results:
            rep.notes.append(f"{tc.test_case_id} removed: it expects the same result as a positive test of "
                             f"{tc.acceptance_criterion_id}; a negative test must expect rejection")
            continue
        kept.append(tc)

    # --- boundary tests for stated limits are generated by code, not the model --
    auto_acs = {ac.id for lim in ctx.limits if (ac := _limit_ac(out, lim.numbers, lim.source))}
    leftover_nums = set().union(*(numbers(b) for b in ctx.leftover_boundaries)) if ctx.leftover_boundaries else set()
    model_bounds = [tc for tc in kept if tc.test_type == "boundary" and not is_generated(tc)
                    and tc.acceptance_criterion_id in auto_acs
                    and not (numbers(" ".join(tc.test_data) + " " + tc.title) & leftover_nums)]
    for tc in model_bounds:
        rep.notes.append(f"{tc.test_case_id} removed: boundary tests for {tc.acceptance_criterion_id}'s limit are "
                         "generated automatically from the stated values")
    kept = [tc for tc in kept if tc not in model_bounds]

    # --- duplicates, mirrors and non-specific tests ----------------------------
    unique: list[TestScenario] = []
    by_sig: dict[str, TestScenario] = {}
    for tc in kept:
        sig = _sig(tc)
        twin = by_sig.get(sig) if sig else None
        if twin is not None:
            if twin.acceptance_criterion_id != tc.acceptance_criterion_id:
                why = f"same steps and data as {twin.test_case_id} (for {twin.acceptance_criterion_id}); not specific to its criterion"
            elif twin.test_type != tc.test_type:
                why = f"same steps and data as {twin.test_case_id}; only the expected result is reversed, which is not a valid {tc.test_type} test"
            else:
                why = f"duplicate of {twin.test_case_id}"
            rep.notes.append(f"{tc.test_case_id} removed: {why}")
            continue
        words = content_words(tc.title + " " + " ".join(tc.test_steps) + " " + " ".join(tc.test_data))
        near = next((u for u in unique if u.acceptance_criterion_id == tc.acceptance_criterion_id
                     and u.test_type == tc.test_type
                     and jaccard(words, content_words(u.title + " " + " ".join(u.test_steps) + " " + " ".join(u.test_data))) >= 0.85),
                    None)
        if near is not None:
            rep.notes.append(f"{tc.test_case_id} removed: near-duplicate of {near.test_case_id}")
            continue
        by_sig[sig] = tc
        unique.append(tc)
    out.test_scenarios = unique

    # --- boundary-value tests -----------------------------------------------
    add_boundary_tests(out, ctx, rep.notes)

    # --- "negative test not applicable" claims ---------------------------------
    na_by_ac: dict[str, str] = {}
    valid_na = []
    for na in out.not_applicable:
        ac = ac_by_id.get(na.acceptance_criterion_id) or ac_by_id.get(canon_to_ac.get(canon_id(na.acceptance_criterion_id), ""))
        if ac is None:
            rep.invalid_references.append(f"not_applicable entry referenced unknown criterion '{na.acceptance_criterion_id}'")
            continue
        text = f"{ac.description} {ac.then}"
        if numbers(text) or _CONSTRAINT_RE.search(text):
            rep.notes.append(f"'negative test not applicable' for {ac.id} rejected: the criterion has a constraint a negative test can violate")
            continue
        if len(na.reason.split()) < 4:
            rep.notes.append(f"'negative test not applicable' for {ac.id} rejected: no real reason given")
            continue
        if jaccard(content_words(na.reason), content_words(ac.description)) >= 0.5:
            rep.notes.append(f"'negative test not applicable' for {ac.id} rejected: the reason only restates the criterion")
            continue
        na.acceptance_criterion_id = ac.id
        na_by_ac[ac.id] = na.reason
        valid_na.append(na)
    out.not_applicable = valid_na

    # --- per-criterion assessment ---------------------------------------------
    rules_by_ac = {s.id: [s.rule] for s in ctx.seeds}
    limit_ac: dict[str, tuple[set[str], str]] = {}  # phrase -> (numbers, ac_id)
    for limit in ctx.limits:
        ac = _limit_ac(out, limit.numbers, limit.source)
        rep.boundaries.append(BoundaryStatus(limit.phrase, ac.id if ac else None, [], False))
        if ac:
            limit_ac[limit.phrase] = (limit.numbers, ac.id)
    for phrase in ctx.leftover_boundaries:
        ac = _limit_ac(out, numbers(phrase), phrase)
        rep.boundaries.append(BoundaryStatus(phrase, ac.id if ac else None, [], False))
        if ac:
            limit_ac[phrase] = (numbers(phrase), ac.id)

    valid_tests = [tc for tc in out.test_scenarios if tc.test_case_id not in rep.unsupported_tests]
    for b in rep.boundaries:
        if b.ac_id is None:
            rep.other_gaps.append(f"limit '{b.limit}' is not represented in any acceptance criterion")
            continue
        nums = limit_ac[b.limit][0]
        b.tests = [tc.test_case_id for tc in valid_tests if tc.acceptance_criterion_id == b.ac_id
                   and tc.test_type == "boundary" and nums <= numbers(" ".join(tc.test_data) + " " + tc.title)]
        b.covered = bool(b.tests)

    for ac in out.acceptance_criteria:
        a = Assessment(ac_id=ac.id, rules=rules_by_ac.get(ac.id, []))
        mine = [tc for tc in out.test_scenarios if tc.acceptance_criterion_id == ac.id]
        mine_valid = [tc for tc in mine if tc.test_case_id not in rep.unsupported_tests]
        a.tests = [tc.test_case_id for tc in mine]
        a.types = sorted({tc.test_type for tc in mine})
        a.has_positive = any(tc.test_type == "positive" for tc in mine_valid)
        a.has_negative = any(tc.test_type == "negative" for tc in mine_valid)
        if ac.id in na_by_ac:
            a.not_applicable.append(f"negative: {na_by_ac[ac.id]}")
        my_bounds = [b for b in rep.boundaries if b.ac_id == ac.id]
        a.boundary_required = bool(my_bounds)
        a.has_boundary = all(b.covered for b in my_bounds) if my_bounds else False
        text = f"{ac.description} {ac.then}"
        # Rule-seeded criteria are checked too: a vague business rule ("Overtime should be
        # handled correctly.") is explicit but untestable, so it must never become "validated".
        # judge description and outcome separately: joined, a short vague rule doubles in length
        # and stops counting as "short" (real bug: "Overtime should be handled correctly." validated)
        a.blocked_terms = sorted(set(blocking_terms(ac.description)) | set(blocking_terms(ac.then)))
        if _PLACEHOLDER_RE.search(text):
            a.blocked_terms.append("placeholder")
        if ac.id not in ctx.seed_ids and _PERF_RE.search(text) and not numbers(text):
            a.blocked_terms.append(PERFORMANCE_TERM)  # "within a specified response time"

        desc = ac.description if len(ac.description) <= 90 else ac.description[:87] + "..."
        pos_ids = [tc.test_case_id for tc in mine_valid if tc.test_type == "positive"]
        if a.blocked_terms:
            # Blocked by an unresolved ambiguity: never validated, whatever its source. The
            # missing/gap text naming the ambiguity IDs is added by finalize_blocked().
            a.status = "needs_clarification"
        elif ac.source == "assumption":
            a.status = "assumption"
        else:
            if not a.has_positive:
                a.missing.append("positive test")
                inside = f" Use a value inside the limit ({my_bounds[0].limit})." if my_bounds else ""
                rep.tasks.append(Task("positive", ac.id,
                    f"{ac.id} ('{desc}') has no positive test: write ONE positive test with valid input that satisfies it. "
                    f"Its expected result must be a success, not an error or rejection.{inside}",
                    summary=f"{ac.id} ('{desc}') has no valid positive test"))
            if not a.has_negative and not a.not_applicable:
                a.missing.append("negative test")
                avoid = f" Its steps or test_data must differ from {', '.join(pos_ids)}." if pos_ids else ""
                rep.tasks.append(Task("negative", ac.id,
                    f"{ac.id} ('{desc}') has no negative test: write ONE negative test that uses invalid input or a "
                    f"failure condition that violates it.{avoid} If no meaningful negative test can exist, add a "
                    f"not_applicable entry for {ac.id} with the reason instead.",
                    summary=f"{ac.id} ('{desc}') has no valid negative test"))
            for b in my_bounds:
                if not b.covered:
                    a.missing.append(f"boundary test for '{b.limit}'")
                    nums = ", ".join(sorted(limit_ac[b.limit][0], key=float))
                    rep.tasks.append(Task("boundary", ac.id,
                        f"{ac.id} has no boundary test for '{b.limit}': write ONE boundary test whose test_data covers "
                        f"the values just below, at, and just above {nums}.", detail=b.limit,
                        summary=f"{ac.id} has no boundary test for '{b.limit}'"))
            if not mine:
                a.status = "untested"
            elif a.missing:
                a.status = "partial"
            else:
                a.status = "validated"
        rep.assessments[ac.id] = a

    # Regenerate only if some criterion could actually be validated by tests. When every criterion is
    # blocked by an ambiguity or is an assumption, more tests cannot change the result - only
    # clarification can (real search run: a full regeneration was wasted on this).
    testable = any(a.status in ("untested", "partial", "validated") for a in rep.assessments.values())
    if testable and not any(not is_generated(tc) for tc in valid_tests):
        rep.errors.append("no valid test scenarios remain after validation")
    return rep


_BVA_RATIONALE = "Deterministic boundary-value analysis"


def is_generated(tc: TestScenario) -> bool:
    """True for boundary tests created by code rather than the model."""
    return tc.automation.rationale.startswith(_BVA_RATIONALE)


def finalize_blocked(rep: CheckReport, blocked_ids: dict[str, list[tuple[str, str]]]) -> None:
    """Write the SAME explanation into traceability.missing and coverage.gaps for every
    blocked criterion, naming the ambiguity IDs from traceability.blocked_by.

    blocked_ids: ac_id -> [(ambiguity_id, term), ...]
    """
    for ac_id, pairs in blocked_ids.items():
        a = rep.assessments[ac_id]
        if a.status != "needs_clarification" or not pairs:
            continue
        what = ", ".join(f"{amb} ({term})" for amb, term in pairs)
        a.missing = [f"clarification of {amb} ({term})" for amb, term in pairs]
        rep.other_gaps.append(f"{ac_id} cannot be validated until {what} is clarified")


def summarize(out: LLMOutput, rep: CheckReport, ctx: Context) -> dict:
    """Numbers for CoverageSummary (validated vs generated coverage)."""
    acs = out.acceptance_criteria
    explicit = [ac for ac in acs if ac.source == "explicit"]
    # Validated-coverage scope: explicit criteria PLUS criteria blocked by an ambiguity (e.g. a
    # placeholder for "fast"). Blocked items are requirement statements awaiting clarification;
    # leaving them out would let "1 of 1 validated = 100 %" hide the unresolved requirement.
    scope = [ac for ac in acs if ac.source == "explicit" or rep.assessments[ac.id].status == "needs_clarification"]
    validated = [ac for ac in scope if rep.assessments[ac.id].status == "validated"]
    generated = [ac for ac in acs if rep.assessments[ac.id].tests]
    rule_rows = []
    for rule in ctx.rules:
        ids = [s.id for s in ctx.seeds if s.rule == rule]
        statuses = [rep.assessments[i].status for i in ids if i in rep.assessments]
        if not statuses:
            status = "missing"
        elif all(s == "validated" for s in statuses):
            status = "validated"
        elif any(s in ("partial", "validated") for s in statuses):
            status = "partial"
        else:
            status = statuses[0]
        rule_rows.append({"rule": rule, "acceptance_criterion_ids": ids, "status": status})
    pct = lambda n, d: round(100.0 * n / d, 1) if d else 0.0  # noqa: E731
    return {
        "total_acceptance_criteria": len(acs),
        "covered_acceptance_criteria": len(generated),
        "coverage_percent": pct(len(validated), len(scope)),
        "scenarios_by_type": dict(Counter(tc.test_type for tc in out.test_scenarios)),
        "generated_coverage_percent": pct(len(generated), len(acs)),
        "validated_acceptance_criteria": len(validated),
        "blocked_acceptance_criteria": sum(rep.assessments[ac.id].status == "needs_clarification" for ac in acs),
        "assumption_criteria": len(acs) - len(explicit),
        "rule_coverage_percent": pct(sum(r["status"] == "validated" for r in rule_rows), len(rule_rows)) if rule_rows else None,
        "rule_coverage": rule_rows,
        "boundary_coverage": [
            {"limit": b.limit, "acceptance_criterion_id": b.ac_id, "test_case_ids": b.tests, "covered": b.covered}
            for b in rep.boundaries
        ],
        "invalid_references": rep.invalid_references,
        "gaps": rep.gaps,
    }
