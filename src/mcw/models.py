"""Dataclasses that cross stage boundaries. They serialize into run artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


def _take(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    names = {item.name for item in fields(cls)}
    missing = names - data.keys()
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise KeyError(f"{cls.__name__} 缺少字段: {missing_list}")
    return {name: data[name] for name in names}


@dataclass
class Brief:
    id: str
    title: str
    locale: str
    product_name: str
    category: str
    selling_points: list[str]
    claims_allowed: list[str]
    disclaimers: list[str]
    audience_segment: str
    pain_points: list[str]
    tone: str
    channel: str
    channel_label: str
    channel_format: str
    max_chars: int
    required_elements: list[str]
    conversion_goal: str
    cta: str
    must_include: list[str]
    must_avoid: list[str]
    forbidden_claims: list[str]
    regulatory_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedFacts:
    """Deterministic fact sheet. Generators may only rely on these fields."""

    brief_id: str
    title: str
    locale: str
    product_name: str
    category: str
    selling_points: list[str]
    claims_allowed: list[str]
    disclaimers: list[str]
    audience_segment: str
    pain_points: list[str]
    tone: str
    channel: str
    channel_label: str
    channel_format: str
    max_chars: int
    required_elements: list[str]
    conversion_goal: str
    cta: str
    must_include: list[str]
    must_avoid: list[str]
    forbidden_claims: list[str]
    regulatory_notes: list[str]
    fact_lines: list[str]
    extractor: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtractedFacts:
        return cls(**_take(cls, data))


@dataclass
class Draft:
    id: str
    variant: str
    angle: str
    title: str
    body: str
    channel: str
    text: str
    char_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Draft:
        return cls(**_take(cls, data))


@dataclass
class Finding:
    rule_id: str
    severity: str
    message: str
    evidence: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(**_take(cls, data))


@dataclass
class Checklist:
    draft_id: str
    passed: bool
    summary: str
    findings: list[Finding]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [item.to_dict() for item in self.findings]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checklist:
        findings = [Finding.from_dict(item) for item in data.get("findings", [])]
        return cls(
            draft_id=data["draft_id"],
            passed=bool(data["passed"]),
            summary=data["summary"],
            findings=findings,
        )


@dataclass
class Approval:
    status: str
    reviewer: str | None
    comment: str | None
    draft_id: str | None
    decided_at: str | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Approval:
        return cls(**_take(cls, data))


@dataclass
class PromptBundle:
    template_id: str
    system: str
    user: str
    angles: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
