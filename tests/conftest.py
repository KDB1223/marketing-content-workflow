from __future__ import annotations

from pathlib import Path

import pytest

from mcw.models import ExtractedFacts

ROOT = Path(__file__).resolve().parents[1]
BRIEFS = ROOT / "briefs"


@pytest.fixture
def briefs_dir() -> Path:
    return BRIEFS


def _make_facts(**overrides: object) -> ExtractedFacts:
    base: dict[str, object] = {
        "brief_id": "fixture",
        "title": "测试简报",
        "locale": "zh-CN",
        "product_name": "澄光防晒乳 SPF50+",
        "category": "护肤",
        "selling_points": ["轻薄不油腻，上脸成膜快", "SPF50+ PA++++", "添加积雪草，舒缓晒后泛红"],
        "claims_allowed": ["轻薄"],
        "disclaimers": ["防晒效果因人而异，长时间外出请及时补涂。"],
        "audience_segment": "18-28 岁都市通勤族",
        "pain_points": ["夏天出油怕搓泥"],
        "tone": "亲切",
        "channel": "xiaohongshu",
        "channel_label": "小红书",
        "channel_format": "note",
        "max_chars": 450,
        "required_elements": ["标题", "正文", "话题标签"],
        "conversion_goal": "收藏",
        "cta": "评论区扣「防晒」领取试用装说明",
        "must_include": ["SPF50+"],
        "must_avoid": ["最", "第一"],
        "forbidden_claims": ["医疗级美白"],
        "regulatory_notes": ["化妆品不得宣称医疗功效。"],
        "fact_lines": ["产品：澄光防晒乳 SPF50+"],
        "extractor": "deterministic-v1",
    }
    base.update(overrides)
    return ExtractedFacts.from_dict(base)


@pytest.fixture
def make_facts():
    """Factory fixture. Tests must not import this from conftest."""

    return _make_facts
