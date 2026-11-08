"""Brief loader. YAML and JSON share one normalized schema."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from mcw.errors import MCWError
from mcw.models import Brief

CHANNEL_ALIASES = {
    "xiaohongshu": "xiaohongshu",
    "xhs": "xiaohongshu",
    "小红书": "xiaohongshu",
    "wechat": "wechat",
    "weixin": "wechat",
    "微信": "wechat",
    "微信公众号": "wechat",
    "公众号": "wechat",
    "douyin": "douyin",
    "抖音": "douyin",
    "official_site": "official_site",
    "official": "official_site",
    "官网": "official_site",
    "ecommerce": "ecommerce",
    "电商": "ecommerce",
    "电商详情": "ecommerce",
    "weibo": "weibo",
    "微博": "weibo",
}

CHANNEL_LABELS = {
    "xiaohongshu": "小红书",
    "wechat": "微信公众号",
    "douyin": "抖音",
    "official_site": "官网",
    "ecommerce": "电商详情",
    "weibo": "微博",
}

DEFAULT_ELEMENTS = {
    "xiaohongshu": ["标题", "正文", "话题标签"],
    "wechat": ["标题", "正文", "行动号召"],
    "douyin": ["钩子", "正文", "话题标签"],
    "official_site": ["标题", "正文", "声明"],
    "ecommerce": ["标题", "卖点", "声明"],
    "weibo": ["正文", "话题标签"],
}


class BriefValidationError(MCWError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        detail = "\n".join(f"- {item}" for item in errors)
        super().__init__(f"Brief 校验失败:\n{detail}")


def load_brief(path: str | Path) -> Brief:
    file_path = Path(path)
    if not file_path.is_file():
        raise MCWError(f"找不到 Brief 文件: {file_path}")
    raw_text = file_path.read_text(encoding="utf-8")
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".json":
            data = json.loads(raw_text)
        elif suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(raw_text)
        else:
            raise MCWError("Brief 只支持 .yaml、.yml 或 .json")
    except json.JSONDecodeError as exc:
        raise BriefValidationError([f"JSON 无法解析: {exc}"]) from exc
    except yaml.YAMLError as exc:
        raise BriefValidationError([f"YAML 无法解析: {exc}"]) from exc
    if not isinstance(data, dict):
        raise BriefValidationError(["根节点必须是对象"])
    return parse_brief(data)


def parse_brief(data: dict[str, Any]) -> Brief:
    errors: list[str] = []

    def require_text(container: dict[str, Any], key: str, label: str) -> str:
        value = container.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label} 必须是非空字符串")
            return ""
        return value.strip()

    def optional_str_list(container: dict[str, Any], key: str, label: str) -> list[str]:
        if key not in container or container[key] is None:
            return []
        value = container[key]
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"{label} 必须是非空字符串组成的数组")
            return []
        return [item.strip() for item in value]

    brief_id = require_text(data, "id", "id")
    title = require_text(data, "title", "title")
    locale = require_text(data, "locale", "locale")

    product = data.get("product")
    audience = data.get("audience")
    channel = data.get("channel")
    conversion = data.get("conversion")
    constraints = data.get("constraints") or {}
    if not isinstance(product, dict):
        errors.append("product 必须是对象")
        product = {}
    if not isinstance(audience, dict):
        errors.append("audience 必须是对象")
        audience = {}
    if not isinstance(channel, dict):
        errors.append("channel 必须是对象")
        channel = {}
    if not isinstance(conversion, dict):
        errors.append("conversion 必须是对象")
        conversion = {}
    if not isinstance(constraints, dict):
        errors.append("constraints 必须是对象")
        constraints = {}

    product_name = require_text(product, "name", "product.name")
    category = product.get("category", "")
    if category is None:
        category = ""
    if not isinstance(category, str):
        errors.append("product.category 必须是字符串")
        category = ""
    selling_points = optional_str_list(product, "selling_points", "product.selling_points")
    if isinstance(product.get("selling_points"), list) and len(selling_points) == 0 and not any(
        item.startswith("product.selling_points") for item in errors
    ):
        errors.append("product.selling_points 至少需要一条卖点")
    if "selling_points" not in product:
        errors.append("缺少 product.selling_points")

    claims_allowed = optional_str_list(product, "claims_allowed", "product.claims_allowed")
    disclaimers = optional_str_list(product, "disclaimers", "product.disclaimers")

    audience_segment = require_text(audience, "segment", "audience.segment")
    tone = require_text(audience, "tone", "audience.tone")
    pain_points = optional_str_list(audience, "pain_points", "audience.pain_points")

    raw_channel = channel.get("name")
    canonical = ""
    if not isinstance(raw_channel, str) or not raw_channel.strip():
        errors.append("channel.name 必须是非空字符串")
    else:
        canonical = CHANNEL_ALIASES.get(raw_channel.strip()) or CHANNEL_ALIASES.get(raw_channel.strip().lower(), "")
        if not canonical:
            known = "、".join(sorted(set(CHANNEL_ALIASES)))
            errors.append(f"channel.name 无法识别: {raw_channel}。可选: {known}")

    channel_format = require_text(channel, "format", "channel.format")
    max_chars_raw = channel.get("max_chars")
    max_chars = 0
    if isinstance(max_chars_raw, bool) or not isinstance(max_chars_raw, int) or max_chars_raw <= 0:
        errors.append("channel.max_chars 必须是正整数")
    else:
        max_chars = max_chars_raw

    if "required_elements" in channel and channel["required_elements"] is not None:
        required_elements = optional_str_list(channel, "required_elements", "channel.required_elements")
    elif canonical:
        required_elements = list(DEFAULT_ELEMENTS[canonical])
    else:
        required_elements = []

    conversion_goal = require_text(conversion, "goal", "conversion.goal")
    cta = require_text(conversion, "cta", "conversion.cta")

    must_include = optional_str_list(constraints, "must_include", "constraints.must_include")
    must_avoid = optional_str_list(constraints, "must_avoid", "constraints.must_avoid")
    forbidden_claims = optional_str_list(constraints, "forbidden_claims", "constraints.forbidden_claims")
    regulatory_notes = optional_str_list(constraints, "regulatory_notes", "constraints.regulatory_notes")

    if errors:
        raise BriefValidationError(errors)

    return Brief(
        id=brief_id,
        title=title,
        locale=locale,
        product_name=product_name,
        category=category.strip(),
        selling_points=selling_points,
        claims_allowed=claims_allowed,
        disclaimers=disclaimers,
        audience_segment=audience_segment,
        pain_points=pain_points,
        tone=tone,
        channel=canonical,
        channel_label=CHANNEL_LABELS[canonical],
        channel_format=channel_format,
        max_chars=max_chars,
        required_elements=required_elements,
        conversion_goal=conversion_goal,
        cta=cta,
        must_include=must_include,
        must_avoid=must_avoid,
        forbidden_claims=forbidden_claims,
        regulatory_notes=regulatory_notes,
    )


def brief_fingerprint(brief: Brief) -> str:
    payload = json.dumps(brief.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
