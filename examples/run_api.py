"""Call the pipeline from Python. The mock backend stays offline."""

from __future__ import annotations

from pathlib import Path

from mcw.llm.mock import MockGenerator
from mcw.pipeline import run_pipeline
from mcw.schema import load_brief

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    brief = load_brief(ROOT / "briefs" / "coffee-wechat.yaml")
    result = run_pipeline(
        brief,
        run_id="example-coffee",
        version="v1",
        generator=MockGenerator(),
        created_at="2026-11-08T00:00:00+00:00",
        reviewer=None,
        comment="初稿",
        approval_path=None,
        variants=3,
        brief_path="briefs/coffee-wechat.yaml",
    )
    best = next(
        score
        for draft, score in zip(result.drafts, result.scores)
        if draft.id == result.best_draft_id
    )
    print(result.best_draft_id, best.overall)
    print(result.facts.fact_lines[0])


if __name__ == "__main__":
    main()
