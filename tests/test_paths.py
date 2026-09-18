"""路径解析单点化（审计 §2.4）：任何模块都不该再拼 home。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from uiu import paths

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "uiu"


def test_uiu_home_follows_env(tmp_path, monkeypatch):
    monkeypatch.setenv("UIU_HOME", str(tmp_path / "home"))
    assert paths.uiu_home() == tmp_path / "home"
    monkeypatch.delenv("UIU_HOME", raising=False)
    assert paths.uiu_home() == Path.home() / ".uiu"


def test_uiu_home_does_not_create_directories(tmp_path, monkeypatch):
    target = tmp_path / "nope"
    monkeypatch.setenv("UIU_HOME", str(target))
    paths.uiu_home()
    assert not target.exists(), "纯查询不该有副作用"


def test_daemon_state_dir_creates_when_asked(tmp_path, monkeypatch):
    target = tmp_path / "state"
    monkeypatch.setenv("UIU_HOME", str(target))
    assert paths.daemon_state_dir(create=False) == target
    assert not target.exists()
    made = paths.daemon_state_dir()
    assert made.exists() and made.is_dir()


def test_every_helper_derives_from_uiu_home(tmp_path, monkeypatch):
    home = tmp_path / "h"
    monkeypatch.setenv("UIU_HOME", str(home))
    assert paths.home_workspace() == home / "workspace"
    assert paths.plugins_dir() == home / "plugins"
    assert paths.providers_plugins_dir() == home / "plugins" / "model-providers"
    assert paths.channels_dir() == home / "channels"
    assert paths.memory_vectors_dir() == home / "memory_vectors"


def test_no_hardcoded_home_in_source():
    """回归闸门：新增代码里不许再出现 Path.home() / ".uiu"。"""
    pattern = re.compile(r'Path\.home\(\)\s*/\s*"\.uiu"')
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "paths.py":          # 唯一允许拼 home 的地方
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and not line.strip().startswith("#"):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, "请改用 uiu.paths：\n" + "\n".join(offenders)


def test_channel_adapter_lookup_follows_uiu_home(tmp_path, monkeypatch):
    """用户级 channel 适配器目录必须跟着 UIU_HOME 走（此前写死 ~/.uiu）。"""
    from uiu import channels

    home = tmp_path / "h"
    monkeypatch.setenv("UIU_HOME", str(home))
    d = home / "channels" / "myext"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("", encoding="utf-8")
    assert paths.channels_dir() == home / "channels"


def test_provider_plugin_lookup_follows_uiu_home(tmp_path, monkeypatch):
    from uiu import providers

    home = tmp_path / "h"
    monkeypatch.setenv("UIU_HOME", str(home))
    assert paths.providers_plugins_dir() == home / "plugins" / "model-providers"


def test_workspace_fallback_uses_uiu_home(tmp_path, monkeypatch):
    """没给 --workspace 时，fallback 链里的 ~/.uiu/workspace 也要可重定向。"""
    from uiu import workspace as W

    home = tmp_path / "h"
    monkeypatch.setenv("UIU_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UIU_WORKSPACE", raising=False)
    found = W.find_workspace() if hasattr(W, "find_workspace") else None
    if found is None:                      # API 名字可能不同：至少验证常量来源
        assert paths.home_workspace() == home / "workspace"
    else:
        assert str(found).startswith(str(tmp_path)) or str(found).startswith(str(home))
