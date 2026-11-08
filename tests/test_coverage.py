"""Unit tests for the deterministic coverage checker (llm_pipeline/coverage.py) and limit parsing."""

from __future__ import annotations

import pytest

from llm_pipeline.ambiguity import detect_ambiguities, merge_ambiguities, parse_limits
from llm_pipeline.coverage import (
    Context,
    _seed_score,
    content_words,
    numbers,
    same_criterion,
    seed_criteria,
    split_rule_clauses,
)
from llm_pipeline.schemas import AcceptanceCriterion, Ambiguity, RequirementInput


@pytest.mark.parametrize("rule, clauses", [
    ("The new password must be between 8 and 64 characters and contain at least 1 digit.",
     ["The new password must be between 8 and 64 characters.", "The new password must contain at least 1 digit."]),
    ("Usernames must be unique and cannot contain spaces.",
     ["Usernames must be unique.", "Usernames cannot contain spaces."]),
    ("The file must be a PDF and be at most 10 MB.", ["The file must be a PDF.", "The file must be at most 10 MB."]),
    ("Orders between 10 and 20 items get a discount.", ["Orders between 10 and 20 items get a discount."]),
    ("A user can request at most 3 reset emails per hour", ["A user can request at most 3 reset emails per hour."]),
])
def test_split_rule_clauses(rule, clauses):
    assert split_rule_clauses(rule) == clauses


def test_seeds_are_numbered_per_clause():
    seeds = seed_criteria(["Rule A must hold.", "The password must be between 8 and 64 characters and contain at least 1 digit."])
    assert [(s.id, s.rule[:6]) for s in seeds] == [("AC-1", "Rule A"), ("AC-2", "The pa"), ("AC-3", "The pa")]


@pytest.mark.parametrize("text, kind, values", [
    ("Passwords must be between 8 and 64 characters.", "range",
     ["7 characters -> rejected", "8 characters -> accepted", "64 characters -> accepted", "65 characters -> rejected"]),
    ("A user can add at most 3 items.", "max", ["2 items -> accepted", "3 items -> accepted", "4 items -> rejected"]),
    ("The password must contain at least 1 digit.", "min", ["0 digits -> rejected", "1 digit -> accepted", "2 digits -> accepted"]),
    ("Accounts with more than 5 failures are flagged.", "xmin",
     ["5 failures -> does not satisfy the condition", "6 failures -> satisfies the condition"]),
    ("Files must be less than 10 MB.", "xmax", ["9 MB -> satisfies the condition", "10 MB -> does not satisfy the condition"]),
    ("The reset link expires 30 minutes after it is sent.", "threshold",
     ["29 minutes -> before the limit", "30 minutes -> exactly at the limit - expected behaviour must be clarified",
      "31 minutes -> after the limit"]),
])
def test_parse_limits_and_boundary_values(text, kind, values):
    (limit,) = parse_limits(RequirementInput(description=text))
    assert limit.kind == kind
    assert limit.test_values() == values
    assert limit.source == text


def test_no_limits_without_numbers_and_bare_numbers_are_not_directional():
    assert parse_limits(RequirementInput(description="The search should be fast and user-friendly.")) == []
    assert parse_limits(RequirementInput(description="The account is locked after 5 attempts.")) == []
    ctx = Context.from_requirement(RequirementInput(description="The account is locked after 5 attempts."))
    assert ctx.leftover_boundaries == ["5 attempts"]  # -> the LLM must write this boundary test


def test_numbers_ignore_ids_and_allowed_numbers_include_neighbours():
    assert numbers("AC-1 and TC-004 for REQ-101 allow 8 to 64 chars") == {"8", "64"}
    ctx = Context.from_requirement(RequirementInput(requirement_id="REQ-101", description="Passwords must be 8 to 64 characters long."))
    assert {"7", "8", "9", "63", "64", "65"} <= ctx.allowed_numbers and "2" not in ctx.allowed_numbers


def test_content_words_strip_plurals():
    assert content_words("Returns relevant categories and brands") == {"return", "relevant", "category", "brand"}


def _ac(text):
    return AcceptanceCriterion(id="AC-9", description=text, given="g", when="w", then=text)


def test_rule_matching_needs_the_same_numbers_and_topic():
    seeds = {s.text: s for s in seed_criteria([
        "The new password must be between 8 and 64 characters.", "A user can request at most 3 reset emails per hour."])}
    length, rate = list(seeds.values())
    assert _seed_score(_ac("A valid 8-character password is accepted."), length) > 0     # fragment of the rule
    assert _seed_score(_ac("A password with more than 64 characters is rejected."), length) > 0
    assert _seed_score(_ac("The password must have at least 3 characters."), rate) == 0  # same number, other topic
    assert _seed_score(_ac("Users can log out."), length) == 0


def test_same_criterion():
    assert same_criterion("The search returns relevant products, categories and brands.",
                          "Search returns relevant product, category and brand.")
    assert not same_criterion("Password must be 8 characters.", "Password must be 9 characters.")


def test_vague_term_ambiguities_are_deduplicated_across_rule_and_llm():
    req = RequirementInput(description="The search should be fast and user-friendly and return relevant products etc.")
    rule = detect_ambiguities(req)
    llm = [
        Ambiguity(id="AMB-1", text="fast", issue="speed undefined", clarification_question="How fast?", source="llm"),
        Ambiguity(id="AMB-2", text="ranking", issue="sort order undefined", clarification_question="Order?", source="llm"),
    ]
    merged = merge_ambiguities(rule, llm)
    assert sum(a.text == "fast" for a in merged) == 0                 # LLM duplicate of the 'fast' rule finding dropped
    assert any(a.text == "ranking" for a in merged)                    # new LLM finding kept
    assert [a.id for a in merged] == [f"AMB-{i}" for i in range(1, len(merged) + 1)]


def test_threshold_limit_creates_inclusivity_ambiguity():
    amb = detect_ambiguities(RequirementInput(description="The reset link expires 30 minutes after it is sent to the user."))
    assert any("exactly 30 minutes" in a.issue for a in amb)
