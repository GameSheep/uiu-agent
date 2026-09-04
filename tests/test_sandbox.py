"""Path sandbox + command guardrails (no LLM / network needed)."""

from pathlib import Path

from uiu._sandbox import (
    check_app_name,
    check_command,
    check_cwd,
    check_path,
)


def test_env_file_denied(tmp_cwd):
    ok, msg, _ = check_path("workspace/.env", for_write=True)
    assert not ok and ".env" in msg


def test_env_file_read_denied(tmp_cwd):
    ok, msg, _ = check_path(str(tmp_cwd / ".env"))
    assert not ok


def test_system_dir_denied():
    import os
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    ok, msg, _ = check_path(str(Path(windir) / "win.ini"))
    assert not ok and "系统目录" in msg


def test_config_yaml_write_denied(tmp_cwd):
    ok, msg, _ = check_path("workspace/config.yaml", for_write=True)
    assert not ok and "config.yaml" in msg


def test_config_yaml_read_allowed(tmp_cwd):
    ok, _, p = check_path("workspace/config.yaml")
    assert ok and p is not None


def test_normal_file_allowed(tmp_cwd):
    ok, _, p = check_path("workspace/notes/hello.txt", for_write=True)
    assert ok and p is not None


def test_empty_and_nul_path_rejected():
    assert not check_path("")[0]
    assert not check_path("a\x00b")[0]


def test_dangerous_commands_blocked():
    for cmd in ("shutdown /s /t 10", "rm -rf /", "mkfs.ext4 /dev/sda1", "format C:"):
        ok, msg = check_command(cmd)
        assert not ok, cmd


def test_benign_command_allowed():
    assert check_command("echo hello")[0]
    assert check_command("git status")[0]


def test_cwd_must_exist_and_be_safe(tmp_path):
    assert check_cwd(None)[0]
    assert check_cwd(str(tmp_path))[0]
    assert not check_cwd(str(tmp_path / "nope"))[0]
    import os
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    assert not check_cwd(windir)[0]


def test_app_name_injection_blocked():
    for bad in ("notepad & calc", "a|b", "x;rm", "$(whoami)", "a>b", ""):
        assert not check_app_name(bad)[0], bad


def test_app_name_legit_ok():
    assert check_app_name("notepad")[0]
    assert check_app_name("微信")[0]
    assert check_app_name("Visual Studio Code")[0]
