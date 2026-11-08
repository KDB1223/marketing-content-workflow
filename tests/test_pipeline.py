from __future__ import annotations

import json
from pathlib import Path

from mcw.llm.mock import MockGenerator
from mcw.pipeline import run_pipeline
from mcw.schema import load_brief
from mcw.scoring.rubric import OFFLINE_SCORE_NOTE
from mcw.store import persist_run, prepare_version


def test_mock_pipeline_for_every_brief(briefs_dir: Path, tmp_path: Path) -> None:
    for path in sorted(briefs_dir.iterdir()):
        if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
            continue
        brief = load_brief(path)
        version = prepare_version(tmp_path, brief.id, brief.id, "unused", continue_run=False)
        # prepare_version checks fingerprint only when continuing; fresh runs ignore it.
        result = run_pipeline(
            brief,
            run_id=brief.id,
            version=version,
            generator=MockGenerator(),
            created_at="2026-11-08T00:00:00+00:00",
            reviewer=None,
            comment="初稿",
            approval_path=None,
            variants=3,
            brief_path=str(path),
        )
        assert len({draft.text for draft in result.drafts}) == 3
        assert all(draft.char_count <= brief.max_chars for draft in result.drafts)
        assert all(checklist.passed for checklist in result.checklists)
        assert all(score.overall == 100 for score in result.scores)
        assert all("【声明】" in draft.text for draft in result.drafts)
        directory = persist_run(tmp_path, result)
        report = (directory / "report.md").read_text(encoding="utf-8")
        assert OFFLINE_SCORE_NOTE in report
        assert "事实清单" in report
        prompts = json.loads((directory / "prompts.json").read_text(encoding="utf-8"))
        assert prompts["backend"] == "mock"
        assert "绝对化" in prompts["system"]
        scores = json.loads((directory / "scores.json").read_text(encoding="utf-8"))
        assert scores["not_business_conversion"] is True
        assert (directory / "versions" / "v1" / "checklist.json").is_file()


def test_revision_comment_is_auditable(briefs_dir: Path, tmp_path: Path) -> None:
    path = briefs_dir / "creditcard-official.yaml"
    brief = load_brief(path)
    from mcw.schema import brief_fingerprint

    run_id = "card-demo"
    created = "2026-11-08T00:00:00+00:00"
    version = prepare_version(tmp_path, run_id, brief.id, brief_fingerprint(brief), continue_run=False)
    first = run_pipeline(
        brief,
        run_id=run_id,
        version=version,
        generator=MockGenerator(),
        created_at=created,
        reviewer=None,
        comment="初稿",
        approval_path=None,
        variants=2,
        brief_path=str(path),
    )
    persist_run(tmp_path, first)
    assert "修订回应" not in first.drafts[0].text
    second_version = prepare_version(
        tmp_path, run_id, brief.id, brief_fingerprint(brief), continue_run=True
    )
    assert second_version == "v2"
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "status": "approved",
                "reviewer": "林可",
                "comment": "声明还在，可以上官网。",
                "draft_id": "A",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second = run_pipeline(
        brief,
        run_id=run_id,
        version=second_version,
        generator=MockGenerator(),
        created_at="2026-11-08T01:00:00+00:00",
        reviewer="林可",
        comment="删掉口头禅，保留审批声明",
        approval_path=approval,
        variants=2,
        brief_path=str(path),
    )
    persist_run(tmp_path, second)
    assert "修订回应：删掉口头禅，保留审批声明" in second.drafts[0].text
    assert second.approval.status == "approved"
    assert second.approval.draft_id == "v2-a"
    history = json.loads((tmp_path / "runs" / run_id / "versions.json").read_text(encoding="utf-8"))
    assert [item["version"] for item in history["versions"]] == ["v1", "v2"]
    assert history["versions"][1]["comment"] == "删掉口头禅，保留审批声明"
    root_drafts = json.loads((tmp_path / "runs" / run_id / "drafts.json").read_text(encoding="utf-8"))
    assert root_drafts["version"] == "v2"


def test_continue_rejects_a_different_brief(briefs_dir: Path, tmp_path: Path) -> None:
    from mcw.schema import brief_fingerprint

    first_path = briefs_dir / "sunscreen-xhs.yaml"
    other_path = briefs_dir / "coffee-wechat.yaml"
    brief = load_brief(first_path)
    run_id = "mixed"
    version = prepare_version(tmp_path, run_id, brief.id, brief_fingerprint(brief), continue_run=False)
    result = run_pipeline(
        brief,
        run_id=run_id,
        version=version,
        generator=MockGenerator(),
        created_at="2026-11-08T00:00:00+00:00",
        reviewer=None,
        comment=None,
        approval_path=None,
        variants=1,
        brief_path=str(first_path),
    )
    persist_run(tmp_path, result)
    other = load_brief(other_path)
    import pytest
    from mcw.errors import MCWError

    with pytest.raises(MCWError, match="Brief 与初次不一致"):
        prepare_version(tmp_path, run_id, other.id, brief_fingerprint(other), continue_run=True)
