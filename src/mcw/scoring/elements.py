"""Channel components shared by the checklist and the 渠道适配 score."""

from __future__ import annotations

from mcw.models import ExtractedFacts
from mcw.textutil import char_count, cjk_bigrams, contains_phrase, latin_tokens


def point_hit(point: str, text: str) -> bool:
    """A selling point lands when its sentence is quoted, or its tokens mostly match.

    Fast path: the whitespace-stripped point is a substring of the draft.
    Otherwise every Latin/number token must appear, and at least 60% of the
    Chinese bigrams must appear. 配料表里的「第一位」因此可以原句命中。
    """

    if contains_phrase(text, point):
        return True
    bigrams = cjk_bigrams(point)
    latins = latin_tokens(point)
    if not bigrams and not latins:
        return False
    text_bigrams = set(cjk_bigrams(text))
    text_latins = set(latin_tokens(text))
    latin_ok = all(token in text_latins for token in latins) if latins else True
    if bigrams:
        covered = sum(1 for gram in bigrams if gram in text_bigrams) / len(bigrams)
        cjk_ok = covered >= 0.6
    else:
        cjk_ok = True
    return latin_ok and cjk_ok


_CTA_HINTS = ("点击", "评论", "立即", "了解", "领取", "扫码", "关注", "购买", "加入", "前往")
_KNOWN = {"标题", "title", "正文", "body", "话题标签", "标签", "hashtag", "行动号召", "cta", "声明", "disclaimer", "钩子", "hook", "卖点"}


def element_satisfied(name: str, text: str, facts: ExtractedFacts) -> tuple[bool, str]:
    """Return (ok, reason). Unknown component names fail closed with a reason."""

    key = name.strip()
    compact_len = char_count(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first = lines[0] if lines else ""

    if key in {"标题", "title"}:
        if first:
            return True, ""
        return False, "缺少标题：文案没有非空首行。"
    if key in {"正文", "body"}:
        if compact_len >= 20:
            return True, ""
        return False, "正文过短：去掉空白后不足 20 字。"
    if key in {"话题标签", "标签", "hashtag"}:
        if "#" in text:
            return True, ""
        return False, "缺少话题标签：文案中没有 #。"
    if key in {"行动号召", "cta"}:
        cta = facts.cta.strip()
        if cta and cta[:6] and cta[:6] in text:
            return True, ""
        if any(hint in text for hint in _CTA_HINTS):
            return True, ""
        return False, "缺少行动号召：没有出现 Brief 里的 CTA，也没有常见动作词。"
    if key in {"声明", "disclaimer"}:
        if not facts.disclaimers:
            return True, ""
        if "【声明】" in text:
            return True, ""
        if any(item.strip()[:8] and item.strip()[:8] in text for item in facts.disclaimers):
            return True, ""
        return False, "缺少声明：没有「【声明】」或声明原文。"
    if key in {"钩子", "hook"}:
        length = len(first)
        if 4 <= length <= 28:
            return True, ""
        return False, f"钩子不合格：抖音首行应为 4–28 个字符，当前是 {length}。"
    if key in {"卖点"}:
        if any(point_hit(point, text) for point in facts.selling_points):
            return True, ""
        return False, "卖点组件未命中：详情里看不出事实清单中的卖点。"
    if key not in _KNOWN:
        return False, f"无法识别的渠道组件「{key}」。"
    return False, f"缺少渠道组件「{key}」。"
