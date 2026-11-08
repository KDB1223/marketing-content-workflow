"""Turn risk-rule findings into a per-draft checklist."""

from __future__ import annotations

from mcw.models import Checklist, Draft, ExtractedFacts
from mcw.risk.rules import run_rules


def summarize(findings_count: int, high_count: int) -> str:
    if findings_count == 0:
        return "未发现风险项。"
    return f"共 {findings_count} 项，其中高风险 {high_count} 项。"


def risk_check(draft: Draft, facts: ExtractedFacts) -> Checklist:
    findings = run_rules(draft.text, facts)
    high_count = sum(1 for item in findings if item.severity == "high")
    return Checklist(
        draft_id=draft.id,
        passed=high_count == 0,
        summary=summarize(len(findings), high_count),
        findings=findings,
    )
