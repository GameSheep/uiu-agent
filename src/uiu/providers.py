"""Provider profiles — Hermes-aligned declarative provider registry.

Mirrors hermes-agent's `providers/base.py` ProviderProfile concept:
- name, api_mode, base_url, models_url, env_vars, auth_type, fallback_models
- live model fetch from {models_url or base_url}/models with fallback to curated list

Not a full port (no plugins, no OAuth, no AWS SDK) — just the config surface
that drives `uiu model`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class ProviderProfile:
    """Declarative description of an inference provider (Hermes-style)."""

    name: str                       # slug, e.g. "deepseek"
    display_name: str = ""
    api_mode: str = "chat_completions"   # chat_completions | anthropic_messages | bedrock_converse
    base_url: str = ""
    models_url: str = ""            # explicit models endpoint; falls back to {base_url}/models
    api_key_env: str = ""           # env var holding the API key
    auth_type: str = "api_key"      # api_key | oauth_device_code | none
    fallback_models: tuple = ()     # curated list shown when live fetch fails
    description: str = ""

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name

    # -- endpoints ------------------------------------------------------
    def models_endpoint(self) -> str:
        if self.models_url:
            return self.models_url
        return f"{self.base_url.rstrip('/')}/models"

    # -- model listing --------------------------------------------------
    def fetch_models(self, api_key: str = "") -> list[str]:
        """Live GET {models_endpoint} with Bearer auth; [] on any failure.
        Cached in _MODELS_CACHE; clear with `uiu model --refresh`."""
        url = self.models_endpoint()
        if not url.startswith("http"):
            return []
        cache_key = f"{self.name}:{url}"
        if cache_key in _MODELS_CACHE:
            return _MODELS_CACHE[cache_key]
        headers = {"User-Agent": "uiu/0.1"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []
        # OpenAI-compatible: {"data": [{"id": "..."}]}
        if isinstance(data, dict):
            items = data.get("data")
            if isinstance(items, list):
                out = []
                for it in items:
                    if isinstance(it, dict) and it.get("id"):
                        out.append(it["id"])
                    elif isinstance(it, str):
                        out.append(it)
                _MODELS_CACHE[cache_key] = out
                return out
        return []

    def available_models(self, api_key: str = "") -> list[str]:
        """Live fetch with curated fallback (Hermes picker behavior)."""
        live = self.fetch_models(api_key)
        return live or list(self.fallback_models)


# ---------------------------------------------------------------------------
# Registry (Hermes: plugins/model-providers/*.py; uiu: this file for now)
# ---------------------------------------------------------------------------

_PROFILES: dict[str, ProviderProfile] = {}
_MODELS_CACHE: dict[str, list[str]] = {}


def register(profile: ProviderProfile) -> None:
    _PROFILES[profile.name] = profile


def get_profile(name: str) -> ProviderProfile | None:
    return _PROFILES.get(name)


def list_profiles() -> list[ProviderProfile]:
    return list(_PROFILES.values())


def find_profile(name: str) -> ProviderProfile | None:
    """Case-insensitive lookup."""
    if name in _PROFILES:
        return _PROFILES[name]
    low = name.lower()
    for p in _PROFILES.values():
        if p.name.lower() == low or p.display_name.lower() == low:
            return p
    return None


def load_builtin_profiles() -> None:
    """Register builtin provider profiles (idempotent)."""
    if _PROFILES:
        return
    for p in _BUILTIN:
        register(p)


# ---------------------------------------------------------------------------
# Builtin profiles — the provider universe, Hermes-aligned
# ---------------------------------------------------------------------------

def _mk(name, display, base_url, key_env, models=(), desc="", api_mode="chat_completions", auth_type="api_key") -> ProviderProfile:
    return ProviderProfile(
        name=name,
        display_name=display,
        base_url=base_url,
        api_key_env=key_env,
        fallback_models=models,
        description=desc,
        api_mode=api_mode,
        auth_type=auth_type,
    )


_BUILTIN: list[ProviderProfile] = [
    _mk("openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY",
        ("gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "o3", "o4-mini"),
        "OpenAI 官方"),
    _mk("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY",
        ("deepseek-chat", "deepseek-reasoner"),
        "便宜、中文好"),
    _mk("moonshot", "Moonshot (Kimi)", "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY",
        ("moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-latest"),
        "Kimi，长上下文"),
    _mk("qwen", "Qwen (通义千问)", "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY",
        ("qwen-plus", "qwen-turbo", "qwen-max"),
        "阿里，OpenAI 兼容"),
    _mk("ollama", "Ollama (本地)", "http://localhost:11434/v1", "",
        ("qwen2.5:7b", "llama3.1:8b", "mistral:7b", "deepseek-r1:7b"),
        "本地免费，不需要 key", auth_type="none"),
    _mk("vllm", "vLLM (本地)", "http://localhost:8000/v1", "",
        ("Qwen/Qwen2.5-7B-Instruct", "meta-llama/Llama-3.1-8B-Instruct"),
        "本地推理服务，OpenAI 兼容", auth_type="none"),
    _mk("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
        ("openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat"),
        "一个 key 用多家模型"),
    _mk("siliconflow", "SiliconFlow (硅基流动)", "https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY",
        ("deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-7B-Instruct"),
        "国内镜像，注册送额度"),
    _mk("custom", "自定义", "", "",
        (),
        "手动填 base_url / key / model"),
]


# convenience: keep the old module-level API working
def find(name: str) -> ProviderProfile | None:
    load_builtin_profiles()
    return find_profile(name)


def choices() -> list[str]:
    load_builtin_profiles()
    return [f"{p.display_name}  ({p.description})" for p in list_profiles()]


def PROVIDERS() -> list[ProviderProfile]:
    load_builtin_profiles()
    return list_profiles()