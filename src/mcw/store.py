"""Persist a run under ``.mcw/runs/<run_id>/`` and read saved runs back."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from mcw.errors import MCWError
from mcw.models import Checklist, Draft, ExtractedFacts
from mcw.pipeline import RunResult
from mcw.report import render_report
from mcw.schema import brief_fingerprint
from mcw.scoring.rubric import DIMENSIONS, OFFLINE_SCORE_NOTE, ScoreCard, WEIGHTS

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_VERSION = re.compile(r"^v[1-9][0-9]{0,3}$")
_APPROVAL_FIRST = ("approved", "pending", "rejected")
LATEST_FILES = (
    "brief.json",
    "extracted.json",
    "drafts.json",
    "checklist.json",
    "scores.json",
    "prompts.json",
    "approval.json",
    "report.md",
)


def validate_run_id(run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id or ""):
        raise MCWError("run id 只能包含字母、数字、点、下划线和短横线，且不能为空")
    return run_id


def validate_version(version: str) -> str:
    if not _VERSION.fullmatch(version or ""):
        raise MCWError(f"版本号不合法: {version}")
    return version


def make_run_id(brief_id: str, created_at: str) -> str:
    digits = re.sub(r"[^0-9]", "", created_at)[:14]
    slug = re.sub(r"[^a-z0-9]+", "-", brief_id.lower()).strip("-")[:24] or "brief"
    return validate_run_id(f"{digits}-{slug}")


def runs_root(out: Path) -> Path:
    return out / "runs"


def run_dir(out: Path, run_id: str) -> Path:
    return runs_root(out) / validate_run_id(run_id)


def version_dir(out: Path, run_id: str, version: str) -> Path:
    return run_dir(out, run_id) / "versions" / validate_version(version)


def prepare_version(out: Path, run_id: str, brief_id: str, fingerprint: str, *, continue_run: bool) -> str:
    directory = run_dir(out, run_id)
    manifest_path = directory / "manifest.json"
    if continue_run:
        if not manifest_path.is_file():
            raise MCWError(f"找不到可续写的运行: {run_id}")
        manifest = _read_json(manifest_path)
        if manifest.get("brief_id") != brief_id or manifest.get("brief_fingerprint") != fingerprint:
            raise MCWError("继续运行时 Brief 与初次不一致。请新建一次运行，避免把两个产品写进同一条版本史。")
        history = _read_json(directory / "versions.json")
        return _next_version([item["version"] for item in history.get("versions", [])])
    if directory.exists():
        raise MCWError(f"运行 {run_id} 已存在。续写请使用 --continue-run。")
    return "v1"


def persist_run(out: Path, result: RunResult) -> Path:
    directory = run_dir(out, result.run_id)
    target = version_dir(out, result.run_id, result.version)
    if target.exists():
        raise MCWError(f"版本目录已存在: {result.run_id}/{result.version}")
    target.mkdir(parents=True, exist_ok=False)
    files = _artifact_files(result)
    for name, text in files.items():
        _write_text(target / name, text)
    record = _version_record(result)
    _write_text(target / "version.json", _dump(record))
    history = _load_history(directory, result.run_id)
    history["versions"].append(record)
    _write_text(directory / "versions.json", _dump(history))
    manifest = {
        "run_id": result.run_id,
        "brief_id": result.brief.id,
        "brief_fingerprint": brief_fingerprint(result.brief),
        "brief_path": result.brief_path,
        "channel": result.brief.channel,
        "channel_label": result.brief.channel_label,
        "created_at": history["versions"][0]["created_at"],
        "latest": result.version,
        "artifact_layout": "mcw-run-v1",
    }
    _write_text(directory / "manifest.json", _dump(manifest))
    for name in LATEST_FILES:
        _write_text(directory / name, files[name])
    return directory


def load_history(out: Path, run_id: str) -> dict[str, Any]:
    path = run_dir(out, run_id) / "versions.json"
    if not path.is_file():
        raise MCWError(f"找不到运行: {run_id}")
    return _read_json(path)


def list_saved_runs(out: Path) -> dict[str, Any]:
    """Inventory runs already written by persist_run.

    Reads manifest.json and versions.json only. overall_score is the stored
    offline content score of the latest version's recommended draft.
    channel and channel_label come from the latest version record, then the
    manifest. Both are unknown when those fields are missing or empty.
    """
    root = runs_root(out)
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    if root.is_dir():
        names = sorted(path.name for path in root.iterdir() if path.is_dir())
        for name in names:
            try:
                row = _saved_run_row(out, name)
            except (MCWError, OSError, UnicodeError):
                skipped.append(name)
                continue
            if row is None:
                skipped.append(name)
                continue
            rows.append(row)
    rows.sort(key=lambda item: (str(item["created_at"]), str(item["run_id"])))
    return {
        "runs": rows,
        "skipped": skipped,
        "note": OFFLINE_SCORE_NOTE,
        "not_business_conversion": True,
    }


def inventory_failures(
    out: Path,
    run_id: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """List saved versions that missed full credit or were rejected.

    Reads manifest.json and versions.json first, using the same latest-version
    rule as list_saved_runs. A row is included when the recommended draft's
    stored overall_score is missing or not a finite number, or is below 100;
    when approval_status is rejected; or when that draft's stored checklist
    failed or contains a high-severity finding. Included rows then read
    checklist.json and scores.json for findings and dimension scores. Missing
    artifact files keep the index row and omit findings. Invalid run
    directories stay in skipped. This does not call a model or recompute the
    rubric. The numbers are stored offline content scores, not conversion rates.
    """
    if version is not None and run_id is None:
        raise MCWError("--version 需要同时提供 run id")
    if run_id is not None:
        failure = _failure_for_named_run(out, run_id, version)
        return _failure_payload([] if failure is None else [failure], [])
    inventory = list_saved_runs(out)
    failures: list[dict[str, Any]] = []
    for row in inventory["runs"]:
        history = load_history(out, str(row["run_id"]))
        selected = _select_latest(history.get("versions"))
        if selected is None:
            continue
        record, _count = selected
        failure = _failure_from_record(out, str(row["run_id"]), str(row["brief_id"]), record)
        if failure is not None:
            failures.append(failure)
    return _failure_payload(failures, list(inventory["skipped"]))


def _saved_run_row(out: Path, name: str) -> dict[str, Any] | None:
    directory = runs_root(out) / name
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file() or not (directory / "versions.json").is_file():
        return None
    history = load_history(out, name)
    manifest = _read_json(manifest_path)
    selected = _select_latest(history.get("versions"))
    if selected is None:
        return None
    latest, version_count = selected
    brief_id = manifest.get("brief_id")
    if not isinstance(brief_id, str) or not brief_id.strip():
        return None
    created_at = latest.get("created_at")
    if not isinstance(created_at, str):
        created_at = ""
    return {
        "run_id": name,
        "brief_id": brief_id,
        "version_count": version_count,
        "latest_version": latest["version"],
        "created_at": created_at,
        "approval_status": latest.get("approval_status"),
        "overall_score": latest.get("overall_score"),
        "best_draft_id": latest.get("best_draft_id"),
        "backend": latest.get("backend"),
        "channel": _indexed_text(latest, manifest, "channel"),
        "channel_label": _indexed_text(latest, manifest, "channel_label"),
        "comment": latest.get("comment"),
        "reviewer": latest.get("reviewer"),
        "dimension_scores": latest.get("dimension_scores"),
    }


def summarize_saved_runs(out: Path) -> dict[str, Any]:
    """Roll up the latest version of each run from list_saved_runs.

    Reads the same manifest.json and versions.json index. Counts and means
    are stored offline content scores, not a live-ad conversion rate.
    Briefs, backends, approval statuses, and channels each include that
    group's stored overall min, max, and mean. A missing channel is unknown.
    """
    inventory = list_saved_runs(out)
    runs = inventory["runs"]
    approval_buckets: dict[str, dict[str, Any]] = {}
    brief_buckets: dict[str, dict[str, Any]] = {}
    backend_buckets: dict[str, dict[str, Any]] = {}
    channel_buckets: dict[str, dict[str, Any]] = {}
    overalls: list[int | float] = []
    dimension_values: dict[str, list[int | float]] = {key: [] for key, _label in DIMENSIONS}
    for row in runs:
        score = row.get("overall_score")
        _record_score(approval_buckets, _label_or_unknown(row.get("approval_status")), score)
        _record_score(brief_buckets, str(row["brief_id"]), score)
        _record_score(backend_buckets, _label_or_unknown(row.get("backend")), score)
        _record_channel(channel_buckets, row, score)
        if _is_number(score):
            overalls.append(score)
        _collect_dimensions(row.get("dimension_scores"), dimension_values)
    approval = _ordered_counts(
        {key: bucket["run_count"] for key, bucket in approval_buckets.items()},
        _APPROVAL_FIRST,
    )
    dimension_scores: dict[str, dict[str, Any]] = {}
    for key, _label in DIMENSIONS:
        values = dimension_values[key]
        if not values:
            continue
        dimension_scores[key] = {
            "count": len(values),
            "mean": round(sum(values) / len(values), 2),
        }
    return {
        "run_count": len(runs),
        "skipped": inventory["skipped"],
        "version_count": sum(row["version_count"] for row in runs),
        "approval": approval,
        "approval_groups": [
            _group_payload(approval_buckets[status], status=status) for status in approval
        ],
        "briefs": _ranked_groups(brief_buckets, "brief_id"),
        "backends": _ranked_groups(backend_buckets, "backend"),
        "channels": _ranked_channels(channel_buckets),
        "overall_scores": _score_summary(overalls),
        "dimension_scores": dimension_scores,
        "note": OFFLINE_SCORE_NOTE,
        "not_business_conversion": True,
    }


def _label_or_unknown(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return "unknown"


def _indexed_text(latest: dict[str, Any], manifest: dict[str, Any], key: str) -> str:
    for source in (latest, manifest):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def _score_summary(values: list[int | float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(sum(values) / len(values), 2),
    }


def _empty_bucket() -> dict[str, Any]:
    return {"run_count": 0, "scores": []}


def _record_score(buckets: dict[str, dict[str, Any]], key: str, score: object) -> None:
    bucket = buckets.get(key)
    if bucket is None:
        bucket = _empty_bucket()
        buckets[key] = bucket
    bucket["run_count"] += 1
    if _is_number(score):
        bucket["scores"].append(score)


def _record_channel(buckets: dict[str, dict[str, Any]], row: dict[str, Any], score: object) -> None:
    channel = _label_or_unknown(row.get("channel"))
    label = _label_or_unknown(row.get("channel_label"))
    bucket = buckets.get(channel)
    if bucket is None:
        bucket = {"run_count": 0, "scores": [], "label": "unknown"}
        buckets[channel] = bucket
    bucket["run_count"] += 1
    if _is_number(score):
        bucket["scores"].append(score)
    if bucket["label"] == "unknown" and label != "unknown":
        bucket["label"] = label


def _group_payload(bucket: dict[str, Any], **fields: object) -> dict[str, Any]:
    row = dict(fields)
    row["run_count"] = bucket["run_count"]
    row["overall_scores"] = _score_summary(bucket["scores"])
    return row


def _ranked_groups(buckets: dict[str, dict[str, Any]], field: str) -> list[dict[str, Any]]:
    names = sorted(buckets, key=lambda name: (-buckets[name]["run_count"], name))
    return [_group_payload(buckets[name], **{field: name}) for name in names]


def _ranked_channels(buckets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    names = sorted(buckets, key=lambda name: (-buckets[name]["run_count"], name))
    return [
        {
            "channel": name,
            "channel_label": buckets[name]["label"],
            "run_count": buckets[name]["run_count"],
            "overall_scores": _score_summary(buckets[name]["scores"]),
        }
        for name in names
    ]


def _is_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not isinstance(value, float) or math.isfinite(value)


def _numbered_versions(versions: object) -> list[tuple[int, dict[str, Any]]]:
    if not isinstance(versions, list):
        return []
    numbered: list[tuple[int, dict[str, Any]]] = []
    for index, record in enumerate(versions):
        if not isinstance(record, dict):
            continue
        version = record.get("version")
        if isinstance(version, str) and _VERSION.fullmatch(version):
            numbered.append((index, record))
    return numbered


def _select_latest(versions: object) -> tuple[dict[str, Any], int] | None:
    """Latest version record and how many numbered versions exist.

    The latest record is the highest version number. Equal numbers keep the
    later index, which is the same rule list_saved_runs uses.
    """
    numbered = _numbered_versions(versions)
    if not numbered:
        return None
    _index, latest = max(numbered, key=lambda pair: (int(pair[1]["version"][1:]), pair[0]))
    return latest, len(numbered)


def _record_for_version(versions: object, version: str) -> dict[str, Any] | None:
    matches = [pair for pair in _numbered_versions(versions) if pair[1]["version"] == version]
    if not matches:
        return None
    return max(matches, key=lambda pair: pair[0])[1]


def _failure_payload(failures: list[dict[str, Any]], skipped: list[str]) -> dict[str, Any]:
    return {
        "kind": "offline_content_score",
        "failures": failures,
        "skipped": skipped,
        "note": OFFLINE_SCORE_NOTE,
        "not_business_conversion": True,
    }


def _failure_for_named_run(out: Path, run_id: str, version: str | None) -> dict[str, Any] | None:
    validate_run_id(run_id)
    history = load_history(out, run_id)
    if version is None:
        selected = _select_latest(history.get("versions"))
        if selected is None:
            raise MCWError(f"找不到运行: {run_id}")
        record = selected[0]
    else:
        validate_version(version)
        record = _record_for_version(history.get("versions"), version)
        if record is None:
            raise MCWError(f"版本索引里没有 {version}")
    manifest_path = run_dir(out, run_id) / "manifest.json"
    if not manifest_path.is_file():
        raise MCWError(f"找不到运行: {run_id}")
    manifest = _read_json(manifest_path)
    brief_id = manifest.get("brief_id")
    if not isinstance(brief_id, str) or not brief_id.strip():
        raise MCWError(f"找不到运行: {run_id}")
    return _failure_from_record(out, run_id, brief_id, record)


def _failure_from_record(
    out: Path,
    run_id: str,
    brief_id: str,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    version = record.get("version")
    if not isinstance(version, str):
        return None
    best_id = record.get("best_draft_id")
    if not isinstance(best_id, str) or not best_id.strip():
        best_id = None
    checklist = _read_optional_json(version_dir(out, run_id, version) / "checklist.json")
    scores = _read_optional_json(version_dir(out, run_id, version) / "scores.json")
    checklist_item = _recommended_checklist(checklist, best_id)
    highs = _high_findings(checklist_item)
    reasons = _failure_reasons(record, checklist_item, highs)
    if not reasons:
        return None
    passed = checklist_item.get("passed") if checklist_item is not None else None
    if not isinstance(passed, bool):
        passed = None
    return {
        "run_id": run_id,
        "brief_id": brief_id,
        "version": version,
        "approval_status": record.get("approval_status"),
        "best_draft_id": best_id,
        "overall_score": record.get("overall_score"),
        "weak_dimensions": _weak_dimensions(record, scores, best_id),
        "high_findings": highs,
        "checklist_passed": passed,
        "variant_scores": _variant_scores(record, scores, best_id),
        "reasons": reasons,
    }


def _failure_reasons(
    record: dict[str, Any],
    checklist_item: dict[str, Any] | None,
    highs: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    score = record.get("overall_score")
    if not _is_number(score):
        reasons.append("overall_unconfirmed")
    elif score < 100:
        reasons.append("overall_below_100")
    if record.get("approval_status") == "rejected":
        reasons.append("rejected")
    if checklist_item is not None and checklist_item.get("passed") is False:
        reasons.append("checklist_failed")
    if highs:
        reasons.append("high_finding")
    return reasons


def _recommended_checklist(checklist: dict[str, Any] | None, best_id: str | None) -> dict[str, Any] | None:
    if checklist is None or best_id is None:
        return None
    items = checklist.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("draft_id") == best_id:
            return item
    return None


def _high_findings(checklist_item: dict[str, Any] | None) -> list[dict[str, Any]]:
    if checklist_item is None:
        return []
    findings = checklist_item.get("findings")
    if not isinstance(findings, list):
        return []
    rows: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("severity") != "high":
            continue
        rows.append(
            {
                "rule_id": finding.get("rule_id"),
                "message": finding.get("message"),
                "evidence": finding.get("evidence"),
            }
        )
    return rows


def _weak_dimensions(
    record: dict[str, Any],
    scores: dict[str, Any] | None,
    best_id: str | None,
) -> list[dict[str, Any]]:
    stored = _score_dimensions(_recommended_score(scores, best_id))
    if stored is None:
        stored = _index_dimensions(record.get("dimension_scores"))
    if stored is None:
        return []
    weak: list[dict[str, Any]] = []
    for key, label in DIMENSIONS:
        value = stored.get(key)
        if _is_number(value) and value < 100:
            weak.append({"key": key, "label": label, "score": value})
    return weak


def _recommended_score(scores: dict[str, Any] | None, best_id: str | None) -> dict[str, Any] | None:
    if scores is None or best_id is None:
        return None
    drafts = scores.get("drafts")
    if not isinstance(drafts, list):
        return None
    for draft in drafts:
        if not isinstance(draft, dict) or draft.get("draft_id") != best_id:
            continue
        score = draft.get("score")
        if isinstance(score, dict):
            return score
    return None


def _score_dimensions(score: dict[str, Any] | None) -> dict[str, Any] | None:
    if score is None:
        return None
    dimensions = score.get("dimensions")
    if not isinstance(dimensions, dict):
        return None
    values: dict[str, Any] = {}
    for key, _label in DIMENSIONS:
        item = dimensions.get(key)
        if isinstance(item, dict):
            values[key] = item.get("score")
        else:
            values[key] = item
    return values


def _index_dimensions(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {key: raw.get(key) for key, _label in DIMENSIONS}


def _variant_scores(
    record: dict[str, Any],
    scores: dict[str, Any] | None,
    best_id: str | None,
) -> list[dict[str, Any]]:
    drafts = scores.get("drafts") if isinstance(scores, dict) else None
    if isinstance(drafts, list) and drafts:
        rows: list[dict[str, Any]] = []
        for draft in drafts:
            if not isinstance(draft, dict):
                continue
            score = draft.get("score")
            overall = score.get("overall") if isinstance(score, dict) else None
            draft_id = draft.get("draft_id")
            rows.append(
                {
                    "draft_id": draft_id,
                    "variant": draft.get("variant"),
                    "overall": overall,
                    "recommended": best_id is not None and draft_id == best_id,
                }
            )
        return rows
    stored = record.get("variant_scores")
    if not isinstance(stored, list):
        return []
    rows = []
    for item in stored:
        if not isinstance(item, dict):
            continue
        draft_id = item.get("draft_id")
        rows.append(
            {
                "draft_id": draft_id,
                "variant": item.get("variant"),
                "overall": item.get("overall"),
                "recommended": best_id is not None and draft_id == best_id,
            }
        )
    return rows


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _collect_dimensions(raw: object, buckets: dict[str, list[int | float]]) -> None:
    if not isinstance(raw, dict):
        return
    for key, _label in DIMENSIONS:
        value = raw.get(key)
        if _is_number(value):
            buckets[key].append(value)


def _ordered_counts(counts: dict[str, int], first: tuple[str, ...]) -> dict[str, int]:
    keys = [key for key in first if key in counts]
    keys.extend(sorted(key for key in counts if key not in first))
    return {key: counts[key] for key in keys}


def load_version_files(out: Path, run_id: str, version: str) -> dict[str, Any]:
    directory = version_dir(out, run_id, version)
    if not directory.is_dir():
        raise MCWError(f"找不到版本: {run_id}/{version}")
    history = load_history(out, run_id)
    record = next((item for item in history["versions"] if item["version"] == version), None)
    if record is None:
        raise MCWError(f"版本索引里没有 {version}")
    return {
        "record": record,
        "extracted": _read_json(directory / "extracted.json"),
        "drafts": _read_json(directory / "drafts.json"),
        "checklist": _read_json(directory / "checklist.json"),
        "scores": _read_json(directory / "scores.json"),
        "approval": _read_json(directory / "approval.json"),
    }


def rescore_version(out: Path, run_id: str, version: str | None) -> tuple[dict[str, Any], list[str]]:
    history = load_history(out, run_id)
    chosen = version or history["versions"][-1]["version"]
    bundle = load_version_files(out, run_id, chosen)
    facts = ExtractedFacts.from_dict(bundle["extracted"])
    drifts: list[str] = []
    fresh_rows = []
    for draft_data, checklist_data, stored in zip(
        bundle["drafts"]["drafts"],
        bundle["checklist"]["items"],
        bundle["scores"]["drafts"],
    ):
        draft = Draft.from_dict(draft_data)
        checklist = Checklist.from_dict(checklist_data)
        fresh = score_text_card(draft.text, facts, checklist)
        fresh_rows.append({"draft_id": draft.id, "variant": draft.variant, "score": fresh.to_dict()})
        stored_score = stored["score"]
        if stored_score["overall"] != fresh.overall or _dimension_scores(stored_score) != fresh.dimension_map():
            drifts.append(draft.id)
    return {
        "run_id": run_id,
        "version": chosen,
        "best_draft_id": bundle["scores"]["best_draft_id"],
        "drafts": fresh_rows,
        "note": OFFLINE_SCORE_NOTE,
    }, drifts


def score_text_card(text: str, facts: ExtractedFacts, checklist: Checklist) -> ScoreCard:
    from mcw.scoring.rubric import score_text

    return score_text(text, facts, findings=checklist.findings)


def _dimension_scores(score_dict: dict[str, Any]) -> dict[str, int]:
    return {key: int(value["score"]) for key, value in score_dict["dimensions"].items()}


def _artifact_files(result: RunResult) -> dict[str, str]:
    scores = {
        "kind": "offline_content_score",
        "not_business_conversion": True,
        "note": OFFLINE_SCORE_NOTE,
        "weights": dict(WEIGHTS),
        "best_draft_id": result.best_draft_id,
        "drafts": [
            {
                "draft_id": draft.id,
                "variant": draft.variant,
                "angle": draft.angle,
                "score": score.to_dict(),
            }
            for draft, score in zip(result.drafts, result.scores)
        ],
    }
    prompts = {
        "backend": result.backend,
        "model": result.model,
        **result.prompts.to_dict(),
    }
    files = {
        "brief.json": _dump(result.brief.to_dict()),
        "extracted.json": _dump(result.facts.to_dict()),
        "drafts.json": _dump(
            {
                "version": result.version,
                "backend": result.backend,
                "model": result.model,
                "drafts": [draft.to_dict() for draft in result.drafts],
            }
        ),
        "checklist.json": _dump({"items": [item.to_dict() for item in result.checklists]}),
        "scores.json": _dump(scores),
        "prompts.json": _dump(prompts),
        "approval.json": _dump(result.approval.to_dict()),
        "report.md": render_report(result),
    }
    return files


def _version_record(result: RunResult) -> dict[str, Any]:
    best_score = next(
        score for draft, score in zip(result.drafts, result.scores) if draft.id == result.best_draft_id
    )
    return {
        "version": result.version,
        "created_at": result.created_at,
        "reviewer": result.reviewer,
        "comment": result.comment,
        "approval_status": result.approval.status,
        "approval_reviewer": result.approval.reviewer,
        "approval_comment": result.approval.comment,
        "approved_draft_id": result.approval.draft_id,
        "overall_score": best_score.overall,
        "best_draft_id": result.best_draft_id,
        "draft_ids": [draft.id for draft in result.drafts],
        "backend": result.backend,
        "channel": result.brief.channel,
        "channel_label": result.brief.channel_label,
        "dimension_scores": best_score.dimension_map(),
        "variant_scores": [
            {"draft_id": draft.id, "variant": draft.variant, "overall": score.overall}
            for draft, score in zip(result.drafts, result.scores)
        ],
    }


def _load_history(directory: Path, run_id: str) -> dict[str, Any]:
    path = directory / "versions.json"
    if path.is_file():
        return _read_json(path)
    return {"run_id": run_id, "versions": []}


def _next_version(existing: list[str]) -> str:
    numbers = [int(item[1:]) for item in existing if _VERSION.fullmatch(item)]
    value = (max(numbers) if numbers else 0) + 1
    if value > 9999:
        raise MCWError("版本号已用尽")
    return f"v{value}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCWError(f"无法读取 {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise MCWError(f"{path.name} 的根节点必须是对象")
    return data


def _dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
