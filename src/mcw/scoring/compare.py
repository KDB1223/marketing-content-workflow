"""Side-by-side version comparison. Deltas are content-score deltas, not lift."""

from __future__ import annotations

import difflib
from typing import Any

from mcw.scoring.rubric import DIMENSIONS, OFFLINE_SCORE_NOTE


def render_comparison(run_id: str, left: dict[str, Any], right: dict[str, Any]) -> str:
    left_record = left["record"]
    right_record = right["record"]
    lines = [
        f"# 版本对照 {run_id} {left_record['version']} → {right_record['version']}",
        "",
        f"> {OFFLINE_SCORE_NOTE}",
        "",
        "分数变化只说明两版文案在离线量表上的差别，不能当成转化提升。",
        "",
        "## 审阅记录",
        "",
        f"- {left_record['version']}：{left_record.get('reviewer') or '—'} · {left_record.get('comment') or '—'}",
        f"- {right_record['version']}：{right_record.get('reviewer') or '—'} · {right_record.get('comment') or '—'}",
        f"- 确认：{left_record.get('approval_status')} → {right_record.get('approval_status')}",
        "",
        "## 推荐变体分数",
        "",
        "| 维度 | "
        + left_record["version"]
        + " | "
        + right_record["version"]
        + " | 变化 |",
        "| --- | ---: | ---: | ---: |",
    ]
    left_dims = left_record["dimension_scores"]
    right_dims = right_record["dimension_scores"]
    for key, label in DIMENSIONS:
        before = int(left_dims[key])
        after = int(right_dims[key])
        lines.append(f"| {label} | {before} | {after} | {_signed(after - before)} |")
    lines.append(
        "| 总分 | {before} | {after} | {delta} |".format(
            before=left_record["overall_score"],
            after=right_record["overall_score"],
            delta=_signed(int(right_record["overall_score"]) - int(left_record["overall_score"])),
        )
    )
    lines.extend(["", "## 变体", ""])
    left_by_variant = {item["variant"]: item for item in left["drafts"]["drafts"]}
    right_by_variant = {item["variant"]: item for item in right["drafts"]["drafts"]}
    letters = sorted(set(left_by_variant) | set(right_by_variant))
    left_findings = _findings_by_variant(left)
    right_findings = _findings_by_variant(right)
    for letter in letters:
        lines.append(f"### 变体 {letter}")
        lines.append("")
        before = left_by_variant.get(letter)
        after = right_by_variant.get(letter)
        if before and after:
            lines.extend(_diff_block(left_record["version"], right_record["version"], letter, before["text"], after["text"]))
        elif before:
            lines.append(f"{left_record['version']} 有此变体，{right_record['version']} 没有。")
        else:
            lines.append(f"{right_record['version']} 新增此变体。")
        resolved, added = _finding_delta(left_findings.get(letter, []), right_findings.get(letter, []))
        lines.append("")
        lines.append(f"- 消除的检查项：{_format_findings(resolved)}")
        lines.append(f"- 新出现的检查项：{_format_findings(added)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _signed(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


def _findings_by_variant(bundle: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    drafts = {item["id"]: item["variant"] for item in bundle["drafts"]["drafts"]}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in bundle["checklist"]["items"]:
        letter = drafts.get(item["draft_id"], "?")
        grouped[letter] = list(item.get("findings", []))
    return grouped


def _finding_key(finding: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(finding.get("rule_id", "")),
        str(finding.get("severity", "")),
        str(finding.get("evidence", "")),
        str(finding.get("message", "")),
    )


def _finding_delta(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    left_keys = {_finding_key(item) for item in left}
    right_keys = {_finding_key(item) for item in right}
    resolved = [item for item in left if _finding_key(item) not in right_keys]
    added = [item for item in right if _finding_key(item) not in left_keys]
    return resolved, added


def _format_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "无"
    parts = []
    for item in findings:
        evidence = item.get("evidence") or "—"
        parts.append(f"{item.get('rule_id')}[{item.get('severity')}:{evidence}]")
    return "；".join(parts)


def _diff_block(left_version: str, right_version: str, letter: str, before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"{left_version} {letter}",
        tofile=f"{right_version} {letter}",
        lineterm="",
    )
    body = "\n".join(diff).strip()
    if not body:
        return ["两版正文一致。"]
    return ["```diff", body, "```"]
