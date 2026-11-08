"""Markdown report stored next to the JSON artifacts."""

from __future__ import annotations

from mcw.pipeline import RunResult
from mcw.scoring.rubric import DIMENSIONS, OFFLINE_SCORE_NOTE


def render_report(result: RunResult) -> str:
    best = next(draft for draft in result.drafts if draft.id == result.best_draft_id)
    lines = [
        f"# 运行报告 {result.run_id} {result.version}",
        "",
        f"> {OFFLINE_SCORE_NOTE}",
        "",
        "## 运行",
        "",
        f"- Brief：{result.brief.title} (`{result.brief.id}`)",
        f"- 渠道：{result.facts.channel_label} / {result.facts.channel_format} / 上限 {result.facts.max_chars} 字",
        f"- 后端：{result.backend}" + (f" / {result.model}" if result.model else ""),
        f"- 时间：{result.created_at}",
        f"- 审阅备注：{result.comment}",
        f"- 提交人：{result.reviewer or '—'}",
        f"- 推荐变体：{best.variant} (`{best.id}`)",
        "",
        "## 事实清单",
        "",
        "提取阶段是确定性的。生成器只能使用这份清单，不能自行加功效。",
        "",
    ]
    lines.extend(f"- {item}" for item in result.facts.fact_lines)
    lines.extend(["", "## 文案变体", ""])
    for draft, checklist, score in zip(result.drafts, result.checklists, result.scores):
        lines.append(f"### {draft.variant} · {draft.angle}")
        lines.append("")
        bits = " · ".join(
            f"{label} {getattr(score, key)}" for key, label in DIMENSIONS
        )
        lines.append(f"离线内容分 {score.overall}（{bits}）· 字数 {draft.char_count} · {checklist.summary}")
        lines.append("")
        lines.append("```text")
        lines.append(draft.text.rstrip())
        lines.append("```")
        lines.append("")
        if checklist.findings:
            lines.append("| 规则 | 级别 | 证据 | 说明 |")
            lines.append("| --- | --- | --- | --- |")
            for finding in checklist.findings:
                evidence = finding.evidence.replace("|", "\\|") or "—"
                message = finding.message.replace("|", "\\|")
                lines.append(f"| `{finding.rule_id}` | {finding.severity} | {evidence} | {message} |")
            lines.append("")
    approval = result.approval
    lines.extend(
        [
            "## 人工确认",
            "",
            f"- 状态：{approval.status}",
            f"- 审阅人：{approval.reviewer or '—'}",
            f"- 选定变体：{approval.draft_id or '—'}",
            f"- 意见：{approval.comment or '—'}",
            f"- 来源：{approval.source}",
            "",
            "## 提示词模板",
            "",
            f"模板 `{result.prompts.template_id}`。在线后端会原样发送；Mock 只按同一份事实清单填模板。",
            "",
            "```text",
            result.prompts.system,
            "```",
            "",
        ]
    )
    return "\n".join(lines) + "\n"
