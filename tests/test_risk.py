from __future__ import annotations

from mcw.risk.rules import run_rules
from tests.conftest import make_facts


def _ids(text: str, **overrides: object) -> list[tuple[str, str, str]]:
    findings = run_rules(text, make_facts(**overrides))
    return [(item.rule_id, item.severity, item.evidence) for item in findings]


def test_absolute_phrase_does_not_also_flag_inner_word() -> None:
    found = _ids("这不是全网第一。", must_avoid=[], forbidden_claims=[])
    absolute = [item for item in found if item[0] == "absolute_words"]
    assert absolute == [("absolute_words", "high", "全网第一")]


def test_ingredient_order_is_not_a_superlative() -> None:
    found = _ids("配料表第一位是生牛乳。", must_avoid=[], forbidden_claims=[])
    assert not any(item[0] == "absolute_words" for item in found)


def test_recent_time_is_not_a_banned_zui() -> None:
    found = _ids("这是最近一批到货。", must_avoid=["最"], forbidden_claims=[])
    assert not any(item[0] == "must_avoid" for item in found)
    flagged = _ids("这是最好的一批。", must_avoid=["最"], forbidden_claims=[])
    assert ("must_avoid", "high", "最") in flagged
    assert ("absolute_words", "high", "最好") in flagged


def test_overclaim_and_forbidden_claim() -> None:
    found = _ids("七天治愈晒伤，医疗级美白。", disclaimers=[])
    assert ("overclaim", "high", "治愈") in found
    assert ("forbidden_claim", "high", "医疗级美白") in found


def test_missing_disclaimer_and_must_include() -> None:
    text = "轻薄不油腻，上脸成膜快。SPF50+ PA++++。添加积雪草，舒缓晒后泛红。\n#小红书\n"
    found = _ids(text)
    assert ("missing_disclaimer", "high", "") in found
    assert not any(item[0] == "missing_must_include" for item in found)


def test_channel_slang_and_hashtag_stuffing() -> None:
    official = _ids(
        "家人们，澄湾联名信用卡今天上线。\n【声明】以审批为准。",
        channel="official_site",
        channel_label="官网",
        product_name="澄湾联名信用卡",
        required_elements=["标题", "正文", "声明"],
        disclaimers=["以审批为准。"],
    )
    assert ("channel_mismatch", "medium", "家人们") in official
    stuffed = "标题\n" + " ".join(f"#话题{i}" for i in range(4))
    wechat = _ids(
        stuffed,
        channel="wechat",
        channel_label="微信公众号",
        required_elements=[],
        disclaimers=[],
        must_avoid=[],
        forbidden_claims=[],
        must_include=[],
    )
    assert any(item[0] == "channel_mismatch" and item[1] == "low" for item in wechat)


def test_length_limit_is_high_on_douyin() -> None:
    text = "燃点训练\n" + "跟练" * 80
    found = _ids(
        text,
        channel="douyin",
        channel_label="抖音",
        product_name="燃点训练",
        max_chars=30,
        required_elements=[],
        disclaimers=[],
        must_avoid=[],
        forbidden_claims=[],
        must_include=[],
        selling_points=["每天 15 分钟跟练"],
    )
    assert ("length_limit", "high", str(__import__("mcw.textutil", fromlist=["char_count"]).char_count(text))) in found
