"""Known LLM providers presets — makes 'uiu model' a pick-from-menu experience.

Add your own by editing config.yaml directly or using `uiu model` custom option.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class ProviderPreset:
    name: str
    base_url: str
    api_key_env: str
    default_model: str
    models: list[str]
    note: str = ""


PROVIDERS: list[ProviderPreset] = [
    ProviderPreset(
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        models=["gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "o3", "o4-mini"],
        note="OpenAI 官方",
    ),
    ProviderPreset(
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-chat",
        models=["deepseek-chat", "deepseek-reasoner"],
        note="便宜、中文好，OpenAI 兼容",
    ),
    ProviderPreset(
        name="Moonshot (Kimi)",
        base_url="https://api.moonshot.cn/v1",
        api_key_env="MOONSHOT_API_KEY",
        default_model="moonshot-v1-8k",
        models=["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-latest"],
        note="Kimi，长上下文",
    ),
    ProviderPreset(
        name="Qwen (通义千问)",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_model="qwen-plus",
        models=["qwen-plus", "qwen-turbo", "qwen-max"],
        note="阿里，OpenAI 兼容",
    ),
    ProviderPreset(
        name="Ollama (本地)",
        base_url="http://localhost:11434/v1",
        api_key_env="OLLAMA_API_KEY",
        default_model="qwen2.5:7b",
        models=["qwen2.5:7b", "llama3.1:8b", "mistral:7b", "deepseek-r1:7b"],
        note="本地免费，不需要 key（填随便什么）",
    ),
    ProviderPreset(
        name="vLLM (本地)",
        base_url="http://localhost:8000/v1",
        api_key_env="VLLM_API_KEY",
        default_model="Qwen/Qwen2.5-7B-Instruct",
        models=["Qwen/Qwen2.5-7B-Instruct", "meta-llama/Llama-3.1-8B-Instruct"],
        note="本地推理服务，OpenAI 兼容",
    ),
    ProviderPreset(
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="openai/gpt-4o-mini",
        models=["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat"],
        note="一个 key 用多家模型",
    ),
    ProviderPreset(
        name="SiliconFlow (硅基流动)",
        base_url="https://api.siliconflow.cn/v1",
        api_key_env="SILICONFLOW_API_KEY",
        default_model="deepseek-ai/DeepSeek-V3",
        models=["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-7B-Instruct"],
        note="国内镜像，注册送额度",
    ),
    ProviderPreset(
        name="自定义",
        base_url="",
        api_key_env="CUSTOM_API_KEY",
        default_model="",
        models=[],
        note="手动填 base_url / key / model",
    ),
]


def find(name: str) -> ProviderPreset | None:
    for p in PROVIDERS:
        if p.name.lower() == name.lower():
            return p
    return None


def choices() -> list[str]:
    return [f"{p.name}  ({p.note})" for p in PROVIDERS]