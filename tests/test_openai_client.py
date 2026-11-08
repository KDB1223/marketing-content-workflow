from __future__ import annotations

import json

import pytest

from mcw.errors import MCWError
from mcw.llm.openai_compat import OpenAICompatGenerator, parse_model_json
from mcw.models import PromptBundle
from mcw.stages.extract import extract
from mcw.schema import load_brief


def test_parse_fenced_json() -> None:
    payload = parse_model_json(
        '```json\n{"drafts":[{"title":"甲","body":"乙"}]}\n```'
    )
    assert payload["drafts"][0]["title"] == "甲"


def test_client_posts_chat_completions_without_storing_the_key(briefs_dir) -> None:
    seen: dict[str, object] = {}

    def transport(url: str, data: bytes, headers: dict[str, str], timeout: float) -> bytes:
        seen["url"] = url
        seen["headers"] = headers
        seen["body"] = json.loads(data.decode("utf-8"))
        seen["timeout"] = timeout
        content = {
            "drafts": [
                {"angle": "痛点切入", "title": "标题甲", "body": "正文甲。"},
                {"angle": "卖点清单", "title": "标题乙", "body": "正文乙。"},
            ]
        }
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}
        ).encode("utf-8")

    generator = OpenAICompatGenerator(
        api_key="sk-test-secret",
        base_url="https://example.invalid/v1",
        model="demo-model",
        transport=transport,
    )
    brief = load_brief(briefs_dir / "coffee-wechat.yaml")
    facts = extract(brief)
    prompts = PromptBundle(template_id="prompt-template-v1", system="系统", user="用户", angles=["痛点切入", "卖点清单"])
    drafts = generator.generate(facts, prompts, version="v1", n=2, revision_note=None)
    assert seen["url"] == "https://example.invalid/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-test-secret"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "demo-model"
    assert body["temperature"] == 0
    assert "sk-test-secret" not in json.dumps(body, ensure_ascii=False)
    assert [draft.title for draft in drafts] == ["标题甲", "标题乙"]
    assert drafts[0].id == "v1-a"


def test_missing_api_key() -> None:
    with pytest.raises(MCWError, match="MCW_LLM_API_KEY"):
        OpenAICompatGenerator(api_key="  ")


def test_non_json_model_output(briefs_dir) -> None:
    def transport(url: str, data: bytes, headers: dict[str, str], timeout: float) -> bytes:
        del url, data, headers, timeout
        return json.dumps({"choices": [{"message": {"content": "不是 JSON"}}]}).encode("utf-8")

    generator = OpenAICompatGenerator(api_key="sk-test", transport=transport)
    prompts = PromptBundle(template_id="t", system="s", user="u", angles=["痛点切入"])
    facts = extract(load_brief(briefs_dir / "coffee-wechat.yaml"))
    with pytest.raises(MCWError, match="不是 JSON"):
        generator.generate(facts, prompts, version="v1", n=1, revision_note=None)
