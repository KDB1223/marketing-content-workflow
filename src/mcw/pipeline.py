"""Brief → extract → generate → risk_check → confirm."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mcw.errors import MCWError
from mcw.models import Approval, Brief, Checklist, Draft, ExtractedFacts, PromptBundle
from mcw.scoring.rubric import ScoreCard, score_text
from mcw.stages.confirm import confirm
from mcw.stages.extract import extract
from mcw.stages.generate import Generator, generate_drafts, prepare_generation
from mcw.stages.risk_check import risk_check


@dataclass
class RunResult:
    run_id: str
    version: str
    created_at: str
    brief_path: str
    brief: Brief
    facts: ExtractedFacts
    drafts: list[Draft]
    checklists: list[Checklist]
    scores: list[ScoreCard]
    prompts: PromptBundle
    backend: str
    model: str | None
    approval: Approval
    comment: str
    reviewer: str | None
    best_draft_id: str
    variants: int


def run_pipeline(
    brief: Brief,
    *,
    run_id: str,
    version: str,
    generator: Generator,
    created_at: str,
    reviewer: str | None,
    comment: str | None,
    approval_path: str | Path | None,
    variants: int,
    brief_path: str = "",
) -> RunResult:
    if not 1 <= variants <= 5:
        raise MCWError("--variants 需要在 1 到 5 之间")
    facts = extract(brief)
    stored_comment = (comment or "").strip() or "初稿"
    prompts, revision = prepare_generation(facts, n=variants, comment=stored_comment)
    drafts = generate_drafts(
        facts,
        generator,
        prompts,
        version=version,
        n=variants,
        revision_note=revision,
    )
    if len(drafts) != variants:
        raise MCWError("生成器返回的变体数量与请求不一致")
    checklists = [risk_check(draft, facts) for draft in drafts]
    scores = [
        score_text(draft.text, facts, findings=checklist.findings)
        for draft, checklist in zip(drafts, checklists)
    ]
    approval = confirm(drafts, approval_path, created_at)
    best_index = min(
        range(len(drafts)),
        key=lambda index: (-scores[index].overall, drafts[index].variant),
    )
    reviewer_name = reviewer.strip() if reviewer and reviewer.strip() else None
    return RunResult(
        run_id=run_id,
        version=version,
        created_at=created_at,
        brief_path=brief_path,
        brief=brief,
        facts=facts,
        drafts=drafts,
        checklists=checklists,
        scores=scores,
        prompts=prompts,
        backend=generator.name,
        model=generator.model,
        approval=approval,
        comment=stored_comment,
        reviewer=reviewer_name,
        best_draft_id=drafts[best_index].id,
        variants=variants,
    )
