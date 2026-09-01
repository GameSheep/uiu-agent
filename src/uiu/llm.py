"""Thin OpenAI-compatible LLM client.

Works with any provider that exposes /chat/completions:
- OpenAI: https://api.openai.com/v1
- DeepSeek: https://api.deepseek.com/v1
- Moonshot: https://api.moonshot.cn/v1
- Ollama: http://localhost:11434/v1
- vLLM / OpenRouter / anything else
"""

from __future__ import annotations

import os
from typing import Iterator

from openai import OpenAI


def make_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY", "sk-no-key-set")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def get_model() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def stream_chat(
    client: OpenAI,
    messages: list[dict],
    tools: list[dict] | None = None,
) -> Iterator[str]:
    """Yield text deltas from a streaming chat completion. Tool calls ignored here."""
    kwargs = {
        "model": get_model(),
        "messages": messages,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content