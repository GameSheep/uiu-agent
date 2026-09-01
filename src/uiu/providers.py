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


# ---------------------------------------------------------------------------
# Builtin profiles — mirrored from hermes-agent plugins/model-providers/
# (extracted 2026-08; base_url/env_vars/fallback_models/api_mode/auth_type
#  match the upstream ProviderProfile declarations)
# ---------------------------------------------------------------------------

_BUILTIN: list[ProviderProfile] = [
    # -- OpenAI-compatible, api_key -------------------------------
    _mk("openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY",
        ("gpt-5.4", "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "o4-mini"),
        "OpenAI 官方"),
    _mk("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY",
        ("deepseek-v4-pro", "deepseek-v4-flash"),
        "DeepSeek — native DeepSeek API"),
    _mk("moonshot", "Moonshot (Kimi)", "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY",
        ("kimi-latest", "moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k"),
        "Kimi，长上下文"),
    _mk("qwen", "Qwen (通义千问)", "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY",
        ("qwen-max", "qwen-plus", "qwen-turbo"),
        "阿里，OpenAI 兼容"),
    _mk("alibaba", "Alibaba Cloud (Token Plan, China)", "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", "ALIBABA_TOKEN_PLAN_API_KEY",
        (), "阿里云百炼 Token Plan（大陆）"),
    _mk("alibaba-coding-plan", "Alibaba Cloud (Coding Plan, China)", "https://coding.dashscope.aliyuncs.com/v1", "ALIBABA_CODING_PLAN_API_KEY",
        (), "阿里云 Coding Plan（大陆）"),
    _mk("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
        ("anthropic/claude-sonnet-4.6", "openai/gpt-5.4", "deepseek/deepseek-chat", "google/gemini-3.7-flash", "qwen/qwen3-plus"),
        "一个 key 用 200+ 模型"),
    _mk("siliconflow", "SiliconFlow (硅基流动)", "https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY",
        ("deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-7B-Instruct"),
        "国内镜像，注册送额度"),
    _mk("deepinfra", "DeepInfra", "https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY",
        (), "100+ open models，按量付费"),
    _mk("fireworks", "Fireworks AI", "https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY",
        ("accounts/fireworks/models/kimi-k2p6", "accounts/fireworks/models/glm-5p2"),
        "OpenAI-compatible 直连"),
    _mk("huggingface", "HuggingFace", "https://router.huggingface.co/v1", "HF_TOKEN",
        ("Qwen/Qwen3.5-72B-Instruct", "deepseek-ai/DeepSeek-V3.2"),
        "HuggingFace Inference API"),
    _mk("gmi", "GMI Cloud", "https://api.gmi-serving.com/v1", "GMI_API_KEY",
        ("zai-org/GLM-5.1-FP8", "deepseek-ai/DeepSeek-V3.2", "moonshotai/Kimi-K2.5", "google/gemini-3.1-flash-lite-preview", "anthropic/claude-sonnet-5"),
        "多模型直连（slash-form model IDs）"),
    _mk("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY",
        ("nvidia/llama-3.1-nemotron-70b-instruct", "nvidia/llama-3.3-70b-instruct"),
        "NVIDIA 加速推理"),
    _mk("novita", "NovitaAI", "https://api.novita.ai/openai/v1", "NOVITA_API_KEY",
        ("moonshotai/kimi-k2.5", "minimax/minimax-m2.7", "zai-org/glm-5", "deepseek/deepseek-v3-0324"),
        "AI-native 云"),
    _mk("nebius", "Nebius Token Factory", "https://api.tokenfactory.nebius.com/v1", "NEBIUS_API_KEY",
        ("Qwen/Qwen3.5-397B-A17B-fast", "deepseek-ai/DeepSeek-V4-Pro", "zai-org/GLM-5.1", "moonshotai/Kimi-K2.5-fast", "NousResearch/Hermes-4-70B"),
        "OpenAI-compatible 推理"),
    _mk("arcee", "Arcee", "https://api.arcee.ai/api/v1", "ARCEEAI_API_KEY",
        (), ""),
    _mk("kilocode", "KiloCode", "https://api.kilo.ai/api/gateway", "KILOCODE_API_KEY",
        (), ""),
    _mk("stepfun", "StepFun (阶跃星辰)", "https://api.stepfun.ai/step_plan/v1", "STEPFUN_API_KEY",
        (), ""),
    _mk("upstage", "Upstage Solar", "https://api.upstage.ai/v1", "UPSTAGE_API_KEY",
        ("solar-pro3",), "Upstage Solar API"),
    _mk("xiaomi", "Xiaomi MiMo", "https://api.xiaomimimo.com/v1", "XIAOMI_API_KEY",
        (), ""),
    _mk("zai", "Z.AI (GLM 智谱)", "https://api.z.ai/api/paas/v4", "GLM_API_KEY",
        ("glm-5.2", "glm-5", "glm-4-9b"), "GLM 智谱模型"),
    _mk("xai", "xAI (Grok)", "https://api.x.ai/v1", "XAI_API_KEY",
        (), "Grok"),
    _mk("ollama-cloud", "Ollama Cloud", "https://ollama.com/v1", "OLLAMA_API_KEY",
        (), "Ollama 云端"),
    _mk("ai-gateway", "AI Gateway", "https://ai-gateway.vercel.sh/v1", "AI_GATEWAY_API_KEY",
        (), ""),
    _mk("opencode-free", "OpenCode Free", "https://opencode.ai/zen/v1", "",
        (), "keyless，免账号", auth_type="none"),
    _mk("opencode-zen", "OpenCode Zen", "https://opencode.ai/zen/go/v1", "OPENCODE_GO_API_KEY",
        (), ""),

    # -- Anthropic Messages API (x-api-key) ------------------------
    _mk("anthropic", "Anthropic (Claude)", "https://api.anthropic.com", "ANTHROPIC_API_KEY",
        ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"),
        "Claude 官方，原生 Messages API", api_mode="anthropic_messages"),
    _mk("commandcode", "CommandCode (Anthropic)", "", "ANTHROPIC_API_KEY",
        ("claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"),
        "Claude via Anthropic Messages API", api_mode="anthropic_messages"),

    # -- local, no key --------------------------------------------
    _mk("ollama", "Ollama (本地)", "http://localhost:11434/v1", "",
        ("qwen2.5:7b", "llama3.1:8b", "mistral:7b", "deepseek-r1:7b"),
        "本地免费，不需要 key", auth_type="none"),
    _mk("vllm", "vLLM (本地)", "http://localhost:8000/v1", "",
        ("Qwen/Qwen2.5-7B-Instruct", "meta-llama/Llama-3.1-8B-Instruct"),
        "本地推理服务，OpenAI 兼容", auth_type="none"),

    # -- needs special auth (OAuth / aws / codex) — listed but marked ---
    _mk("nous", "Nous Research", "https://inference-api.nousresearch.com/v1", "NOUS_API_KEY",
        ("hermes-3-405b", "hermes-3-70b"), "Hermes 模型家族"),
    _mk("gemini", "Gemini (Google)", "https://generativelanguage.googleapis.com/v1beta", "GOOGLE_API_KEY",
        (), "Google Gemini", auth_type="api_key"),
    _mk("azure-foundry", "Azure Foundry", "", "AZURE_FOUNDRY_API_KEY",
        (), "Microsoft Foundry，用户提供 base URL"),
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