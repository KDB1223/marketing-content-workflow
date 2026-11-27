from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcw.errors import MCWError
from mcw.scoring.rubric import DIMENSIONS, OFFLINE_SCORE_NOTE
from mcw.store import (
    FINDINGS_INVENTORY_NOTE,
    inventory_drafts,
    inventory_failures,
    inventory_findings,
    list_saved_runs,
    show_drafts,
    summarize_saved_runs,
)


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


def test_inventory_findings_empty(tmp_path: Path) -> None:
    payload = inventory_findings(tmp_path / "missing")
    assert payload["findings"] == []
    assert payload["skipped"] == []
    assert payload["n"] == 0
    assert payload["n_with_findings"] == 0
    assert payload["n_without_findings"] == 0
    assert payload["n_listed"] == 0
    assert payload["by_rule"] == []
    assert payload["by_severity"] == []
    assert payload["filters"] == {
        "run": None,
        "version": None,
        "rule": None,
        "severity": None,
        "channel": None,
        "draft": None,
        "brief": None,
    }
    assert payload["kind"] == "stored_checklist_findings"
    assert payload["note"] == FINDINGS_INVENTORY_NOTE
    assert "checklist.json" in payload["note"]
    assert "转化率" in payload["note"]
    assert payload["not_business_conversion"] is True


def test_inventory_findings_lists_every_draft_and_keeps_counts_under_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("list-findings must not score or call a model")

    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    monkeypatch.setattr("mcw.risk.rules.run_rules", fail)
    monkeypatch.setattr("urllib.request.urlopen", fail)

    out = tmp_path / "out"
    _save(
        out,
        "zzz",
        "coffee-wechat",
        [
            _version(
                "v1",
                overall_score=10,
                approval_status="pending",
                best_draft_id="v1-a",
                created_at="2024-01-01T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
            ),
            _version(
                "v2",
                overall_score=100,
                approval_status="pending",
                best_draft_id="z-a",
                created_at="2024-01-02T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
                dimension_scores=_FULL_DIMS,
            ),
        ],
        channel="wechat",
        channel_label="微信公众号",
    )
    _version_artifact(
        out,
        "zzz",
        "v1",
        "checklist.json",
        _checklist([_checklist_item("v1-a", False, [_finding("old_only", "high", "旧版", "旧证据")])]),
    )
    _version_artifact(
        out,
        "zzz",
        "v2",
        "checklist.json",
        _checklist(
            [
                _checklist_item(
                    "z-b",
                    False,
                    [
                        _finding("required_element", "medium", "缺话题", "话题"),
                        "not-a-dict",
                        None,
                        4,
                        _finding("absolute_claim", "high", "绝对化用语", "全网第一"),
                        {},
                    ],
                ),
                _checklist_item(
                    "z-a",
                    True,
                    [
                        {
                            "rule_id": "tone",
                            "severity": "medium",
                            "message": "语气偏硬",
                            "evidence": "必须",
                            "suggestion": "改语气",
                        }
                    ],
                ),
                {"draft_id": "z-c"},
                "not-an-item",
                _checklist_item("z-d", True, []),
                {"draft_id": "z-e", "passed": True, "summary": "", "findings": "nope"},
            ]
        ),
    )
    _write(
        out / "runs" / "zzz" / "checklist.json",
        _checklist([_checklist_item("z-a", False, [_finding("root_only", "high", "根目录", "不读")])]),
    )
    _save(
        out,
        "quiet",
        "kidsnack-ecommerce",
        [
            _version(
                "v1",
                overall_score=100,
                approval_status="pending",
                best_draft_id="q-a",
                created_at="2024-03-01T00:00:00+00:00",
                dimension_scores=_FULL_DIMS,
            )
        ],
    )
    _version_artifact(
        out,
        "quiet",
        "v1",
        "checklist.json",
        _checklist(
            [
                _checklist_item("q-a", True, ["nope", None]),
                {"draft_id": "q-b", "findings": {}},
            ]
        ),
    )
    _save(
        out,
        "bare",
        "creditcard-official",
        [
            _version(
                "v1",
                overall_score=100,
                approval_status="pending",
                best_draft_id="b-a",
                created_at="2024-04-01T00:00:00+00:00",
                dimension_scores=_FULL_DIMS,
            )
        ],
    )
    _save(
        out,
        "aaa",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                overall_score=100,
                approval_status="pending",
                best_draft_id="a-a",
                created_at="2024-05-01T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
                dimension_scores=_FULL_DIMS,
            )
        ],
        channel="xiaohongshu",
        channel_label="小红书",
    )
    _version_artifact(
        out,
        "aaa",
        "v1",
        "checklist.json",
        _checklist(
            [
                _checklist_item("a-a", True, []),
                _checklist_item(
                    "a-b",
                    False,
                    [{"rule_id": "tone", "severity": "medium", "message": None, "evidence": None}],
                ),
            ]
        ),
    )
    (out / "runs" / "empty-junk").mkdir(parents=True)
    bad = out / "runs" / "bad-json"
    bad.mkdir()
    (bad / "manifest.json").write_text("{", encoding="utf-8")
    (bad / "versions.json").write_text("{", encoding="utf-8")

    before = _tree(out)
    payload = inventory_findings(out)
    assert _tree(out) == before
    assert inventory_failures(out)["failures"] == []
    assert payload["skipped"] == list_saved_runs(out)["skipped"]
    assert payload["n"] == 4
    assert payload["n_with_findings"] == 2
    assert payload["n_without_findings"] == 2
    assert payload["n_listed"] == 5
    assert [row["run_id"] for row in payload["findings"]] == ["zzz", "zzz", "zzz", "zzz", "aaa"]
    assert [row["draft_id"] for row in payload["findings"]] == ["z-b", "z-b", "z-b", "z-a", "a-b"]
    assert [row["rule_id"] for row in payload["findings"]] == [
        "required_element",
        "absolute_claim",
        None,
        "tone",
        "tone",
    ]
    assert payload["findings"][0]["version"] == "v2"
    assert payload["findings"][0]["channel"] == "wechat"
    assert payload["findings"][0]["channel_label"] == "微信公众号"
    assert payload["findings"][3]["suggestion"] == "改语气"
    assert payload["findings"][3]["message"] == "语气偏硬"
    assert payload["findings"][4]["evidence"] is None
    assert payload["findings"][4]["message"] is None
    assert payload["findings"][4]["suggestion"] is None
    assert payload["findings"][4]["channel"] == "xiaohongshu"
    assert "old_only" not in json.dumps(payload["findings"], ensure_ascii=False)
    assert "root_only" not in json.dumps(payload["findings"], ensure_ascii=False)
    assert payload["by_rule"] == [
        {"rule_id": "tone", "count": 2},
        {"rule_id": "absolute_claim", "count": 1},
        {"rule_id": "required_element", "count": 1},
        {"rule_id": "unknown", "count": 1},
    ]
    assert payload["by_severity"] == [
        {"severity": "medium", "count": 3},
        {"severity": "high", "count": 1},
        {"severity": "unknown", "count": 1},
    ]
    assert payload["note"] == FINDINGS_INVENTORY_NOTE
    assert payload["not_business_conversion"] is True

    tone = inventory_findings(out, rule="tone", severity="medium")
    assert [row["draft_id"] for row in tone["findings"]] == ["z-a", "a-b"]
    assert tone["n"] == payload["n"]
    assert tone["n_with_findings"] == payload["n_with_findings"]
    assert tone["n_without_findings"] == payload["n_without_findings"]
    assert tone["n_listed"] == 2
    assert tone["by_rule"] == [{"rule_id": "tone", "count": 2}]
    assert tone["filters"]["rule"] == "tone"
    assert tone["filters"]["severity"] == "medium"

    missed = inventory_findings(out, rule="absolute_claim", severity="medium")
    assert missed["findings"] == []
    assert missed["n_listed"] == 0
    assert missed["n_with_findings"] == 2
    assert missed["n_without_findings"] == 2
    assert missed["by_rule"] == []
    assert missed["by_severity"] == []

    draft_rows = inventory_findings(out, draft="z-b")
    assert [row["rule_id"] for row in draft_rows["findings"]] == ["required_element", "absolute_claim", None]
    assert draft_rows["n_with_findings"] == 2

    brief_rows = inventory_findings(out, brief="sunscreen-xhs")
    assert [row["run_id"] for row in brief_rows["findings"]] == ["aaa"]
    assert brief_rows["n_with_findings"] == 2

    for channel in ("xhs", "小红书", "xiaohongshu", " XHS "):
        matched = inventory_findings(out, channel=channel)
        assert [row["run_id"] for row in matched["findings"]] == ["aaa"]
        assert matched["n_with_findings"] == 2
    for channel in ("wechat", "微信", "微信公众号"):
        matched = inventory_findings(out, channel=channel)
        assert [row["run_id"] for row in matched["findings"]] == ["zzz", "zzz", "zzz", "zzz"]
    unknown = inventory_findings(out, channel="unknown")
    assert unknown["findings"] == []
    assert unknown["n"] == 4
    assert unknown["n_with_findings"] == 2
    assert unknown["n_without_findings"] == 2
    assert unknown["n_listed"] == 0
    combined = inventory_findings(out, channel="xhs", rule="absolute_claim")
    assert combined["findings"] == []
    assert combined["n_with_findings"] == 2

    named = inventory_findings(out, run_id="zzz", version="v1")
    assert named["n"] == 1
    assert named["n_with_findings"] == 1
    assert named["n_without_findings"] == 0
    assert named["skipped"] == []
    assert [row["rule_id"] for row in named["findings"]] == ["old_only"]
    assert named["findings"][0]["version"] == "v1"
    assert named["filters"]["run"] == "zzz"
    assert named["filters"]["version"] == "v1"
    latest = inventory_findings(out, run_id="zzz")
    assert latest["n"] == 1
    assert [row["rule_id"] for row in latest["findings"]] == [
        "required_element",
        "absolute_claim",
        None,
        "tone",
    ]
    assert "old_only" not in json.dumps(latest["findings"], ensure_ascii=False)


def test_inventory_findings_channel_fallback_and_version_tie(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(
        out,
        "from-manifest",
        "fitness-douyin",
        [_version("v1", overall_score=100, best_draft_id="v1-a", created_at="2024-01-01T00:00:00+00:00")],
        channel="douyin",
        channel_label="抖音",
    )
    _version_artifact(
        out,
        "from-manifest",
        "v1",
        "checklist.json",
        _checklist([_checklist_item("v1-b", False, [_finding("tone", "medium", "口语", "家人们")])]),
    )
    _save(
        out,
        "tie",
        "sunscreen-xhs",
        [
            _version(
                "v2",
                overall_score=100,
                best_draft_id="v2-a",
                created_at="2024-02-01T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
            ),
            _version(
                "v2",
                overall_score=100,
                best_draft_id="v2-a",
                created_at="2024-03-01T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
            ),
        ],
        channel="wechat",
        channel_label="微信公众号",
    )
    _version_artifact(
        out,
        "tie",
        "v2",
        "checklist.json",
        _checklist([_checklist_item("v2-b", False, [_finding("absolute_claim", "high", "绝对化用语", "全网第一")])]),
    )
    fallback = inventory_findings(out, run_id="from-manifest")
    assert fallback["findings"][0]["channel"] == "douyin"
    assert fallback["findings"][0]["channel_label"] == "抖音"
    assert fallback["findings"][0]["draft_id"] == "v1-b"
    assert inventory_findings(out, channel="抖音")["n_listed"] == 1
    assert inventory_findings(out, channel="unknown", run_id="from-manifest")["findings"] == []

    tied = inventory_findings(out, run_id="tie")
    assert tied["findings"][0]["channel"] == "xiaohongshu"
    assert tied["findings"][0]["channel_label"] == "小红书"
    scanned = inventory_findings(out)
    tie_rows = [row for row in scanned["findings"] if row["run_id"] == "tie"]
    assert tie_rows[0]["channel"] == "xiaohongshu"


def test_inventory_findings_named_run_errors(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(out, "sun", "sunscreen-xhs", [_version("v1", overall_score=100, approval_status="pending")])
    with pytest.raises(MCWError, match="找不到运行"):
        inventory_findings(out, run_id="missing")
    with pytest.raises(MCWError, match="版本索引里没有 v9"):
        inventory_findings(out, run_id="sun", version="v9")
    with pytest.raises(MCWError, match="版本号不合法"):
        inventory_findings(out, run_id="sun", version="latest")
    with pytest.raises(MCWError, match="--version 需要同时提供 run id"):
        inventory_findings(out, version="v1")
    payload = inventory_findings(out, run_id="sun")
    assert payload["n"] == 1
    assert payload["n_with_findings"] == 0
    assert payload["findings"] == []
    assert payload["skipped"] == []


def test_inventory_drafts_empty(tmp_path: Path) -> None:
    payload = inventory_drafts(tmp_path / "missing")
    assert payload["drafts"] == []
    assert payload["skipped"] == []
    assert payload["n"] == 0
    assert payload["n_with_drafts"] == 0
    assert payload["n_without_drafts"] == 0
    assert payload["n_listed"] == 0
    assert payload["n_recommended"] == 0
    assert payload["n_not_recommended"] == 0
    assert payload["by_brief"] == []
    assert payload["by_channel"] == []
    assert payload["by_variant"] == []
    assert payload["filters"] == {
        "run": None,
        "version": None,
        "draft": None,
        "variant": None,
        "channel": None,
        "brief": None,
    }
    assert payload["kind"] == "stored_drafts"
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert "转化率" in payload["note"]
    assert payload["not_business_conversion"] is True


def test_inventory_drafts_lists_every_draft_and_keeps_counts_under_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("list-drafts must not score or call a model")

    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    monkeypatch.setattr("mcw.risk.rules.run_rules", fail)
    monkeypatch.setattr("mcw.textutil.char_count", fail)
    monkeypatch.setattr("urllib.request.urlopen", fail)

    out = tmp_path / "out"
    _save(
        out,
        "zzz",
        "coffee-wechat",
        [
            _version(
                "v1",
                overall_score=11,
                best_draft_id="old-a",
                created_at="2024-01-01T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
            ),
            _version(
                "v2",
                overall_score=100,
                best_draft_id="z-a",
                created_at="2024-01-02T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
                variant_scores=[{"draft_id": "index-only", "variant": "Z", "overall": 1}],
            ),
        ],
        channel="wechat",
        channel_label="微信公众号",
    )
    _version_artifact(
        out,
        "zzz",
        "v1",
        "drafts.json",
        {"drafts": [_stored_draft("old-a", "A", "旧版", 10)]},
    )
    _version_artifact(
        out,
        "zzz",
        "v2",
        "drafts.json",
        {
            "drafts": [
                "skip",
                None,
                _stored_draft("z-b", "B", "痛点", 80),
                _stored_draft("z-a", "A", "清单", 90),
                _stored_draft("z-c", "C", "", 70),
                4,
            ]
        },
    )
    _version_artifact(
        out,
        "zzz",
        "v2",
        "scores.json",
        {
            "drafts": [
                _stored_score("z-b", "B", "痛点", 70),
                _stored_score("z-b", "B", "痛点", 1),
                _stored_score("z-a", "A", "清单", 100),
                _stored_score("score-only", "Z", "多余", 5),
                "skip",
            ]
        },
    )
    _version_artifact(
        out,
        "zzz",
        "v2",
        "checklist.json",
        _checklist(
            [
                _checklist_item(
                    "z-b",
                    False,
                    [_finding("absolute_claim", "high", "绝对化用语", "全网第一"), "skip", _finding("tone", "medium", "语气", "必须")],
                ),
                _checklist_item("z-b", True, []),
                _checklist_item("z-a", True, []),
                "not-an-item",
            ]
        ),
    )
    _write(
        out / "runs" / "zzz" / "drafts.json",
        {"drafts": [_stored_draft("root-only", "A", "根目录", 1)]},
    )
    _save(
        out,
        "quiet",
        "kidsnack-ecommerce",
        [_version("v1", overall_score=100, best_draft_id="q-a", created_at="2024-03-01T00:00:00+00:00")],
    )
    _save(
        out,
        "aaa",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                overall_score=100,
                best_draft_id="a-a",
                created_at="2024-05-01T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
            )
        ],
        channel="xiaohongshu",
        channel_label="小红书",
    )
    _version_artifact(
        out,
        "aaa",
        "v1",
        "drafts.json",
        {"drafts": [_stored_draft("a-b", "B", "场景", 40), _stored_draft("a-a", "A", "痛点", 50)]},
    )
    _version_artifact(
        out,
        "aaa",
        "v1",
        "scores.json",
        {"drafts": [_stored_score("a-b", "B", "场景", 88), _stored_score("a-a", "A", "痛点", 100)]},
    )
    _version_artifact(
        out,
        "aaa",
        "v1",
        "checklist.json",
        _checklist(
            [
                _checklist_item("a-b", False, [_finding("tone", "medium", "语气", "家人们")]),
                _checklist_item("a-a", True, []),
            ]
        ),
    )
    (out / "runs" / "empty-junk").mkdir(parents=True)

    before = _tree(out)
    payload = inventory_drafts(out)
    assert _tree(out) == before
    assert payload["skipped"] == list_saved_runs(out)["skipped"]
    assert payload["n"] == 3
    assert payload["n_with_drafts"] == 2
    assert payload["n_without_drafts"] == 1
    assert payload["n_listed"] == 5
    assert payload["n_recommended"] == 2
    assert payload["n_not_recommended"] == 3
    assert [row["draft_id"] for row in payload["drafts"]] == ["z-b", "z-a", "z-c", "a-b", "a-a"]
    assert [row["run_id"] for row in payload["drafts"]] == ["zzz", "zzz", "zzz", "aaa", "aaa"]
    assert payload["drafts"][0]["version"] == "v2"
    assert payload["drafts"][0]["recommended"] is False
    assert payload["drafts"][0]["overall"] == 70
    assert payload["drafts"][0]["char_count"] == 80
    assert payload["drafts"][0]["angle"] == "痛点"
    assert payload["drafts"][0]["checklist_passed"] is False
    assert payload["drafts"][0]["high_finding_count"] == 1
    assert payload["drafts"][0]["channel"] == "wechat"
    assert payload["drafts"][1]["recommended"] is True
    assert payload["drafts"][1]["draft_id"] == "z-a"
    assert payload["drafts"][1]["overall"] == 100
    assert payload["drafts"][1]["checklist_passed"] is True
    assert payload["drafts"][1]["high_finding_count"] == 0
    assert payload["drafts"][2]["angle"] == ""
    assert payload["drafts"][2]["overall"] is None
    assert payload["drafts"][2]["checklist_passed"] is None
    assert payload["drafts"][2]["high_finding_count"] is None
    assert payload["drafts"][2]["recommended"] is False
    assert payload["drafts"][3]["high_finding_count"] == 0
    assert payload["drafts"][3]["checklist_passed"] is False
    assert payload["drafts"][4]["recommended"] is True
    assert "old-only" not in json.dumps(payload["drafts"], ensure_ascii=False)
    assert "root-only" not in json.dumps(payload["drafts"], ensure_ascii=False)
    assert "index-only" not in json.dumps(payload["drafts"], ensure_ascii=False)
    assert "score-only" not in json.dumps(payload["drafts"], ensure_ascii=False)
    assert payload["by_brief"] == [
        {"brief_id": "coffee-wechat", "count": 3},
        {"brief_id": "sunscreen-xhs", "count": 2},
    ]
    assert payload["by_channel"] == [
        {"channel": "wechat", "count": 3},
        {"channel": "xiaohongshu", "count": 2},
    ]
    assert payload["by_variant"] == [
        {"variant": "A", "count": 2},
        {"variant": "B", "count": 2},
        {"variant": "C", "count": 1},
    ]
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True

    filtered = inventory_drafts(out, draft="a-b", variant="B", channel="xhs", brief="sunscreen-xhs")
    assert [row["draft_id"] for row in filtered["drafts"]] == ["a-b"]
    assert filtered["n"] == payload["n"]
    assert filtered["n_with_drafts"] == payload["n_with_drafts"]
    assert filtered["n_without_drafts"] == payload["n_without_drafts"]
    assert filtered["n_listed"] == 1
    assert filtered["n_recommended"] == 0
    assert filtered["n_not_recommended"] == 1
    assert filtered["filters"]["draft"] == "a-b"
    assert filtered["filters"]["variant"] == "B"
    assert filtered["filters"]["channel"] == "xhs"
    assert filtered["filters"]["brief"] == "sunscreen-xhs"

    missed = inventory_drafts(out, draft="a-b", variant="A")
    assert missed["drafts"] == []
    assert missed["n_listed"] == 0
    assert missed["n_with_drafts"] == 2
    assert missed["n_without_drafts"] == 1
    assert missed["by_variant"] == []

    for channel in ("xhs", "小红书", "xiaohongshu", " XHS "):
        matched = inventory_drafts(out, channel=channel)
        assert [row["draft_id"] for row in matched["drafts"]] == ["a-b", "a-a"]
        assert matched["n_with_drafts"] == 2
    unknown = inventory_drafts(out, channel="unknown")
    assert unknown["drafts"] == []
    assert unknown["n"] == 3
    assert unknown["n_with_drafts"] == 2

    older = inventory_drafts(out, run_id="zzz", version="v1")
    assert older["n"] == 1
    assert older["skipped"] == []
    assert [row["draft_id"] for row in older["drafts"]] == ["old-a"]
    assert older["drafts"][0]["version"] == "v1"
    assert older["drafts"][0]["overall"] is None
    assert older["drafts"][0]["recommended"] is True
    assert older["filters"]["version"] == "v1"
    latest = inventory_drafts(out, run_id="zzz")
    assert [row["draft_id"] for row in latest["drafts"]] == ["z-b", "z-a", "z-c"]
    assert "old-a" not in json.dumps(latest["drafts"], ensure_ascii=False)


def test_inventory_drafts_falls_back_when_drafts_json_is_unusable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("list-drafts must not score or call a model")

    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    monkeypatch.setattr("mcw.textutil.char_count", fail)

    out = tmp_path / "out"
    _save(
        out,
        "from-scores",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                best_draft_id="f-a",
                created_at="2024-01-05T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
                variant_scores=[{"draft_id": "index-only", "variant": "Z", "overall": 1}],
            )
        ],
        channel="xiaohongshu",
        channel_label="小红书",
    )
    score_b = _stored_score("f-b", "B", "痛点", 33)
    score_b["char_count"] = 5
    _version_artifact(
        out,
        "from-scores",
        "v1",
        "scores.json",
        {"drafts": ["skip", score_b, _stored_score("f-a", "A", "清单", 90)]},
    )
    _version_artifact(
        out,
        "from-scores",
        "v1",
        "checklist.json",
        _checklist(
            [
                _checklist_item("f-b", False, [_finding("absolute_claim", "high", "绝对化用语", "全网第一")]),
                _checklist_item("f-a", True, []),
            ]
        ),
    )
    _save(
        out,
        "from-index",
        "coffee-wechat",
        [
            _version(
                "v1",
                best_draft_id="i-a",
                created_at="2024-01-04T00:00:00+00:00",
                variant_scores=[
                    "skip",
                    {"draft_id": "i-b", "variant": "B", "overall": 15},
                    {"draft_id": "i-a", "variant": "A", "overall": 80},
                ],
            )
        ],
    )
    (out / "runs" / "from-index" / "versions" / "v1").mkdir(parents=True)
    (out / "runs" / "from-index" / "versions" / "v1" / "scores.json").write_text("{", encoding="utf-8")
    _version_artifact(
        out,
        "from-index",
        "v1",
        "checklist.json",
        _checklist(
            [
                _checklist_item("i-b", False, [_finding("tone", "high", "语气", "必须")]),
                _checklist_item("i-a", True, []),
            ]
        ),
    )
    _save(
        out,
        "bad-shape",
        "creditcard-official",
        [
            _version(
                "v1",
                best_draft_id="b-a",
                created_at="2024-01-02T00:00:00+00:00",
                channel="official_site",
                channel_label="官网",
            )
        ],
        channel="official_site",
        channel_label="官网",
    )
    _version_artifact(out, "bad-shape", "v1", "drafts.json", {"version": "v1"})
    _version_artifact(
        out,
        "bad-shape",
        "v1",
        "scores.json",
        {"drafts": [_stored_score("b-a", "A", "费率", 60)]},
    )
    _save(
        out,
        "empty-list",
        "fitness-douyin",
        [
            _version(
                "v1",
                best_draft_id="decoy",
                created_at="2024-01-03T00:00:00+00:00",
                channel="douyin",
                channel_label="抖音",
                variant_scores=[{"draft_id": "decoy", "variant": "Z", "overall": 1}],
            )
        ],
        channel="douyin",
        channel_label="抖音",
    )
    _version_artifact(out, "empty-list", "v1", "drafts.json", {"drafts": []})
    _save(
        out,
        "non-dicts",
        "kidsnack-ecommerce",
        [
            _version(
                "v1",
                best_draft_id="n-a",
                created_at="2024-01-06T00:00:00+00:00",
                channel="ecommerce",
                channel_label="电商详情",
            )
        ],
        channel="ecommerce",
        channel_label="电商详情",
    )
    _version_artifact(out, "non-dicts", "v1", "drafts.json", {"drafts": ["skip", 1, None]})
    _version_artifact(
        out,
        "non-dicts",
        "v1",
        "scores.json",
        {"drafts": [_stored_score("n-a", "A", "配料", 50)]},
    )
    _save(
        out,
        "priority",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                best_draft_id="p-a",
                created_at="2024-01-07T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
                variant_scores=[{"draft_id": "v-extra", "variant": "Z", "overall": 2}],
            )
        ],
        channel="xiaohongshu",
        channel_label="小红书",
    )
    _version_artifact(out, "priority", "v1", "drafts.json", {"drafts": [_stored_draft("p-a", "A", "场景", 21)]})
    _version_artifact(
        out,
        "priority",
        "v1",
        "scores.json",
        {"drafts": [_stored_score("p-a", "A", "场景", 77), _stored_score("e-a", "B", "多余", 10)]},
    )
    _save(
        out,
        "unreadable",
        "coffee-wechat",
        [
            _version(
                "v1",
                best_draft_id="u-a",
                created_at="2024-01-08T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
            )
        ],
        channel="wechat",
        channel_label="微信公众号",
    )
    broken = _stored_draft("u-b", "D", "坏", 0)
    broken["char_count"] = True
    _version_artifact(
        out,
        "unreadable",
        "v1",
        "drafts.json",
        {"drafts": ["skip", _stored_draft("u-a", "C", "声明", 8), broken]},
    )
    version_dir = out / "runs" / "unreadable" / "versions" / "v1"
    (version_dir / "scores.json").write_text("{", encoding="utf-8")
    (version_dir / "checklist.json").write_text("{", encoding="utf-8")
    _save(
        out,
        "bad-json",
        "fitness-douyin",
        [
            _version(
                "v1",
                best_draft_id="s-a",
                created_at="2024-01-01T00:00:00+00:00",
                channel="douyin",
                channel_label="抖音",
            )
        ],
        channel="douyin",
        channel_label="抖音",
    )
    bad_dir = out / "runs" / "bad-json" / "versions" / "v1"
    bad_dir.mkdir(parents=True)
    (bad_dir / "drafts.json").write_text("{", encoding="utf-8")
    kept = _stored_score("s-a", "A", "备用", 40)
    kept["char_count"] = 99
    _version_artifact(out, "bad-json", "v1", "scores.json", {"drafts": [kept]})
    _version_artifact(
        out,
        "bad-json",
        "v1",
        "checklist.json",
        _checklist([_checklist_item("s-a", True, [])]),
    )

    payload = inventory_drafts(out)
    assert payload["n"] == 8
    assert payload["n_with_drafts"] == 6
    assert payload["n_without_drafts"] == 2
    assert [row["draft_id"] for row in payload["drafts"]] == [
        "s-a",
        "b-a",
        "i-b",
        "i-a",
        "f-b",
        "f-a",
        "p-a",
        "u-a",
        "u-b",
    ]
    by_id = {row["draft_id"]: row for row in payload["drafts"]}
    assert by_id["s-a"]["char_count"] is None
    assert by_id["s-a"]["overall"] == 40
    assert by_id["s-a"]["angle"] == "备用"
    assert by_id["s-a"]["recommended"] is True
    assert by_id["s-a"]["checklist_passed"] is True
    assert by_id["s-a"]["high_finding_count"] == 0
    assert by_id["b-a"]["overall"] == 60
    assert by_id["b-a"]["checklist_passed"] is None
    assert by_id["b-a"]["char_count"] is None
    assert by_id["i-b"]["angle"] is None
    assert by_id["i-b"]["char_count"] is None
    assert by_id["i-b"]["overall"] == 15
    assert by_id["i-b"]["recommended"] is False
    assert by_id["i-b"]["checklist_passed"] is False
    assert by_id["i-b"]["high_finding_count"] == 1
    assert by_id["i-b"]["channel"] == "unknown"
    assert by_id["i-a"]["recommended"] is True
    assert by_id["i-a"]["overall"] == 80
    assert by_id["f-b"]["char_count"] is None
    assert by_id["f-b"]["angle"] == "痛点"
    assert by_id["f-b"]["overall"] == 33
    assert by_id["f-b"]["recommended"] is False
    assert by_id["f-a"]["recommended"] is True
    assert by_id["p-a"]["char_count"] == 21
    assert by_id["p-a"]["overall"] == 77
    assert by_id["p-a"]["checklist_passed"] is None
    assert by_id["u-a"]["char_count"] == 8
    assert by_id["u-a"]["overall"] is None
    assert by_id["u-a"]["checklist_passed"] is None
    assert by_id["u-a"]["high_finding_count"] is None
    assert by_id["u-a"]["recommended"] is True
    assert by_id["u-b"]["char_count"] is None
    assert by_id["u-b"]["recommended"] is False
    assert "index-only" not in by_id
    assert "decoy" not in by_id
    assert "n-a" not in by_id
    assert "e-a" not in by_id
    assert "v-extra" not in by_id
    assert payload["n_recommended"] == 6
    assert payload["n_not_recommended"] == 3


def test_inventory_drafts_channel_fallback_and_version_tie(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(
        out,
        "from-manifest",
        "fitness-douyin",
        [_version("v1", overall_score=100, best_draft_id="m-a", created_at="2024-01-01T00:00:00+00:00")],
        channel="douyin",
        channel_label="抖音",
    )
    _version_artifact(out, "from-manifest", "v1", "drafts.json", {"drafts": [_stored_draft("m-a", "A", "钩子", 12)]})
    _save(
        out,
        "tie",
        "sunscreen-xhs",
        [
            _version(
                "v2",
                overall_score=100,
                best_draft_id="tie-a",
                created_at="2024-02-01T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
            ),
            _version(
                "v2",
                overall_score=100,
                best_draft_id="tie-b",
                created_at="2024-03-01T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
            ),
        ],
        channel="wechat",
        channel_label="微信公众号",
    )
    _version_artifact(
        out,
        "tie",
        "v2",
        "drafts.json",
        {"drafts": [_stored_draft("tie-a", "A", "先写", 10), _stored_draft("tie-b", "B", "后写", 11)]},
    )
    fallback = inventory_drafts(out, run_id="from-manifest")
    assert fallback["drafts"][0]["channel"] == "douyin"
    assert fallback["drafts"][0]["channel_label"] == "抖音"
    assert inventory_drafts(out, channel="抖音")["n_listed"] == 1
    assert inventory_drafts(out, channel="unknown", run_id="from-manifest")["drafts"] == []

    tied = inventory_drafts(out, run_id="tie")
    assert [row["draft_id"] for row in tied["drafts"]] == ["tie-a", "tie-b"]
    assert tied["drafts"][0]["recommended"] is False
    assert tied["drafts"][1]["recommended"] is True
    assert tied["drafts"][0]["channel"] == "xiaohongshu"
    assert tied["drafts"][0]["channel_label"] == "小红书"
    scanned = inventory_drafts(out)
    tie_rows = [row for row in scanned["drafts"] if row["run_id"] == "tie"]
    assert tie_rows[0]["channel"] == "xiaohongshu"
    assert tie_rows[1]["recommended"] is True


def test_inventory_drafts_named_run_errors(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(out, "sun", "sunscreen-xhs", [_version("v1", overall_score=100, approval_status="pending")])
    with pytest.raises(MCWError, match="找不到运行"):
        inventory_drafts(out, run_id="missing")
    with pytest.raises(MCWError, match="版本索引里没有 v9"):
        inventory_drafts(out, run_id="sun", version="v9")
    with pytest.raises(MCWError, match="版本号不合法"):
        inventory_drafts(out, run_id="sun", version="latest")
    with pytest.raises(MCWError, match="--version 需要同时提供 run id"):
        inventory_drafts(out, version="v1")
    payload = inventory_drafts(out, run_id="sun")
    assert payload["n"] == 1
    assert payload["n_with_drafts"] == 0
    assert payload["drafts"] == []
    assert payload["skipped"] == []


def test_show_drafts_empty(tmp_path: Path) -> None:
    payload = show_drafts(tmp_path / "missing")
    assert payload["drafts"] == []
    assert payload["skipped"] == []
    assert payload["n"] == 0
    assert payload["n_with_drafts"] == 0
    assert payload["n_without_drafts"] == 0
    assert payload["n_listed"] == 0
    assert payload["n_recommended"] == 0
    assert payload["n_not_recommended"] == 0
    assert payload["by_brief"] == []
    assert payload["by_channel"] == []
    assert payload["by_variant"] == []
    assert payload["filters"] == {
        "run": None,
        "version": None,
        "draft": None,
        "variant": None,
        "channel": None,
        "brief": None,
    }
    assert payload["kind"] == "stored_draft_text"
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert "转化率" in payload["note"]
    assert payload["not_business_conversion"] is True


def test_show_drafts_lists_every_draft_and_keeps_counts_under_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("show must not score or call a model")

    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    monkeypatch.setattr("mcw.risk.rules.run_rules", fail)
    monkeypatch.setattr("mcw.textutil.char_count", fail)
    monkeypatch.setattr("urllib.request.urlopen", fail)

    out = tmp_path / "out"
    _save(
        out,
        "zzz",
        "coffee-wechat",
        [
            _version(
                "v1",
                overall_score=11,
                best_draft_id="old-a",
                created_at="2024-01-01T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
            ),
            _version(
                "v2",
                overall_score=100,
                best_draft_id="z-a",
                created_at="2024-01-02T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
                variant_scores=[{"draft_id": "index-only", "variant": "Z", "overall": 1, "text": "索引不该出现"}],
                approval_status="approved",
                reviewer="提交人",
                comment="版本备注",
                approval_reviewer="林可",
                approval_comment="保留声明",
                approved_draft_id="z-a",
            ),
        ],
        channel="wechat",
        channel_label="微信公众号",
    )
    _version_artifact(
        out,
        "zzz",
        "v1",
        "drafts.json",
        {"drafts": [_stored_draft("old-a", "A", "旧版", 10, text="旧版正文")]},
    )
    numbered = _stored_draft("z-c", "C", "", 70, text="不要把数字当正文")
    numbered["text"] = 12
    _version_artifact(
        out,
        "zzz",
        "v2",
        "drafts.json",
        {
            "drafts": [
                "skip",
                None,
                _stored_draft("z-b", "B", "痛点", 80, text="痛点第一行\n痛点第二行"),
                _stored_draft("z-a", "A", "清单", 90, text="清单正文"),
                numbered,
                4,
            ]
        },
    )
    _version_artifact(
        out,
        "zzz",
        "v2",
        "scores.json",
        {
            "drafts": [
                _stored_score(
                    "z-b",
                    "B",
                    "痛点",
                    70,
                    dimensions=_dimension_scores(
                        {
                            "selling_point_accuracy": 80,
                            "channel_fit": 70,
                            "compliance": True,
                        }
                    ),
                ),
                _stored_score(
                    "z-b",
                    "B",
                    "痛点",
                    1,
                    dimensions=_dimension_scores({"selling_point_accuracy": 1}),
                ),
                _stored_score(
                    "z-a",
                    "A",
                    "清单",
                    100,
                    dimensions=_dimension_scores(
                        {key: 100 for key, _label in DIMENSIONS}
                    ),
                ),
                _stored_score("score-only", "Z", "多余", 5),
                "skip",
            ]
        },
    )
    _version_artifact(
        out,
        "zzz",
        "v2",
        "checklist.json",
        _checklist(
            [
                _checklist_item(
                    "z-b",
                    False,
                    [
                        _finding("absolute_claim", "high", "绝对化用语", "全网第一"),
                        "skip",
                        _finding("tone", "medium", "语气偏硬", "必须"),
                    ],
                ),
                _checklist_item("z-b", True, []),
                _checklist_item("z-a", True, []),
                "not-an-item",
            ]
        ),
    )
    _version_artifact(
        out,
        "zzz",
        "v2",
        "approval.json",
        {"status": "rejected", "reviewer": "文件里的人", "comment": "文件里的话", "draft_id": "z-b"},
    )
    _write(
        out / "runs" / "zzz" / "drafts.json",
        {"drafts": [_stored_draft("root-only", "A", "根目录", 1, text="根目录不该出现")]},
    )
    _save(
        out,
        "quiet",
        "kidsnack-ecommerce",
        [_version("v1", overall_score=100, best_draft_id="q-a", created_at="2024-03-01T00:00:00+00:00")],
    )
    _save(
        out,
        "aaa",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                overall_score=100,
                best_draft_id="a-a",
                created_at="2024-05-01T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
            )
        ],
        channel="xiaohongshu",
        channel_label="小红书",
    )
    _version_artifact(
        out,
        "aaa",
        "v1",
        "drafts.json",
        {
            "drafts": [
                _stored_draft("a-b", "B", "场景", 40, text="场景正文"),
                _stored_draft("a-a", "A", "痛点", 50, text="痛点正文"),
            ]
        },
    )
    _version_artifact(
        out,
        "aaa",
        "v1",
        "scores.json",
        {
            "drafts": [
                _stored_score("a-b", "B", "场景", 88, dimensions=_dimension_scores({"readability": 90})),
                _stored_score("a-a", "A", "痛点", 100),
            ]
        },
    )
    _version_artifact(
        out,
        "aaa",
        "v1",
        "checklist.json",
        _checklist(
            [
                _checklist_item("a-b", False, [_finding("tone", "medium", "语气", "家人们")]),
                _checklist_item("a-a", True, []),
            ]
        ),
    )
    _version_artifact(
        out,
        "aaa",
        "v1",
        "approval.json",
        {"status": "approved", "reviewer": "文件审阅", "comment": "文件意见", "draft_id": "a-a"},
    )
    _save(
        out,
        "bare",
        "kidsnack-ecommerce",
        [
            _version(
                "v1",
                overall_score=100,
                best_draft_id="bare-a",
                created_at="2024-06-01T00:00:00+00:00",
                approval_status=None,
            )
        ],
    )
    _version_artifact(
        out,
        "bare",
        "v1",
        "drafts.json",
        {"drafts": [_stored_draft("bare-a", "A", "配料", 12, text="配料表第一位是燕麦")]},
    )
    _version_artifact(
        out,
        "bare",
        "v1",
        "approval.json",
        {"status": "rejected", "reviewer": "周宁", "comment": "语气太满", "draft_id": "bare-a"},
    )
    (out / "runs" / "empty-junk").mkdir(parents=True)

    before = _tree(out)
    payload = show_drafts(out)
    assert _tree(out) == before
    catalog = inventory_drafts(out)
    assert "text" not in catalog["drafts"][0]
    assert "findings" not in catalog["drafts"][0]
    assert "dimensions" not in catalog["drafts"][0]
    assert payload["skipped"] == list_saved_runs(out)["skipped"]
    assert payload["kind"] == "stored_draft_text"
    assert payload["n"] == 4
    assert payload["n_with_drafts"] == 3
    assert payload["n_without_drafts"] == 1
    assert payload["n_listed"] == 6
    assert payload["n_recommended"] == 3
    assert payload["n_not_recommended"] == 3
    assert [row["draft_id"] for row in payload["drafts"]] == ["z-b", "z-a", "z-c", "a-b", "a-a", "bare-a"]
    assert [row["run_id"] for row in payload["drafts"]] == ["zzz", "zzz", "zzz", "aaa", "aaa", "bare"]
    pain = payload["drafts"][0]
    assert pain["version"] == "v2"
    assert pain["text"] == "痛点第一行\n痛点第二行"
    assert pain["recommended"] is False
    assert pain["overall"] == 70
    assert pain["char_count"] == 80
    assert pain["dimensions"] == {
        "selling_point_accuracy": 80,
        "channel_fit": 70,
        "compliance": None,
        "readability": None,
    }
    assert pain["checklist_passed"] is False
    assert pain["high_finding_count"] == 1
    assert pain["findings"] == [
        {
            "rule_id": "absolute_claim",
            "severity": "high",
            "message": "绝对化用语",
            "evidence": "全网第一",
            "suggestion": "",
        },
        {
            "rule_id": "tone",
            "severity": "medium",
            "message": "语气偏硬",
            "evidence": "必须",
            "suggestion": "",
        },
    ]
    assert pain["approval_status"] == "approved"
    assert pain["reviewer"] == "林可"
    assert pain["comment"] == "保留声明"
    assert pain["approved_draft_id"] == "z-a"
    assert payload["drafts"][1]["text"] == "清单正文"
    assert payload["drafts"][1]["recommended"] is True
    assert payload["drafts"][1]["dimensions"] == {key: 100 for key, _label in DIMENSIONS}
    assert payload["drafts"][1]["findings"] == []
    assert payload["drafts"][1]["approval_status"] == "approved"
    missing = payload["drafts"][2]
    assert missing["text"] is None
    assert missing["angle"] == ""
    assert missing["overall"] is None
    assert missing["dimensions"] is None
    assert missing["checklist_passed"] is None
    assert missing["high_finding_count"] is None
    assert missing["findings"] == []
    assert missing["recommended"] is False
    scene = payload["drafts"][3]
    assert scene["text"] == "场景正文"
    assert scene["checklist_passed"] is False
    assert scene["high_finding_count"] == 0
    assert scene["findings"][0]["severity"] == "medium"
    assert scene["findings"][0]["evidence"] == "家人们"
    assert scene["dimensions"]["readability"] == 90
    assert scene["dimensions"]["selling_point_accuracy"] is None
    assert scene["approval_status"] == "pending"
    assert scene["reviewer"] == "文件审阅"
    assert scene["comment"] == "文件意见"
    assert scene["approved_draft_id"] == "a-a"
    assert payload["drafts"][4]["recommended"] is True
    assert payload["drafts"][4]["dimensions"] is None
    assert payload["drafts"][4]["findings"] == []
    bare = payload["drafts"][5]
    assert bare["text"] == "配料表第一位是燕麦"
    assert bare["channel"] == "unknown"
    assert bare["dimensions"] is None
    assert bare["findings"] == []
    assert bare["checklist_passed"] is None
    assert bare["recommended"] is True
    assert bare["approval_status"] == "rejected"
    assert bare["reviewer"] == "周宁"
    assert bare["comment"] == "语气太满"
    assert bare["approved_draft_id"] == "bare-a"
    rendered = json.dumps(payload["drafts"], ensure_ascii=False)
    assert "旧版正文" not in rendered
    assert "根目录不该出现" not in rendered
    assert "索引不该出现" not in rendered
    assert "文件里的人" not in rendered
    assert "score-only" not in rendered
    assert payload["by_brief"] == [
        {"brief_id": "coffee-wechat", "count": 3},
        {"brief_id": "sunscreen-xhs", "count": 2},
        {"brief_id": "kidsnack-ecommerce", "count": 1},
    ]
    assert payload["by_channel"] == [
        {"channel": "wechat", "count": 3},
        {"channel": "xiaohongshu", "count": 2},
        {"channel": "unknown", "count": 1},
    ]
    assert payload["by_variant"] == [
        {"variant": "A", "count": 3},
        {"variant": "B", "count": 2},
        {"variant": "C", "count": 1},
    ]
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True

    filtered = show_drafts(out, draft="a-b", variant="B", channel="xhs", brief="sunscreen-xhs")
    assert [row["draft_id"] for row in filtered["drafts"]] == ["a-b"]
    assert filtered["drafts"][0]["text"] == "场景正文"
    assert filtered["n"] == payload["n"]
    assert filtered["n_with_drafts"] == payload["n_with_drafts"]
    assert filtered["n_without_drafts"] == payload["n_without_drafts"]
    assert filtered["n_listed"] == 1
    assert filtered["n_recommended"] == 0
    assert filtered["n_not_recommended"] == 1
    assert filtered["filters"]["draft"] == "a-b"
    assert filtered["filters"]["variant"] == "B"
    assert filtered["filters"]["channel"] == "xhs"
    assert filtered["filters"]["brief"] == "sunscreen-xhs"

    missed = show_drafts(out, draft="a-b", variant="A")
    assert missed["drafts"] == []
    assert missed["n_listed"] == 0
    assert missed["n_with_drafts"] == 3
    assert missed["n_without_drafts"] == 1
    assert missed["by_variant"] == []

    for channel in ("xhs", "小红书", "xiaohongshu", " XHS "):
        matched = show_drafts(out, channel=channel)
        assert [row["draft_id"] for row in matched["drafts"]] == ["a-b", "a-a"]
        assert [row["text"] for row in matched["drafts"]] == ["场景正文", "痛点正文"]
        assert matched["n_with_drafts"] == 3
    unknown = show_drafts(out, channel="unknown")
    assert [row["draft_id"] for row in unknown["drafts"]] == ["bare-a"]
    assert unknown["n"] == 4
    assert unknown["n_with_drafts"] == 3

    older = show_drafts(out, run_id="zzz", version="v1")
    assert older["n"] == 1
    assert older["skipped"] == []
    assert [row["draft_id"] for row in older["drafts"]] == ["old-a"]
    assert older["drafts"][0]["text"] == "旧版正文"
    assert older["drafts"][0]["version"] == "v1"
    assert older["drafts"][0]["overall"] is None
    assert older["drafts"][0]["dimensions"] is None
    assert older["drafts"][0]["findings"] == []
    assert older["drafts"][0]["recommended"] is True
    assert older["filters"]["version"] == "v1"
    latest = show_drafts(out, run_id="zzz")
    assert [row["draft_id"] for row in latest["drafts"]] == ["z-b", "z-a", "z-c"]
    assert [row["text"] for row in latest["drafts"]] == ["痛点第一行\n痛点第二行", "清单正文", None]
    assert "旧版正文" not in json.dumps(latest["drafts"], ensure_ascii=False)


def test_show_drafts_falls_back_when_drafts_json_is_unusable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("show must not score or call a model")

    monkeypatch.setattr("mcw.scoring.rubric.score_text", fail)
    monkeypatch.setattr("mcw.store.score_text_card", fail)
    monkeypatch.setattr("mcw.textutil.char_count", fail)

    out = tmp_path / "out"
    _save(
        out,
        "from-scores",
        "sunscreen-xhs",
        [
            _version(
                "v1",
                best_draft_id="f-a",
                created_at="2024-01-05T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
                variant_scores=[{"draft_id": "index-only", "variant": "Z", "overall": 1, "text": "索引正文"}],
            )
        ],
        channel="xiaohongshu",
        channel_label="小红书",
    )
    score_b = _stored_score(
        "f-b",
        "B",
        "痛点",
        33,
        dimensions=_dimension_scores({"selling_point_accuracy": 40, "compliance": 75}),
    )
    score_b["text"] = "不要用这段"
    score_b["char_count"] = 5
    score_a = _stored_score("f-a", "A", "清单", 90)
    score_a["text"] = "甲稿也不该从分数里长出来"
    _version_artifact(out, "from-scores", "v1", "scores.json", {"drafts": ["skip", score_b, score_a]})
    _version_artifact(
        out,
        "from-scores",
        "v1",
        "checklist.json",
        _checklist(
            [
                _checklist_item("f-b", False, [_finding("absolute_claim", "high", "绝对化用语", "全网第一")]),
                _checklist_item("f-a", True, []),
            ]
        ),
    )
    _save(
        out,
        "from-index",
        "coffee-wechat",
        [
            _version(
                "v1",
                best_draft_id="i-a",
                created_at="2024-01-04T00:00:00+00:00",
                variant_scores=[
                    "skip",
                    {"draft_id": "i-b", "variant": "B", "overall": 15, "text": "索引正文"},
                    {"draft_id": "i-a", "variant": "A", "overall": 80, "text": "索引甲"},
                ],
            )
        ],
    )
    (out / "runs" / "from-index" / "versions" / "v1").mkdir(parents=True)
    (out / "runs" / "from-index" / "versions" / "v1" / "scores.json").write_text("{", encoding="utf-8")
    _version_artifact(
        out,
        "from-index",
        "v1",
        "checklist.json",
        _checklist([_checklist_item("i-b", False, [_finding("tone", "high", "语气", "必须")])]),
    )
    _save(
        out,
        "kept-text",
        "creditcard-official",
        [
            _version(
                "v1",
                best_draft_id="k-a",
                created_at="2024-01-08T00:00:00+00:00",
                channel="official_site",
                channel_label="官网",
                approval_status="pending",
                comment="索引备注",
            )
        ],
        channel="official_site",
        channel_label="官网",
    )
    _version_artifact(
        out,
        "kept-text",
        "v1",
        "drafts.json",
        {"drafts": [_stored_draft("k-a", "A", "费率", 21, text="声明还在")]},
    )
    kept_dir = out / "runs" / "kept-text" / "versions" / "v1"
    (kept_dir / "scores.json").write_text("{", encoding="utf-8")
    (kept_dir / "checklist.json").write_text("{", encoding="utf-8")
    (kept_dir / "approval.json").write_text("{", encoding="utf-8")
    _save(
        out,
        "bad-json",
        "fitness-douyin",
        [
            _version(
                "v1",
                best_draft_id="s-a",
                created_at="2024-01-01T00:00:00+00:00",
                channel="douyin",
                channel_label="抖音",
            )
        ],
        channel="douyin",
        channel_label="抖音",
    )
    bad_dir = out / "runs" / "bad-json" / "versions" / "v1"
    bad_dir.mkdir(parents=True)
    (bad_dir / "drafts.json").write_text("{", encoding="utf-8")
    kept = _stored_score("s-a", "A", "备用", 40)
    kept["text"] = "备用正文"
    kept["char_count"] = 99
    _version_artifact(out, "bad-json", "v1", "scores.json", {"drafts": [kept]})
    _save(
        out,
        "empty-list",
        "kidsnack-ecommerce",
        [
            _version(
                "v1",
                best_draft_id="decoy",
                created_at="2024-01-03T00:00:00+00:00",
                channel="ecommerce",
                channel_label="电商详情",
                variant_scores=[{"draft_id": "decoy", "variant": "Z", "overall": 1, "text": "空列表不该退回"}],
            )
        ],
        channel="ecommerce",
        channel_label="电商详情",
    )
    _version_artifact(out, "empty-list", "v1", "drafts.json", {"drafts": []})
    _version_artifact(
        out,
        "empty-list",
        "v1",
        "scores.json",
        {"drafts": [_stored_score("decoy", "Z", "诱饵", 1)]},
    )

    before = _tree(out)
    payload = show_drafts(out)
    assert _tree(out) == before
    assert payload["n"] == 5
    assert payload["n_with_drafts"] == 4
    assert payload["n_without_drafts"] == 1
    assert [row["draft_id"] for row in payload["drafts"]] == ["s-a", "i-b", "i-a", "f-b", "f-a", "k-a"]
    by_id = {row["draft_id"]: row for row in payload["drafts"]}
    assert by_id["s-a"]["text"] is None
    assert by_id["s-a"]["char_count"] is None
    assert by_id["s-a"]["overall"] == 40
    assert by_id["s-a"]["angle"] == "备用"
    assert by_id["s-a"]["dimensions"] is None
    assert by_id["s-a"]["recommended"] is True
    assert by_id["i-b"]["text"] is None
    assert by_id["i-b"]["angle"] is None
    assert by_id["i-b"]["overall"] == 15
    assert by_id["i-b"]["dimensions"] is None
    assert by_id["i-b"]["findings"][0]["evidence"] == "必须"
    assert by_id["i-b"]["checklist_passed"] is False
    assert by_id["i-a"]["text"] is None
    assert by_id["i-a"]["recommended"] is True
    assert by_id["i-a"]["findings"] == []
    assert by_id["f-b"]["text"] is None
    assert by_id["f-b"]["char_count"] is None
    assert by_id["f-b"]["overall"] == 33
    assert by_id["f-b"]["dimensions"]["selling_point_accuracy"] == 40
    assert by_id["f-b"]["dimensions"]["compliance"] == 75
    assert by_id["f-b"]["dimensions"]["channel_fit"] is None
    assert by_id["f-b"]["findings"][0]["severity"] == "high"
    assert by_id["f-b"]["recommended"] is False
    assert by_id["f-a"]["text"] is None
    assert by_id["f-a"]["recommended"] is True
    assert by_id["f-a"]["dimensions"] is None
    assert by_id["k-a"]["text"] == "声明还在"
    assert by_id["k-a"]["char_count"] == 21
    assert by_id["k-a"]["overall"] is None
    assert by_id["k-a"]["dimensions"] is None
    assert by_id["k-a"]["findings"] == []
    assert by_id["k-a"]["checklist_passed"] is None
    assert by_id["k-a"]["high_finding_count"] is None
    assert by_id["k-a"]["approval_status"] == "pending"
    assert by_id["k-a"]["comment"] == "索引备注"
    assert by_id["k-a"]["reviewer"] is None
    assert by_id["k-a"]["approved_draft_id"] is None
    rendered = json.dumps(payload["drafts"], ensure_ascii=False)
    assert "不要用这段" not in rendered
    assert "索引正文" not in rendered
    assert "备用正文" not in rendered
    assert "空列表不该退回" not in rendered
    assert "decoy" not in by_id
    assert "index-only" not in by_id


def test_show_drafts_channel_fallback_and_version_tie(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(
        out,
        "from-manifest",
        "fitness-douyin",
        [_version("v1", overall_score=100, best_draft_id="m-a", created_at="2024-01-01T00:00:00+00:00")],
        channel="douyin",
        channel_label="抖音",
    )
    _version_artifact(
        out,
        "from-manifest",
        "v1",
        "drafts.json",
        {"drafts": [_stored_draft("m-a", "A", "钩子", 12, text="钩子正文")]},
    )
    _save(
        out,
        "tie",
        "sunscreen-xhs",
        [
            _version(
                "v2",
                overall_score=100,
                best_draft_id="tie-a",
                created_at="2024-02-01T00:00:00+00:00",
                channel="wechat",
                channel_label="微信公众号",
                comment="先写的备注",
            ),
            _version(
                "v2",
                overall_score=100,
                best_draft_id="tie-b",
                created_at="2024-03-01T00:00:00+00:00",
                channel="xiaohongshu",
                channel_label="小红书",
                comment="后写的备注",
            ),
        ],
        channel="wechat",
        channel_label="微信公众号",
    )
    _version_artifact(
        out,
        "tie",
        "v2",
        "drafts.json",
        {
            "drafts": [
                _stored_draft("tie-a", "A", "先写", 10, text="先写正文"),
                _stored_draft("tie-b", "B", "后写", 11, text="后写正文"),
            ]
        },
    )
    fallback = show_drafts(out, run_id="from-manifest")
    assert fallback["drafts"][0]["channel"] == "douyin"
    assert fallback["drafts"][0]["channel_label"] == "抖音"
    assert fallback["drafts"][0]["text"] == "钩子正文"
    assert show_drafts(out, channel="抖音")["n_listed"] == 1
    assert show_drafts(out, channel="unknown", run_id="from-manifest")["drafts"] == []

    tied = show_drafts(out, run_id="tie")
    assert [row["draft_id"] for row in tied["drafts"]] == ["tie-a", "tie-b"]
    assert [row["text"] for row in tied["drafts"]] == ["先写正文", "后写正文"]
    assert tied["drafts"][0]["recommended"] is False
    assert tied["drafts"][1]["recommended"] is True
    assert tied["drafts"][0]["channel"] == "xiaohongshu"
    assert tied["drafts"][0]["channel_label"] == "小红书"
    assert tied["drafts"][0]["comment"] == "后写的备注"
    scanned = show_drafts(out)
    tie_rows = [row for row in scanned["drafts"] if row["run_id"] == "tie"]
    assert tie_rows[0]["channel"] == "xiaohongshu"
    assert tie_rows[1]["recommended"] is True
    assert tie_rows[1]["text"] == "后写正文"


def test_show_drafts_named_run_errors(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _save(out, "sun", "sunscreen-xhs", [_version("v1", overall_score=100, approval_status="pending")])
    with pytest.raises(MCWError, match="找不到运行"):
        show_drafts(out, run_id="missing")
    with pytest.raises(MCWError, match="版本索引里没有 v9"):
        show_drafts(out, run_id="sun", version="v9")
    with pytest.raises(MCWError, match="版本号不合法"):
        show_drafts(out, run_id="sun", version="latest")
    with pytest.raises(MCWError, match="--version 需要同时提供 run id"):
        show_drafts(out, version="v1")
    payload = show_drafts(out, run_id="sun")
    assert payload["n"] == 1
    assert payload["n_with_drafts"] == 0
    assert payload["drafts"] == []
    assert payload["skipped"] == []
    assert payload["kind"] == "stored_draft_text"


def _stored_draft(
    draft_id: str,
    variant: str,
    angle: str,
    char_count: object,
    text: str | None = "stored",
) -> dict:
    return {
        "id": draft_id,
        "variant": variant,
        "angle": angle,
        "title": "",
        "body": "",
        "channel": "xiaohongshu",
        "text": text,
        "char_count": char_count,
    }


def _stored_score(
    draft_id: str,
    variant: str,
    angle: str,
    overall: object,
    dimensions: dict | None = None,
) -> dict:
    score: dict = {"overall": overall}
    if dimensions is not None:
        score["dimensions"] = dimensions
    return {
        "draft_id": draft_id,
        "variant": variant,
        "angle": angle,
        "score": score,
    }


def _dimension_scores(scores: dict[str, object]) -> dict[str, dict[str, object]]:
    return {key: {"label": label, "score": scores[key]} for key, label in DIMENSIONS if key in scores}
