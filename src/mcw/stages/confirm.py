"""File-based human confirm stub.

Generation is not blocked. The approval JSON is stored beside the drafts so a
reviewer decision is part of the version history.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcw.errors import MCWError
from mcw.models import Approval, Draft

_STATUSES = {"pending", "approved", "rejected"}


def confirm(
    drafts: list[Draft],
    approval_path: str | Path | None,
    now: str,
) -> Approval:
    if approval_path is None:
        return Approval(
            status="pending",
            reviewer=None,
            comment=None,
            draft_id=None,
            decided_at=None,
            source="stub",
        )
    path = Path(approval_path)
    if not path.is_file():
        raise MCWError(f"找不到确认文件: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCWError(f"确认文件不是 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MCWError("确认文件的根节点必须是对象")
    status = data.get("status")
    if status not in _STATUSES:
        raise MCWError("approval.status 必须是 pending、approved 或 rejected")
    reviewer = _optional_text(data.get("reviewer"), "reviewer")
    comment = _optional_text(data.get("comment"), "comment")
    draft_token = _optional_text(data.get("draft_id"), "draft_id")
    decided_raw = data.get("decided_at")
    if decided_raw is not None and not isinstance(decided_raw, str):
        raise MCWError("approval.decided_at 必须是字符串")
    if status in {"approved", "rejected"}:
        if not reviewer:
            raise MCWError("approved 或 rejected 必须填写 reviewer")
        if not draft_token:
            raise MCWError("approved 或 rejected 必须填写 draft_id，可用变体字母 A/B/C")
    draft_id = resolve_draft_id(draft_token, drafts) if draft_token else None
    if status == "pending":
        decided_at = None
    else:
        decided_at = decided_raw or now
    return Approval(
        status=status,
        reviewer=reviewer,
        comment=comment,
        draft_id=draft_id,
        decided_at=decided_at,
        source=str(path),
    )


def resolve_draft_id(token: str, drafts: list[Draft]) -> str:
    by_id = {draft.id: draft.id for draft in drafts}
    if token in by_id:
        return by_id[token]
    by_letter = {draft.variant.upper(): draft.id for draft in drafts}
    if token.upper() in by_letter:
        return by_letter[token.upper()]
    known = ", ".join(draft.variant for draft in drafts)
    raise MCWError(f"approval.draft_id 无法匹配当前文案: {token}。可选变体: {known}")


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MCWError(f"approval.{field} 必须是字符串")
    text = value.strip()
    return text or None
