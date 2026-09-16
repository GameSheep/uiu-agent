"""Doctor — diagnose & fix uiu configuration (OpenClaw-style, minimal)."""

import os
from pathlib import Path


def _ws(tmp_cwd) -> Path:
    p = tmp_cwd / "workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_lint_clean_workspace_ok(tmp_cwd):
    """完整 workspace + 本地 provider(无需 key) → 无 error。"""
    from uiu.config import ensure_workspace, AppConfig, save_config
    root = _ws(tmp_cwd)
    ensure_workspace(root)
    cfg = AppConfig()
    cfg.model.provider = "ollama"
    cfg.model.api_mode = "chat_completions"
    save_config(root, cfg)
    from uiu.doctor import _all_checks
    items = _all_checks(root)
    errs = [f for f in items if f.severity == "error"]
    assert errs == [], [f.message for f in items]


def test_flags_bad_tui_theme_and_colors(tmp_cwd):
    """tui.theme / tui.colors typos become warnings, not silent fallbacks."""
    from uiu.config import AppConfig, ensure_workspace, save_config
    from uiu.doctor import _all_checks

    root = _ws(tmp_cwd)
    ensure_workspace(root)
    cfg = AppConfig()
    cfg.model.provider = "ollama"
    cfg.tui = {"theme": "nope", "colors": {"primary": "not-a-color", "bogus": "#fff"}}
    save_config(root, cfg)

    ids = {f.id for f in _all_checks(root)}
    assert "tui/unknown-theme" in ids
    assert "tui/bad-color" in ids
    assert "tui/unknown-color-slot" in ids


def test_fix_repairs_tui_prefs(tmp_cwd):
    """--fix resets an unknown theme and drops broken colour slots."""
    from uiu.config import AppConfig, ensure_workspace, load_config, save_config
    from uiu.doctor import Finding, _all_checks, _fix_one

    root = _ws(tmp_cwd)
    ensure_workspace(root)
    cfg = AppConfig()
    cfg.model.provider = "ollama"
    cfg.tui = {"theme": "nope",
               "colors": {"primary": "not-a-color", "bogus": "#fff", "accent": "#37D6C4"}}
    save_config(root, cfg)

    for f in _all_checks(root):
        if f.id.startswith("tui/"):
            assert f.can_fix, f"{f.id} should be auto-fixable"
            ok, _msg = _fix_one(root, f)
            assert ok, f.id

    fixed = load_config(root)
    assert fixed.tui["theme"] == "uiu-dark"
    assert "primary" not in fixed.tui.get("colors", {})
    assert "bogus" not in fixed.tui.get("colors", {})
    assert fixed.tui["colors"].get("accent") == "#37D6C4"
    assert not [f for f in _all_checks(root) if f.id.startswith("tui/")]


def test_accepts_valid_tui_prefs(tmp_cwd):
    from uiu.config import AppConfig, ensure_workspace, save_config
    from uiu.doctor import _all_checks

    root = _ws(tmp_cwd)
    ensure_workspace(root)
    cfg = AppConfig()
    cfg.model.provider = "ollama"
    cfg.tui = {"theme": "uiu-neon", "colors": {"primary": "#FF8800"}}
    save_config(root, cfg)

    ids = {f.id for f in _all_checks(root)}
    assert not any(i.startswith("tui/") for i in ids), ids


def test_detect_bad_api_mode(tmp_cwd):
    from uiu.config import ensure_workspace, AppConfig, save_config
    from uiu.doctor import _all_checks
    root = _ws(tmp_cwd)
    ensure_workspace(root)
    cfg = AppConfig()
    cfg.model.api_mode = "bogus_mode"
    save_config(root, cfg)
    items = _all_checks(root)
    assert any(f.id == "model/bad-api-mode" for f in items)


def test_detect_missing_key(tmp_cwd, monkeypatch):
    from uiu.config import ensure_workspace
    from uiu.doctor import _all_checks
    root = _ws(tmp_cwd)
    ensure_workspace(root)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    items = _all_checks(root)
    assert any(f.id == "model/no-api-key" for f in items)


def test_local_provider_no_key_ok(tmp_cwd, monkeypatch):
    """ollama (auth_type=none) 不报缺 key。"""
    from uiu.config import ensure_workspace, AppConfig, save_config
    from uiu.doctor import _all_checks
    root = _ws(tmp_cwd)
    ensure_workspace(root)
    cfg = AppConfig()
    cfg.model.provider = "ollama"
    save_config(root, cfg)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    items = _all_checks(root)
    assert not any(f.id == "model/no-api-key" for f in items)


def test_fix_bad_api_mode(tmp_cwd):
    from uiu.config import ensure_workspace, AppConfig, save_config, load_config
    from uiu.doctor import _all_checks, _fix_one
    root = _ws(tmp_cwd)
    ensure_workspace(root)
    cfg = AppConfig()
    cfg.model.api_mode = "nonsense"
    save_config(root, cfg)
    finding = next(f for f in _all_checks(root) if f.id == "model/bad-api-mode")
    ok, _ = _fix_one(root, finding)
    assert ok
    assert load_config(root).model.api_mode == "chat_completions"
    assert not any(f.id == "model/bad-api-mode" for f in _all_checks(root))


def test_fix_broken_config_yaml_backs_up(tmp_cwd):
    """坏 config.yaml → fix 备份后重置。"""
    from uiu.config import ensure_workspace, load_config
    from uiu.doctor import _all_checks, _fix_one
    root = _ws(tmp_cwd)
    ensure_workspace(root)
    (root / "config.yaml").write_text("model: [broken\n  : :", encoding="utf-8")
    finding = next(f for f in _all_checks(root) if f.id == "config/parse-error")
    assert finding
    ok, msg = _fix_one(root, finding)
    assert ok, msg
    assert (root / "config.yaml.bak").exists(), "坏文件应备份"
    assert load_config(root).model.provider == "openai"


def test_fix_missing_config(tmp_cwd):
    from uiu.doctor import _all_checks, _fix_one
    root = _ws(tmp_cwd)
    finding = next(f for f in _all_checks(root) if f.id == "config/missing")
    assert finding
    ok, _ = _fix_one(root, finding)
    assert ok and (root / "config.yaml").exists()


def test_fix_persona_files(tmp_cwd):
    from uiu.config import ensure_workspace
    from uiu.doctor import _all_checks, _fix_one
    root = _ws(tmp_cwd)
    (root / "SOUL.md").write_text("# SOUL\nx\n", encoding="utf-8")  # 只有 SOUL
    items = _all_checks(root)
    finding = next((f for f in items if f.id == "workspace/persona-files"), None)
    if finding:
        ok, _ = _fix_one(root, finding)
        assert ok
        assert (root / "MEMORY.md").exists()


def test_run_doctor_lint_exit_code(tmp_cwd):
    from uiu.doctor import run_doctor
    root = _ws(tmp_cwd)  # 空 workspace → error
    assert run_doctor(root, lint=True) == 1


def test_run_doctor_fix_yes(tmp_cwd, capsys):
    """--fix --yes 全自动修复可修项；修完 error 级应消失（key 除外不可修）。"""
    from uiu.doctor import run_doctor
    root = _ws(tmp_cwd)
    rc = run_doctor(root, fix=True, yes=True)
    out = capsys.readouterr().out
    assert "已修复" in out
    assert (root / "config.yaml").exists()
    assert (root / "SOUL.md").exists()
    assert (root / ".env").exists()
    # 重扫：workspace/config 类已修；no-api-key 不可修仍在 → rc 1
    assert rc == 1  # 剩 model/no-api-key（不可自动修）


def test_cli_doctor_parser(tmp_cwd):
    import argparse
    from uiu.commands import cmd_doctor
    ns = argparse.Namespace(workspace=str(tmp_cwd), lint=True, fix=False, yes=False)
    rc = cmd_doctor(ns)
    assert rc in (0, 1)


def test_detect_env_bad_lines(tmp_cwd):
    from uiu.doctor import _all_checks
    root = _ws(tmp_cwd)
    (root / ".env").write_text("GOOD=1\nthis is not env line\n", encoding="utf-8")
    items = _all_checks(root)
    assert any(f.id == "env/dotenv-bad-lines" for f in items)
