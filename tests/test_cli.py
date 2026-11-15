from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcw.cli import main
from mcw.scoring.rubric import DIMENSIONS, OFFLINE_SCORE_NOTE


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


def test_stats_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "empty"
    code = main(["stats", "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有运行" in captured.out
    assert OFFLINE_SCORE_NOTE in captured.out
    assert "runs:" not in captured.out
    assert captured.err == ""

    code = main(["stats", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_count"] == 0
    assert payload["version_count"] == 0
    assert payload["briefs"] == []
    assert payload["backends"] == []
    assert payload["approval"] == {}
    assert payload["dimension_scores"] == {}
    assert payload["overall_scores"] == {"count": 0, "min": None, "max": None, "mean": None}
    assert payload["skipped"] == []
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True

    present = tmp_path / "present"
    (present / "runs").mkdir(parents=True)
    code = main(["stats", "--out", str(present)])
    assert code == 0
    assert "没有运行" in capsys.readouterr().out

    junk_only = tmp_path / "junk-only"
    (junk_only / "runs" / "nope").mkdir(parents=True)
    code = main(["stats", "--out", str(junk_only)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有运行" in captured.out
    assert OFFLINE_SCORE_NOTE in captured.out
    assert "nope" not in captured.out
    assert "跳过无效运行目录: nope" in captured.err

    code = main(["stats", "--out", str(junk_only), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_count"] == 0
    assert payload["briefs"] == []
    assert payload["skipped"] == ["nope"]
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True


def test_stats_inventory_uses_stored_scores(
    briefs_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
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
    stored = [sun["overall_score"], coffee["overall_score"]]
    code = main(["stats", "--out", str(out)])
    assert code == 0
    listing = capsys.readouterr().out
    assert "runs: 2" in listing
    assert "versions: 2" in listing
    assert "approval: pending 2" in listing
    assert "briefs: coffee-wechat 1, sunscreen-xhs 1" in listing
    assert "backends: mock 2" in listing
    assert f"overall: count 2, min {min(stored)}, max {max(stored)}, mean {_mean(stored)}" in listing
    assert f"dimensions: {_dimension_line(_paired_means(sun, coffee))}" in listing
    assert OFFLINE_SCORE_NOTE in listing

    code = main(["stats", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_count"] == 2
    assert payload["version_count"] == 2
    assert payload["approval"] == {"pending": 2}
    assert payload["briefs"] == [
        {"brief_id": "coffee-wechat", "run_count": 1},
        {"brief_id": "sunscreen-xhs", "run_count": 1},
    ]
    assert payload["backends"] == [{"backend": "mock", "run_count": 2}]
    assert payload["overall_scores"]["count"] == 2
    assert payload["overall_scores"]["min"] == min(stored)
    assert payload["overall_scores"]["max"] == max(stored)
    assert payload["overall_scores"]["mean"] == _mean(stored)
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True
    _assert_dimension_means(payload, [sun["dimension_scores"], coffee["dimension_scores"]])

    (out / "runs" / "empty-junk").mkdir()
    bad = out / "runs" / "bad-json"
    bad.mkdir()
    (bad / "manifest.json").write_text("{not json", encoding="utf-8")
    (bad / "versions.json").write_text("{not json", encoding="utf-8")
    shape = out / "runs" / "bad-shape"
    shape.mkdir()
    _write_json(shape / "manifest.json", {"run_id": "bad-shape", "brief_id": "x"})
    (shape / "versions.json").write_text("[]\n", encoding="utf-8")

    code = main(["stats", "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert "runs: 2" in captured.out
    for junk in ("empty-junk", "bad-json", "bad-shape"):
        assert junk not in captured.out
        assert f"跳过无效运行目录: {junk}" in captured.err
    assert OFFLINE_SCORE_NOTE in captured.out

    scores_path = out / "runs" / "run-coffee" / "scores.json"
    file_overall = json.loads(scores_path.read_text(encoding="utf-8"))["drafts"][0]["score"]["overall"]
    coffee_path = out / "runs" / "run-coffee" / "versions.json"
    coffee_history = json.loads(coffee_path.read_text(encoding="utf-8"))
    coffee_history["versions"][-1]["overall_score"] = 42
    _write_json(coffee_path, coffee_history)
    assert file_overall != 42

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
    sun_latest = _latest_record(out, "run-sun")
    coffee_latest = _latest_record(out, "run-coffee")
    assert coffee_latest["overall_score"] == 42
    rolled = [sun_latest["overall_score"], 42]

    def _forbid_rescore(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("stats must not recompute the rubric")

    monkeypatch.setattr("mcw.scoring.rubric.score_text", _forbid_rescore)
    code = main(["stats", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_count"] == 2
    assert payload["version_count"] == 3
    assert payload["approval"] == {"approved": 1, "pending": 1}
    assert payload["briefs"] == [
        {"brief_id": "coffee-wechat", "run_count": 1},
        {"brief_id": "sunscreen-xhs", "run_count": 1},
    ]
    assert payload["backends"] == [{"backend": "mock", "run_count": 2}]
    assert payload["overall_scores"] == {
        "count": 2,
        "min": min(rolled),
        "max": max(rolled),
        "mean": _mean(rolled),
    }
    assert payload["skipped"] == ["bad-json", "bad-shape", "empty-junk"]
    assert payload["not_business_conversion"] is True
    assert payload["note"] == OFFLINE_SCORE_NOTE
    _assert_dimension_means(
        payload,
        [sun_latest["dimension_scores"], coffee_latest["dimension_scores"]],
    )
    assert json.loads(scores_path.read_text(encoding="utf-8"))["drafts"][0]["score"]["overall"] == file_overall

    code = main(["stats", "--out", str(out)])
    assert code == 0
    listing = capsys.readouterr().out
    assert "runs: 2" in listing
    assert "versions: 3" in listing
    assert "approval: approved 1, pending 1" in listing
    assert "briefs: coffee-wechat 1, sunscreen-xhs 1" in listing
    assert "backends: mock 2" in listing
    assert f"overall: count 2, min {min(rolled)}, max {max(rolled)}, mean {_mean(rolled)}" in listing
    assert listing.split("dimensions: ", 1)[1].splitlines()[0] == _dimension_line(payload["dimension_scores"])
    assert OFFLINE_SCORE_NOTE in listing


def test_stats_text_skips_non_numeric_scores(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "edges"
    _save_index(
        out,
        "approved-run",
        "sunscreen-xhs",
        [
            {
                "version": "v1",
                "created_at": "2024-01-01T00:00:00+00:00",
                "approval_status": "approved",
                "overall_score": True,
                "backend": "",
                "dimension_scores": {"compliance": "nope"},
            }
        ],
    )
    _save_index(
        out,
        "pending-run",
        "coffee-wechat",
        [
            {
                "version": "v1",
                "created_at": "2024-01-02T00:00:00+00:00",
                "approval_status": "pending",
                "overall_score": "42",
                "backend": None,
            }
        ],
    )
    _save_index(
        out,
        "rejected-run",
        "coffee-wechat",
        [
            {
                "version": "v2",
                "created_at": "2024-01-03T00:00:00+00:00",
                "approval_status": "rejected",
                "overall_score": None,
                "dimension_scores": "bad",
            }
        ],
    )
    _save_index(
        out,
        "other-run",
        "zeta-brief",
        [
            {
                "version": "v1",
                "created_at": "2024-01-04T00:00:00+00:00",
                "approval_status": "needs-edit",
                "backend": "live",
            }
        ],
    )
    code = main(["stats", "--out", str(out)])
    assert code == 0
    listing = capsys.readouterr().out
    assert "runs: 4" in listing
    assert "versions: 4" in listing
    assert "approval: approved 1, pending 1, rejected 1, needs-edit 1" in listing
    assert "briefs: coffee-wechat 2, sunscreen-xhs 1, zeta-brief 1" in listing
    assert "backends: unknown 3, live 1" in listing
    assert "overall: count 0" in listing
    assert "min " not in listing
    assert "dimensions:" not in listing
    assert OFFLINE_SCORE_NOTE in listing


def _save_index(out: Path, name: str, brief_id: str, versions: list[dict]) -> None:
    directory = out / "runs" / name
    directory.mkdir(parents=True)
    _write_json(directory / "manifest.json", {"run_id": name, "brief_id": brief_id})
    _write_json(directory / "versions.json", {"run_id": name, "versions": versions})


def test_stats_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["stats", "--help"])
    assert code == 0
    text = capsys.readouterr().out
    assert "--out" in text
    assert "--json" in text
    assert "确认状态" in text
    assert "Brief" in text
    assert "离线分数" in text

    code = main(["--help"])
    assert code == 0
    parent = capsys.readouterr().out
    assert "stats" in parent
    assert "确认状态" in parent
    assert "Brief" in parent
    assert "离线分数" in parent


def _mean(values: list[int | float]) -> float:
    return round(sum(values) / len(values), 2)


def _assert_dimension_means(payload: dict, maps: list[dict]) -> None:
    assert list(payload["dimension_scores"]) == [key for key, _label in DIMENSIONS]
    for key, _label in DIMENSIONS:
        assert payload["dimension_scores"][key]["count"] == len(maps)
        assert payload["dimension_scores"][key]["mean"] == _mean([item[key] for item in maps])


def _paired_means(left: dict, right: dict) -> dict:
    return {
        key: {"mean": _mean([left["dimension_scores"][key], right["dimension_scores"][key]])}
        for key, _label in DIMENSIONS
    }


def _dimension_line(dimension_scores: dict) -> str:
    parts = [
        f"{label} {dimension_scores[key]['mean']}"
        for key, label in DIMENSIONS
        if key in dimension_scores
    ]
    return ", ".join(parts)


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
