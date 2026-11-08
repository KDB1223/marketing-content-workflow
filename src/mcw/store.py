"""Persist a run under ``.mcw/runs/<run_id>/``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcw.errors import MCWError
from mcw.models import Checklist, Draft, ExtractedFacts
from mcw.pipeline import RunResult
from mcw.report import render_report
from mcw.schema import brief_fingerprint
from mcw.scoring.rubric import OFFLINE_SCORE_NOTE, ScoreCard, WEIGHTS

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_VERSION = re.compile(r"^v[1-9][0-9]{0,3}$")
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
