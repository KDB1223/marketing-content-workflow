"""Bundled drafts used by ``mcw score --fixtures``."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from mcw.models import ExtractedFacts
from mcw.scoring.rubric import score_text


def load_cases() -> list[dict[str, Any]]:
    raw = files("mcw.fixtures").joinpath("cases.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("fixtures/cases.json 缺少 cases 数组")
    return cases


def score_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in load_cases():
        facts = ExtractedFacts.from_dict(case["facts"])
        card = score_text(case["draft"], facts)
        actual = {**card.dimension_map(), "overall": card.overall}
        expect = case.get("expect")
        matched = expect == actual
        rows.append(
            {
                "id": case["id"],
                "description": case.get("description", ""),
                "actual": actual,
                "expect": expect,
                "matched": matched,
                "note": card.to_dict()["note"],
            }
        )
    return rows
