"""Project a validated Brief into the fact sheet a generator is allowed to use."""

from __future__ import annotations

from mcw.models import Brief, ExtractedFacts

EXTRACTOR_ID = "deterministic-v1"


def extract(brief: Brief) -> ExtractedFacts:
    lines = [
        f"产品：{brief.product_name}",
        f"品类：{brief.category or '未填写'}",
        f"受众：{brief.audience_segment}",
        f"语气：{brief.tone}",
        f"渠道：{brief.channel_label} / {brief.channel_format} / 上限 {brief.max_chars} 字",
        f"转化目标：{brief.conversion_goal}",
        f"行动号召：{brief.cta}",
    ]
    for index, point in enumerate(brief.selling_points, start=1):
        lines.append(f"卖点{index}：{point}")
    for point in brief.pain_points:
        lines.append(f"痛点：{point}")
    for claim in brief.claims_allowed:
        lines.append(f"允许表述：{claim}")
    for disclaimer in brief.disclaimers:
        lines.append(f"声明：{disclaimer}")
    for item in brief.must_include:
        lines.append(f"必须出现：{item}")
    for item in brief.must_avoid:
        lines.append(f"禁止出现：{item}")
    for item in brief.forbidden_claims:
        lines.append(f"禁用宣称：{item}")
    for note in brief.regulatory_notes:
        lines.append(f"合规备注：{note}")
    return ExtractedFacts(
        brief_id=brief.id,
        title=brief.title,
        locale=brief.locale,
        product_name=brief.product_name,
        category=brief.category,
        selling_points=list(brief.selling_points),
        claims_allowed=list(brief.claims_allowed),
        disclaimers=list(brief.disclaimers),
        audience_segment=brief.audience_segment,
        pain_points=list(brief.pain_points),
        tone=brief.tone,
        channel=brief.channel,
        channel_label=brief.channel_label,
        channel_format=brief.channel_format,
        max_chars=brief.max_chars,
        required_elements=list(brief.required_elements),
        conversion_goal=brief.conversion_goal,
        cta=brief.cta,
        must_include=list(brief.must_include),
        must_avoid=list(brief.must_avoid),
        forbidden_claims=list(brief.forbidden_claims),
        regulatory_notes=list(brief.regulatory_notes),
        fact_lines=lines,
        extractor=EXTRACTOR_ID,
    )
