"""The generation pipeline.

    Requirement input
      -> 1. Requirement validation          (validation.py)
      -> 2. Static analysis                 (ambiguity.py, coverage.Context: rule clauses -> seeded criteria,
                                             numeric limits, ambiguities)
      -> 3. LLM generation                  (prompts.py + llm_client.py)
      -> 4. JSON parsing / recovery         (parsing.py, incl. salvage of truncated output)
      -> 5. Schema validation               (schemas.LLMOutput; single invalid tests dropped)
      -> 6. Rule anchoring + grounding      (coverage.align_criteria / ground_criteria)
      -> 7. Validation + coverage check     (coverage.check_output -> precise tasks)
      -> 8. Bounded repair:
              * unusable output -> full regeneration with a repair prompt (max_attempts)
              * coverage tasks  -> small supplement requests, a few tasks each
                                   (max_supplement_rounds); a usable draft is never discarded
      -> 9. Final structured GenerationResult (traceability, validated vs generated
            coverage, remaining gaps, automation summary)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .ambiguity import detect_ambiguities, merge_ambiguities_with_map
from .config import LLMSettings, get_settings
from .coverage import (
    PERFORMANCE_TERM,
    PERFORMANCE_WORDS,
    REJECTION_RE,
    CheckReport,
    Context,
    Task,
    align_criteria,
    canon_id,
    check_output,
    drop_template_echoes,
    finalize_blocked,
    ground_criteria,
    id_number,
    summarize,
)
from .errors import (
    EmptyResponseError,
    GenerationFailedError,
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    OutputParseError,
)
from .llm_client import ChatMessage, LLMClient, OllamaClient, inline_json_schema_refs
from .parsing import parse_llm_json, salvage_truncated_json
from .prompts import (
    MAX_ACCEPTANCE_CRITERIA,
    MAX_AMBIGUITIES,
    MAX_ASSUMPTIONS,
    MAX_EXTRA_CRITERIA,
    MAX_TASK_ATTEMPTS,
    MAX_TASKS_PER_SUPPLEMENT,
    MAX_TEST_SCENARIOS,
    PROMPT_VERSION,
    SUPPLEMENT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_repair_prompt,
    build_supplement_prompt,
    build_user_prompt,
)
from .schemas import (
    Ambiguity,
    AutomationSummary,
    CoverageSummary,
    EdgeCase,
    GenerationMetadata,
    GenerationResult,
    LLMOutput,
    RequirementInput,
    SupplementOutput,
    TestScenario,
    TraceabilityLink,
)
from .validation import validate_requirement

logger = logging.getLogger(__name__)

_SCENARIO_REQUIRED = [
    "test_case_id", "title", "requirement_id", "acceptance_criterion_id", "test_type",
    "test_steps", "expected_result", "priority", "automation",
]
_AC_REQUIRED = ["id", "description", "given", "when", "then", "source"]


def _decoding_schema(model: type, caps: dict[str, int]) -> dict[str, Any]:
    """JSON schema sent to Ollama for constrained decoding.

    Stricter than the Pydantic validation on purpose: every top-level key is
    required (so the model cannot skip "ambiguities"), and list sizes are
    capped with maxItems (so answers fit the token budget).
    """
    schema = inline_json_schema_refs(model.model_json_schema())
    props = schema["properties"]
    schema["required"] = list(props)
    for key, cap in caps.items():
        props[key]["maxItems"] = cap
    if "test_scenarios" in props:
        props["test_scenarios"]["items"]["required"] = _SCENARIO_REQUIRED
    if "acceptance_criteria" in props:
        props["acceptance_criteria"]["items"]["required"] = _AC_REQUIRED
    return schema


def build_output_schema(max_criteria: int = MAX_ACCEPTANCE_CRITERIA) -> dict[str, Any]:
    return _decoding_schema(LLMOutput, {
        "ambiguities": MAX_AMBIGUITIES,
        "assumptions": MAX_ASSUMPTIONS,
        "acceptance_criteria": max_criteria,
        "test_scenarios": MAX_TEST_SCENARIOS,
        "not_applicable": max_criteria,
    })


LLM_OUTPUT_JSON_SCHEMA = build_output_schema()


def _format_validation_error(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:15]]


def validate_scenarios_leniently(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop individual invalid test scenarios instead of rejecting everything.

    Regenerating a whole answer costs minutes on a laptop; losing one broken
    test (reported in warnings, and re-requested by the coverage check) is
    cheaper. If *every* scenario is invalid, the data is returned unchanged so
    schema validation fails and triggers a retry.
    """
    scenarios = data.get("test_scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return data, []
    good, notes = [], []
    for i, s in enumerate(scenarios, start=1):
        try:
            TestScenario.model_validate(s)
            good.append(s)
        except ValidationError as exc:
            sid = s.get("test_case_id", f"#{i}") if isinstance(s, dict) else f"#{i}"
            notes.append(f"dropped invalid test scenario {sid}: {_format_validation_error(exc)[0]}")
    if not good or len(good) == len(scenarios):
        return data, []
    return {**data, "test_scenarios": good}, notes


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


@dataclass
class _Draft:
    out: LLMOutput
    report: CheckReport
    notes: list[str]  # notes accumulated across all calls


class _RetryableQualityError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class GenerationPipeline:
    def __init__(self, client: LLMClient | None = None, settings: LLMSettings | None = None):
        self.settings = settings or get_settings()
        self.client: LLMClient = client or OllamaClient(self.settings)

    async def _call(self, messages: list[ChatMessage], schema: dict[str, Any]):
        # Outer timeout is a safety net in case the client itself hangs.
        return await asyncio.wait_for(
            self.client.chat(messages, json_schema=schema),
            timeout=self.settings.request_timeout_s + 5,
        )

    @staticmethod
    def _parse(content: str, truncated: bool, notes: list[str]) -> dict[str, Any]:
        try:
            return parse_llm_json(content)
        except OutputParseError:
            if not truncated:
                raise
            notes.append("model output hit the token limit; incomplete trailing items were discarded")
            return salvage_truncated_json(content)

    async def generate(self, requirement: RequirementInput) -> GenerationResult:
        started = time.perf_counter()

        # 1. validation (raises InvalidRequirementError -> HTTP 422)
        req = validate_requirement(requirement)

        # 2. static analysis
        rule_ambiguities = detect_ambiguities(req)
        ctx = Context.from_requirement(req)

        base_messages = [
            ChatMessage("system", SYSTEM_PROMPT),
            ChatMessage("user", build_user_prompt(req, rule_ambiguities, ctx)),
        ]
        schema = build_output_schema(max(MAX_ACCEPTANCE_CRITERIA, len(ctx.seeds) + MAX_EXTRA_CRITERIA))
        messages = list(base_messages)
        history: list[str] = []
        calls = 0
        draft: _Draft | None = None
        fallback: _Draft | None = None  # usable criteria, but every model-written test was invalid

        # ---- phase 1: full generation, retried only if the output is unusable --
        for attempt in range(1, self.settings.max_attempts + 1):
            calls += 1
            raw: str | None = None
            truncated = False
            try:
                resp = await self._call(messages, schema)
                raw, truncated = resp.content, resp.truncated
                notes: list[str] = []
                data, dropped = validate_scenarios_leniently(self._parse(raw, truncated, notes))
                notes += dropped
                out = LLMOutput.model_validate(data)
                drop_template_echoes(out, notes)  #    text copied from the prompt's JSON shape
                align_criteria(out, ctx, notes)   # 6. rule anchoring
                ground_criteria(out, ctx, notes)  #    grounding
                report = check_output(out, ctx)   # 7. validation + coverage
                if report.errors:
                    fallback = _Draft(out, report, notes + report.notes)
                    # tell the model WHY each test was rejected, otherwise it repeats the same mistakes
                    removed = [n for n in report.notes if " removed: " in n][:8]
                    raise _RetryableQualityError(report.errors + removed + report.invalid_references[:5])
                draft = _Draft(out, report, notes + report.notes)
                break
            except LLMUnavailableError:
                raise  # Ollama down / model missing: retrying will not help
            except (asyncio.TimeoutError, LLMTimeoutError):
                history.append(f"call {calls}: LLM timed out after {self.settings.request_timeout_s:.0f}s")
                messages = list(base_messages)
            except EmptyResponseError:
                history.append(f"call {calls}: empty response")
                messages = [*base_messages, ChatMessage("user", build_repair_prompt(["your response was empty"]))]
            except OutputParseError as exc:
                history.append(f"call {calls}: invalid JSON ({'; '.join(exc.details)})")
                messages = self._repair(base_messages, raw, ["response was not valid JSON", *exc.details], truncated)
            except ValidationError as exc:
                errs = _format_validation_error(exc)
                history.append(f"call {calls}: schema validation failed ({'; '.join(errs[:5])})")
                messages = self._repair(base_messages, raw, errs, truncated)
            except _RetryableQualityError as exc:
                history.append(f"call {calls}: quality check failed ({'; '.join(exc.problems[:5])})")
                messages = self._repair(base_messages, raw, exc.problems, truncated)
            except LLMError as exc:
                history.append(f"call {calls}: LLM error ({exc.message})")
                messages = list(base_messages)
            logger.warning("generation %s", history[-1])

        if draft is None and fallback is not None:
            # The criteria are usable; missing tests are requested per criterion in phase 2
            # instead of failing the whole request.
            draft = fallback
            draft.notes.append(f"no valid model-written test after {self.settings.max_attempts} generation "
                               "attempts; tests are requested per criterion instead")
        if draft is None:
            raise GenerationFailedError(
                f"Could not generate valid output after {self.settings.max_attempts} attempts",
                attempts=self.settings.max_attempts,
                details=history,
            )

        # ---- phase 2: targeted supplements for the exact missing coverage -----
        tries: Counter = Counter()           # task key -> times asked
        feedback: dict[tuple[str, str], str] = {}  # (kind, ac_id) -> why the last attempt was rejected
        for _ in range(self.settings.max_supplement_rounds):
            pending = sorted((t for t in draft.report.tasks if tries[t.key] < MAX_TASK_ATTEMPTS),
                             key=lambda t: tries[t.key])  # never-asked tasks first
            if not pending:
                break
            batch = pending[:MAX_TASKS_PER_SUPPLEMENT]
            asked = [Task(t.kind, t.ac_id, t.text + (f" Previous attempt rejected: {feedback[(t.kind, t.ac_id)]}."
                                                       if (t.kind, t.ac_id) in feedback else ""), t.detail, t.summary)
                     for t in batch]
            calls += 1
            logger.info("supplement round for %d task(s): %s", len(batch), [f"{t.kind}:{t.ac_id}" for t in batch])
            try:
                draft, fb = await self._supplement(draft, ctx, asked)
                feedback.update(fb)
            except LLMUnavailableError as exc:
                history.append(f"call {calls}: LLM unavailable during supplement ({exc.message})")
                break  # keep the draft we already have
            except (asyncio.TimeoutError, LLMTimeoutError):
                history.append(f"call {calls}: supplement timed out after {self.settings.request_timeout_s:.0f}s")
            except (LLMError, ValidationError) as exc:
                history.append(f"call {calls}: supplement rejected ({str(exc)[:200]})")
            for t in batch:
                tries[t.key] += 1
            if history and history[-1].startswith(f"call {calls}:"):
                logger.warning("generation %s", history[-1])

        result = self._build_result(req, ctx, draft, rule_ambiguities, calls, started)
        # logged after building the result: blocked-criterion gaps are only named there
        logger.info("generation finished after %d call(s); %d gap(s) remain", calls, len(result.coverage.gaps))
        return result

    async def _supplement(
        self, draft: _Draft, ctx: Context, tasks: list[Task]
    ) -> tuple[_Draft, dict[tuple[str, str], str]]:
        """Ask for exactly ``tasks``, merge what fills them, and re-validate everything.

        Returns the new draft and, for every task that is still open, a short
        reason that is shown to the model if the task is asked again."""
        out = draft.out
        next_n = max((id_number(tc.test_case_id) for tc in out.test_scenarios), default=0) + 1
        n_neg = sum(t.kind == "negative" for t in tasks)
        messages = [
            ChatMessage("system", SUPPLEMENT_SYSTEM_PROMPT),
            ChatMessage("user", build_supplement_prompt(ctx.requirement_id, out.acceptance_criteria,
                                                        out.test_scenarios, tasks, next_n)),
        ]
        schema = _decoding_schema(SupplementOutput, {"test_scenarios": len(tasks), "not_applicable": max(1, n_neg)})
        resp = await self._call(messages, schema)
        notes = list(draft.notes)
        data, dropped = validate_scenarios_leniently(self._parse(resp.content, resp.truncated, notes))
        notes += dropped
        supp = SupplementOutput.model_validate(data)

        merged = out.model_copy(deep=True)
        ac_by_canon = {canon_id(ac.id): ac.id for ac in merged.acceptance_criteria}
        open_tasks = {(t.kind, t.ac_id) for t in tasks}
        feedback: dict[tuple[str, str], str] = {}
        new_ids: dict[str, tuple[str, str]] = {}  # new test id -> task it fills
        added = ignored = 0
        for tc in supp.test_scenarios:
            ac_id = ac_by_canon.get(canon_id(tc.acceptance_criterion_id))
            if ac_id is None:
                notes.append(f"supplement test '{tc.title}' ignored: unknown criterion '{tc.acceptance_criterion_id}'")
                continue
            if tc.test_type == "positive" and REJECTION_RE.search(tc.expected_result):
                if ("positive", ac_id) in open_tasks:
                    feedback[("positive", ac_id)] = (f"your test '{tc.title[:50]}' expected an error or rejection, so it "
                                                     "is a negative test; a positive test must end in success")
                tc = tc.model_copy(update={"test_type": "negative"})
            if (tc.test_type, ac_id) not in open_tasks:
                ignored += 1  # small models pad answers; keep only what fills a task
                for kind, task_ac in open_tasks:
                    if task_ac == ac_id and (kind, ac_id) not in feedback:
                        feedback[(kind, ac_id)] = f"you wrote a {tc.test_type} test for {ac_id}, but a {kind} test was requested"
                continue
            open_tasks.discard((tc.test_type, ac_id))
            new_id = f"TC-{next_n:03d}"
            new_ids[new_id] = (tc.test_type, ac_id)
            merged.test_scenarios.append(tc.model_copy(update={
                "test_case_id": new_id, "acceptance_criterion_id": ac_id, "requirement_id": ctx.requirement_id}))
            next_n += 1
            added += 1
        for na in supp.not_applicable:
            ac_id = ac_by_canon.get(canon_id(na.acceptance_criterion_id))
            if ac_id and ("negative", ac_id) in open_tasks:
                merged.not_applicable.append(na.model_copy(update={"acceptance_criterion_id": ac_id}))
        if added:
            notes.append(f"{added} test scenario(s) added by a targeted coverage request")
        if ignored:
            notes.append(f"{ignored} supplement test(s) ignored because they did not match a requested task")

        report = check_output(merged, ctx)  # re-validate EVERYTHING, not just the new tests
        if report.errors:
            raise LLMError(f"merged supplement failed checks: {report.errors}")
        # findings about items removed in earlier rounds must not disappear from the final report
        report.invalid_references = _dedupe(draft.report.invalid_references + report.invalid_references)

        # explain to the model why a test it wrote for a task did not survive validation
        kept_ids = {t.test_case_id for t in merged.test_scenarios} - set(report.unsupported_tests)
        for new_id, key in new_ids.items():
            if new_id not in kept_ids:
                why = next((n for n in report.notes if n.startswith(new_id)), f"{new_id} was rejected by validation")
                feedback[key] = why.replace(new_id, "your test", 1)
        still_open = {(t.kind, t.ac_id) for t in report.tasks}
        for t in tasks:
            if (t.kind, t.ac_id) in still_open:
                feedback.setdefault((t.kind, t.ac_id), "no usable test was returned for this task")
        return _Draft(merged, report, notes + report.notes), {k: v for k, v in feedback.items() if k in still_open}

    @staticmethod
    def _repair(base: list[ChatMessage], raw: str | None, errors: list[str], truncated: bool) -> list[ChatMessage]:
        msgs = list(base)
        if raw and not truncated:
            msgs.append(ChatMessage("assistant", raw[:6000]))
        msgs.append(ChatMessage("user", build_repair_prompt(errors, truncated=truncated)))
        return msgs

    def _build_result(
        self,
        req: RequirementInput,
        ctx: Context,
        draft: _Draft,
        rule_ambiguities: list[Ambiguity],
        calls: int,
        started: float,
    ) -> GenerationResult:
        out, rep = draft.out, draft.report
        llm_amb = [a.model_copy(update={"source": "llm"}) for a in out.ambiguities]
        ambiguities, amb_map = merge_ambiguities_with_map(rule_ambiguities, llm_amb)

        # The model's AMB-n references (placeholders, assumption reasons) must point at the FINAL ids.
        def remap_refs(text: str) -> str:
            # a reference to an ambiguity the model never defined is marked unknown, not left
            # pointing at whatever ambiguity happens to get that number after renumbering
            return re.sub(r"\bAMB-\d+\b", lambda m: amb_map.get(m.group(0), "AMB-?"), text)

        for ac in out.acceptance_criteria:
            ac.description, ac.given, ac.when, ac.then = (remap_refs(x) for x in (ac.description, ac.given, ac.when, ac.then))
        for asm in out.assumptions:
            asm.statement, asm.reason = remap_refs(asm.statement), remap_refs(asm.reason)

        # Link criteria that are not measurable to the ambiguity that blocks them.
        blocked: dict[str, list[str]] = {}
        pairs: dict[str, list[tuple[str, str]]] = {}
        for ac in out.acceptance_criteria:
            a = rep.assessments[ac.id]
            ids: list[str] = []
            pairs[ac.id] = []
            # placeholders last: they usually stand for a vague term that is matched first
            for term in sorted(a.blocked_terms, key=lambda t: t == "placeholder"):
                if term == "placeholder":
                    refs = re.findall(r"AMB-\d+", f"{ac.description} {ac.then}")
                    if ids:
                        # The placeholder's topic already matched an ambiguity (e.g. "response time" ->
                        # 'fast'). A reference to a DIFFERENT ambiguity is the model's numbering mistake
                        # (real output: "[response time to be confirmed - AMB-1]" with AMB-1 = 'user-friendly').
                        wrong = [ref for ref in refs if ref not in ids]
                        if wrong:
                            fix = lambda t: re.sub(r"\bAMB-\d+\b", lambda m: ids[0] if m.group(0) in wrong else m.group(0), t)  # noqa: E731
                            ac.description, ac.then = fix(ac.description), fix(ac.then)
                            for asm in out.assumptions:
                                if asm.statement.startswith(f"{ac.id}:"):
                                    asm.statement = fix(asm.statement)
                            draft.notes.append(f"{ac.id}: placeholder referenced {', '.join(wrong)}, which is about a "
                                               f"different topic; reference corrected to {ids[0]}")
                        continue
                    match = [x.id for x in ambiguities if x.id in refs]
                elif term == PERFORMANCE_TERM:
                    match = [x.id for x in ambiguities if any(w in x.issue.lower() for w in PERFORMANCE_WORDS)][:1]
                else:
                    # prefer the finding that NAMES the term ("Vague, unmeasurable term 'relevant'");
                    # a negated form ("irrelevant") maps to the base term's finding
                    names = [term] + [term[len(p):] for p in ("ir", "un", "in") if term.startswith(p)]
                    match = ([x.id for n in names for x in ambiguities if f"'{n}'" in x.issue.lower()]
                             or [x.id for x in ambiguities if x.text.lower().strip() == term]
                             or [x.id for x in ambiguities if term in x.issue.lower()])[:1]
                if not match:
                    new = Ambiguity(
                        id=f"AMB-{len(ambiguities) + 1}",
                        text=term if term != "placeholder" else ac.description,
                        issue=f"{ac.id} is not measurable: "
                              + (f"it uses the vague term '{term}'." if term != "placeholder" else "it contains an unresolved placeholder."),
                        clarification_question=f"What measurable value should {ac.id} use?",
                        severity="medium",
                        source="rule",
                    )
                    ambiguities.append(new)
                    match = [new.id]
                label = "unresolved placeholder" if term == "placeholder" else term
                for m in match:
                    if m not in ids:
                        ids.append(m)
                        pairs[ac.id].append((m, label))
            blocked[ac.id] = ids
        finalize_blocked(rep, pairs)  # same wording in traceability.missing and coverage.gaps

        links = []
        for ac in out.acceptance_criteria:
            a = rep.assessments[ac.id]
            links.append(TraceabilityLink(
                requirement_id=ctx.requirement_id,
                acceptance_criterion_id=ac.id,
                acceptance_criterion=ac.description,
                test_case_ids=a.tests,
                test_types=a.types,
                covered=bool(a.tests),
                business_rules=a.rules,
                has_positive=a.has_positive,
                has_negative=a.has_negative,
                boundary_required=a.boundary_required,
                has_boundary=a.has_boundary,
                not_applicable=a.not_applicable,
                blocked_by=blocked[ac.id],
                status=a.status,
                missing=a.missing,
            ))
        coverage = CoverageSummary(**summarize(out, rep, ctx))

        edge_cases = [
            EdgeCase(test_case_id=tc.test_case_id, acceptance_criterion_id=tc.acceptance_criterion_id,
                     test_type=tc.test_type, description=tc.title, expected_result=tc.expected_result)  # type: ignore[arg-type]
            for tc in out.test_scenarios if tc.test_type in ("boundary", "edge_case")
        ]

        auto = [tc for tc in out.test_scenarios if tc.automation.automatable and tc.automation.level != "manual"]
        by_level = Counter(tc.automation.level for tc in out.test_scenarios)
        tools = [t for t, _ in Counter(tc.automation.suggested_tool for tc in auto if tc.automation.suggested_tool).most_common()]
        manual = len(out.test_scenarios) - len(auto)
        level_txt = ", ".join(f"{n} at {lvl} level" for lvl, n in by_level.most_common() if lvl != "manual")
        recommendation = (
            f"Automate {len(auto)} of {len(out.test_scenarios)} scenarios"
            + (f" ({level_txt})" if level_txt else "")
            + (f" using {', '.join(tools[:3])}" if tools else "")
            + (f"; keep {manual} as manual/exploratory checks." if manual else ".")
        )

        warnings = _dedupe(draft.notes + rep.invalid_references + [f"remaining gap: {g}" for g in rep.gaps])
        return GenerationResult(
            requirement_id=ctx.requirement_id,
            title=req.title,
            original_requirement=req.full_text(),
            needs_clarification=any(a.severity == "high" for a in ambiguities)
            or any(link.status == "needs_clarification" for link in links),
            ambiguities=ambiguities,
            assumptions=out.assumptions,
            acceptance_criteria=out.acceptance_criteria,
            test_scenarios=out.test_scenarios,
            edge_cases=edge_cases,
            traceability=links,
            coverage=coverage,
            automation_recommendations=AutomationSummary(
                automatable_count=len(auto), manual_count=manual, by_level=dict(by_level),
                suggested_tools=tools, recommendation=recommendation,
            ),
            metadata=GenerationMetadata(
                model=self.client.model,
                prompt_version=PROMPT_VERSION,
                attempts=calls,
                duration_ms=int((time.perf_counter() - started) * 1000),
                warnings=warnings,
            ),
        )
