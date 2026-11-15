from __future__ import annotations

import json
from pathlib import Path

from mcw.scoring.rubric import OFFLINE_SCORE_NOTE
from mcw.store import list_saved_runs, summarize_saved_runs


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


def _save(out: Path, name: str, brief_id: str, versions: list[dict]) -> None:
    directory = out / "runs" / name
    _write(directory / "manifest.json", {"run_id": name, "brief_id": brief_id})
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
        {"brief_id": "sunscreen-xhs", "run_count": 2},
        {"brief_id": "coffee-wechat", "run_count": 1},
        {"brief_id": "zeta-brief", "run_count": 1},
    ]
    assert payload["backends"] == [
        {"backend": "mock", "run_count": 2},
        {"backend": "unknown", "run_count": 2},
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
    assert payload["overall_scores"] == {"count": 0, "min": None, "max": None, "mean": None}
    assert payload["dimension_scores"] == {}
    assert payload["note"] == OFFLINE_SCORE_NOTE
    assert payload["not_business_conversion"] is True
