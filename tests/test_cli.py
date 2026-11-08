from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcw.cli import main
from mcw.scoring.rubric import OFFLINE_SCORE_NOTE


def test_offline_commands(briefs_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "artifacts"
    code = main(
        [
            "run",
            str(briefs_dir / "sunscreen-xhs.yaml"),
            "--mock",
            "--run-id",
            "demo-sunscreen",
            "--out",
            str(out),
            "--variants",
            "3",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "run_id: demo-sunscreen" in captured.out
    assert "离线内容分" in captured.out
    root = out / "runs" / "demo-sunscreen"
    drafts = json.loads((root / "drafts.json").read_text(encoding="utf-8"))
    checklist = json.loads((root / "checklist.json").read_text(encoding="utf-8"))
    assert len(drafts["drafts"]) == 3
    assert len(checklist["items"]) == 3
    assert (root / "report.md").is_file()
    assert OFFLINE_SCORE_NOTE in (root / "report.md").read_text(encoding="utf-8")

    code = main(["score", "--fixtures"])
    assert code == 0
    scored = capsys.readouterr().out
    assert "clean-xiaohongshu" in scored
    assert "| ok" in scored

    code = main(["score", "--run", "demo-sunscreen", "--version", "v1", "--out", str(out)])
    assert code == 0
    assert "总分100" in capsys.readouterr().out.replace(" ", "")

    code = main(
        [
            "run",
            str(briefs_dir / "sunscreen-xhs.yaml"),
            "--mock",
            "--continue-run",
            "demo-sunscreen",
            "--out",
            str(out),
            "--reviewer",
            "林可",
            "--comment",
            "保留声明",
            "--approval",
            str(Path(__file__).parents[1] / "examples" / "approval-approved.json"),
        ]
    )
    assert code == 0
    capsys.readouterr()
    code = main(["list-versions", "demo-sunscreen", "--out", str(out)])
    assert code == 0
    listing = capsys.readouterr().out
    assert "v1" in listing and "v2" in listing
    assert "保留声明" in listing
    assert "approved" in listing

    code = main(
        ["compare", "demo-sunscreen", "--left", "v1", "--right", "v2", "--out", str(out)]
    )
    assert code == 0
    compared = capsys.readouterr().out
    assert "版本对照" in compared
    assert "不能当成转化提升" in compared
    assert (root / "compare-v1-v2.md").is_file()


def test_score_single_draft(briefs_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    draft = tmp_path / "draft.txt"
    draft.write_text("只有一句话，没有卖点。\n", encoding="utf-8")
    code = main(
        [
            "score",
            "--brief",
            str(briefs_dir / "fitness-douyin.yaml"),
            "--draft",
            str(draft),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "offline_content_score"
    assert payload["not_business_conversion"] is True
    assert payload["dimensions"]["selling_point_accuracy"]["score"] < 100


def test_mock_flag_ignores_missing_key(
    briefs_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MCW_LLM_API_KEY", raising=False)
    code = main(
        [
            "run",
            str(briefs_dir / "kidsnack-ecommerce.json"),
            "--mock",
            "--run-id",
            "snack",
            "--out",
            str(tmp_path),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"] == "mock"
    blob = json.dumps(
        json.loads((tmp_path / "runs" / "snack" / "prompts.json").read_text(encoding="utf-8")),
        ensure_ascii=False,
    )
    assert "sk-" not in blob


def test_live_backend_requires_a_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], briefs_dir: Path) -> None:
    monkeypatch.delenv("MCW_LLM_API_KEY", raising=False)
    code = main(["run", str(briefs_dir / "sunscreen-xhs.yaml"), "--run-id", "needs-key"])
    assert code == 2
    assert "MCW_LLM_API_KEY" in capsys.readouterr().err


def test_rejects_path_like_run_id(briefs_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["run", str(briefs_dir / "sunscreen-xhs.yaml"), "--mock", "--run-id", "../escape"]
    )
    assert code == 2
    assert "run id" in capsys.readouterr().err


def test_score_drift_exits_one(briefs_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert main(
        ["run", str(briefs_dir / "fitness-douyin.yaml"), "--mock", "--run-id", "fit", "--out", str(out)]
    ) == 0
    capsys.readouterr()
    scores_path = out / "runs" / "fit" / "versions" / "v1" / "scores.json"
    payload = json.loads(scores_path.read_text(encoding="utf-8"))
    payload["drafts"][0]["score"]["overall"] = 1
    scores_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    code = main(["score", "--run", "fit", "--version", "v1", "--out", str(out)])
    assert code == 1
    assert "drift" in capsys.readouterr().err
