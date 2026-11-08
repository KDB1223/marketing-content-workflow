"""OpenAI-compatible chat client. Used only when MCW_LLM_API_KEY is set."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from mcw.errors import MCWError
from mcw.llm.mock import split_text
from mcw.models import Draft, ExtractedFacts, PromptBundle
from mcw.textutil import char_count

Transport = Callable[[str, bytes, dict[str, str], float], bytes]

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


class OpenAICompatGenerator:
    """POST ``{base_url}/chat/completions`` and require a JSON drafts array.

    The API key stays in the Authorization header. It is not written into
    prompts or run artifacts.
    """

    name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
        transport: Transport | None = None,
    ):
        if not api_key or not api_key.strip():
            raise MCWError("未设置 MCW_LLM_API_KEY。离线运行请加 --mock。")
        if not base_url or not base_url.strip():
            raise MCWError("MCW_LLM_BASE_URL 不能为空")
        if not model or not model.strip():
            raise MCWError("MCW_LLM_MODEL 不能为空")
        self.api_key = api_key.strip()
        self.base_url = base_url.strip().rstrip("/")
        self.model = model.strip()
        self.timeout = timeout
        self._transport = transport or urllib_transport

    def generate(
        self,
        facts: ExtractedFacts,
        prompts: PromptBundle,
        *,
        version: str,
        n: int,
        revision_note: str | None,
    ) -> list[Draft]:
        del facts, revision_note  # revision is already inside prompts.user
        content = self.complete(prompts.system, prompts.user)
        data = parse_model_json(content)
        raw_drafts = data.get("drafts")
        if not isinstance(raw_drafts, list) or len(raw_drafts) < n:
            raise MCWError("模型输出缺少足够的 drafts 数组")
        drafts: list[Draft] = []
        for index, item in enumerate(raw_drafts[:n]):
            if not isinstance(item, dict):
                raise MCWError(f"第 {index + 1} 条草稿不是对象")
            title = str(item.get("title", "")).strip()
            body = str(item.get("body", "")).strip()
            if not title or not body:
                raise MCWError(f"第 {index + 1} 条草稿缺少 title 或 body")
            angle = str(item.get("angle") or prompts.angles[index]).strip()
            text = f"{title}\n\n{body}\n"
            parsed_title, parsed_body = split_text(text)
            letter = chr(ord("A") + index)
            drafts.append(
                Draft(
                    id=f"{version}-{letter.lower()}",
                    variant=letter,
                    angle=angle,
                    title=parsed_title,
                    body=parsed_body,
                    channel="",
                    text=text,
                    char_count=char_count(text),
                )
            )
        # Channel is part of the audit record. Fill it from the prompt facts via caller
        # by patching after return if empty. Set it here when the body of prompts is
        # not a reliable source: the pipeline overwrites channel from facts.
        return drafts

    def complete(self, system: str, user: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = self.base_url + "/chat/completions"
        raw = self._transport(url, body, headers, self.timeout)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MCWError("LLM 响应不是 JSON") from exc
        try:
            return str(parsed["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise MCWError("LLM 响应缺少 choices[0].message.content") from exc


def urllib_transport(url: str, data: bytes, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise MCWError(f"LLM 请求失败 HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise MCWError(f"LLM 请求失败: {exc.reason}") from exc


def parse_model_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MCWError(f"模型输出不是 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise MCWError("模型输出 JSON 必须是对象")
    return data
