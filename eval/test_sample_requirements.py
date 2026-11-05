"""Guards the evaluation dataset so a bad edit to sample requirements fails CI."""
import json
from pathlib import Path

from schemas import Requirement

DATA = Path(__file__).parent / "sample_requirements.json"


def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_all_requirements_match_schema():
    for item in load():
        item = {k: v for k, v in item.items() if k != "intentionally_ambiguous"}
        Requirement(**item)


def test_ids_are_unique():
    ids = [r["id"] for r in load()]
    assert len(ids) == len(set(ids))


def test_has_ambiguous_cases_for_clarification_eval():
    assert any(r.get("intentionally_ambiguous") for r in load())
