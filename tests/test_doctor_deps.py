"""doctor 的可选依赖体检（审计 §2.2 / P2-15）。

诊断的意义在于「用户能看懂并能立刻照做」：缺哪个栈、影响什么能力、装哪条命令。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uiu import doctor


def _ws(tmp_path: Path) -> Path:
    from uiu.config import ensure_workspace

    ws = tmp_path / "ws"
    ensure_workspace(ws)
    return ws


def _fake_missing(*missing: str):
    """让 doctor 认为只有这些模块缺失。"""
    def _f(name: str) -> bool:
        return name in missing
    return _f


def test_missing_stack_is_reported_as_info(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_module_missing", lambda name: True)
    findings = {f.id: f for f in doctor._chk_optional_deps(_ws(tmp_path))}

    for stack, extra in (("browser", "browser"), ("voice-tts", "voice"),
                         ("voice-stt", "voice"), ("rag", "rag")):
        finding = findings.get(f"deps/{stack}-missing")
        assert finding is not None, f"缺少 deps/{stack}-missing: {list(findings)}"
        assert finding.severity == "info"
        assert finding.can_fix is True
        assert f"uiu[{extra}]" in finding.fix_hint


def test_present_stack_is_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_module_missing", lambda name: False)
    ids = [f.id for f in doctor._chk_optional_deps(_ws(tmp_path))]
    assert not [i for i in ids if i.startswith("deps/")], ids


def test_uia_check_is_windows_only(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_module_missing", lambda name: True)
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    ids = [f.id for f in doctor._chk_optional_deps(_ws(tmp_path))]
    assert "deps/desktop-uia-missing" not in ids, "非 Windows 不该提示装 uiautomation"
    monkeypatch.undo()

    monkeypatch.setattr(doctor, "_module_missing", lambda name: True)
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    ids = [f.id for f in doctor._chk_optional_deps(_ws(tmp_path))]
    assert "deps/desktop-uia-missing" in ids
    monkeypatch.undo()


def test_mcp_missing_stays_a_warning(tmp_path, monkeypatch):
    from uiu.config import load_config, save_config

    ws = _ws(tmp_path)
    cfg = load_config(ws)
    cfg.mcp_servers = [{"name": "x", "command": "npx"}]
    save_config(ws, cfg)

    monkeypatch.setattr(doctor, "_module_missing", lambda name: True)
    findings = {f.id: f for f in doctor._chk_optional_deps(ws)}
    assert findings["deps/mcp-missing"].severity == "warning"


def test_missing_textual_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_module_missing", lambda name: name == "textual")
    findings = {f.id: f for f in doctor._chk_optional_deps(_ws(tmp_path))}
    assert findings["deps/textual-missing"].severity == "error"


def test_info_findings_do_not_fail_the_exit_code(tmp_path, monkeypatch, capsys):
    """可选栈缺失是 info：不该改变 uiu doctor --lint 的退出码。"""
    ws = _ws(tmp_path)

    monkeypatch.setattr(doctor, "_module_missing", lambda name: name != "textual")
    rc_with_infos = doctor.run_doctor(ws, lint=True)
    shown = capsys.readouterr().out
    assert "deps/browser-missing" in shown, "应当报出可选栈缺失"

    monkeypatch.setattr(doctor, "_module_missing", lambda name: False)
    rc_clean = doctor.run_doctor(ws, lint=True)
    capsys.readouterr()
    assert rc_with_infos == rc_clean, "info 级发现不应改变退出码"


def test_fix_runs_pip_install_for_the_right_extra(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    monkeypatch.setattr(doctor, "_module_missing", lambda name: True)
    finding = next(f for f in doctor._chk_optional_deps(ws)
                   if f.id == "deps/browser-missing")

    seen: dict = {}

    class _Proc:
        returncode = 0
        stdout = "Successfully installed playwright-1.0"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(doctor, "_run_pip", _fake_run)
    ok, msg = doctor._fix_one(ws, finding)
    assert ok is True
    assert "uiu[browser]" in " ".join(seen["cmd"])
    assert "已安装" in msg


def test_fix_reports_pip_failure(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    monkeypatch.setattr(doctor, "_module_missing", lambda name: True)
    finding = next(f for f in doctor._chk_optional_deps(ws)
                   if f.id == "deps/voice-tts-missing")

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "ERROR: Could not find a version that satisfies the requirement"

    monkeypatch.setattr(doctor, "_run_pip", lambda cmd: _Proc())
    ok, msg = doctor._fix_one(ws, finding)
    assert ok is False
    assert "pip 安装失败" in msg
    assert "手动执行" in msg


def test_fix_without_install_deps_never_runs_pip(tmp_path, monkeypatch, capsys):
    """--fix --yes 不该顺手装几十上百 MB 的可选栈（这是真的会花钱/花时间）。"""
    ws = _ws(tmp_path)
    monkeypatch.setattr(doctor, "_module_missing", lambda name: name != "mcp")

    def _explode(cmd):                     # 只要被调用就说明门禁失效
        raise AssertionError(f"不该执行 pip: {cmd}")

    monkeypatch.setattr(doctor, "_run_pip", _explode)
    doctor.run_doctor(ws, fix=True, yes=True)
    out = capsys.readouterr().out
    assert "--install-deps" in out, "必须告诉用户怎么装"


def test_fix_with_install_deps_does_run_pip(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    monkeypatch.setattr(doctor, "_module_missing", lambda name: name != "mcp")
    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(doctor, "_run_pip",
                        lambda cmd: (calls.append(cmd), _Proc())[1])
    doctor.run_doctor(ws, fix=True, yes=True, install_deps=True)
    joined = " ".join(" ".join(c) for c in calls)
    assert "uiu[browser]" in joined, calls
    assert "uiu[voice]" in joined, calls


def test_cli_doctor_lint_lists_missing_stacks(tmp_path, monkeypatch, capsys):
    from uiu.main import main

    ws = _ws(tmp_path)
    monkeypatch.setattr(doctor, "_module_missing", lambda name: True)
    rc = main(["--workspace", str(ws), "doctor", "--lint"])
    out = capsys.readouterr().out
    assert "deps/browser-missing" in out
    assert "uiu[browser]" in out, "诊断必须给出可执行的安装命令"
    assert rc == 1, "缺 API key 是 error 级，rc 应为 1"
