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
