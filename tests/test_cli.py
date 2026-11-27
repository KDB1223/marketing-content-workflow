from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcw.cli import main
from mcw.scoring.rubric import DIMENSIONS, OFFLINE_SCORE_NOTE
from mcw.store import FINDINGS_INVENTORY_NOTE


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
    assert "小红书" not in listing
    assert "微信公众号" not in listing
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
    assert by_id["run-sun"]["channel"] == "xiaohongshu"
    assert by_id["run-sun"]["channel_label"] == "小红书"
    assert by_id["run-coffee"]["brief_id"] == "coffee-wechat"
    assert by_id["run-coffee"]["channel"] == "wechat"
    assert by_id["run-coffee"]["channel_label"] == "微信公众号"
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
    assert by_id["run-sun"]["channel"] == "xiaohongshu"
    assert by_id["run-sun"]["channel_label"] == "小红书"
    assert by_id["run-coffee"]["channel"] == "wechat"
    assert by_id["run-coffee"]["channel_label"] == "微信公众号"

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
    assert "channels:" not in captured.out
    assert captured.err == ""

    code = main(["stats", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_count"] == 0
    assert payload["version_count"] == 0
    assert payload["briefs"] == []
    assert payload["backends"] == []
    assert payload["channels"] == []
    assert payload["approval"] == {}
    assert payload["approval_groups"] == []
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
    assert payload["channels"] == []
    assert payload["approval_groups"] == []
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
    assert sun["channel"] == "xiaohongshu"
    assert sun["channel_label"] == "小红书"
    assert coffee["channel"] == "wechat"
    assert coffee["channel_label"] == "微信公众号"
    sun_manifest = json.loads((out / "runs" / "run-sun" / "manifest.json").read_text(encoding="utf-8"))
    coffee_manifest = json.loads((out / "runs" / "run-coffee" / "manifest.json").read_text(encoding="utf-8"))
    assert sun_manifest["channel"] == sun["channel"]
    assert sun_manifest["channel_label"] == sun["channel_label"]
    assert coffee_manifest["channel"] == coffee["channel"]
    assert coffee_manifest["channel_label"] == coffee["channel_label"]
    stored = [sun["overall_score"], coffee["overall_score"]]
    sun_scores = _score_summary([sun["overall_score"]])
    coffee_scores = _score_summary([coffee["overall_score"]])
    both_scores = _score_summary(stored)
    code = main(["stats", "--out", str(out)])
    assert code == 0
    listing = capsys.readouterr().out
    assert "runs: 2" in listing
    assert "versions: 2" in listing
    assert f"approval: pending 2{_score_suffix(both_scores)}" in listing
    assert (
        "briefs: "
        f"coffee-wechat 1{_score_suffix(coffee_scores)}, "
        f"sunscreen-xhs 1{_score_suffix(sun_scores)}"
    ) in listing
    assert f"backends: mock 2{_score_suffix(both_scores)}" in listing
    assert (
        "channels: "
        f"微信公众号 1{_score_suffix(coffee_scores)}, "
        f"小红书 1{_score_suffix(sun_scores)}"
    ) in listing
    assert f"overall: count 2, min {min(stored)}, max {max(stored)}, mean {_mean(stored)}" in listing
    assert f"dimensions: {_dimension_line(_paired_means(sun, coffee))}" in listing
    assert OFFLINE_SCORE_NOTE in listing

    code = main(["stats", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_count"] == 2
    assert payload["version_count"] == 2
    assert payload["approval"] == {"pending": 2}
    assert payload["approval_groups"] == [
        {"status": "pending", "run_count": 2, "overall_scores": both_scores}
    ]
    assert payload["briefs"] == [
        {"brief_id": "coffee-wechat", "run_count": 1, "overall_scores": coffee_scores},
        {"brief_id": "sunscreen-xhs", "run_count": 1, "overall_scores": sun_scores},
    ]
    assert payload["backends"] == [{"backend": "mock", "run_count": 2, "overall_scores": both_scores}]
    assert payload["channels"] == [
        {
            "channel": "wechat",
            "channel_label": "微信公众号",
            "run_count": 1,
            "overall_scores": coffee_scores,
        },
        {
            "channel": "xiaohongshu",
            "channel_label": "小红书",
            "run_count": 1,
            "overall_scores": sun_scores,
        },
    ]
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
    sun_only = _score_summary([sun_latest["overall_score"]])
    coffee_only = _score_summary([42])
    rolled_summary = _score_summary(rolled)
    assert payload["approval"] == {"approved": 1, "pending": 1}
    assert payload["approval_groups"] == [
        {"status": "approved", "run_count": 1, "overall_scores": sun_only},
        {"status": "pending", "run_count": 1, "overall_scores": coffee_only},
    ]
    assert payload["briefs"] == [
        {"brief_id": "coffee-wechat", "run_count": 1, "overall_scores": coffee_only},
        {"brief_id": "sunscreen-xhs", "run_count": 1, "overall_scores": sun_only},
    ]
    assert payload["backends"] == [{"backend": "mock", "run_count": 2, "overall_scores": rolled_summary}]
    assert payload["channels"] == [
        {
            "channel": "wechat",
            "channel_label": "微信公众号",
            "run_count": 1,
            "overall_scores": coffee_only,
        },
        {
            "channel": "xiaohongshu",
            "channel_label": "小红书",
            "run_count": 1,
            "overall_scores": sun_only,
        },
    ]
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
    assert (
        "approval: "
        f"approved 1{_score_suffix(sun_only)}, "
        f"pending 1{_score_suffix(coffee_only)}"
    ) in listing
    assert (
        "briefs: "
        f"coffee-wechat 1{_score_suffix(coffee_only)}, "
        f"sunscreen-xhs 1{_score_suffix(sun_only)}"
    ) in listing
    assert f"backends: mock 2{_score_suffix(rolled_summary)}" in listing
    assert (
        "channels: "
        f"微信公众号 1{_score_suffix(coffee_only)}, "
        f"小红书 1{_score_suffix(sun_only)}"
    ) in listing
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
    assert "channels: unknown 4" in listing
    assert "overall: count 0" in listing
    assert "min " not in listing
    assert "mean " not in listing
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
    assert "渠道" in text

    code = main(["--help"])
    assert code == 0
    parent = capsys.readouterr().out
    assert "stats" in parent
    assert "确认状态" in parent
    assert "Brief" in parent
    assert "离线分数" in parent
    assert "渠道" in parent


def _mean(values: list[int | float]) -> float:
    return round(sum(values) / len(values), 2)


def _score_summary(values: list[int | float]) -> dict:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": _mean(values),
    }


def _score_suffix(summary: dict) -> str:
    if summary["count"] == 0:
        return ""
    if summary["count"] == 1 or summary["min"] == summary["max"]:
        return f" mean {summary['mean']}"
    return f" min {summary['min']}, max {summary['max']}, mean {summary['mean']}"


def test_stats_text_rolls_up_different_group_scores(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "groups"
    _save_index(
        out,
        "sun-a",
        "sunscreen-xhs",
        [
            {
                "version": "v1",
                "created_at": "2024-01-01T00:00:00+00:00",
                "approval_status": "pending",
                "overall_score": 10,
                "backend": "mock",
                "channel": "xiaohongshu",
                "channel_label": "小红书",
            },
            {
                "version": "v2",
                "created_at": "2024-02-01T00:00:00+00:00",
                "approval_status": "approved",
                "overall_score": 90,
                "backend": "mock",
                "channel": "xiaohongshu",
                "channel_label": "小红书",
            },
        ],
    )
    _save_index(
        out,
        "sun-b",
        "sunscreen-xhs",
        [
            {
                "version": "v1",
                "created_at": "2024-01-02T00:00:00+00:00",
                "approval_status": "rejected",
                "overall_score": 1,
                "backend": "mock",
                "channel": "xiaohongshu",
                "channel_label": "小红书",
            },
            {
                "version": "v3",
                "created_at": "2024-03-01T00:00:00+00:00",
                "approval_status": "approved",
                "overall_score": 40,
                "backend": "mock",
                "channel": "xiaohongshu",
                "channel_label": "unknown",
            },
        ],
    )
    _save_index(
        out,
        "coffee-a",
        "coffee-wechat",
        [
            {
                "version": "v1",
                "created_at": "2024-04-01T00:00:00+00:00",
                "approval_status": "pending",
                "overall_score": 42,
                "backend": "mock",
                "channel": "wechat",
                "channel_label": "微信公众号",
            }
        ],
    )
    _save_index(
        out,
        "coffee-b",
        "coffee-wechat",
        [
            {
                "version": "v1",
                "created_at": "2024-04-02T00:00:00+00:00",
                "approval_status": "pending",
                "overall_score": 42,
                "backend": "mock",
                "channel": "wechat",
                "channel_label": "微信公众号",
            }
        ],
    )
    code = main(["stats", "--out", str(out)])
    assert code == 0
    listing = capsys.readouterr().out
    assert "runs: 4" in listing
    assert "versions: 6" in listing
    assert "approval: approved 2 min 40, max 90, mean 65.0, pending 2 mean 42.0" in listing
    assert (
        "briefs: coffee-wechat 2 mean 42.0, sunscreen-xhs 2 min 40, max 90, mean 65.0" in listing
    )
    assert "backends: mock 4 min 40, max 90, mean 53.5" in listing
    assert "channels: 微信公众号 2 mean 42.0, 小红书 2 min 40, max 90, mean 65.0" in listing
    assert "overall: count 4, min 40, max 90, mean 53.5" in listing
    assert OFFLINE_SCORE_NOTE in listing

    code = main(["stats", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    shared = {"count": 2, "min": 40, "max": 90, "mean": 65.0}
    sunscreen = next(row for row in payload["briefs"] if row["brief_id"] == "sunscreen-xhs")
    assert sunscreen["run_count"] == 2
    assert sunscreen["overall_scores"] == shared
    channel = next(row for row in payload["channels"] if row["channel"] == "xiaohongshu")
    assert channel["channel_label"] == "小红书"
    assert channel["overall_scores"] == shared
    assert payload["overall_scores"]["min"] == 40


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


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_failures_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "empty"
    code = main(["failures", "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有未满分或被驳回的运行" in captured.out
    assert OFFLINE_SCORE_NOTE in captured.out
    assert captured.err == ""

    code = main(["failures", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["failures"] == []
    assert payload["skipped"] == []
    assert payload["kind"] == "offline_content_score"
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True

    junk_only = tmp_path / "junk-only"
    (junk_only / "runs" / "nope").mkdir(parents=True)
    code = main(["failures", "--out", str(junk_only)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有未满分或被驳回的运行" in captured.out
    assert "nope" not in captured.out
    assert "跳过无效运行目录: nope" in captured.err


def test_failures_text_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    run = out / "runs" / "low"
    (run / "versions" / "v1").mkdir(parents=True)
    _write_json(
        run / "manifest.json",
        {"run_id": "low", "brief_id": "coffee-wechat"},
    )
    _write_json(
        run / "versions.json",
        {
            "run_id": "low",
            "versions": [
                {
                    "version": "v1",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "approval_status": "pending",
                    "overall_score": 86,
                    "best_draft_id": "v1-a",
                    "dimension_scores": {
                        "selling_point_accuracy": 100,
                        "channel_fit": 100,
                        "compliance": 100,
                        "readability": 100,
                    },
                }
            ],
        },
    )
    _write_json(
        run / "versions" / "v1" / "checklist.json",
        {
            "items": [
                {
                    "draft_id": "v1-a",
                    "passed": False,
                    "summary": "",
                    "findings": [
                        {
                            "rule_id": "absolute_claim",
                            "severity": "high",
                            "message": "绝对化用语",
                            "evidence": "全网第一",
                            "suggestion": "",
                        }
                    ],
                }
            ]
        },
    )
    _write_json(
        run / "versions" / "v1" / "scores.json",
        {
            "kind": "offline_content_score",
            "not_business_conversion": True,
            "best_draft_id": "v1-a",
            "drafts": [
                {
                    "draft_id": "v1-a",
                    "variant": "A",
                    "score": {
                        "overall": 86,
                        "dimensions": {
                            "selling_point_accuracy": {"label": "WRONG", "score": 80},
                            "channel_fit": {"label": "WRONG", "score": 100},
                            "compliance": {"label": "WRONG", "score": 75},
                            "readability": {"label": "WRONG", "score": 100},
                        },
                    },
                },
                {
                    "draft_id": "v1-b",
                    "variant": "B",
                    "score": {"overall": 60, "dimensions": {}},
                },
            ],
        },
    )
    before = _snapshot(out)
    code = main(["failures", "--out", str(out)])
    assert code == 0
    assert _snapshot(out) == before
    text = capsys.readouterr().out
    assert "low | coffee-wechat | v1 | approval pending | best v1-a | overall 86" in text
    assert "dimensions: 卖点准确 80, 合规 75" in text
    assert "checklist: failed" in text
    assert "high: absolute_claim | 绝对化用语 | 全网第一" in text
    assert "variants: B v1-b 60" in text
    assert "WRONG" not in text
    assert f"note: {OFFLINE_SCORE_NOTE}" in text

    code = main(["failures", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "offline_content_score"
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True
    assert payload["skipped"] == []
    assert len(payload["failures"]) == 1
    row = payload["failures"][0]
    assert row["run_id"] == "low"
    assert row["brief_id"] == "coffee-wechat"
    assert row["version"] == "v1"
    assert row["overall_score"] == 86
    assert row["weak_dimensions"][0]["label"] == "卖点准确"
    assert row["high_findings"][0]["evidence"] == "全网第一"
    assert row["variant_scores"][1]["overall"] == 60


def test_failures_named_missing_run_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    run = out / "runs" / "sun"
    run.mkdir(parents=True)
    _write_json(run / "manifest.json", {"run_id": "sun", "brief_id": "sunscreen-xhs"})
    _write_json(
        run / "versions.json",
        {
            "run_id": "sun",
            "versions": [
                {
                    "version": "v1",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "approval_status": "pending",
                    "overall_score": 100,
                    "best_draft_id": "v1-a",
                }
            ],
        },
    )
    code = main(["failures", "missing-run", "--out", str(out)])
    assert code == 2
    assert "找不到运行" in capsys.readouterr().err

    code = main(["failures", "sun", "--version", "v9", "--out", str(out)])
    assert code == 2
    assert "版本索引里没有 v9" in capsys.readouterr().err

    code = main(["failures", "--version", "v1", "--out", str(out)])
    assert code == 2
    assert "--version" in capsys.readouterr().err


def test_failures_mock_run_is_omitted_and_does_not_call_a_model(
    briefs_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("failures must not call a model or rescore")

    out = tmp_path / "out"
    assert (
        main(
            [
                "run",
                str(briefs_dir / "sunscreen-xhs.yaml"),
                "--mock",
                "--run-id",
                "demo-sunscreen",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    before = _snapshot(out)
    monkeypatch.setattr("mcw.cli.rescore_version", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("urllib.request.urlopen", fail)
    code = main(["failures", "--out", str(out)])
    assert code == 0
    assert _snapshot(out) == before
    captured = capsys.readouterr()
    assert "没有未满分或被驳回的运行" in captured.out
    assert "demo-sunscreen" not in captured.out
    assert OFFLINE_SCORE_NOTE in captured.out
    assert captured.err == ""


def test_failures_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["failures", "--help"])
    assert code == 0
    text = capsys.readouterr().out
    assert "--out" in text
    assert "--json" in text
    assert "--version" in text

    code = main(["--help"])
    assert code == 0
    assert "failures" in capsys.readouterr().out


def test_list_findings_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "empty"
    code = main(["list-findings", "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有发现" in captured.out
    assert "runs: 0" in captured.out
    assert "with_findings: 0" in captured.out
    assert "without_findings: 0" in captured.out
    assert "listed: 0" in captured.out
    assert FINDINGS_INVENTORY_NOTE in captured.out
    assert captured.err == ""

    code = main(["list-findings", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"] == []
    assert payload["skipped"] == []
    assert payload["n"] == 0
    assert payload["n_listed"] == 0
    assert payload["kind"] == "stored_checklist_findings"
    assert payload["note"] == FINDINGS_INVENTORY_NOTE
    assert payload["not_business_conversion"] is True

    junk_only = tmp_path / "junk-only"
    (junk_only / "runs" / "nope").mkdir(parents=True)
    code = main(["list-findings", "--out", str(junk_only)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有发现" in captured.out
    assert "nope" not in captured.out
    assert "跳过无效运行目录: nope" in captured.err


def test_list_findings_text_json_and_filters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    _write_finding_run(
        out,
        "zzz",
        "coffee-wechat",
        "2024-01-01T00:00:00+00:00",
        "wechat",
        "微信公众号",
        [
            {
                "draft_id": "z-b",
                "passed": False,
                "summary": "",
                "findings": [
                    {
                        "rule_id": "absolute_claim",
                        "severity": "high",
                        "message": "绝对化用语",
                        "evidence": "全网第一",
                        "suggestion": "删掉",
                    },
                    "skip",
                ],
            },
            {
                "draft_id": "z-a",
                "passed": True,
                "summary": "",
                "findings": [
                    {
                        "rule_id": "tone",
                        "severity": "medium",
                        "message": "语气偏硬",
                        "evidence": "",
                        "suggestion": "改语气",
                    }
                ],
            },
        ],
    )
    _write_finding_run(
        out,
        "aaa",
        "sunscreen-xhs",
        "2024-05-01T00:00:00+00:00",
        "xiaohongshu",
        "小红书",
        [
            {"draft_id": "a-a", "passed": True, "summary": "", "findings": []},
            {
                "draft_id": "a-b",
                "passed": False,
                "summary": "",
                "findings": [{"rule_id": "tone", "severity": "medium"}],
            },
        ],
    )
    (out / "runs" / "nope").mkdir(parents=True)
    before = _snapshot(out)
    code = main(["list-findings", "--out", str(out)])
    assert code == 0
    assert _snapshot(out) == before
    captured = capsys.readouterr()
    assert "跳过无效运行目录: nope" in captured.err
    text = captured.out
    assert "没有发现" not in text
    assert "zzz | coffee-wechat | v1 | z-b | absolute_claim | high | 全网第一" in text
    assert "zzz | coffee-wechat | v1 | z-a | tone | medium | —" in text
    assert "aaa | sunscreen-xhs | v1 | a-b | tone | medium | —" in text
    assert text.index("zzz |") < text.index("aaa |")
    assert "runs: 2" in text
    assert "with_findings: 2" in text
    assert "without_findings: 0" in text
    assert "listed: 3" in text
    assert "by_rule: tone 2, absolute_claim 1" in text
    assert "by_severity: medium 2, high 1" in text
    assert f"note: {FINDINGS_INVENTORY_NOTE}" in text

    code = main(["list-findings", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n_listed"] == 3
    assert payload["not_business_conversion"] is True
    assert payload["note"] == FINDINGS_INVENTORY_NOTE
    assert payload["skipped"] == ["nope"]
    row = payload["findings"][0]
    assert row["suggestion"] == "删掉"
    assert row["channel"] == "wechat"
    assert row["channel_label"] == "微信公众号"
    assert payload["findings"][2]["evidence"] is None
    assert payload["findings"][2]["draft_id"] == "a-b"
    assert payload["filters"]["rule"] is None

    code = main(["list-findings", "--rule", "tone", "--severity", "medium", "--channel", "xhs", "--out", str(out)])
    assert code == 0
    filtered = capsys.readouterr().out
    assert "aaa | sunscreen-xhs | v1 | a-b | tone | medium | —" in filtered
    assert "absolute_claim" not in filtered
    assert "zzz |" not in filtered
    assert "with_findings: 2" in filtered
    assert "listed: 1" in filtered

    code = main(
        ["list-findings", "--rule", "absolute_claim", "--severity", "medium", "--out", str(out)]
    )
    assert code == 0
    empty = capsys.readouterr().out
    assert "没有发现" in empty
    assert "with_findings: 2" in empty
    assert "without_findings: 0" in empty
    assert "listed: 0" in empty
    assert "by_rule: —" in empty

    code = main(["list-findings", "--channel", "unknown", "--out", str(out), "--json"])
    assert code == 0
    unknown = json.loads(capsys.readouterr().out)
    assert unknown["findings"] == []
    assert unknown["n_with_findings"] == 2
    assert unknown["n_listed"] == 0


def test_list_findings_named_missing_run_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    _write_finding_run(
        out,
        "sun",
        "sunscreen-xhs",
        "2024-01-01T00:00:00+00:00",
        "xiaohongshu",
        "小红书",
        [{"draft_id": "v1-a", "passed": True, "summary": "", "findings": []}],
    )
    code = main(["list-findings", "missing-run", "--out", str(out)])
    assert code == 2
    assert "找不到运行" in capsys.readouterr().err

    code = main(["list-findings", "sun", "--version", "v9", "--out", str(out)])
    assert code == 2
    assert "版本索引里没有 v9" in capsys.readouterr().err

    code = main(["list-findings", "--version", "v1", "--out", str(out)])
    assert code == 2
    assert "--version" in capsys.readouterr().err


def test_list_findings_mock_run_has_no_rows_and_does_not_call_a_model(
    briefs_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("list-findings must not call a model or rescore")

    out = tmp_path / "out"
    assert (
        main(
            [
                "run",
                str(briefs_dir / "sunscreen-xhs.yaml"),
                "--mock",
                "--run-id",
                "demo-sunscreen",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    before = _snapshot(out)
    monkeypatch.setattr("mcw.cli.rescore_version", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("mcw.risk.rules.run_rules", fail)
    monkeypatch.setattr("urllib.request.urlopen", fail)
    code = main(["list-findings", "--out", str(out)])
    assert code == 0
    assert _snapshot(out) == before
    captured = capsys.readouterr()
    assert "没有发现" in captured.out
    assert "demo-sunscreen" not in captured.out
    assert FINDINGS_INVENTORY_NOTE in captured.out
    assert "with_findings: 0" in captured.out
    assert captured.err == ""


def test_list_findings_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["list-findings", "--help"])
    assert code == 0
    text = capsys.readouterr().out
    assert "--out" in text
    assert "--json" in text
    assert "--version" in text
    assert "--rule" in text
    assert "--severity" in text
    assert "--channel" in text
    assert "--draft" in text
    assert "--brief" in text

    code = main(["--help"])
    assert code == 0
    assert "list-findings" in capsys.readouterr().out


def _write_finding_run(
    out: Path,
    run_id: str,
    brief_id: str,
    created_at: str,
    channel: str,
    channel_label: str,
    items: list[dict],
) -> None:
    run = out / "runs" / run_id
    (run / "versions" / "v1").mkdir(parents=True)
    _write_json(
        run / "manifest.json",
        {
            "run_id": run_id,
            "brief_id": brief_id,
            "channel": channel,
            "channel_label": channel_label,
        },
    )
    _write_json(
        run / "versions.json",
        {
            "run_id": run_id,
            "versions": [
                {
                    "version": "v1",
                    "created_at": created_at,
                    "approval_status": "pending",
                    "overall_score": 100,
                    "best_draft_id": "recommended",
                    "channel": channel,
                    "channel_label": channel_label,
                }
            ],
        },
    )
    _write_json(run / "versions" / "v1" / "checklist.json", {"items": items})


_VALID_BRIEF = """\
id: ok-brief
title: 有效样例
locale: zh-CN
product:
  name: 示例产品
  category: 测试
  selling_points:
    - 卖点甲
    - 卖点乙
audience:
  segment: 测试人群
  tone: 平静
channel:
  name: 小红书
  format: note
  max_chars: 200
conversion:
  goal: 收藏
  cta: 评论告诉我
constraints:
  must_include:
    - 卖点甲
  forbidden_claims:
    - 医疗级
"""

_SHIPPED_IDS = [
    "coffee-wechat",
    "creditcard-official",
    "fitness-douyin",
    "kidsnack-ecommerce",
    "sunscreen-xhs",
]

_SHIPPED_LABELS = {
    "coffee-wechat": "微信公众号",
    "creditcard-official": "官网",
    "fitness-douyin": "抖音",
    "kidsnack-ecommerce": "电商详情",
    "sunscreen-xhs": "小红书",
}


def test_list_briefs_shipped(
    briefs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("list-briefs must not call a model or score a draft")

    root = briefs_dir.parent
    monkeypatch.chdir(root)
    monkeypatch.setattr("urllib.request.urlopen", fail)
    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    before = _snapshot(briefs_dir)
    mcw_dir = root / ".mcw"
    mcw_existed = mcw_dir.exists()
    before_mcw = _snapshot(mcw_dir) if mcw_existed else None

    code = main(["list-briefs"])
    assert code == 0
    captured = capsys.readouterr()
    listing = captured.out
    assert captured.err == ""
    assert "没有 Brief" not in listing
    assert "离线内容分" not in listing
    assert (
        "sunscreen-xhs | 夏季防晒乳小红书种草 | 小红书 | "
        "卖点 3 | 必含 1 | 禁称 2 | briefs/sunscreen-xhs.yaml"
    ) in listing
    for brief_id, label in _SHIPPED_LABELS.items():
        assert brief_id in listing
        assert label in listing
    assert "briefs: 5" in listing
    assert "channels: 抖音 1, 电商详情 1, 官网 1, 微信公众号 1, 小红书 1" in listing
    positions = [listing.index(brief_id) for brief_id in _SHIPPED_IDS]
    assert positions == sorted(positions)
    assert _snapshot(briefs_dir) == before
    if mcw_existed:
        assert _snapshot(mcw_dir) == before_mcw
    else:
        assert not mcw_dir.exists()

    code = main(["list-briefs", "--json"])
    assert code == 0
    raw = capsys.readouterr().out
    assert "小红书" in raw
    assert "\\u5c0f" not in raw
    payload = json.loads(raw)
    assert payload["directory"] == "briefs"
    assert payload["brief_count"] == 5
    assert payload["skipped"] == []
    assert [row["id"] for row in payload["briefs"]] == _SHIPPED_IDS
    assert "note" not in payload
    assert "not_business_conversion" not in payload
    by_id = {row["id"]: row for row in payload["briefs"]}
    for brief_id, label in _SHIPPED_LABELS.items():
        assert by_id[brief_id]["channel_label"] == label
        assert by_id[brief_id]["path"] == f"briefs/{Path(by_id[brief_id]['path']).name}"
    sun = by_id["sunscreen-xhs"]
    assert sun["path"] == "briefs/sunscreen-xhs.yaml"
    assert sun["title"] == "夏季防晒乳小红书种草"
    assert sun["locale"] == "zh-CN"
    assert sun["product_name"] == "澄光防晒乳 SPF50+"
    assert sun["category"] == "护肤"
    assert sun["audience_segment"] == "18-28 岁都市通勤族"
    assert sun["tone"] == "亲切、口语、不夸张"
    assert sun["channel"] == "xiaohongshu"
    assert sun["channel_format"] == "note"
    assert sun["max_chars"] == 450
    for key in (
        "selling_points",
        "must_include",
        "must_avoid",
        "forbidden_claims",
        "regulatory_notes",
        "disclaimers",
        "pain_points",
        "claims_allowed",
        "required_elements",
    ):
        assert isinstance(sun[key], int)
    assert sun["selling_points"] == 3
    assert sun["must_include"] == 1
    assert sun["must_avoid"] == 3
    assert sun["forbidden_claims"] == 2
    assert sun["regulatory_notes"] == 1
    assert sun["disclaimers"] == 1
    assert sun["pain_points"] == 1
    assert sun["claims_allowed"] == 3
    assert sun["required_elements"] == 3
    assert [(row["channel"], row["channel_label"], row["brief_count"]) for row in payload["channels"]] == [
        ("douyin", "抖音", 1),
        ("ecommerce", "电商详情", 1),
        ("official_site", "官网", 1),
        ("wechat", "微信公众号", 1),
        ("xiaohongshu", "小红书", 1),
    ]


def test_list_briefs_filters(
    briefs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(briefs_dir.parent)
    for channel in ("小红书", "xiaohongshu", "xhs"):
        code = main(["list-briefs", "--channel", channel])
        assert code == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        assert "sunscreen-xhs | 夏季防晒乳小红书种草 | 小红书 |" in captured.out
        for other in ("coffee-wechat", "fitness-douyin", "creditcard-official", "kidsnack-ecommerce"):
            assert other not in captured.out
        assert "briefs: 1" in captured.out
        assert "channels: 小红书 1" in captured.out

    code = main(["list-briefs", "--id", "coffee-wechat"])
    assert code == 0
    listing = capsys.readouterr().out
    assert "coffee-wechat | 精品咖啡订阅公众号推文 | 微信公众号 |" in listing
    assert "sunscreen-xhs" not in listing
    assert "briefs: 1" in listing

    code = main(["list-briefs", "--channel", "抖音", "--id", "coffee-wechat"])
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "没有 Brief"
    assert "briefs:" not in captured.out
    assert captured.err == ""

    code = main(["list-briefs", "--channel", "抖音", "--id", "coffee-wechat", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["directory"] == "briefs"
    assert payload["briefs"] == []
    assert payload["skipped"] == []
    assert payload["brief_count"] == 0
    assert payload["channels"] == []


def test_list_briefs_missing_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing-briefs"
    code = main(["list-briefs", str(missing)])
    assert code == 2
    assert f"找不到 Brief 目录: {missing}" in capsys.readouterr().err

    not_dir = tmp_path / "a-file.yaml"
    not_dir.write_text("id: x\n", encoding="utf-8")
    code = main(["list-briefs", str(not_dir)])
    assert code == 2
    assert f"找不到 Brief 目录: {not_dir}" in capsys.readouterr().err


def test_list_briefs_skips_invalid_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "inbox"
    folder.mkdir()
    (folder / "ok.yaml").write_text(_VALID_BRIEF, encoding="utf-8")
    (folder / "bad.yaml").write_text("id: [\n", encoding="utf-8")
    (folder / "notes.txt").write_text("ignore", encoding="utf-8")
    (folder / ".hidden.yaml").write_text("id: hidden\n", encoding="utf-8")
    nested = folder / "nested"
    nested.mkdir()
    (nested / "inside.yaml").write_text(_VALID_BRIEF, encoding="utf-8")
    before = _snapshot(folder)

    code = main(["list-briefs", str(folder)])
    assert code == 0
    captured = capsys.readouterr()
    expected = (Path(str(folder)) / "ok.yaml").as_posix()
    expected_bad = (Path(str(folder)) / "bad.yaml").as_posix()
    assert f"ok-brief | 有效样例 | 小红书 | 卖点 2 | 必含 1 | 禁称 1 | {expected}" in captured.out
    assert "briefs: 1" in captured.out
    assert "channels: 小红书 1" in captured.out
    assert "inside.yaml" not in captured.out
    assert "notes.txt" not in captured.out
    assert ".hidden.yaml" not in captured.out
    assert f"跳过无效 Brief 文件: {expected_bad}:" in captured.err
    assert "notes.txt" not in captured.err
    assert ".hidden.yaml" not in captured.err
    assert "inside.yaml" not in captured.err
    assert _snapshot(folder) == before
    assert not (tmp_path / ".mcw").exists()

    code = main(["list-briefs", str(folder), "--json"])
    assert code == 0
    raw = capsys.readouterr()
    assert raw.err == ""
    payload = json.loads(raw.out)
    assert payload["directory"] == str(folder)
    assert payload["brief_count"] == 1
    assert payload["briefs"][0]["id"] == "ok-brief"
    assert payload["briefs"][0]["selling_points"] == 2
    assert isinstance(payload["briefs"][0]["forbidden_claims"], int)
    assert payload["skipped"] == [
        {"path": expected_bad, "error": payload["skipped"][0]["error"]},
    ]
    assert payload["skipped"][0]["error"]
    assert "\n" not in payload["skipped"][0]["error"]


def test_list_briefs_empty_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = tmp_path / "empty-briefs"
    empty.mkdir()
    (empty / "notes.txt").write_text("not a brief", encoding="utf-8")
    (empty / "nested").mkdir()
    code = main(["list-briefs", str(empty)])
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "没有 Brief"
    assert "briefs:" not in captured.out
    assert captured.err == ""

    code = main(["list-briefs", str(empty), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["directory"] == str(empty)
    assert payload["briefs"] == []
    assert payload["skipped"] == []
    assert payload["brief_count"] == 0
    assert payload["channels"] == []


def test_list_briefs_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["list-briefs", "--help"])
    assert code == 0
    text = capsys.readouterr().out
    assert "--json" in text
    assert "--channel" in text
    assert "--id" in text
    assert "briefs" in text

    code = main(["--help"])
    assert code == 0
    assert "list-briefs" in capsys.readouterr().out


def test_list_drafts_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "empty"
    code = main(["list-drafts", "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有文案" in captured.out
    assert "runs: 0" in captured.out
    assert "with_drafts: 0" in captured.out
    assert "without_drafts: 0" in captured.out
    assert "listed: 0" in captured.out
    assert "recommended: 0" in captured.out
    assert "not_recommended: 0" in captured.out
    assert OFFLINE_SCORE_NOTE in captured.out
    assert captured.err == ""

    code = main(["list-drafts", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["drafts"] == []
    assert payload["skipped"] == []
    assert payload["n"] == 0
    assert payload["n_listed"] == 0
    assert payload["kind"] == "stored_drafts"
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True

    junk_only = tmp_path / "junk-only"
    (junk_only / "runs" / "nope").mkdir(parents=True)
    code = main(["list-drafts", "--out", str(junk_only)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有文案" in captured.out
    assert "nope" not in captured.out
    assert "跳过无效运行目录: nope" in captured.err


def test_list_drafts_text_json_and_filters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    _write_draft_run(
        out,
        "zzz",
        "coffee-wechat",
        "2024-01-01T00:00:00+00:00",
        "wechat",
        "微信公众号",
        [
            "skip",
            None,
            {"id": "z-b", "variant": "B", "angle": "痛点", "char_count": 80},
            {"id": "z-a", "variant": "A", "angle": "清单", "char_count": 90},
            {"id": "z-c", "variant": "C", "angle": "", "char_count": 70},
        ],
        "z-a",
        scores=[
            {"draft_id": "z-b", "variant": "B", "angle": "痛点", "score": {"overall": 70}},
            {"draft_id": "z-a", "variant": "A", "angle": "清单", "score": {"overall": 100}},
        ],
        checklist_items=[
            {
                "draft_id": "z-b",
                "passed": False,
                "findings": [{"rule_id": "absolute_claim", "severity": "high"}, "skip"],
            },
            {"draft_id": "z-a", "passed": True, "findings": []},
        ],
    )
    _write_draft_run(
        out,
        "aaa",
        "sunscreen-xhs",
        "2024-05-01T00:00:00+00:00",
        "xiaohongshu",
        "小红书",
        [
            {"id": "a-b", "variant": "B", "angle": "场景", "char_count": 40},
            {"id": "a-a", "variant": "A", "angle": "痛点", "char_count": 50},
        ],
        "a-a",
        scores=[
            {"draft_id": "a-b", "variant": "B", "angle": "场景", "score": {"overall": 88}},
            {"draft_id": "a-a", "variant": "A", "angle": "痛点", "score": {"overall": 100}},
        ],
        checklist_items=[
            {"draft_id": "a-b", "passed": False, "findings": [{"severity": "medium"}]},
            {"draft_id": "a-a", "passed": True, "findings": []},
        ],
    )
    _write_draft_run(
        out,
        "bare",
        "kidsnack-ecommerce",
        "2024-06-01T00:00:00+00:00",
        None,
        None,
        [{"id": "bare-a", "variant": "A", "angle": "配料", "char_count": 12}],
        "bare-a",
        include_scores=False,
        include_checklist=False,
    )
    (out / "runs" / "nope").mkdir(parents=True)
    before = _snapshot(out)
    code = main(["list-drafts", "--out", str(out)])
    assert code == 0
    assert _snapshot(out) == before
    captured = capsys.readouterr()
    assert "跳过无效运行目录: nope" in captured.err
    text = captured.out
    assert "没有文案" not in text
    assert "skip" not in text
    assert "zzz | coffee-wechat | v1 | z-b | B | 痛点 | chars 80 | overall 70 | — | checklist failed | high 1" in text
    assert (
        "zzz | coffee-wechat | v1 | z-a | A | 清单 | chars 90 | overall 100 | recommended | checklist passed | high 0"
        in text
    )
    assert "zzz | coffee-wechat | v1 | z-c | C | — | chars 70 | overall — | — | checklist — | high —" in text
    assert (
        "aaa | sunscreen-xhs | v1 | a-b | B | 场景 | chars 40 | overall 88 | — | checklist failed | high 0"
        in text
    )
    assert (
        "aaa | sunscreen-xhs | v1 | a-a | A | 痛点 | chars 50 | overall 100 | recommended | checklist passed | high 0"
        in text
    )
    assert (
        "bare | kidsnack-ecommerce | v1 | bare-a | A | 配料 | chars 12 | overall — | recommended | checklist — | high —"
        in text
    )
    assert text.index("zzz |") < text.index("aaa |") < text.index("bare |")
    assert "runs: 3" in text
    assert "with_drafts: 3" in text
    assert "without_drafts: 0" in text
    assert "listed: 6" in text
    assert "recommended: 3" in text
    assert "not_recommended: 3" in text
    assert "by_brief: coffee-wechat 3, sunscreen-xhs 2, kidsnack-ecommerce 1" in text
    assert "by_channel: wechat 3, xiaohongshu 2, unknown 1" in text
    assert "by_variant: A 3, B 2, C 1" in text
    assert f"note: {OFFLINE_SCORE_NOTE}" in text

    code = main(["list-drafts", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n_listed"] == 6
    assert payload["not_business_conversion"] is True
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["skipped"] == ["nope"]
    assert payload["drafts"][2]["angle"] == ""
    assert payload["drafts"][2]["overall"] is None
    assert payload["drafts"][2]["checklist_passed"] is None
    assert payload["drafts"][5]["channel"] == "unknown"
    assert payload["drafts"][5]["high_finding_count"] is None
    assert payload["filters"]["draft"] is None

    code = main(
        [
            "list-drafts",
            "--draft",
            "a-b",
            "--variant",
            "B",
            "--channel",
            "xhs",
            "--brief",
            "sunscreen-xhs",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    filtered = capsys.readouterr().out
    assert "aaa | sunscreen-xhs | v1 | a-b | B | 场景 | chars 40 | overall 88 | — | checklist failed | high 0" in filtered
    assert "zzz |" not in filtered
    assert "bare |" not in filtered
    assert "with_drafts: 3" in filtered
    assert "listed: 1" in filtered
    assert "recommended: 0" in filtered
    assert "not_recommended: 1" in filtered

    code = main(["list-drafts", "--draft", "a-b", "--variant", "A", "--out", str(out)])
    assert code == 0
    empty = capsys.readouterr().out
    assert "没有文案" in empty
    assert "with_drafts: 3" in empty
    assert "without_drafts: 0" in empty
    assert "listed: 0" in empty
    assert "by_brief: —" in empty

    code = main(["list-drafts", "--channel", "unknown", "--out", str(out), "--json"])
    assert code == 0
    unknown = json.loads(capsys.readouterr().out)
    assert [row["draft_id"] for row in unknown["drafts"]] == ["bare-a"]
    assert unknown["n_with_drafts"] == 3
    assert unknown["n_listed"] == 1


def test_list_drafts_named_missing_run_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    _write_draft_run(
        out,
        "sun",
        "sunscreen-xhs",
        "2024-01-01T00:00:00+00:00",
        "xiaohongshu",
        "小红书",
        [{"id": "v1-a", "variant": "A", "angle": "痛点", "char_count": 10}],
        "v1-a",
        include_scores=False,
        include_checklist=False,
    )
    code = main(["list-drafts", "missing-run", "--out", str(out)])
    assert code == 2
    assert "找不到运行" in capsys.readouterr().err

    code = main(["list-drafts", "sun", "--version", "v9", "--out", str(out)])
    assert code == 2
    assert "版本索引里没有 v9" in capsys.readouterr().err

    code = main(["list-drafts", "--version", "v1", "--out", str(out)])
    assert code == 2
    assert "--version 需要同时提供 run id" in capsys.readouterr().err

    broken = out / "runs" / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{", encoding="utf-8")
    (broken / "versions.json").write_text("{", encoding="utf-8")
    code = main(["list-drafts", "broken", "--out", str(out)])
    assert code == 2
    assert "无法读取" in capsys.readouterr().err


def test_list_drafts_selects_latest_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    run = out / "runs" / "sun"
    for version, draft_id, overall in (("v1", "old-a", 11), ("v2", "new-a", 22)):
        directory = run / "versions" / version
        directory.mkdir(parents=True)
        _write_json(
            directory / "drafts.json",
            {"drafts": [{"id": draft_id, "variant": "A", "angle": version, "char_count": 3}]},
        )
        _write_json(
            directory / "scores.json",
            {
                "drafts": [
                    {
                        "draft_id": draft_id,
                        "variant": "A",
                        "angle": version,
                        "score": {"overall": overall},
                    }
                ]
            },
        )
    _write_json(
        run / "manifest.json",
        {"run_id": "sun", "brief_id": "sunscreen-xhs", "channel": "xiaohongshu", "channel_label": "小红书"},
    )
    _write_json(
        run / "versions.json",
        {
            "run_id": "sun",
            "versions": [
                {
                    "version": "v1",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "best_draft_id": "old-a",
                    "channel": "wechat",
                    "channel_label": "微信公众号",
                },
                {
                    "version": "v2",
                    "created_at": "2024-02-01T00:00:00+00:00",
                    "best_draft_id": "new-a",
                    "channel": "xiaohongshu",
                    "channel_label": "小红书",
                },
            ],
        },
    )
    _write_json(run / "drafts.json", {"drafts": [{"id": "root-only", "variant": "A", "angle": "根", "char_count": 1}]})
    quiet = out / "runs" / "quiet"
    (quiet / "versions" / "v1").mkdir(parents=True)
    _write_json(quiet / "manifest.json", {"run_id": "quiet", "brief_id": "coffee-wechat"})
    _write_json(
        quiet / "versions.json",
        {
            "run_id": "quiet",
            "versions": [
                {"version": "v1", "created_at": "2024-03-01T00:00:00+00:00", "best_draft_id": "q-a"}
            ],
        },
    )

    code = main(["list-drafts", "--out", str(out)])
    assert code == 0
    text = capsys.readouterr().out
    assert "sun | sunscreen-xhs | v2 | new-a | A | v2 | chars 3 | overall 22 | recommended" in text
    assert "old-a" not in text
    assert "root-only" not in text
    assert "runs: 2" in text
    assert "with_drafts: 1" in text
    assert "without_drafts: 1" in text
    assert "listed: 1" in text

    code = main(["list-drafts", "sun", "--version", "v1", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n"] == 1
    assert payload["drafts"][0]["draft_id"] == "old-a"
    assert payload["drafts"][0]["version"] == "v1"
    assert payload["drafts"][0]["overall"] == 11
    assert payload["drafts"][0]["channel"] == "wechat"
    assert payload["drafts"][0]["recommended"] is True
    assert "new-a" not in json.dumps(payload["drafts"], ensure_ascii=False)


def test_list_drafts_mock_run_lists_every_draft_and_does_not_call_a_model(
    briefs_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("list-drafts must not call a model or rescore")

    out = tmp_path / "out"
    assert (
        main(
            [
                "run",
                str(briefs_dir / "sunscreen-xhs.yaml"),
                "--mock",
                "--run-id",
                "demo-sunscreen",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    root = out / "runs" / "demo-sunscreen" / "versions" / "v1"
    stored = json.loads((root / "drafts.json").read_text(encoding="utf-8"))
    scores = json.loads((root / "scores.json").read_text(encoding="utf-8"))
    checklist = json.loads((root / "checklist.json").read_text(encoding="utf-8"))
    assert len(stored["drafts"]) == 3
    before = _snapshot(out)
    monkeypatch.setattr("mcw.cli.rescore_version", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("mcw.risk.rules.run_rules", fail)
    monkeypatch.setattr("mcw.textutil.char_count", fail)
    monkeypatch.setattr("urllib.request.urlopen", fail)
    code = main(["list-drafts", "--out", str(out)])
    assert code == 0
    assert _snapshot(out) == before
    captured = capsys.readouterr()
    text = captured.out
    assert captured.err == ""
    assert "没有文案" not in text
    assert OFFLINE_SCORE_NOTE in text
    assert "listed: 3" in text
    assert "recommended: 1" in text
    assert "not_recommended: 2" in text
    best_id = scores["best_draft_id"]
    best_seen = False
    for draft in stored["drafts"]:
        assert draft["id"] in text
        line = next(line for line in text.splitlines() if draft["id"] in line)
        if draft["id"] == best_id:
            assert "recommended" in line
            best_seen = True
        else:
            assert "recommended" not in line
    assert best_seen
    assert len({item["draft_id"] for item in checklist["items"]}) == 3

    code = main(["list-drafts", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["not_business_conversion"] is True
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert [row["draft_id"] for row in payload["drafts"]] == [item["id"] for item in stored["drafts"]]
    assert [row["variant"] for row in payload["drafts"]] == [item["variant"] for item in stored["drafts"]]
    assert [row["char_count"] for row in payload["drafts"]] == [item["char_count"] for item in stored["drafts"]]
    stored_overall = {item["draft_id"]: item["score"]["overall"] for item in scores["drafts"]}
    assert [row["overall"] for row in payload["drafts"]] == [
        stored_overall[item["id"]] for item in stored["drafts"]
    ]
    assert sum(1 for row in payload["drafts"] if row["recommended"]) == 1
    assert next(row["draft_id"] for row in payload["drafts"] if row["recommended"]) == best_id
    assert all(row["checklist_passed"] is True for row in payload["drafts"])
    assert all(row["high_finding_count"] == 0 for row in payload["drafts"])


def test_list_drafts_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["list-drafts", "--help"])
    assert code == 0
    text = capsys.readouterr().out
    assert "--out" in text
    assert "--json" in text
    assert "--version" in text
    assert "--draft" in text
    assert "--variant" in text
    assert "--channel" in text
    assert "--brief" in text

    code = main(["--help"])
    assert code == 0
    assert "list-drafts" in capsys.readouterr().out


def test_show_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "empty"
    code = main(["show", "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有文案" in captured.out
    assert "runs: 0" in captured.out
    assert "with_drafts: 0" in captured.out
    assert "without_drafts: 0" in captured.out
    assert "listed: 0" in captured.out
    assert "recommended: 0" in captured.out
    assert "not_recommended: 0" in captured.out
    assert OFFLINE_SCORE_NOTE in captured.out
    assert "```text" not in captured.out
    assert captured.err == ""

    code = main(["show", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["drafts"] == []
    assert payload["skipped"] == []
    assert payload["n"] == 0
    assert payload["n_listed"] == 0
    assert payload["kind"] == "stored_draft_text"
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True

    junk_only = tmp_path / "junk-only"
    (junk_only / "runs" / "nope").mkdir(parents=True)
    code = main(["show", "--out", str(junk_only)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有文案" in captured.out
    assert "nope" not in captured.out
    assert "跳过无效运行目录: nope" in captured.err


def test_show_text_json_and_filters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    _write_draft_run(
        out,
        "zzz",
        "coffee-wechat",
        "2024-01-01T00:00:00+00:00",
        "wechat",
        "微信公众号",
        [
            "skip",
            None,
            {"id": "z-b", "variant": "B", "angle": "痛点", "char_count": 80, "text": "痛点第一行\n痛点第二行"},
            {"id": "z-a", "variant": "A", "angle": "清单", "char_count": 90, "text": "清单正文"},
            {"id": "z-c", "variant": "C", "angle": "", "char_count": 70, "text": 12},
        ],
        "z-a",
        scores=[
            {
                "draft_id": "z-b",
                "variant": "B",
                "angle": "痛点",
                "score": {
                    "overall": 70,
                    "dimensions": {
                        "selling_point_accuracy": {"label": "卖点准确", "score": 80},
                        "channel_fit": {"label": "渠道适配", "score": 70},
                        "compliance": {"label": "合规", "score": 60},
                    },
                },
            },
            {
                "draft_id": "z-a",
                "variant": "A",
                "angle": "清单",
                "score": {
                    "overall": 100,
                    "dimensions": {
                        key: {"label": label, "score": 100} for key, label in DIMENSIONS
                    },
                },
            },
        ],
        checklist_items=[
            {
                "draft_id": "z-b",
                "passed": False,
                "findings": [
                    {
                        "rule_id": "absolute_claim",
                        "severity": "high",
                        "message": "绝对化用语",
                        "evidence": "全网第一",
                    },
                    "skip",
                    {"rule_id": "tone", "severity": "medium", "message": "语气偏硬", "evidence": "必须"},
                ],
            },
            {"draft_id": "z-a", "passed": True, "findings": []},
        ],
        record_extra={
            "approval_status": "approved",
            "reviewer": "提交人",
            "comment": "版本备注",
            "approval_reviewer": "林可",
            "approval_comment": "保留声明",
            "approved_draft_id": "z-a",
        },
        approval={"status": "rejected", "reviewer": "文件里的人", "comment": "文件里的话", "draft_id": "z-b"},
    )
    _write_draft_run(
        out,
        "aaa",
        "sunscreen-xhs",
        "2024-05-01T00:00:00+00:00",
        "xiaohongshu",
        "小红书",
        [
            {"id": "a-b", "variant": "B", "angle": "场景", "char_count": 40, "text": "场景正文"},
            {"id": "a-a", "variant": "A", "angle": "痛点", "char_count": 50, "text": "痛点正文"},
        ],
        "a-a",
        scores=[
            {"draft_id": "a-b", "variant": "B", "angle": "场景", "score": {"overall": 88}},
            {"draft_id": "a-a", "variant": "A", "angle": "痛点", "score": {"overall": 100}},
        ],
        checklist_items=[
            {
                "draft_id": "a-b",
                "passed": False,
                "findings": [{"severity": "medium", "rule_id": "tone", "message": "语气", "evidence": "家人们"}],
            },
            {"draft_id": "a-a", "passed": True, "findings": []},
        ],
        approval={"status": "approved", "reviewer": "文件审阅", "comment": "文件意见", "draft_id": "a-a"},
    )
    _write_draft_run(
        out,
        "bare",
        "kidsnack-ecommerce",
        "2024-06-01T00:00:00+00:00",
        None,
        None,
        [{"id": "bare-a", "variant": "A", "angle": "配料", "char_count": 12, "text": "配料表第一位是燕麦"}],
        "bare-a",
        include_scores=False,
        include_checklist=False,
        record_extra={"approval_status": None},
        approval={"status": "rejected", "reviewer": "周宁", "comment": "语气太满", "draft_id": "bare-a"},
    )
    (out / "runs" / "nope").mkdir(parents=True)
    before = _snapshot(out)
    code = main(["list-drafts", "--out", str(out)])
    assert code == 0
    assert _snapshot(out) == before
    listing = capsys.readouterr().out
    assert "```text" not in listing
    assert "痛点第一行" not in listing
    assert "配料表第一位是燕麦" not in listing

    code = main(["show", "--out", str(out)])
    assert code == 0
    assert _snapshot(out) == before
    captured = capsys.readouterr()
    assert "跳过无效运行目录: nope" in captured.err
    text = captured.out
    lines = text.splitlines()
    assert "没有文案" not in text
    assert "文件里的人" not in text
    assert "版本备注" not in text
    assert text.index("zzz |") < text.index("aaa |") < text.index("bare |")
    z_b = _header_index(lines, "z-b")
    assert lines[z_b] == (
        "zzz | coffee-wechat | v1 | z-b | B | 痛点 | chars 80 | overall 70 | — | checklist failed | high 1"
    )
    assert lines[z_b + 1] == "dimensions: 卖点准确 80, 渠道适配 70, 合规 60, 可读性 —"
    assert lines[z_b + 2] == "```text"
    assert lines[z_b + 3] == "痛点第一行"
    assert lines[z_b + 4] == "痛点第二行"
    assert lines[z_b + 5] == "```"
    assert lines[z_b + 6] == "high: absolute_claim | 绝对化用语 | 全网第一"
    assert lines[z_b + 7] == "medium: tone | 语气偏硬 | 必须"
    z_a = _header_index(lines, "z-a")
    assert "recommended" in lines[z_a]
    assert lines[z_a + 1] == "dimensions: 卖点准确 100, 渠道适配 100, 合规 100, 可读性 100"
    assert lines[z_a + 2 : z_a + 5] == ["```text", "清单正文", "```"]
    z_c = _header_index(lines, "z-c")
    assert lines[z_c] == "zzz | coffee-wechat | v1 | z-c | C | — | chars 70 | overall — | — | checklist — | high —"
    assert lines[z_c + 1] == "text: —"
    assert lines[z_c + 2] == "approval: approved | reviewer 林可 | 保留声明 | draft z-a"
    a_b = _header_index(lines, "a-b")
    assert lines[a_b + 1] == "```text"
    assert lines[a_b + 2] == "场景正文"
    assert "medium: tone | 语气 | 家人们" in text
    bare = _header_index(lines, "bare-a")
    assert lines[bare].startswith(
        "bare | kidsnack-ecommerce | v1 | bare-a | A | 配料 | chars 12 | overall — | recommended | checklist — | high —"
    )
    assert lines[bare + 1] == "```text"
    assert lines[bare + 2] == "配料表第一位是燕麦"
    assert lines[bare + 3] == "```"
    assert lines[bare + 4] == "approval: rejected | reviewer 周宁 | 语气太满 | draft bare-a"
    assert text.count("approval:") == 3
    assert "runs: 3" in text
    assert "with_drafts: 3" in text
    assert "without_drafts: 0" in text
    assert "listed: 6" in text
    assert "recommended: 3" in text
    assert "not_recommended: 3" in text
    assert "by_brief: coffee-wechat 3, sunscreen-xhs 2, kidsnack-ecommerce 1" in text
    assert "by_channel: wechat 3, xiaohongshu 2, unknown 1" in text
    assert "by_variant: A 3, B 2, C 1" in text
    assert f"note: {OFFLINE_SCORE_NOTE}" in text

    code = main(["show", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "stored_draft_text"
    assert payload["n_listed"] == 6
    assert payload["not_business_conversion"] is True
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["skipped"] == ["nope"]
    assert [row["text"] for row in payload["drafts"]] == [
        "痛点第一行\n痛点第二行",
        "清单正文",
        None,
        "场景正文",
        "痛点正文",
        "配料表第一位是燕麦",
    ]
    assert payload["drafts"][2]["dimensions"] is None
    assert payload["drafts"][2]["findings"] == []
    assert payload["drafts"][0]["dimensions"]["readability"] is None
    assert payload["drafts"][0]["dimensions"]["compliance"] == 60
    assert payload["drafts"][0]["findings"][1]["severity"] == "medium"
    assert payload["drafts"][0]["approval_status"] == "approved"
    assert payload["drafts"][0]["reviewer"] == "林可"
    assert payload["drafts"][3]["approval_status"] == "pending"
    assert payload["drafts"][3]["reviewer"] == "文件审阅"
    assert payload["drafts"][5]["channel"] == "unknown"
    assert payload["drafts"][5]["approval_status"] == "rejected"
    assert payload["filters"]["draft"] is None

    code = main(
        [
            "show",
            "--draft",
            "a-b",
            "--variant",
            "B",
            "--channel",
            "xhs",
            "--brief",
            "sunscreen-xhs",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    filtered = capsys.readouterr().out
    assert "场景正文" in filtered
    assert "痛点第一行" not in filtered
    assert "配料表第一位是燕麦" not in filtered
    assert "zzz |" not in filtered
    assert "bare |" not in filtered
    assert "with_drafts: 3" in filtered
    assert "listed: 1" in filtered
    assert "recommended: 0" in filtered
    assert "not_recommended: 1" in filtered
    assert filtered.count("approval:") == 1

    code = main(["show", "--draft", "a-b", "--variant", "A", "--out", str(out)])
    assert code == 0
    empty = capsys.readouterr().out
    assert "没有文案" in empty
    assert "```text" not in empty
    assert "with_drafts: 3" in empty
    assert "without_drafts: 0" in empty
    assert "listed: 0" in empty
    assert "by_brief: —" in empty

    code = main(["show", "--channel", "unknown", "--out", str(out), "--json"])
    assert code == 0
    unknown = json.loads(capsys.readouterr().out)
    assert [row["draft_id"] for row in unknown["drafts"]] == ["bare-a"]
    assert unknown["drafts"][0]["text"] == "配料表第一位是燕麦"
    assert unknown["n_with_drafts"] == 3
    assert unknown["n_listed"] == 1


def test_show_named_missing_run_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    _write_draft_run(
        out,
        "sun",
        "sunscreen-xhs",
        "2024-01-01T00:00:00+00:00",
        "xiaohongshu",
        "小红书",
        [{"id": "v1-a", "variant": "A", "angle": "痛点", "char_count": 10, "text": "还在"}],
        "v1-a",
        include_scores=False,
        include_checklist=False,
    )
    code = main(["show", "missing-run", "--out", str(out)])
    assert code == 2
    assert "找不到运行" in capsys.readouterr().err

    code = main(["show", "sun", "--version", "v9", "--out", str(out)])
    assert code == 2
    assert "版本索引里没有 v9" in capsys.readouterr().err

    code = main(["show", "--version", "v1", "--out", str(out)])
    assert code == 2
    assert "--version 需要同时提供 run id" in capsys.readouterr().err

    broken = out / "runs" / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{", encoding="utf-8")
    (broken / "versions.json").write_text("{", encoding="utf-8")
    code = main(["show", "broken", "--out", str(out)])
    assert code == 2
    assert "无法读取" in capsys.readouterr().err


def test_show_selects_latest_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    run = out / "runs" / "sun"
    for version, draft_id, overall, copy in (
        ("v1", "old-a", 11, "旧版正文"),
        ("v2", "new-a", 22, "新版第一行\n新版第二行"),
    ):
        directory = run / "versions" / version
        directory.mkdir(parents=True)
        _write_json(
            directory / "drafts.json",
            {"drafts": [{"id": draft_id, "variant": "A", "angle": version, "char_count": 3, "text": copy}]},
        )
        _write_json(
            directory / "scores.json",
            {
                "drafts": [
                    {
                        "draft_id": draft_id,
                        "variant": "A",
                        "angle": version,
                        "score": {
                            "overall": overall,
                            "dimensions": {
                                "selling_point_accuracy": {"score": overall},
                                "channel_fit": {"score": overall},
                                "compliance": {"score": overall},
                                "readability": {"score": overall},
                            },
                        },
                    }
                ]
            },
        )
    _write_json(
        run / "manifest.json",
        {"run_id": "sun", "brief_id": "sunscreen-xhs", "channel": "xiaohongshu", "channel_label": "小红书"},
    )
    _write_json(
        run / "versions.json",
        {
            "run_id": "sun",
            "versions": [
                {
                    "version": "v1",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "best_draft_id": "old-a",
                    "channel": "wechat",
                    "channel_label": "微信公众号",
                    "approval_status": "pending",
                },
                {
                    "version": "v2",
                    "created_at": "2024-02-01T00:00:00+00:00",
                    "best_draft_id": "new-a",
                    "channel": "xiaohongshu",
                    "channel_label": "小红书",
                    "approval_status": "approved",
                    "approval_reviewer": "林可",
                    "approval_comment": "用新版",
                    "approved_draft_id": "new-a",
                },
            ],
        },
    )
    _write_json(
        run / "drafts.json",
        {"drafts": [{"id": "root-only", "variant": "A", "angle": "根", "char_count": 1, "text": "根目录正文"}]},
    )
    quiet = out / "runs" / "quiet"
    (quiet / "versions" / "v1").mkdir(parents=True)
    _write_json(quiet / "manifest.json", {"run_id": "quiet", "brief_id": "coffee-wechat"})
    _write_json(
        quiet / "versions.json",
        {
            "run_id": "quiet",
            "versions": [
                {"version": "v1", "created_at": "2024-03-01T00:00:00+00:00", "best_draft_id": "q-a"}
            ],
        },
    )

    code = main(["show", "--out", str(out)])
    assert code == 0
    text = capsys.readouterr().out
    assert "新版第一行" in text
    assert "新版第二行" in text
    assert "旧版正文" not in text
    assert "根目录正文" not in text
    assert "old-a" not in text
    assert "root-only" not in text
    assert "sun | sunscreen-xhs | v2 | new-a | A | v2 | chars 3 | overall 22 | recommended" in text
    assert "dimensions: 卖点准确 22, 渠道适配 22, 合规 22, 可读性 22" in text
    assert "approval: approved | reviewer 林可 | 用新版 | draft new-a" in text
    assert "runs: 2" in text
    assert "with_drafts: 1" in text
    assert "without_drafts: 1" in text
    assert "listed: 1" in text

    code = main(["show", "sun", "--version", "v1", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n"] == 1
    assert payload["drafts"][0]["draft_id"] == "old-a"
    assert payload["drafts"][0]["text"] == "旧版正文"
    assert payload["drafts"][0]["version"] == "v1"
    assert payload["drafts"][0]["overall"] == 11
    assert payload["drafts"][0]["channel"] == "wechat"
    assert payload["drafts"][0]["recommended"] is True
    assert payload["drafts"][0]["approval_status"] == "pending"
    assert "new-a" not in json.dumps(payload["drafts"], ensure_ascii=False)
    assert "根目录正文" not in json.dumps(payload["drafts"], ensure_ascii=False)


def test_show_mock_run_prints_stored_text_and_does_not_call_a_model(
    briefs_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("show must not call a model or rescore")

    out = tmp_path / "out"
    assert (
        main(
            [
                "run",
                str(briefs_dir / "sunscreen-xhs.yaml"),
                "--mock",
                "--run-id",
                "demo-sunscreen",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    capsys.readouterr()
    root = out / "runs" / "demo-sunscreen" / "versions" / "v1"
    stored = json.loads((root / "drafts.json").read_text(encoding="utf-8"))
    scores = json.loads((root / "scores.json").read_text(encoding="utf-8"))
    checklist = json.loads((root / "checklist.json").read_text(encoding="utf-8"))
    history = json.loads((out / "runs" / "demo-sunscreen" / "versions.json").read_text(encoding="utf-8"))
    record = history["versions"][0]
    assert len(stored["drafts"]) == 3
    before = _snapshot(out)
    monkeypatch.setattr("mcw.cli.rescore_version", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("mcw.risk.rules.run_rules", fail)
    monkeypatch.setattr("mcw.textutil.char_count", fail)
    monkeypatch.setattr("urllib.request.urlopen", fail)
    code = main(["show", "--out", str(out)])
    assert code == 0
    assert _snapshot(out) == before
    captured = capsys.readouterr()
    text = captured.out
    lines = text.splitlines()
    assert captured.err == ""
    assert "没有文案" not in text
    assert OFFLINE_SCORE_NOTE in text
    assert "listed: 3" in text
    assert "recommended: 1" in text
    assert "not_recommended: 2" in text
    assert text.count("approval:") == 1
    best_id = scores["best_draft_id"]
    best_seen = False
    score_by_id = {item["draft_id"]: item["score"] for item in scores["drafts"]}
    findings_by_id = {item["draft_id"]: item["findings"] for item in checklist["items"]}
    for draft in stored["drafts"]:
        assert draft["text"] in text
        header = next(
            line
            for line in lines
            if line.startswith("demo-sunscreen") and f"| {draft['id']} |" in line
        )
        if draft["id"] == best_id:
            assert "recommended" in header
            best_seen = True
        else:
            assert "recommended" not in header
        pos = lines.index(header)
        dims = score_by_id[draft["id"]]["dimensions"]
        expected_dims = "dimensions: " + ", ".join(
            f"{label} {dims[key]['score']}" for key, label in DIMENSIONS
        )
        assert lines[pos + 1] == expected_dims
        body = draft["text"].splitlines()
        assert lines[pos + 2] == "```text"
        assert lines[pos + 3 : pos + 3 + len(body)] == body
        assert lines[pos + 3 + len(body)] == "```"
    assert best_seen
    assert f"approval: {record['approval_status']} | {record['comment']}" in text

    code = main(["show", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "stored_draft_text"
    assert payload["not_business_conversion"] is True
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert [row["draft_id"] for row in payload["drafts"]] == [item["id"] for item in stored["drafts"]]
    assert [row["text"] for row in payload["drafts"]] == [item["text"] for item in stored["drafts"]]
    assert [row["variant"] for row in payload["drafts"]] == [item["variant"] for item in stored["drafts"]]
    assert [row["char_count"] for row in payload["drafts"]] == [item["char_count"] for item in stored["drafts"]]
    assert [row["overall"] for row in payload["drafts"]] == [
        score_by_id[item["id"]]["overall"] for item in stored["drafts"]
    ]
    for row in payload["drafts"]:
        stored_dims = score_by_id[row["draft_id"]]["dimensions"]
        assert row["dimensions"] == {key: stored_dims[key]["score"] for key, _label in DIMENSIONS}
        assert row["findings"] == [
            {
                "rule_id": finding["rule_id"],
                "severity": finding["severity"],
                "message": finding["message"],
                "evidence": finding["evidence"],
                "suggestion": finding["suggestion"],
            }
            for finding in findings_by_id[row["draft_id"]]
        ]
        assert row["approval_status"] == record["approval_status"]
        assert row["comment"] == record["comment"]
    assert sum(1 for row in payload["drafts"] if row["recommended"]) == 1
    assert next(row["draft_id"] for row in payload["drafts"] if row["recommended"]) == best_id
    assert all(row["checklist_passed"] is True for row in payload["drafts"])
    assert all(row["high_finding_count"] == 0 for row in payload["drafts"])


def test_show_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["show", "--help"])
    assert code == 0
    text = capsys.readouterr().out
    assert "--out" in text
    assert "--json" in text
    assert "--version" in text
    assert "--draft" in text
    assert "--variant" in text
    assert "--channel" in text
    assert "--brief" in text

    code = main(["--help"])
    assert code == 0
    assert "show" in capsys.readouterr().out


def _header_index(lines: list[str], draft_id: str) -> int:
    return next(index for index, line in enumerate(lines) if f"| {draft_id} |" in line)


def _write_draft_run(
    out: Path,
    run_id: str,
    brief_id: str,
    created_at: str,
    channel: str | None,
    channel_label: str | None,
    drafts: list,
    best_draft_id: str,
    *,
    scores: list | None = None,
    checklist_items: list | None = None,
    include_scores: bool = True,
    include_checklist: bool = True,
    record_extra: dict | None = None,
    approval: dict | None = None,
) -> None:
    run = out / "runs" / run_id
    version_dir = run / "versions" / "v1"
    version_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"run_id": run_id, "brief_id": brief_id}
    record: dict = {
        "version": "v1",
        "created_at": created_at,
        "approval_status": "pending",
        "overall_score": 100,
        "best_draft_id": best_draft_id,
    }
    if channel is not None:
        manifest["channel"] = channel
        record["channel"] = channel
    if channel_label is not None:
        manifest["channel_label"] = channel_label
        record["channel_label"] = channel_label
    if record_extra:
        record.update(record_extra)
    _write_json(run / "manifest.json", manifest)
    _write_json(run / "versions.json", {"run_id": run_id, "versions": [record]})
    _write_json(version_dir / "drafts.json", {"drafts": drafts})
    if include_scores:
        _write_json(version_dir / "scores.json", {"best_draft_id": best_draft_id, "drafts": scores or []})
    if include_checklist:
        _write_json(version_dir / "checklist.json", {"items": checklist_items or []})
    if approval is not None:
        _write_json(version_dir / "approval.json", approval)
