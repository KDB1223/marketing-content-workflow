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
from mcw.schema import CHANNEL_ALIASES, brief_fingerprint
from mcw.scoring.rubric import DIMENSIONS, OFFLINE_SCORE_NOTE, ScoreCard, WEIGHTS

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_VERSION = re.compile(r"^v[1-9][0-9]{0,3}$")
_APPROVAL_FIRST = ("approved", "pending", "rejected")
FINDINGS_INVENTORY_NOTE = (
    "这些行来自已保存的 checklist.json，列出已经记下的清单发现。"
    "它不是真实投放转化率，也不能代替 A/B 实验或业务结果。"
)

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


def inventory_findings(
    out: Path,
    run_id: str | None = None,
    version: str | None = None,
    *,
    rule: str | None = None,
    severity: str | None = None,
    channel: str | None = None,
    draft: str | None = None,
    brief: str | None = None,
) -> dict[str, Any]:
    """Inventory stored checklist findings for the selected versions.

    Reads manifest.json and versions.json first, using the same latest-version
    rule as list_saved_runs. Then reads that version's checklist.json. Every
    draft item is walked, in file order, and every severity is kept. A missing
    checklist, a missing findings field, a non-list, or an empty list adds no
    rows. Non-dict finding entries are skipped. Filters are exact and combined.
    ``channel`` matches a canonical id, the Chinese label, or CHANNEL_ALIASES.
    An index without a channel is ``unknown`` and only matches that text.
    Counts of runs with and without findings are taken before filters.
    ``n_listed`` and the rule/severity breakdowns count only the remaining rows.
    This does not call a model, recompute risk rules, or write files. The rows
    are stored checklist findings, not a conversion rate.
    """
    if version is not None and run_id is None:
        raise MCWError("--version 需要同时提供 run id")
    if run_id is not None:
        selected = [_named_finding_source(out, run_id, version)]
        skipped: list[str] = []
    else:
        inventory = list_saved_runs(out)
        selected = [_finding_source_from_row(row) for row in inventory["runs"]]
        skipped = list(inventory["skipped"])
    loaded: list[tuple[dict[str, str], list[dict[str, Any]]]] = []
    for source in selected:
        checklist = _read_optional_json(
            version_dir(out, source["run_id"], source["version"]) / "checklist.json"
        )
        loaded.append((source, _stored_findings(source, checklist)))
    listed: list[dict[str, Any]] = []
    for source, findings in loaded:
        if not _finding_source_matches(source, channel=channel, brief=brief):
            continue
        for row in findings:
            if _finding_row_matches(row, rule=rule, severity=severity, draft=draft):
                listed.append(row)
    n_with = sum(1 for _source, findings in loaded if findings)
    return {
        "kind": "stored_checklist_findings",
        "n": len(loaded),
        "n_with_findings": n_with,
        "n_without_findings": len(loaded) - n_with,
        "n_listed": len(listed),
        "by_rule": _ranked_named_counts([_bucket_name(row.get("rule_id")) for row in listed], "rule_id"),
        "by_severity": _ranked_named_counts(
            [_bucket_name(row.get("severity")) for row in listed],
            "severity",
        ),
        "filters": {
            "run": run_id,
            "version": version,
            "rule": rule,
            "severity": severity,
            "channel": channel,
            "draft": draft,
            "brief": brief,
        },
        "skipped": skipped,
        "findings": listed,
        "note": FINDINGS_INVENTORY_NOTE,
        "not_business_conversion": True,
    }


def inventory_drafts(
    out: Path,
    run_id: str | None = None,
    version: str | None = None,
    *,
    draft: str | None = None,
    variant: str | None = None,
    channel: str | None = None,
    brief: str | None = None,
) -> dict[str, Any]:
    """Inventory stored drafts for the selected versions.

    Reads manifest.json and versions.json first, using the same latest-version
    rule as list_saved_runs. Then reads that version's drafts.json and walks
    every draft, in file order, not only best_draft_id. scores.json and
    checklist.json are joined when they can be read. A missing or unreadable
    score or checklist file keeps the draft row and leaves those fields null.
    If drafts.json is missing or has no list, the drafts list in scores.json
    is used, then variant_scores on the version index. A list is used even
    when it is empty or contains only non-dict entries; those entries are
    skipped. Filters are exact and combined. ``channel`` matches a canonical
    id, the Chinese label, or CHANNEL_ALIASES. An index without a channel is
    ``unknown`` and only matches that text. Loaded-run counts are taken before
    filters. ``n_listed``, recommended counts, and the breakdowns count only
    the remaining rows. This does not call a model, recompute the rubric,
    re-run risk rules, or write files. The numbers are stored offline content
    scores, not conversion rates.
    """
    if version is not None and run_id is None:
        raise MCWError("--version 需要同时提供 run id")
    if run_id is not None:
        selected = [_draft_source(out, run_id, version)]
        skipped: list[str] = []
    else:
        inventory = list_saved_runs(out)
        selected = [_draft_source_from_row(out, row) for row in inventory["runs"]]
        skipped = list(inventory["skipped"])
    loaded: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for source in selected:
        loaded.append((source, _stored_drafts(out, source)))
    listed: list[dict[str, Any]] = []
    for source, drafts in loaded:
        if not _finding_source_matches(source, channel=channel, brief=brief):
            continue
        for row in drafts:
            if _draft_row_matches(row, draft=draft, variant=variant):
                listed.append(row)
    n_with = sum(1 for _source, drafts in loaded if drafts)
    n_recommended = sum(1 for row in listed if row["recommended"])
    return {
        "kind": "stored_drafts",
        "n": len(loaded),
        "n_with_drafts": n_with,
        "n_without_drafts": len(loaded) - n_with,
        "n_listed": len(listed),
        "n_recommended": n_recommended,
        "n_not_recommended": len(listed) - n_recommended,
        "by_brief": _ranked_named_counts([_bucket_name(row.get("brief_id")) for row in listed], "brief_id"),
        "by_channel": _ranked_named_counts([_bucket_name(row.get("channel")) for row in listed], "channel"),
        "by_variant": _ranked_named_counts([_bucket_name(row.get("variant")) for row in listed], "variant"),
        "filters": {
            "run": run_id,
            "version": version,
            "draft": draft,
            "variant": variant,
            "channel": channel,
            "brief": brief,
        },
        "skipped": skipped,
        "drafts": listed,
        "note": OFFLINE_SCORE_NOTE,
        "not_business_conversion": True,
    }


def show_drafts(
    out: Path,
    run_id: str | None = None,
    version: str | None = None,
    *,
    draft: str | None = None,
    variant: str | None = None,
    channel: str | None = None,
    brief: str | None = None,
) -> dict[str, Any]:
    """Read stored draft text for the selected versions.

    Uses the same latest-version rule, filters, and draft fallback as
    inventory_drafts. Reads manifest.json and versions.json first, then that
    version's drafts.json. scores.json and checklist.json are joined by draft
    id when they can be read. Approval is taken from the version index
    (approval_status, and reviewer, comment, and draft id when those strings
    are stored) and any missing field is filled from approval.json when that
    file can be read. A missing or unreadable score, checklist, or approval
    file keeps the row and leaves those fields empty. Text comes only from
    drafts.json. The scores.json and index fallbacks keep the row and set text
    to null. This does not call a model, recompute the rubric, re-run risk
    rules, or write files. The numbers are stored offline content scores, not
    conversion rates.
    """
    if version is not None and run_id is None:
        raise MCWError("--version 需要同时提供 run id")
    if run_id is not None:
        selected = [_draft_source(out, run_id, version)]
        skipped: list[str] = []
    else:
        inventory = list_saved_runs(out)
        selected = [_draft_source_from_row(out, row) for row in inventory["runs"]]
        skipped = list(inventory["skipped"])
    loaded: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for source in selected:
        loaded.append((source, _stored_show_drafts(out, source)))
    listed: list[dict[str, Any]] = []
    for source, drafts in loaded:
        if not _finding_source_matches(source, channel=channel, brief=brief):
            continue
        for row in drafts:
            if _draft_row_matches(row, draft=draft, variant=variant):
                listed.append(row)
    n_with = sum(1 for _source, drafts in loaded if drafts)
    n_recommended = sum(1 for row in listed if row["recommended"])
    return {
        "kind": "stored_draft_text",
        "n": len(loaded),
        "n_with_drafts": n_with,
        "n_without_drafts": len(loaded) - n_with,
        "n_listed": len(listed),
        "n_recommended": n_recommended,
        "n_not_recommended": len(listed) - n_recommended,
        "by_brief": _ranked_named_counts([_bucket_name(row.get("brief_id")) for row in listed], "brief_id"),
        "by_channel": _ranked_named_counts([_bucket_name(row.get("channel")) for row in listed], "channel"),
        "by_variant": _ranked_named_counts([_bucket_name(row.get("variant")) for row in listed], "variant"),
        "filters": {
            "run": run_id,
            "version": version,
            "draft": draft,
            "variant": variant,
            "channel": channel,
            "brief": brief,
        },
        "skipped": skipped,
        "drafts": listed,
        "note": OFFLINE_SCORE_NOTE,
        "not_business_conversion": True,
    }


def _finding_source_from_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "run_id": str(row["run_id"]),
        "brief_id": str(row["brief_id"]),
        "version": str(row["latest_version"]),
        "channel": str(row["channel"]),
        "channel_label": str(row["channel_label"]),
    }


def _named_finding_source(out: Path, run_id: str, version: str | None) -> dict[str, str]:
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
    chosen = record.get("version")
    if not isinstance(chosen, str):
        raise MCWError(f"找不到运行: {run_id}")
    return {
        "run_id": run_id,
        "brief_id": brief_id,
        "version": chosen,
        "channel": _indexed_text(record, manifest, "channel"),
        "channel_label": _indexed_text(record, manifest, "channel_label"),
    }


def _stored_findings(source: dict[str, str], checklist: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(checklist, dict):
        return []
    items = checklist.get("items")
    if not isinstance(items, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        findings = item.get("findings")
        if not isinstance(findings, list):
            continue
        draft_id = item.get("draft_id")
        for finding in findings:
            if isinstance(finding, dict):
                rows.append(_finding_row(source, draft_id, finding))
    return rows


def _finding_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _finding_row(source: dict[str, str], draft_id: object, finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": source["run_id"],
        "brief_id": source["brief_id"],
        "version": source["version"],
        "draft_id": draft_id if isinstance(draft_id, str) else None,
        "rule_id": _finding_text(finding.get("rule_id")),
        "severity": _finding_text(finding.get("severity")),
        "evidence": _finding_text(finding.get("evidence")),
        "message": _finding_text(finding.get("message")),
        "suggestion": _finding_text(finding.get("suggestion")),
        "channel": source["channel"],
        "channel_label": source["channel_label"],
    }


def _finding_source_matches(source: dict[str, str], *, channel: str | None, brief: str | None) -> bool:
    if brief is not None and source["brief_id"] != brief:
        return False
    if channel is None:
        return True
    return _channel_query_matches(source["channel"], source["channel_label"], channel)


def _channel_query_matches(channel: str, label: str, query: str) -> bool:
    """Match a channel query the way ``list-briefs`` does.

    Canonical ids, Chinese labels, and ``CHANNEL_ALIASES`` all count. An index
    without a channel is the string ``unknown`` and only matches that text.
    """
    text = query.strip()
    if text == channel or text == label:
        return True
    canonical = CHANNEL_ALIASES.get(text) or CHANNEL_ALIASES.get(text.lower())
    return bool(canonical) and canonical == channel


def _finding_row_matches(
    row: dict[str, Any],
    *,
    rule: str | None,
    severity: str | None,
    draft: str | None,
) -> bool:
    if rule is not None and row.get("rule_id") != rule:
        return False
    if severity is not None and row.get("severity") != severity:
        return False
    if draft is not None and row.get("draft_id") != draft:
        return False
    return True


def _draft_source(out: Path, run_id: str, version: str | None) -> dict[str, Any]:
    return _with_draft_index(out, _named_finding_source(out, run_id, version))


def _draft_source_from_row(out: Path, row: dict[str, Any]) -> dict[str, Any]:
    return _with_draft_index(out, _finding_source_from_row(row))


def _with_draft_index(out: Path, source: dict[str, str]) -> dict[str, Any]:
    history = load_history(out, source["run_id"])
    record = _record_for_version(history.get("versions"), source["version"])
    enriched: dict[str, Any] = dict(source)
    if record is None:
        enriched["best_draft_id"] = None
        enriched["variant_scores"] = []
        return enriched
    enriched["best_draft_id"] = _best_draft_id(record.get("best_draft_id"))
    stored = record.get("variant_scores")
    enriched["variant_scores"] = stored if isinstance(stored, list) else []
    return enriched


def _best_draft_id(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _stored_drafts(out: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    directory = version_dir(out, source["run_id"], source["version"])
    drafts_doc = _read_optional_json(directory / "drafts.json")
    scores_doc = _read_optional_json(directory / "scores.json")
    checklist_doc = _read_optional_json(directory / "checklist.json")
    entries, origin = _draft_entries(drafts_doc, scores_doc, source)
    scores_index = _index_score_entries(scores_doc)
    checklist_index = _index_checklist_entries(checklist_doc)
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict):
            rows.append(_draft_row(source, entry, origin, scores_index, checklist_index))
    return rows


def _draft_entries(
    drafts_doc: dict[str, Any] | None,
    scores_doc: dict[str, Any] | None,
    source: dict[str, Any],
) -> tuple[list[Any], str]:
    """Pick the draft list: drafts.json, then scores.json, then the index.

    A list is usable even when it is empty. A missing file, an unreadable
    file, a missing key, or a non-list is not, and the next source is used.
    """
    drafts = _optional_list(drafts_doc, "drafts")
    if drafts is not None:
        return drafts, "drafts"
    scores = _optional_list(scores_doc, "drafts")
    if scores is not None:
        return scores, "scores"
    stored = source.get("variant_scores")
    if isinstance(stored, list):
        return stored, "index"
    return [], "index"


def _optional_list(document: dict[str, Any] | None, key: str) -> list[Any] | None:
    if not isinstance(document, dict):
        return None
    value = document.get(key)
    if isinstance(value, list):
        return value
    return None


def _index_score_entries(scores: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return _index_by_id(_optional_list(scores, "drafts"), "draft_id")


def _index_checklist_entries(checklist: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return _index_by_id(_optional_list(checklist, "items"), "draft_id")


def _index_by_id(entries: list[Any] | None, field: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    if not isinstance(entries, list):
        return indexed
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identity = entry.get(field)
        if isinstance(identity, str) and identity not in indexed:
            indexed[identity] = entry
    return indexed


def _draft_row(
    source: dict[str, Any],
    entry: dict[str, Any],
    origin: str,
    scores_index: dict[str, dict[str, Any]],
    checklist_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if origin == "drafts":
        draft_id = _finding_text(entry.get("id"))
        char_count = _stored_number(entry.get("char_count"))
        overall = _joined_overall(scores_index.get(draft_id) if draft_id is not None else None)
    elif origin == "scores":
        draft_id = _finding_text(entry.get("draft_id"))
        char_count = None
        overall = _joined_overall(entry)
    else:
        draft_id = _finding_text(entry.get("draft_id"))
        char_count = None
        overall = _stored_number(entry.get("overall"))
    checklist_item = checklist_index.get(draft_id) if draft_id is not None else None
    if checklist_item is None:
        checklist_passed = None
        high_finding_count = None
    else:
        passed = checklist_item.get("passed")
        checklist_passed = passed if isinstance(passed, bool) else None
        high_finding_count = _high_finding_count(checklist_item)
    best_id = source.get("best_draft_id")
    return {
        "run_id": source["run_id"],
        "brief_id": source["brief_id"],
        "version": source["version"],
        "draft_id": draft_id,
        "variant": _finding_text(entry.get("variant")),
        "angle": _finding_text(entry.get("angle")),
        "char_count": char_count,
        "overall": overall,
        "recommended": isinstance(best_id, str) and draft_id == best_id,
        "checklist_passed": checklist_passed,
        "high_finding_count": high_finding_count,
        "channel": source["channel"],
        "channel_label": source["channel_label"],
    }


def _joined_overall(entry: dict[str, Any] | None) -> int | float | None:
    if not isinstance(entry, dict):
        return None
    score = entry.get("score")
    if not isinstance(score, dict):
        return None
    return _stored_number(score.get("overall"))


def _high_finding_count(item: dict[str, Any]) -> int:
    findings = item.get("findings")
    if not isinstance(findings, list):
        return 0
    return sum(1 for finding in findings if isinstance(finding, dict) and finding.get("severity") == "high")


def _draft_row_matches(row: dict[str, Any], *, draft: str | None, variant: str | None) -> bool:
    if draft is not None and row.get("draft_id") != draft:
        return False
    if variant is not None and row.get("variant") != variant:
        return False
    return True


def _stored_show_drafts(out: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    directory = version_dir(out, source["run_id"], source["version"])
    drafts_doc = _read_optional_json(directory / "drafts.json")
    scores_doc = _read_optional_json(directory / "scores.json")
    checklist_doc = _read_optional_json(directory / "checklist.json")
    entries, origin = _draft_entries(drafts_doc, scores_doc, source)
    scores_index = _index_score_entries(scores_doc)
    checklist_index = _index_checklist_entries(checklist_doc)
    approval = _stored_approval(out, source)
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        row = _draft_row(source, entry, origin, scores_index, checklist_index)
        draft_id = row["draft_id"]
        row["text"] = _stored_draft_text(entry, origin)
        row["dimensions"] = _joined_dimensions(entry, origin, scores_index, draft_id)
        checklist_item = checklist_index.get(draft_id) if isinstance(draft_id, str) else None
        row["findings"] = _stored_draft_findings(source, draft_id, checklist_item)
        row.update(approval)
        rows.append(row)
    return rows


def _stored_draft_text(entry: dict[str, Any], origin: str) -> str | None:
    if origin != "drafts":
        return None
    return _finding_text(entry.get("text"))


def _joined_dimensions(
    entry: dict[str, Any],
    origin: str,
    scores_index: dict[str, dict[str, Any]],
    draft_id: str | None,
) -> dict[str, int | float | None] | None:
    if origin == "scores":
        score_entry: dict[str, Any] | None = entry
    elif isinstance(draft_id, str):
        score_entry = scores_index.get(draft_id)
    else:
        score_entry = None
    if not isinstance(score_entry, dict):
        return None
    score = score_entry.get("score")
    if not isinstance(score, dict):
        return None
    raw = _score_dimensions(score)
    if raw is None:
        return None
    return {key: _stored_number(raw.get(key)) for key, _label in DIMENSIONS}


def _stored_draft_findings(
    source: dict[str, Any],
    draft_id: object,
    checklist_item: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(checklist_item, dict):
        return []
    findings = checklist_item.get("findings")
    if not isinstance(findings, list):
        return []
    identity = {
        "run_id": str(source["run_id"]),
        "brief_id": str(source["brief_id"]),
        "version": str(source["version"]),
        "channel": str(source["channel"]),
        "channel_label": str(source["channel_label"]),
    }
    rows: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        stored = _finding_row(identity, draft_id, finding)
        rows.append(
            {
                "rule_id": stored["rule_id"],
                "severity": stored["severity"],
                "message": stored["message"],
                "evidence": stored["evidence"],
                "suggestion": stored["suggestion"],
            }
        )
    return rows


def _stored_approval(out: Path, source: dict[str, Any]) -> dict[str, Any]:
    """Approval strings from the version index, then approval.json.

    Index fields win when they are strings, including an empty string.
    approval_reviewer, approval_comment, and approved_draft_id are preferred
    over the version's reviewer and comment. A missing or unreadable
    approval.json leaves the remaining fields null.
    """
    history = load_history(out, str(source["run_id"]))
    record = _record_for_version(history.get("versions"), str(source["version"]))
    if not isinstance(record, dict):
        record = {}
    file_approval = _read_optional_json(
        version_dir(out, str(source["run_id"]), str(source["version"])) / "approval.json"
    )
    if not isinstance(file_approval, dict):
        file_approval = {}
    return {
        "approval_status": _coalesce_text(record.get("approval_status"), file_approval.get("status")),
        "reviewer": _coalesce_text(
            record.get("approval_reviewer"),
            record.get("reviewer"),
            file_approval.get("reviewer"),
        ),
        "comment": _coalesce_text(
            record.get("approval_comment"),
            record.get("comment"),
            file_approval.get("comment"),
        ),
        "approved_draft_id": _coalesce_text(
            record.get("approved_draft_id"),
            record.get("draft_id"),
            file_approval.get("draft_id"),
        ),
    }


def _coalesce_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str):
            return value
    return None


def _stored_number(value: object) -> int | float | None:
    if not _is_number(value):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _bucket_name(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return "unknown"


def _ranked_named_counts(names: list[str], field: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    ordered = sorted(counts, key=lambda name: (-counts[name], name))
    return [{field: name, "count": counts[name]} for name in ordered]


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
