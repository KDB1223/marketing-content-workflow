from __future__ import annotations

from mcw.fixtures import score_cases
from mcw.risk.rules import run_rules
from mcw.scoring.rubric import score_readability, score_text, weighted_overall


def test_weights_round_half_up() -> None:
    # 0.35*100 + 0.25*100 + 0.25*75 + 0.15*90 = 92.25
    assert weighted_overall(100, 100, 75, 90) == 92


def test_fixture_scores_match_recorded_values() -> None:
    rows = score_cases()
    assert rows
    assert all(row["matched"] for row in rows)
    by_id = {row["id"]: row["actual"] for row in rows}
    assert by_id["clean-xiaohongshu"]["overall"] == 100
    assert by_id["absolute-claim"]["compliance"] == 75
    assert by_id["absolute-claim"]["overall"] == 94
    assert by_id["missing-disclaimer"]["compliance"] == 75
    assert by_id["official-slang"]["channel_fit"] == 80
    assert by_id["missed-selling-points"]["selling_point_accuracy"] == 0
    assert by_id["partial-selling-point"]["selling_point_accuracy"] == 33
    assert by_id["partial-selling-point"]["overall"] == 77
    assert by_id["dense-sentence"]["readability"] == 85
    assert by_id["dense-sentence"]["overall"] == 98
    assert all(row["note"].startswith("离线内容分") for row in rows)


def test_score_is_reproducible(make_facts) -> None:
    facts = make_facts()
    text = "标题\n轻薄不油腻，上脸成膜快。SPF50+ PA++++。添加积雪草，舒缓晒后泛红。\n#护肤\n【声明】防晒效果因人而异，长时间外出请及时补涂。\n"
    first = score_text(text, facts)
    second = score_text(text, facts)
    assert first.to_dict() == second.to_dict()
    assert first.to_dict()["not_business_conversion"] is True


def test_channel_penalty_does_not_reduce_compliance(make_facts) -> None:
    facts = make_facts(required_elements=["标题", "正文", "话题标签"])
    text = "澄光防晒乳 SPF50+\n轻薄不油腻，上脸成膜快。SPF50+ PA++++。添加积雪草，舒缓晒后泛红。\n【声明】防晒效果因人而异，长时间外出请及时补涂。\n"
    findings = run_rules(text, facts)
    card = score_text(text, facts, findings=findings)
    assert any(item.rule_id == "required_element" for item in findings)
    assert card.compliance == 100
    assert card.channel_fit <= 85


def test_length_penalty_is_channel_fit_only(make_facts) -> None:
    facts = make_facts(max_chars=40, required_elements=[])
    text = "澄光防晒乳 SPF50+\n轻薄不油腻，上脸成膜快。SPF50+ PA++++。添加积雪草，舒缓晒后泛红。评论区扣「防晒」领取试用装说明。\n【声明】防晒效果因人而异，长时间外出请及时补涂。\n#小红书\n"
    card = score_text(text, facts)
    assert card.channel_fit <= 70
    assert card.compliance == 100


def test_readability_edges() -> None:
    assert score_readability("") == 0
    assert score_readability("   ") == 0
    long_line = "没有标点的句子" * 20
    assert score_readability(long_line) < 70
    stutter = "天天天天天天，真的天天天天天天。"
    assert score_readability(stutter) <= 90
