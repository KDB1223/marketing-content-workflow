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


def _latest_record(out: Path, run_id: str) -> dict:
    history = json.loads((out / "runs" / run_id / "versions.json").read_text(encoding="utf-8"))
    return history["versions"][-1]


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_latest_created_at(out: Path, run_id: str, created_at: str) -> None:
    path = out / "runs" / run_id / "versions.json"
    history = json.loads(path.read_text(encoding="utf-8"))
    history["versions"][-1]["created_at"] = created_at
    _write_json(path, history)


def test_list_runs_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "empty"
    code = main(["list-runs", "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有运行" in captured.out
    assert OFFLINE_SCORE_NOTE in captured.out
    assert captured.err == ""

    code = main(["list-runs", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runs"] == []
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True

    present = tmp_path / "present"
    (present / "runs").mkdir(parents=True)
    code = main(["list-runs", "--out", str(present)])
    assert code == 0
    assert "没有运行" in capsys.readouterr().out

    junk_only = tmp_path / "junk-only"
    (junk_only / "runs" / "nope").mkdir(parents=True)
    code = main(["list-runs", "--out", str(junk_only)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有运行" in captured.out
    assert OFFLINE_SCORE_NOTE in captured.out
    assert "nope" not in captured.out


def test_list_runs_inventory_skips_junk(
    briefs_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "artifacts"
    approval = Path(__file__).parents[1] / "examples" / "approval-approved.json"
    assert (
        main(
            [
                "run",
                str(briefs_dir / "sunscreen-xhs.yaml"),
                "--mock",
                "--run-id",
                "run-sun",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "run",
                str(briefs_dir / "coffee-wechat.yaml"),
                "--mock",
                "--run-id",
                "run-coffee",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()

    sun = _latest_record(out, "run-sun")
    coffee = _latest_record(out, "run-coffee")
    code = main(["list-runs", "--out", str(out)])
    assert code == 0
    listing = capsys.readouterr().out
    assert "run-sun" in listing
    assert "run-coffee" in listing
    assert "sunscreen-xhs" in listing
    assert "coffee-wechat" in listing
    assert "versions 1" in listing
    assert "| v1 |" in listing
    assert "approval pending" in listing
    assert f"overall {sun['overall_score']}" in listing
    assert f"overall {coffee['overall_score']}" in listing
    assert OFFLINE_SCORE_NOTE in listing

    (out / "runs" / "empty-junk").mkdir()
    bad = out / "runs" / "bad-json"
    bad.mkdir()
    (bad / "manifest.json").write_text("{not json", encoding="utf-8")
    (bad / "versions.json").write_text("{not json", encoding="utf-8")
    shape = out / "runs" / "bad-shape"
    shape.mkdir()
    _write_json(shape / "manifest.json", {"run_id": "bad-shape", "brief_id": "x"})
    (shape / "versions.json").write_text("[]\n", encoding="utf-8")

    code = main(["list-runs", "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert "run-sun" in captured.out
    assert "run-coffee" in captured.out
    for junk in ("empty-junk", "bad-json", "bad-shape"):
        assert junk not in captured.out
        assert junk in captured.err
    assert OFFLINE_SCORE_NOTE in captured.out

    code = main(["list-runs", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True
    ids = [row["run_id"] for row in payload["runs"]]
    assert set(ids) == {"run-sun", "run-coffee"}
    assert ids == [row["run_id"] for row in sorted(payload["runs"], key=lambda row: (row["created_at"], row["run_id"]))]
    assert "empty-junk" in payload["skipped"]
    assert "bad-json" in payload["skipped"]
    assert "bad-shape" in payload["skipped"]
    by_id = {row["run_id"]: row for row in payload["runs"]}
    assert by_id["run-sun"]["brief_id"] == "sunscreen-xhs"
    assert by_id["run-coffee"]["brief_id"] == "coffee-wechat"
    assert by_id["run-sun"]["version_count"] == 1
    assert by_id["run-sun"]["latest_version"] == "v1"
    assert by_id["run-sun"]["approval_status"] == "pending"
    assert by_id["run-sun"]["overall_score"] == sun["overall_score"]
    assert by_id["run-coffee"]["overall_score"] == coffee["overall_score"]
    assert by_id["run-coffee"]["approval_status"] == "pending"

    coffee_path = out / "runs" / "run-coffee" / "versions.json"
    coffee_history = json.loads(coffee_path.read_text(encoding="utf-8"))
    coffee_history["versions"][-1]["overall_score"] = 42
    _write_json(coffee_path, coffee_history)

    assert (
        main(
            [
                "run",
                str(briefs_dir / "sunscreen-xhs.yaml"),
                "--mock",
                "--continue-run",
                "run-sun",
                "--out",
                str(out),
                "--reviewer",
                "林可",
                "--comment",
                "保留声明",
                "--approval",
                str(approval),
            ]
        )
        == 0
    )
    capsys.readouterr()
    code = main(["list-runs", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["not_business_conversion"] is True
    by_id = {row["run_id"]: row for row in payload["runs"]}
    assert set(by_id) == {"run-sun", "run-coffee"}
    assert by_id["run-sun"]["version_count"] == 2
    assert by_id["run-sun"]["latest_version"] == "v2"
    assert by_id["run-sun"]["approval_status"] == "approved"
    assert by_id["run-sun"]["overall_score"] == _latest_record(out, "run-sun")["overall_score"]
    assert by_id["run-coffee"]["version_count"] == 1
    assert by_id["run-coffee"]["latest_version"] == "v1"
    assert by_id["run-coffee"]["approval_status"] == "pending"
    assert by_id["run-coffee"]["overall_score"] == 42

    _set_latest_created_at(out, "run-sun", "2000-01-01T00:00:00+00:00")
    _set_latest_created_at(out, "run-coffee", "2001-01-01T00:00:00+00:00")
    code = main(["list-runs", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["run_id"] for row in payload["runs"]] == ["run-sun", "run-coffee"]

    _set_latest_created_at(out, "run-sun", "2000-01-01T00:00:00+00:00")
    _set_latest_created_at(out, "run-coffee", "2000-01-01T00:00:00+00:00")
    code = main(["list-runs", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["run_id"] for row in payload["runs"]] == ["run-coffee", "run-sun"]


def test_list_runs_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["list-runs", "--help"])
    assert code == 0
    text = capsys.readouterr().out
    assert "--out" in text
    assert "--json" in text

    code = main(["--help"])
    assert code == 0
    parent = capsys.readouterr().out
    assert "list-runs" in parent
    assert "离线总分" in parent


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
