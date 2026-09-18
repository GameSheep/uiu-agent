"""单点的路径解析（审计 §2.4）。

以前 `Path.home() / ".uiu" / ...` 散落在 10 个模块里，导致：

- 容器 / 受限环境 / 多用户机器上无法重定向（家目录不可写就直接失败）；
- 想改一处布局要改十处，且总有人漏改（本仓库就漏过：daemon 支持 UIU_HOME，
  但 plugins/channels/memory_vectors 各自硬编码）。

现在统一走这里：**`UIU_HOME` 覆盖优先，否则 `~/.uiu`**。任何新代码都不该再拼 home。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["uiu_home", "home_workspace", "plugins_dir", "providers_plugins_dir",
           "channels_dir", "memory_vectors_dir", "daemon_state_dir"]


def uiu_home() -> Path:
    """uiu 的用户级目录（不创建）。`UIU_HOME` 优先。"""
    override = os.environ.get("UIU_HOME", "").strip()
    return Path(override) if override else Path.home() / ".uiu"


def home_workspace() -> Path:
    """用户级默认 workspace（`uiu init` 没给路径时）。"""
    return uiu_home() / "workspace"


def plugins_dir() -> Path:
    """用户插件目录（channel 适配器等）。"""
    return uiu_home() / "plugins"


def providers_plugins_dir() -> Path:
    """自定义 model provider 插件目录（Hermes 风格）。"""
    return plugins_dir() / "model-providers"


def channels_dir() -> Path:
    """用户自定义 channel 适配器目录。"""
    return uiu_home() / "channels"


def memory_vectors_dir() -> Path:
    """RAG 向量库落地目录。"""
    return uiu_home() / "memory_vectors"


def daemon_state_dir(create: bool = True) -> Path:
    """后台守护进程的状态目录（pid / log / autostart 脚本）。"""
    d = uiu_home()
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d
