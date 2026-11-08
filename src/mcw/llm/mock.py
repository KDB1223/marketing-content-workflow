"""Deterministic copy generator for demos and CI. No network, no API key."""

from __future__ import annotations

from mcw.models import Draft, ExtractedFacts, PromptBundle
from mcw.textutil import char_count


class MockGenerator:
    """Fill channel templates from the fact sheet.

    The copy is intentionally templated. It keeps selling points verbatim so
    the offline rubric can be replayed. Fluent variation belongs to the
    OpenAI-compatible backend, not to this fixture.
    """

    name = "mock"
    model = None

    def generate(
        self,
        facts: ExtractedFacts,
        prompts: PromptBundle,
        *,
        version: str,
        n: int,
        revision_note: str | None,
    ) -> list[Draft]:
        drafts: list[Draft] = []
        for index, angle in enumerate(prompts.angles[:n]):
            text = render_mock(facts, angle, revision_note)
            title, body = split_text(text)
            letter = chr(ord("A") + index)
            drafts.append(
                Draft(
                    id=f"{version}-{letter.lower()}",
                    variant=letter,
                    angle=angle,
                    title=title,
                    body=body,
                    channel=facts.channel,
                    text=text,
                    char_count=char_count(text),
                )
            )
        return drafts


def split_text(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    title = lines[0].strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    return title, body


def render_mock(facts: ExtractedFacts, angle: str, revision_note: str | None) -> str:
    lines = [title_for(facts, angle), "", body_for(facts, angle)]
    if facts.disclaimers:
        lines.append("【声明】" + "".join(facts.disclaimers))
    tags = hashtags_for(facts)
    if tags:
        lines.append(tags)
    text = "\n".join(lines).strip() + "\n"
    if revision_note and revision_note.strip():
        extra = f"修订回应：{revision_note.strip()[:40]}"
        candidate = text + extra + "\n"
        if char_count(candidate) <= facts.max_chars:
            text = candidate
    return text


def title_for(facts: ExtractedFacts, angle: str) -> str:
    pain = facts.pain_points[0] if facts.pain_points else facts.product_name
    if facts.channel == "douyin":
        title = facts.product_name.strip()
        if len(title) > 28:
            title = title[:18]
        if len(title) < 4:
            title = (title + "看这里")[:18]
        return title
    if angle == "痛点切入":
        return f"{pain}？看看{facts.product_name}"
    if angle == "卖点清单":
        return f"{facts.product_name}的事实清单"
    if angle == "场景故事":
        return f"把{facts.product_name}放进具体场景"
    if angle == "澄清边界":
        return f"{facts.product_name}：写到事实为止"
    return f"了解{facts.product_name}的下一步"


def body_for(facts: ExtractedFacts, angle: str) -> str:
    lead = lead_for(facts, angle)
    cta = facts.cta.strip()
    if not cta.endswith(("。", "！", "？", "!", "?")):
        cta = cta + "。"
    if facts.channel == "ecommerce":
        sentences = [point if point.endswith("。") else point + "。" for point in facts.selling_points]
        return lead + "".join(sentences) + cta
    joined = "；".join(facts.selling_points)
    return f"{lead}{joined}。{cta}"


def lead_for(facts: ExtractedFacts, angle: str) -> str:
    pain = facts.pain_points[0] if facts.pain_points else facts.audience_segment
    product = facts.product_name
    if facts.channel == "douyin":
        if angle == "痛点切入":
            return f"{pain}。"
        if angle == "卖点清单":
            return "先看事实。"
        if angle == "场景故事":
            return f"{facts.audience_segment}。"
        if angle == "澄清边界":
            return "只说能核对的。"
        return "想试再点。"
    if angle == "痛点切入":
        return f"{facts.audience_segment}如果也被「{pain}」卡住，可以先核对这几条事实。"
    if angle == "卖点清单":
        return f"下面只列{product}已经确认的信息，方便直接核对。"
    if angle == "场景故事":
        return f"场景限定在{facts.audience_segment}：先处理「{pain}」，再看{product}本身。"
    if angle == "澄清边界":
        return f"{product}不额外承诺事实清单之外的效果，能写下来的只有这些。"
    return f"如果这些事实符合需要，再按行动号召了解{product}。"


def hashtags_for(facts: ExtractedFacts) -> str:
    if facts.channel not in {"xiaohongshu", "douyin", "weibo"}:
        return ""
    category = facts.category or "好物"
    return f"#{facts.channel_label} #{category}"
