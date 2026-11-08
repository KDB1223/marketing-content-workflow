from __future__ import annotations

from pathlib import Path

import pytest

from mcw.errors import MCWError
from mcw.schema import BriefValidationError, brief_fingerprint, load_brief, parse_brief


def test_load_yaml_and_json_briefs(briefs_dir: Path) -> None:
    files = list(briefs_dir.glob("*.yaml")) + list(briefs_dir.glob("*.json"))
    assert len(files) >= 5
    ids = set()
    for path in files:
        brief = load_brief(path)
        ids.add(brief.id)
        assert brief.locale == "zh-CN"
        assert brief.selling_points
        assert brief.max_chars > 0
        assert brief.channel_label
    assert ids == {
        "sunscreen-xhs",
        "coffee-wechat",
        "fitness-douyin",
        "creditcard-official",
        "kidsnack-ecommerce",
    }


def test_channel_alias_and_defaults() -> None:
    brief = parse_brief(
        {
            "id": "alias",
            "title": "别名",
            "locale": "zh-CN",
            "product": {"name": "示例", "selling_points": ["卖点甲"]},
            "audience": {"segment": "新手", "tone": "平静"},
            "channel": {"name": "小红书", "format": "note", "max_chars": 200},
            "conversion": {"goal": "收藏", "cta": "评论告诉我"},
        }
    )
    assert brief.channel == "xiaohongshu"
    assert brief.required_elements == ["标题", "正文", "话题标签"]


def test_empty_required_elements_are_respected() -> None:
    brief = parse_brief(
        {
            "id": "opt-out",
            "title": "自定组件",
            "locale": "zh-CN",
            "product": {"name": "示例", "selling_points": ["卖点甲"]},
            "audience": {"segment": "新手", "tone": "平静"},
            "channel": {
                "name": "xiaohongshu",
                "format": "note",
                "max_chars": 200,
                "required_elements": [],
            },
            "conversion": {"goal": "收藏", "cta": "评论告诉我"},
        }
    )
    assert brief.required_elements == []


def test_reject_missing_selling_point_and_bool_limit() -> None:
    with pytest.raises(BriefValidationError) as caught:
        parse_brief(
            {
                "id": "bad",
                "title": "坏样本",
                "locale": "zh-CN",
                "product": {"name": "示例"},
                "audience": {"segment": "新手", "tone": "平静"},
                "channel": {"name": "官网", "format": "page", "max_chars": True},
                "conversion": {"goal": "", "cta": "前往"},
            }
        )
    text = str(caught.value)
    assert "selling_points" in text
    assert "max_chars" in text
    assert "conversion.goal" in text


def test_unknown_channel() -> None:
    with pytest.raises(BriefValidationError) as caught:
        parse_brief(
            {
                "id": "bad",
                "title": "坏样本",
                "locale": "zh-CN",
                "product": {"name": "示例", "selling_points": ["卖点甲"]},
                "audience": {"segment": "新手", "tone": "平静"},
                "channel": {"name": "电梯广告", "format": "poster", "max_chars": 40},
                "conversion": {"goal": "扫码", "cta": "扫码"},
            }
        )
    assert "无法识别" in str(caught.value)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MCWError):
        load_brief(tmp_path / "missing.yaml")


def test_fingerprint_changes_with_claims() -> None:
    payload = {
        "id": "fp",
        "title": "指纹",
        "locale": "zh-CN",
        "product": {"name": "示例", "selling_points": ["卖点甲"]},
        "audience": {"segment": "新手", "tone": "平静"},
        "channel": {"name": "wechat", "format": "article", "max_chars": 300},
        "conversion": {"goal": "阅读", "cta": "点击阅读原文"},
    }
    first = parse_brief(payload)
    payload["product"]["selling_points"] = ["卖点乙"]
    second = parse_brief(payload)
    assert brief_fingerprint(first) != brief_fingerprint(second)
    assert brief_fingerprint(first) == brief_fingerprint(parse_brief({**payload, "product": {"name": "示例", "selling_points": ["卖点甲"]}}))
