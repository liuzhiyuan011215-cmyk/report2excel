"""多模态大模型客户端：OpenAI 兼容接口（仿 CardMaker llm/client.py）。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from .config import LLMSettings


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.calls += other.calls


class FatalLLMError(RuntimeError):
    """重试也没用的致命错误（Key 无效、权限不足、模型不存在）。"""


def explain_error(exc: Exception) -> str:
    import openai

    if isinstance(exc, openai.AuthenticationError):
        return "API Key 不正确或已失效，请重新运行 report2excel config set-key。"
    if isinstance(exc, openai.PermissionDeniedError):
        return "这个 API Key 没有调用该模型的权限，请在平台控制台检查。"
    if isinstance(exc, openai.NotFoundError):
        return "找不到这个模型或接口地址，请检查配置中的 model 和 base_url。"
    if isinstance(exc, openai.RateLimitError):
        return "请求太频繁，或额度已用完，请稍后再试。"
    if isinstance(exc, openai.APIConnectionError):
        return "连不上大模型服务，请检查网络或本地 Ollama 是否已启动。"
    return f"{type(exc).__name__}: {exc}"


class ChatModel(Protocol):
    """抽象协议：测试与内置演示可注入本地假模型。"""

    def chat(self, messages: list[dict]) -> tuple[str, Usage]: ...


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        json_mode: bool = True,
        temperature: float = 0.1,
        timeout: float = 120.0,
        extra_body: dict | None = None,
    ):
        from openai import OpenAI

        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key or "ollama",
            timeout=timeout,
            max_retries=0,  # 重试由 extractor 统一控制，避免叠加
        )
        self.model = model
        self.json_mode = json_mode
        self.temperature = temperature
        self.extra_body = extra_body or {}

    @classmethod
    def from_settings(cls, settings: LLMSettings) -> "LLMClient":
        return cls(
            settings.base_url,
            settings.api_key,
            settings.model,
            json_mode=settings.json_mode,
            temperature=settings.temperature,
            timeout=settings.timeout,
            extra_body=settings.extra_body,
        )

    def chat(self, messages: list[dict]) -> tuple[str, Usage]:
        import openai

        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError) as exc:
            raise FatalLLMError(explain_error(exc)) from exc
        content = resp.choices[0].message.content or ""
        usage = Usage(calls=1)
        if resp.usage:
            usage.prompt_tokens = resp.usage.prompt_tokens or 0
            usage.completion_tokens = resp.usage.completion_tokens or 0
        return content, usage


def parse_json_object(raw: str) -> dict:
    """从模型回复中稳健提取第一个 JSON 对象（容忍 Markdown 代码块包裹）。"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象")
    return data


def check_connection(settings: LLMSettings) -> str:
    client = LLMClient.from_settings(settings)
    content, usage = client.chat([
        {"role": "user", "content": '请只输出一个 JSON 对象：{"ok": true}'}
    ])
    parse_json_object(content)
    return f"连接成功！模型 {settings.model}（token {usage.prompt_tokens}+{usage.completion_tokens}）"
