"""Deterministic risk rules for Chinese marketing copy.

The checklist is an audit artifact. Score dimensions pick subsets of these
rule ids so a channel-format issue does not also count as a compliance hit.
"""

from __future__ import annotations

import re
from typing import Protocol

from mcw.models import ExtractedFacts, Finding
from mcw.textutil import char_count, contains_phrase, find_phrases

# 第一位 / 第一步 are ordinary order words. 全网第一 still matches as its own phrase.
_FIRST_EXCEPTIONS = ["第一时间", "第一位", "第一步", "第一次"]
_ZUI_EXCEPTIONS = ["最近", "最后", "最终", "最为", "最初"]

ABSOLUTE_HIGH = [
    "国家级",
    "最高级",
    "最佳",
    "最好",
    "最强",
    "最优",
    "全网最低",
    "全网第一",
    "销量第一",
    "唯一",
    "绝对",
    "永久",
    "万能",
    "100%",
    "百分之百",
    "史无前例",
]
ABSOLUTE_MEDIUM = ["第一", "最新"]
ABSOLUTE_EXCEPTIONS = {
    "第一": _FIRST_EXCEPTIONS,
    "最": _ZUI_EXCEPTIONS,
}

OVERCLAIM_HIGH = [
    "治愈",
    "根治",
    "药到病除",
    "医学证明",
    "医院同款",
    "无副作用",
    "零副作用",
    "处方级",
    "药用",
    "抗癌",
    "保证治愈",
    "三天见效",
    "彻底消除",
]
OVERCLAIM_MEDIUM = ["特效", "无效退款", "消炎", "治疗"]

SLANG = ("家人们", "宝子", "yyds", "绝绝子", "集美")
_HASHTAG = re.compile(r"#\S+")

COMPLIANCE_RULES = {
    "absolute_words",
    "overclaim",
    "missing_disclaimer",
    "forbidden_claim",
    "must_avoid",
}
CHANNEL_SCORE_RULES = {"channel_mismatch", "required_element"}


class RiskRule(Protocol):
    id: str

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        ...


def builtin_rules() -> list[RiskRule]:
    return [
        AbsoluteWordsRule(),
        OverclaimRule(),
        MustAvoidRule(),
        ForbiddenClaimRule(),
        MissingDisclaimerRule(),
        MissingMustIncludeRule(),
        LengthLimitRule(),
        RequiredElementsRule(),
        ChannelMismatchRule(),
    ]


def run_rules(
    text: str,
    facts: ExtractedFacts,
    rules: list[RiskRule] | None = None,
) -> list[Finding]:
    selected = builtin_rules() if rules is None else rules
    findings: list[Finding] = []
    for rule in selected:
        findings.extend(rule.check(text, facts))
    return findings


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _finding(
    rule_id: str,
    severity: str,
    message: str,
    evidence: str,
    suggestion: str,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message=message,
        evidence=evidence,
        suggestion=suggestion,
    )


class AbsoluteWordsRule:
    id = "absolute_words"

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        del facts
        findings: list[Finding] = []
        high = set(ABSOLUTE_HIGH)
        hits = _unique(find_phrases(text, ABSOLUTE_HIGH + ABSOLUTE_MEDIUM, ABSOLUTE_EXCEPTIONS))
        for phrase in hits:
            if phrase in high:
                findings.append(
                    _finding(
                        self.id,
                        "high",
                        f"出现绝对化用语「{phrase}」。广告法语境下这类词容易被认定无法证实。",
                        phrase,
                        "改成事实清单里的具体表述，例如成分、规格或适用条件。",
                    )
                )
            else:
                findings.append(
                    _finding(
                        self.id,
                        "medium",
                        f"出现容易被平台判为绝对化的词「{phrase}」。",
                        phrase,
                        "如果它不是在说顺序（如配料表第一位），就删掉或改成可核对的事实。",
                    )
                )
        return findings


class OverclaimRule:
    id = "overclaim"

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        del facts
        findings: list[Finding] = []
        high = set(OVERCLAIM_HIGH)
        hits = _unique(find_phrases(text, OVERCLAIM_HIGH + OVERCLAIM_MEDIUM))
        for phrase in hits:
            if phrase in high:
                findings.append(
                    _finding(
                        self.id,
                        "high",
                        f"出现疗效或保证性表述「{phrase}」，超出普通商品文案可证实的范围。",
                        phrase,
                        "删除医疗化承诺。功效只保留事实清单里的原句。",
                    )
                )
            else:
                findings.append(
                    _finding(
                        self.id,
                        "medium",
                        f"出现偏强的效果承诺「{phrase}」。",
                        phrase,
                        "改成使用条件、感官描述，或直接删去。",
                    )
                )
        return findings


class MustAvoidRule:
    id = "must_avoid"

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        findings: list[Finding] = []
        for phrase in facts.must_avoid:
            hits = _unique(
                find_phrases(text, [phrase], {"最": _ZUI_EXCEPTIONS, "第一": _FIRST_EXCEPTIONS})
            )
            if not hits and contains_phrase(text, phrase) and phrase not in {"最", "第一"}:
                hits = [phrase]
            for hit in hits:
                findings.append(
                    _finding(
                        self.id,
                        "high",
                        f"Brief 明确禁止出现「{phrase}」，文案里仍有「{hit}」。",
                        hit,
                        "按 Brief 的禁止列表改写，不要用近义的绝对化说法顶替。",
                    )
                )
        return findings


class ForbiddenClaimRule:
    id = "forbidden_claim"

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        findings: list[Finding] = []
        for claim in facts.forbidden_claims:
            if contains_phrase(text, claim):
                findings.append(
                    _finding(
                        self.id,
                        "high",
                        f"出现 Brief 禁用宣称「{claim}」。",
                        claim,
                        "删除该宣称。不要换成另一句事实清单之外的功效。",
                    )
                )
        return findings


class MissingDisclaimerRule:
    id = "missing_disclaimer"

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        if not facts.disclaimers:
            return []
        if "【声明】" in text:
            return []
        for disclaimer in facts.disclaimers:
            snippet = disclaimer.strip()[:12]
            if snippet and snippet in text:
                return []
        return [
            _finding(
                self.id,
                "high",
                "事实清单要求声明，文案里没有「【声明】」或声明原文。",
                "",
                "在文末加上「【声明】」并附上事实清单中的声明原文。",
            )
        ]


class MissingMustIncludeRule:
    id = "missing_must_include"

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        findings: list[Finding] = []
        folded = text.casefold()
        for item in facts.must_include:
            if item.casefold() not in folded:
                findings.append(
                    _finding(
                        self.id,
                        "medium",
                        f"必含信息「{item}」没有出现在文案中。",
                        item,
                        "把这条信息原样写进正文或声明，不要只写在标题注释里。",
                    )
                )
        return findings


class LengthLimitRule:
    id = "length_limit"

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        count = char_count(text)
        if facts.max_chars and count > facts.max_chars:
            severity = "high" if facts.channel == "douyin" else "medium"
            return [
                _finding(
                    self.id,
                    severity,
                    f"文案 {count} 字，超过{facts.channel_label}上限 {facts.max_chars} 字。",
                    str(count),
                    "删去事实清单之外的修饰，保留卖点、行动号召和声明。",
                )
            ]
        return []


class RequiredElementsRule:
    id = "required_element"

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        from mcw.scoring.elements import element_satisfied

        findings: list[Finding] = []
        for name in facts.required_elements:
            ok, reason = element_satisfied(name, text, facts)
            if ok:
                continue
            findings.append(
                _finding(
                    self.id,
                    "medium",
                    reason or f"缺少渠道组件「{name}」。",
                    name,
                    "按 Brief 的 required_elements 补齐。未识别的组件名需要改成文档中的名称。",
                )
            )
        return findings


class ChannelMismatchRule:
    id = "channel_mismatch"

    def check(self, text: str, facts: ExtractedFacts) -> list[Finding]:
        findings: list[Finding] = []
        folded = text.casefold()
        slang_hits = [word for word in SLANG if word.casefold() in folded]
        hashtags = len(_HASHTAG.findall(text))
        channel = facts.channel

        if channel == "official_site" and slang_hits:
            findings.append(
                _finding(
                    self.id,
                    "medium",
                    f"官网文案出现网络俚语「{slang_hits[0]}」，和正式渠道不一致。",
                    slang_hits[0],
                    "改成费率、规格、适用条件这类可核对的句子。",
                )
            )
        elif channel == "wechat" and slang_hits:
            findings.append(
                _finding(
                    self.id,
                    "low",
                    f"公众号正文出现强口语「{slang_hits[0]}」。",
                    slang_hits[0],
                    "若账号调性不是段子号，改成编辑部口吻。",
                )
            )

        if channel in {"wechat", "official_site"} and hashtags >= 4:
            findings.append(
                _finding(
                    self.id,
                    "low",
                    f"{facts.channel_label}堆了 {hashtags} 个话题标签，读起来像把小红书直接粘过来。",
                    f"#{hashtags}",
                    "长文渠道保留标题和行动号召即可，话题标签不是必需品。",
                )
            )

        if channel == "xiaohongshu" and "阅读原文" in text:
            findings.append(
                _finding(
                    self.id,
                    "low",
                    "小红书正文出现「阅读原文」，这是公众号组件。",
                    "阅读原文",
                    "改成评论、收藏或主页链接一类小红书里真实存在的动作。",
                )
            )

        if channel == "douyin" and any(token in text for token in ("尊敬的用户", "本公司", "兹有")):
            findings.append(
                _finding(
                    self.id,
                    "medium",
                    "抖音口播使用了公文或官网套话。",
                    "公文套话",
                    "开头用一句短钩子，再接事实清单里的卖点。",
                )
            )

        if channel == "ecommerce" and facts.product_name and facts.product_name not in text:
            findings.append(
                _finding(
                    self.id,
                    "medium",
                    "电商详情没有出现产品名，规格和卖点会对不上商品。",
                    facts.product_name,
                    "在标题或首段写上产品名。",
                )
            )
        return findings
