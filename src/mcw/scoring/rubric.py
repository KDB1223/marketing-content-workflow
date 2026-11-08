"""Offline content rubric.

卖点准确、渠道适配、合规、可读性 are deterministic and replayable.
They judge the draft against the Brief. They are not a business conversion rate.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from mcw.models import ExtractedFacts, Finding
from mcw.risk.rules import COMPLIANCE_RULES, run_rules
from mcw.scoring.elements import point_hit
from mcw.textutil import char_count

OFFLINE_SCORE_NOTE = (
    "离线内容分只评估文案与 Brief 的一致性、渠道形态、合规风险和可读性。"
    "它不是真实投放转化率，也不能代替 A/B 实验或业务结果。"
)

WEIGHTS = {
    "selling_point_accuracy": 0.35,
    "channel_fit": 0.25,
    "compliance": 0.25,
    "readability": 0.15,
}

DIMENSIONS = (
    ("selling_point_accuracy", "卖点准确"),
    ("channel_fit", "渠道适配"),
    ("compliance", "合规"),
    ("readability", "可读性"),
)

_SENTENCE_SPLIT = re.compile(r"[。！？!?]+")
_PUNCT = re.compile(r"[。！？，、]")
_SEVERITY_PENALTY = {"high": 25, "medium": 12, "low": 5}


@dataclass
class ScoreCard:
    selling_point_accuracy: int
    channel_fit: int
    compliance: int
    readability: int
    overall: int

    def to_dict(self) -> dict:
        return {
            "kind": "offline_content_score",
            "not_business_conversion": True,
            "note": OFFLINE_SCORE_NOTE,
            "weights": dict(WEIGHTS),
            "dimensions": {
                "selling_point_accuracy": {
                    "label": "卖点准确",
                    "score": self.selling_point_accuracy,
                },
                "channel_fit": {"label": "渠道适配", "score": self.channel_fit},
                "compliance": {"label": "合规", "score": self.compliance},
                "readability": {"label": "可读性", "score": self.readability},
            },
            "overall": self.overall,
        }

    def dimension_map(self) -> dict[str, int]:
        return {
            "selling_point_accuracy": self.selling_point_accuracy,
            "channel_fit": self.channel_fit,
            "compliance": self.compliance,
            "readability": self.readability,
        }


def weighted_overall(
    selling_point_accuracy: int,
    channel_fit: int,
    compliance: int,
    readability: int,
) -> int:
    total = (
        WEIGHTS["selling_point_accuracy"] * selling_point_accuracy
        + WEIGHTS["channel_fit"] * channel_fit
        + WEIGHTS["compliance"] * compliance
        + WEIGHTS["readability"] * readability
    )
    return _round_half_up(total)


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def score_selling_points(text: str, facts: ExtractedFacts) -> int:
    if not facts.selling_points:
        return 0
    hits = sum(1 for point in facts.selling_points if point_hit(point, text))
    score = _round_half_up(100 * hits / len(facts.selling_points))
    folded = text.casefold()
    for item in facts.must_include:
        if item.casefold() not in folded:
            score -= 15
    return _clamp(score)


def score_channel_fit(text: str, facts: ExtractedFacts, findings: list[Finding]) -> int:
    score = 100
    count = char_count(text)
    if facts.max_chars and count > facts.max_chars:
        score -= 30
    if count < 12:
        score -= 20
    missing = sum(1 for item in findings if item.rule_id == "required_element")
    mismatches = sum(1 for item in findings if item.rule_id == "channel_mismatch")
    score -= 15 * missing
    score -= 20 * mismatches
    return _clamp(score)


def score_compliance(findings: list[Finding]) -> int:
    penalty = 0
    for finding in findings:
        if finding.rule_id not in COMPLIANCE_RULES:
            continue
        penalty += _SEVERITY_PENALTY.get(finding.severity, 0)
    return _clamp(100 - penalty)


def score_readability(text: str) -> int:
    total = char_count(text)
    if total == 0:
        return 0
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    if not parts:
        return 0
    average = total / len(parts)
    score = 100
    if average < 8:
        score -= 20
    elif average > 45:
        score -= min(40, math.ceil((average - 45) / 10.0) * 10)
    if not _PUNCT.search(text) and total > 30:
        score -= 25
    if total > 80 and "\n" not in text:
        score -= 15
    cjk = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    if len(cjk) >= 4:
        grams = [cjk[i : i + 4] for i in range(len(cjk) - 3)]
        most = Counter(grams).most_common(1)[0][1]
        if most >= 5:
            score -= 10
    return _clamp(score)


def score_text(
    text: str,
    facts: ExtractedFacts,
    findings: list[Finding] | None = None,
) -> ScoreCard:
    resolved = run_rules(text, facts) if findings is None else findings
    accuracy = score_selling_points(text, facts)
    channel_fit = score_channel_fit(text, facts, resolved)
    compliance = score_compliance(resolved)
    readability = score_readability(text)
    overall = weighted_overall(accuracy, channel_fit, compliance, readability)
    return ScoreCard(
        selling_point_accuracy=accuracy,
        channel_fit=channel_fit,
        compliance=compliance,
        readability=readability,
        overall=overall,
    )
