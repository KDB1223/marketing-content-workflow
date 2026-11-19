from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcw.errors import MCWError
from mcw.scoring.rubric import DIMENSIONS, OFFLINE_SCORE_NOTE
from mcw.store import inventory_failures, list_saved_runs, summarize_saved_runs


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _version(version: str, **overrides: object) -> dict:
    record: dict = {
        "version": version,
        "created_at": "2024-01-01T00:00:00+00:00",
        "approval_status": "pending",
        "overall_score": 100,
        "backend": "mock",
        "dimension_scores": {
            "selling_point_accuracy": 100,
            "channel_fit": 100,
            "compliance": 100,
            "readability": 100,
        },
    }
    record.update(overrides)
    return record


def _save(out: Path, name: str, brief_id: str, versions: list[dict], **manifest: object) -> None:
    directory = out / "runs" / name
    body: dict = {"run_id": name, "brief_id": brief_id}
    body.update(manifest)
    _write(directory / "manifest.json", body)
    _write(directory / "versions.json", {"run_id": name, "versions": versions})


def test_summarize_saved_runs_uses_latest_stored_numbers(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(
        out,
        "sun",
        "sunscreen-xhs",
        [
            _version("v1", overall_score=10, approval_status="pending"),
            _version(
                "v2",
                overall_score=90,
                approval_status="approved",
                dimension_scores={
                    "selling_point_accuracy": 80,
                    "channel_fit": 70,
                    "compliance": 60,
                    "readability": 50,
                    "ignored": 1,
                },
            ),
        ],
    )
    _save(
        out,
        "coffee",
        "coffee-wechat",
        [_version("v1", overall_score=42, approval_status="pending", backend="")],
    )
    _save(
        out,
        "zeta",
        "zeta-brief",
        [
            _version(
                "v1",
                overall_score=True,
                approval_status=None,
                backend=None,
                dimension_scores=["nope"],
            )
        ],
    )
    _save(
        out,
        "extra",
        "sunscreen-xhs",
        [
            _version(
                "v3",
                overall_score="n/a",
                approval_status="needs-edit",
                backend="mock",
                dimension_scores={
                    "selling_point_accuracy": True,
                    "channel_fit": "80",
                    "compliance": 90,
                    "readability": None,
                },
            ),
            _version("v1", overall_score=1, approval_status="rejected"),
        ],
    )
    (out / "runs" / "empty-junk").mkdir(parents=True)
    bad = out / "runs" / "bad-json"
    bad.mkdir()
    (bad / "manifest.json").write_text("{", encoding="utf-8")
    (bad / "versions.json").write_text("{", encoding="utf-8")
    shape = out / "runs" / "bad-shape"
    shape.mkdir()
    _write(shape / "manifest.json", {"brief_id": "x"})
    (shape / "versions.json").write_text("[]\n", encoding="utf-8")
    _write(out / "runs" / "sun" / "scores.json", {"drafts": [{"score": {"overall": 100}}]})

    payload = summarize_saved_runs(out)
    assert payload["skipped"] == list_saved_runs(out)["skipped"]
    assert payload["run_count"] == 4
    assert payload["version_count"] == 2 + 1 + 1 + 2
    assert payload["approval"] == {
        "approved": 1,
        "pending": 1,
        "needs-edit": 1,
        "unknown": 1,
    }
    assert payload["briefs"] == [
        {
            "brief_id": "sunscreen-xhs",
            "run_count": 2,
            "overall_scores": {"count": 1, "min": 90, "max": 90, "mean": 90.0},
        },
        {
            "brief_id": "coffee-wechat",
            "run_count": 1,
            "overall_scores": {"count": 1, "min": 42, "max": 42, "mean": 42.0},
        },
        {
            "brief_id": "zeta-brief",
            "run_count": 1,
            "overall_scores": {"count": 0, "min": None, "max": None, "mean": None},
        },
    ]
    assert payload["backends"] == [
        {
            "backend": "mock",
            "run_count": 2,
            "overall_scores": {"count": 1, "min": 90, "max": 90, "mean": 90.0},
        },
        {
            "backend": "unknown",
            "run_count": 2,
            "overall_scores": {"count": 1, "min": 42, "max": 42, "mean": 42.0},
        },
    ]
    assert payload["approval_groups"] == [
        {
            "status": "approved",
            "run_count": 1,
            "overall_scores": {"count": 1, "min": 90, "max": 90, "mean": 90.0},
        },
        {
            "status": "pending",
            "run_count": 1,
            "overall_scores": {"count": 1, "min": 42, "max": 42, "mean": 42.0},
        },
        {
            "status": "needs-edit",
            "run_count": 1,
            "overall_scores": {"count": 0, "min": None, "max": None, "mean": None},
        },
        {
            "status": "unknown",
            "run_count": 1,
            "overall_scores": {"count": 0, "min": None, "max": None, "mean": None},
        },
    ]
    # Hand-written indexes have no channel, so every run lands in unknown.
    # Latest only: sun v2 = 90 and coffee v1 = 42. extra's v1 score of 1 is not latest.
    assert payload["channels"] == [
        {
            "channel": "unknown",
            "channel_label": "unknown",
            "run_count": 4,
            "overall_scores": {"count": 2, "min": 42, "max": 90, "mean": 66.0},
        }
    ]
    # latest only: sun v2 = 90, coffee v1 = 42. bools and non-numeric strings are not scores.
    # extra's latest version is v3, not the earlier v1 score of 1.
    assert payload["overall_scores"] == {"count": 2, "min": 42, "max": 90, "mean": 66.0}
    assert payload["dimension_scores"]["selling_point_accuracy"] == {"count": 2, "mean": 90.0}
    assert payload["dimension_scores"]["channel_fit"] == {"count": 2, "mean": 85.0}
    assert payload["dimension_scores"]["compliance"] == {"count": 3, "mean": 83.33}
    assert payload["dimension_scores"]["readability"] == {"count": 2, "mean": 75.0}
    assert "ignored" not in payload["dimension_scores"]
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True
    assert json.loads((out / "runs" / "sun" / "scores.json").read_text(encoding="utf-8"))["drafts"][0]["score"][
        "overall"
    ] == 100


def test_summarize_saved_runs_empty(tmp_path: Path) -> None:
    payload = summarize_saved_runs(tmp_path / "missing")
    assert payload["run_count"] == 0
    assert payload["skipped"] == []
    assert payload["version_count"] == 0
    assert payload["briefs"] == []
    assert payload["backends"] == []
    assert payload["channels"] == []
    assert payload["approval"] == {}
    assert payload["approval_groups"] == []
    assert payload["overall_scores"] == {"count": 0, "min": None, "max": None, "mean": None}
    assert payload["dimension_scores"] == {}
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True


def test_saved_run_channel_prefers_version_then_manifest(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(
        out,
        "from-version",
        "sunscreen-xhs",
        [_version("v1", channel="wechat", channel_label="微信公众号")],
        channel="xiaohongshu",
        channel_label="小红书",
    )
    _save(
        out,
        "from-manifest",
        "coffee-wechat",
        [_version("v1", channel="", channel_label="  ")],
        channel=" wechat ",
        channel_label="微信公众号",
    )
    _save(out, "missing", "zeta-brief", [_version("v1", channel=None, channel_label=12)])
    _save(
        out,
        "label-from-manifest",
        "sunscreen-xhs",
        [_version("v1", channel="xiaohongshu", channel_label="")],
        channel="douyin",
        channel_label="抖音",
    )
    rows = {row["run_id"]: row for row in list_saved_runs(out)["runs"]}
    assert set(rows) == {"from-version", "from-manifest", "missing", "label-from-manifest"}
    assert rows["from-version"]["channel"] == "wechat"
    assert rows["from-version"]["channel_label"] == "微信公众号"
    assert rows["from-manifest"]["channel"] == "wechat"
    assert rows["from-manifest"]["channel_label"] == "微信公众号"
    assert rows["missing"]["channel"] == "unknown"
    assert rows["missing"]["channel_label"] == "unknown"
    assert rows["label-from-manifest"]["channel"] == "xiaohongshu"
    assert rows["label-from-manifest"]["channel_label"] == "抖音"


def test_summarize_shared_brief_and_channel_use_latest_scores(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(
        out,
        "sun-early-label",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                overall_score=1,
                created_at="2024-01-01T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
            ),
            _version(
                "v3",
                overall_score=40,
                created_at="2024-02-01T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="unknown",
            ),
        ],
    )
    _save(
        out,
        "sun-later-label",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                overall_score=10,
                created_at="2024-01-15T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
            ),
            _version(
                "v2",
                overall_score=90,
                created_at="2024-03-01T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
            ),
        ],
    )
    payload = summarize_saved_runs(out)
    shared = {"count": 2, "min": 40, "max": 90, "mean": 65.0}
    assert payload["overall_scores"] == shared
    assert payload["briefs"] == [
        {"brief_id": "sunscreen-xhs", "run_count": 2, "overall_scores": shared}
    ]
    assert payload["channels"] == [
        {
            "channel": "xiaohongshu",
            "channel_label": "小红书",
            "run_count": 2,
            "overall_scores": shared,
        }
    ]
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True


_FULL_DIMS = {
    "selling_point_accuracy": 100,
    "channel_fit": 100,
    "compliance": 100,
    "readability": 100,
}


def _version_artifact(out: Path, name: str, version: str, filename: str, payload: object) -> None:
    _write(out / "runs" / name / "versions" / version / filename, payload)


def _finding(rule_id: str, severity: str, message: str, evidence: str) -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "evidence": evidence,
        "suggestion": "",
    }


def _checklist(items: list[dict]) -> dict:
    return {"items": items}


def _checklist_item(draft_id: str, passed: bool, findings: list[dict]) -> dict:
    return {"draft_id": draft_id, "passed": passed, "summary": "", "findings": findings}


def _scores(best_id: str, drafts: list[dict]) -> dict:
    return {
        "kind": "offline_content_score",
        "not_business_conversion": True,
        "note": OFFLINE_SCORE_NOTE,
        "best_draft_id": best_id,
        "drafts": drafts,
    }


def _draft_score(draft_id: str, variant: str, overall: object, dims: dict) -> dict:
    return {
        "draft_id": draft_id,
        "variant": variant,
        "score": {
            "overall": overall,
            "dimensions": {
                key: {"label": "WRONG", "score": dims[key]}
                for key, _label in DIMENSIONS
            },
        },
    }


def _tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_inventory_failures_empty(tmp_path: Path) -> None:
    payload = inventory_failures(tmp_path / "missing")
    assert payload["failures"] == []
    assert payload["skipped"] == []
    assert payload["kind"] == "offline_content_score"
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True


def test_inventory_failures_omits_clean_pending_and_weaker_alternatives(tmp_path: Path) -> None:
    out = tmp_path / "out"
    dims = dict(_FULL_DIMS)
    _save(
        out,
        "clean",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                overall_score=100,
                approval_status="pending",
                best_draft_id="v1-a",
                dimension_scores=dims,
                variant_scores=[
                    {"draft_id": "v1-a", "variant": "A", "overall": 100},
                    {"draft_id": "v1-b", "variant": "B", "overall": 40},
                ],
            )
        ],
    )
    _version_artifact(
        out,
        "clean",
        "v1",
        "checklist.json",
        _checklist(
            [
                _checklist_item("v1-a", True, []),
                _checklist_item(
                    "v1-b",
                    False,
                    [_finding("absolute_claim", "high", "绝对化用语", "全网第一")],
                ),
            ]
        ),
    )
    _version_artifact(
        out,
        "clean",
        "v1",
        "scores.json",
        _scores(
            "v1-a",
            [
                _draft_score("v1-a", "A", 100, dims),
                _draft_score("v1-b", "B", 40, {**dims, "compliance": 40}),
            ],
        ),
    )
    payload = inventory_failures(out)
    assert payload["failures"] == []
    assert payload["skipped"] == []


def test_inventory_failures_lists_stored_dimension_drops(tmp_path: Path) -> None:
    out = tmp_path / "out"
    weak = {**_FULL_DIMS, "selling_point_accuracy": 80, "compliance": 75}
    _save(
        out,
        "low",
        "coffee-wechat",
        [
            _version(
                "v1",
                overall_score=10,
                approval_status="pending",
                best_draft_id="v1-a",
                created_at="2024-02-01T00:00:00+00:00",
                dimension_scores=_FULL_DIMS,
            ),
            _version(
                "v2",
                overall_score=86,
                approval_status="pending",
                best_draft_id="v2-a",
                created_at="2024-03-01T00:00:00+00:00",
                dimension_scores=_FULL_DIMS,
                variant_scores=[
                    {"draft_id": "v2-a", "variant": "A", "overall": 1},
                    {"draft_id": "v2-b", "variant": "B", "overall": 1},
                ],
            ),
        ],
    )
    _version_artifact(
        out,
        "low",
        "v2",
        "checklist.json",
        _checklist([_checklist_item("v2-a", True, [_finding("tone", "low", "口语", "家人们")])]),
    )
    _version_artifact(
        out,
        "low",
        "v2",
        "scores.json",
        _scores(
            "v2-a",
            [
                _draft_score("v2-a", "A", 86, weak),
                _draft_score("v2-b", "B", 60, {**_FULL_DIMS, "readability": 60}),
            ],
        ),
    )
    # v1's drop is not the latest version. The run-root copy is not that version's file.
    _version_artifact(out, "low", "v1", "scores.json", _scores("v1-a", [_draft_score("v1-a", "A", 10, weak)]))
    _write(out / "runs" / "low" / "scores.json", {"drafts": [{"draft_id": "v2-a", "score": {"overall": 100}}]})

    before = _tree(out)
    payload = inventory_failures(out)
    assert _tree(out) == before
    assert [row["run_id"] for row in payload["failures"]] == ["low"]
    row = payload["failures"][0]
    assert row["version"] == "v2"
    assert row["brief_id"] == "coffee-wechat"
    assert row["approval_status"] == "pending"
    assert row["best_draft_id"] == "v2-a"
    assert row["overall_score"] == 86
    assert row["reasons"] == ["overall_below_100"]
    assert row["weak_dimensions"] == [
        {"key": "selling_point_accuracy", "label": "卖点准确", "score": 80},
        {"key": "compliance", "label": "合规", "score": 75},
    ]
    assert row["high_findings"] == []
    assert row["checklist_passed"] is True
    assert row["variant_scores"] == [
        {"draft_id": "v2-a", "variant": "A", "overall": 86, "recommended": True},
        {"draft_id": "v2-b", "variant": "B", "overall": 60, "recommended": False},
    ]
    assert "WRONG" not in json.dumps(row, ensure_ascii=False)
    named = inventory_failures(out, run_id="low", version="v1")
    assert named["failures"][0]["version"] == "v1"
    assert named["failures"][0]["overall_score"] == 10
    assert named["failures"][0]["weak_dimensions"][0]["label"] == "卖点准确"


def test_inventory_failures_lists_rejected_full_score(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(
        out,
        "no",
        "creditcard-official",
        [
            _version(
                "v1",
                overall_score=100,
                approval_status="rejected",
                best_draft_id="v1-a",
                dimension_scores=_FULL_DIMS,
            )
        ],
    )
    _version_artifact(out, "no", "v1", "checklist.json", _checklist([_checklist_item("v1-a", True, [])]))
    _version_artifact(
        out,
        "no",
        "v1",
        "scores.json",
        _scores(
            "v1-a",
            [
                _draft_score("v1-a", "A", 100, _FULL_DIMS),
                _draft_score("v1-b", "B", 70, {**_FULL_DIMS, "channel_fit": 70}),
            ],
        ),
    )
    row = inventory_failures(out)["failures"][0]
    assert row["overall_score"] == 100
    assert row["approval_status"] == "rejected"
    assert row["reasons"] == ["rejected"]
    assert row["weak_dimensions"] == []
    assert row["high_findings"] == []
    assert row["variant_scores"][1]["overall"] == 70
    assert row["variant_scores"][1]["recommended"] is False


def test_inventory_failures_lists_stored_high_finding_and_failed_checklist(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(
        out,
        "risk",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                overall_score=100,
                approval_status="pending",
                best_draft_id="v1-a",
                dimension_scores=_FULL_DIMS,
                created_at="2024-01-02T00:00:00+00:00",
            )
        ],
    )
    _save(
        out,
        "soft",
        "coffee-wechat",
        [
            _version(
                "v1",
                overall_score=100,
                approval_status="pending",
                best_draft_id="v1-a",
                dimension_scores=_FULL_DIMS,
                created_at="2024-01-01T00:00:00+00:00",
            )
        ],
    )
    _version_artifact(
        out,
        "risk",
        "v1",
        "checklist.json",
        _checklist(
            [
                _checklist_item(
                    "v1-a",
                    False,
                    [
                        _finding("tone", "medium", "语气偏硬", "必须"),
                        _finding("absolute_claim", "high", "绝对化用语", "全网第一"),
                    ],
                )
            ]
        ),
    )
    _version_artifact(out, "risk", "v1", "scores.json", _scores("v1-a", [_draft_score("v1-a", "A", 100, _FULL_DIMS)]))
    _version_artifact(
        out,
        "soft",
        "v1",
        "checklist.json",
        _checklist([_checklist_item("v1-a", False, [_finding("tone", "medium", "语气偏硬", "必须")])]),
    )
    payload = inventory_failures(out)
    assert [row["run_id"] for row in payload["failures"]] == ["soft", "risk"]
    soft, risk = payload["failures"]
    assert soft["reasons"] == ["checklist_failed"]
    assert soft["high_findings"] == []
    assert soft["checklist_passed"] is False
    assert risk["reasons"] == ["checklist_failed", "high_finding"]
    assert risk["high_findings"] == [
        {"rule_id": "absolute_claim", "message": "绝对化用语", "evidence": "全网第一"}
    ]
    assert risk["weak_dimensions"] == []


def test_inventory_failures_missing_artifacts_keep_index_hits(tmp_path: Path) -> None:
    out = tmp_path / "out"
    weak = {**_FULL_DIMS, "readability": 85}
    _save(
        out,
        "index-only",
        "zeta-brief",
        [
            _version(
                "v1",
                overall_score=90,
                approval_status="pending",
                best_draft_id="v1-a",
                dimension_scores=weak,
                variant_scores=[
                    {"draft_id": "v1-a", "variant": "A", "overall": 90},
                    {"draft_id": "v1-c", "variant": "C", "overall": 50},
                ],
            )
        ],
    )
    _save(
        out,
        "unconfirmed",
        "zeta-brief",
        [_version("v1", overall_score=None, approval_status="pending", best_draft_id="v1-a")],
    )
    _save(
        out,
        "not-a-number",
        "zeta-brief",
        [_version("v1", overall_score="n/a", approval_status="approved", best_draft_id="v1-a")],
    )
    _save(
        out,
        "full-without-files",
        "sunscreen-xhs",
        [_version("v1", overall_score=100, approval_status="pending", best_draft_id="v1-a", dimension_scores=_FULL_DIMS)],
    )
    broken = out / "runs" / "index-only" / "versions" / "v1"
    broken.mkdir(parents=True)
    (broken / "checklist.json").write_text("{", encoding="utf-8")
    (broken / "scores.json").write_text("[]\n", encoding="utf-8")
    # A checklist copied to the run root is not the version artifact.
    _write(
        out / "runs" / "index-only" / "checklist.json",
        _checklist([_checklist_item("v1-a", False, [_finding("absolute_claim", "high", "绝对化用语", "全网第一")])]),
    )

    payload = inventory_failures(out)
    ids = [row["run_id"] for row in payload["failures"]]
    assert "full-without-files" not in ids
    by_id = {row["run_id"]: row for row in payload["failures"]}
    assert by_id["index-only"]["weak_dimensions"] == [{"key": "readability", "label": "可读性", "score": 85}]
    assert by_id["index-only"]["high_findings"] == []
    assert by_id["index-only"]["checklist_passed"] is None
    assert by_id["index-only"]["variant_scores"][1] == {
        "draft_id": "v1-c",
        "variant": "C",
        "overall": 50,
        "recommended": False,
    }
    assert by_id["unconfirmed"]["reasons"] == ["overall_unconfirmed"]
    assert by_id["unconfirmed"]["overall_score"] is None
    assert by_id["not-a-number"]["reasons"] == ["overall_unconfirmed"]
    assert by_id["not-a-number"]["overall_score"] == "n/a"


def test_inventory_failures_skips_invalid_directories(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(out, "low", "coffee-wechat", [_version("v1", overall_score=42, approval_status="pending")])
    (out / "runs" / "empty-junk").mkdir(parents=True)
    bad = out / "runs" / "bad-json"
    bad.mkdir()
    (bad / "manifest.json").write_text("{", encoding="utf-8")
    (bad / "versions.json").write_text("{", encoding="utf-8")
    shape = out / "runs" / "bad-shape"
    shape.mkdir()
    _write(shape / "manifest.json", {"brief_id": "x"})
    (shape / "versions.json").write_text("[]\n", encoding="utf-8")

    payload = inventory_failures(out)
    assert payload["skipped"] == list_saved_runs(out)["skipped"]
    assert [row["run_id"] for row in payload["failures"]] == ["low"]
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True


def test_inventory_failures_named_run_errors(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(out, "sun", "sunscreen-xhs", [_version("v1", overall_score=100, approval_status="pending")])
    with pytest.raises(MCWError, match="找不到运行"):
        inventory_failures(out, run_id="missing")
    with pytest.raises(MCWError, match="版本索引里没有 v9"):
        inventory_failures(out, run_id="sun", version="v9")
    with pytest.raises(MCWError, match="版本号不合法"):
        inventory_failures(out, run_id="sun", version="latest")
    with pytest.raises(MCWError, match="--version 需要同时提供 run id"):
        inventory_failures(out, version="v1")
    assert inventory_failures(out, run_id="sun")["failures"] == []


def test_inventory_failures_does_not_score(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("failures must not score")

    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    out = tmp_path / "out"
    _save(
        out,
        "low",
        "coffee-wechat",
        [_version("v1", overall_score=70, approval_status="rejected", best_draft_id="v1-a")],
    )
    payload = inventory_failures(out)
    assert payload["failures"][0]["reasons"] == ["overall_below_100", "rejected"]
