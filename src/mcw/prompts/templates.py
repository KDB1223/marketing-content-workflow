"""Prompt templates recorded with every run so the wording is auditable."""

from __future__ import annotations

from mcw.models import ExtractedFacts, PromptBundle

TEMPLATE_ID = "prompt-template-v1"

ANGLES = ["痛点切入", "卖点清单", "场景故事", "澄清边界", "行动收束"]

SYSTEM_PROMPT = """你是一名严谨的中文营销文案编辑，正在执行可审计的写作任务。
只使用「事实清单」里已经给出的产品事实，不得新增功效、数据、荣誉、价格或用户评价。
不得使用绝对化用语，例如：最、第一、唯一、绝对、100%、国家级。
如果事实清单包含声明，文案末尾必须原样附上声明，并以「【声明】」开头。
按渠道控制篇幅，不超过给定字数（字数不计空白）。
只输出 JSON 对象，不要 Markdown。格式：
{"drafts":[{"angle":"角度名","title":"标题","body":"正文"}]}
drafts 的数量必须等于要求的变体数，angle 使用给定角度名。"""


def build_prompts(
    facts: ExtractedFacts,
    *,
    n: int,
    revision_note: str | None = None,
) -> PromptBundle:
    angles = ANGLES[:n]
    fact_block = "\n".join(f"- {line}" for line in facts.fact_lines)
    elements = "、".join(facts.required_elements) if facts.required_elements else "无额外组件"
    user = (
        f"请基于下列事实清单写 {n} 条{facts.channel_label}文案。\n"
        f"渠道形态：{facts.channel_format}\n"
        f"字数上限（不计空白）：{facts.max_chars}\n"
        f"语气：{facts.tone}\n"
        f"必要组件：{elements}\n"
        f"转化目标：{facts.conversion_goal}\n"
        f"行动号召（请原句出现）：{facts.cta}\n"
        f"角度：{'、'.join(angles)}\n\n"
        f"事实清单：\n{fact_block}\n\n"
        "每条变体都要覆盖全部卖点原句。卖点里没有的功效不要写。"
    )
    if revision_note:
        user += f"\n审阅意见（只调整表达，不能新增事实）：{revision_note.strip()}"
    return PromptBundle(
        template_id=TEMPLATE_ID,
        system=SYSTEM_PROMPT,
        user=user,
        angles=angles,
    )
