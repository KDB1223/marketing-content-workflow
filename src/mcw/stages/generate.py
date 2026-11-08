"""Generate stage. Revision comments change the prompt; 「初稿」 does not."""

from __future__ import annotations

from typing import Protocol

from mcw.models import Draft, ExtractedFacts, PromptBundle
from mcw.prompts.templates import build_prompts


class Generator(Protocol):
    name: str
    model: str | None

    def generate(
        self,
        facts: ExtractedFacts,
        prompts: PromptBundle,
        *,
        version: str,
        n: int,
        revision_note: str | None,
    ) -> list[Draft]:
        ...


def revision_note_for(comment: str | None) -> str | None:
    if comment is None:
        return None
    text = comment.strip()
    if not text or text == "初稿":
        return None
    return text


def prepare_generation(
    facts: ExtractedFacts,
    *,
    n: int,
    comment: str | None,
) -> tuple[PromptBundle, str | None]:
    note = revision_note_for(comment)
    return build_prompts(facts, n=n, revision_note=note), note


def generate_drafts(
    facts: ExtractedFacts,
    generator: Generator,
    prompts: PromptBundle,
    *,
    version: str,
    n: int,
    revision_note: str | None,
) -> list[Draft]:
    drafts = generator.generate(
        facts,
        prompts,
        version=version,
        n=n,
        revision_note=revision_note,
    )
    normalized: list[Draft] = []
    for draft in drafts:
        if draft.channel:
            normalized.append(draft)
            continue
        normalized.append(
            Draft(
                id=draft.id,
                variant=draft.variant,
                angle=draft.angle,
                title=draft.title,
                body=draft.body,
                channel=facts.channel,
                text=draft.text,
                char_count=draft.char_count,
            )
        )
    return normalized
