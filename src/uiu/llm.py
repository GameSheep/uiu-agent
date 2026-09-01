"""LLM client — Hermes-aligned: dispatches on ModelConfig.api_mode.

- chat_completions  -> openai SDK (OpenAI-compatible: openai, deepseek, kimi, ollama, …)
- anthropic_messages -> anthropic SDK (native Claude Messages API)
- bedrock_converse  -> not yet supported (needs boto3)
"""

from __future__ import annotations

import os
from typing import Iterator

from .config import ModelConfig


def make_client(cfg: ModelConfig | None = None):
    cfg = cfg or _env_model_config()
    if cfg.api_mode == "anthropic_messages":
        from anthropic import Anthropic
        api_key = cfg.resolved_api_key() or os.environ.get("ANTHROPIC_API_KEY", "sk-no-key-set")
        return Anthropic(api_key=api_key)
    from openai import OpenAI
    api_key = cfg.resolved_api_key() or "sk-no-key-set"
    base_url = _effective_base_url(cfg)
    return OpenAI(api_key=api_key, base_url=base_url)


def _effective_base_url(cfg: ModelConfig) -> str:
    if cfg.base_url:
        return cfg.base_url
    try:
        from .providers import get_profile
        prof = get_profile(cfg.provider)
        if prof and prof.base_url:
            return prof.base_url
    except Exception:
        pass
    return "https://api.openai.com/v1"


def _env_model_config() -> ModelConfig:
    """Fallback when no ModelConfig passed — build from env (legacy path)."""
    return ModelConfig(
        provider=os.environ.get("UIU_PROVIDER", "openai"),
        default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        base_url=os.environ.get("OPENAI_BASE_URL", ""),
        api_key_env=os.environ.get("UIU_API_KEY_ENV", "OPENAI_API_KEY"),
    )


def get_model(cfg: ModelConfig | None = None) -> str:
    if cfg is not None:
        return cfg.default
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def _create(client, cfg: ModelConfig, **kwargs):
    """Call the right SDK create() based on api_mode. Returns a response with
    `.choices[0].message.content` (openai) or `.content[0].text` (anthropic)."""
    if cfg.api_mode == "anthropic_messages":
        resp = client.messages.create(
            model=cfg.default,
            messages=_to_anthropic_messages(kwargs.pop("messages")),
            max_tokens=cfg.max_tokens or 4096,
            **kwargs,
        )
        # normalize to a .choices[0].message.content-like shape
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return _AnthropicResp(text)
    return client.chat.completions.create(**kwargs)


class _AnthropicResp:
    """Minimal adapter: exposes .choices[0].message.content like OpenAI SDK."""
    def __init__(self, text: str):
        self._text = text
        self.choices = [_Choice(_Msg(text))]


class _Choice:
    def __init__(self, msg):
        self.message = msg


class _Msg:
    def __init__(self, text: str):
        self.content = text
        self.tool_calls = None


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-format messages to Anthropic format (system excluded)."""
    out = []
    for m in messages:
        if m.get("role") == "system":
            continue  # anthropic takes system separately
        role = "assistant" if m.get("role") == "assistant" else "user"
        content = m.get("content") or ""
        out.append({"role": role, "content": content})
    return out


def stream_chat(
    client,
    messages: list[dict],
    tools: list[dict] | None = None,
    cfg: ModelConfig | None = None,
) -> Iterator[str]:
    """Yield text deltas from a streaming chat completion. Tool calls ignored here."""
    cfg = cfg or _env_model_config()
    if cfg.api_mode == "anthropic_messages":
        sys_msgs = [m["content"] for m in messages if m.get("role") == "system"]
        user_msgs = [m for m in messages if m.get("role") != "system"]
        system = "\n\n".join(sys_msgs) or None
        stream = client.messages.stream(
            model=cfg.default,
            system=system,
            messages=_to_anthropic_messages(user_msgs),
            max_tokens=cfg.max_tokens or 4096,
        )
        with stream as s:
            for text in s.text_stream:
                yield text
        return

    from openai import OpenAI
    kwargs = {
        "model": get_model(cfg),
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