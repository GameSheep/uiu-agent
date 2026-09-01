"""LLM client — reads from ModelConfig (Hermes-aligned: provider/default/base_url/api_mode).

For chat_completions (default) and anthropic_messages we use the OpenAI-compatible
SDK pointed at the configured base_url; providers expose /chat/completions for
both. bedrock_converse is not yet supported by the SDK transport here.
"""

from __future__ import annotations

import os
from typing import Iterator

from openai import OpenAI

from .config import ModelConfig


def make_client(cfg: ModelConfig | None = None) -> OpenAI:
    cfg = cfg or _env_model_config()
    api_key = cfg.resolved_api_key() or "sk-no-key-set"
    base_url = _effective_base_url(cfg)
    return OpenAI(api_key=api_key, base_url=base_url)


def _effective_base_url(cfg: ModelConfig) -> str:
    if cfg.base_url:
        return cfg.base_url
    # fall back to provider profile default
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


def stream_chat(
    client: OpenAI,
    messages: list[dict],
    tools: list[dict] | None = None,
    cfg: ModelConfig | None = None,
) -> Iterator[str]:
    """Yield text deltas from a streaming chat completion. Tool calls ignored here."""
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