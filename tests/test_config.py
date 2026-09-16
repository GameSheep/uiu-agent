"""Config load/save round-trip + malformed-file tolerance."""

from pathlib import Path

import pytest


def test_save_load_roundtrip(tmp_path):
    from uiu.config import AppConfig, ChannelConfig, ModelConfig, load_config, save_config
    ws = tmp_path / "ws"
    cfg = AppConfig(
        agent_name="t",
        model=ModelConfig(provider="openai", default="gpt-4o-mini"),
        channels=[ChannelConfig(type="telegram", name="tg", secret_env="TELEGRAM_BOT_TOKEN")],
    )
    save_config(ws, cfg)
    back = load_config(ws)
    assert back.model.default == "gpt-4o-mini"
    assert len(back.channels) == 1 and back.channels[0].name == "tg"


def test_config_cli_theme_and_color(tmp_path):
    """uiu config --theme / --color write tui prefs; bad input exits 2."""
    from argparse import Namespace

    from uiu.commands import cmd_config
    from uiu.config import load_config

    def args(**kw):
        base = dict(workspace=str(tmp_path), theme=None, color=None, agent_name="",
                    api_key=None, set_secret=None, unset_secret=None, list=False,
                    show_values=False)
        base.update(kw)
        return Namespace(**base)

    assert cmd_config(args(theme="uiu-neon")) == 0
    assert load_config(tmp_path).tui["theme"] == "uiu-neon"

    assert cmd_config(args(theme="nope")) == 2
    assert load_config(tmp_path).tui["theme"] == "uiu-neon"

    assert cmd_config(args(color="primary=#FF8800")) == 0
    assert load_config(tmp_path).tui["colors"]["primary"] == "#FF8800"

    assert cmd_config(args(color="bogus=#fff")) == 2
    assert cmd_config(args(color="primary=nonsense")) == 2

    assert cmd_config(args(color="primary=")) == 0
    assert "primary" not in (load_config(tmp_path).tui.get("colors") or {})


def test_malformed_yaml_raises_friendly(tmp_path):
    from uiu.config import load_config
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "config.yaml").write_text(":::bad{{\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="config.yaml"):
        load_config(ws)


def test_non_mapping_yaml_raises_friendly(tmp_path):
    from uiu.config import load_config
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "config.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="config.yaml"):
        load_config(ws)


def test_missing_config_returns_default(tmp_path):
    from uiu.config import load_config
    assert load_config(tmp_path / "none").model.default == "gpt-4o-mini"
