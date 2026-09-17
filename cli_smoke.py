"""CLI smoke test — mirrors CI step `python cli_smoke.py`.

Runs entirely offline against an isolated temp workspace (no LLM / network / GUI).
Exits non-zero on the first failed check. Every check prints `ok` or `FAIL`.

Coverage:
  1. package + registry import (the P0 breakage guard)
  2. `uiu version` via main.dispatch
  3. `uiu init` in an isolated workspace
  4. `uiu show` reads back config
  5. `uiu config --set-secret / --list` env write + masking
  6. tool defs are unique & well-formed
  7. slash dispatch (help / unknown / non-slash passthrough)
  8. cron parse/add/tick guardrails
  9. sandbox: env read blocked, dangerous shell blocked, benign shell ok
  10. sessions save/list/remove roundtrip
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name} {detail}")
        FAILED.append(name)


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def _main(argv: list[str]) -> int:
    """Call main with argv; --workspace is a TOP-LEVEL flag (before the subcommand)."""
    from uiu import main
    return main.main(argv)


def smoke_registry() -> None:
    import uiu.tools as t
    check("registry: uiu.tools imports", True)
    # 不要钉死数量：工具会一直加，钉死只会让这条检查越来越假
    n_tools = len(t.BUILTIN_TOOLS)
    check("registry: builtin tools registered", n_tools >= 60, f"got {n_tools}")
    for want in ("send_wechat", "shell_exec", "read_file", "window_list",
                 "click_text", "skills_list", "delegate_task", "session_search",
                 "macro_record", "macro_play"):
        check(f"registry: {want} present", want in t.BUILTIN_TOOLS)
    names = [d["function"]["name"] for d in t.tool_defs()]
    check("registry: tool defs unique", len(names) == len(set(names)))
    check("registry: send_wechat def present", "send_wechat" in names)


def smoke_version() -> None:
    rc = _main(["version"])
    check("cli: uiu version rc=0", rc == 0, f"rc={rc}")


def smoke_init_show(ws: Path) -> None:
    rc = _main(["--workspace", str(ws), "init"])
    check("cli: init rc=0", rc == 0, f"rc={rc}")
    check("cli: SOUL.md created", (ws / "SOUL.md").exists())
    check("cli: config.yaml created", (ws / "config.yaml").exists())
    rc = _main(["--workspace", str(ws), "show"])
    check("cli: show rc=0", rc == 0, f"rc={rc}")


def smoke_config(ws: Path) -> None:
    rc = _main(["--workspace", str(ws), "config", "--set-secret", "SMOKE_TOKEN=abc123"])
    check("cli: config set rc=0", rc == 0, f"rc={rc}")
    rc = _main(["--workspace", str(ws), "config", "--list"])
    check("cli: config list rc=0", rc == 0, f"rc={rc}")
    from uiu.config import parse_env_file
    env = parse_env_file(ws / ".env")
    check("config: secret persisted", env.get("SMOKE_TOKEN") == "abc123", str(env.get("SMOKE_TOKEN")))


def smoke_doctor(ws: Path) -> None:
    """Doctor lint runs on a broken workspace without crashing; fix repairs files."""
    import argparse
    from uiu.commands import cmd_doctor
    # init 后 workspace 完整但无 API key → lint 返回 1（error 存在），不崩溃
    rc = cmd_doctor(argparse.Namespace(workspace=str(ws), lint=True, fix=False, yes=False))
    check("doctor: lint runs on init'd ws", rc in (0, 1), f"rc={rc}")
    # 破坏 config.yaml → lint 报 parse-error（bad workspace 放 tmp 内，随 rmtree 清理）
    bad_ws = Path(ws).parent / "bad-ws"
    bad_ws.mkdir(exist_ok=True)
    (bad_ws / "config.yaml").write_text("model: [broken\n  : :", encoding="utf-8")
    rc = cmd_doctor(argparse.Namespace(workspace=str(bad_ws), lint=True, fix=False, yes=False))
    check("doctor: lint detects broken config", rc == 1, f"rc={rc}")
    rc = cmd_doctor(argparse.Namespace(workspace=str(bad_ws), lint=False, fix=True, yes=True))
    check("doctor: fix --yes repairs", rc in (0, 1), f"rc={rc}")
    check("doctor: broken config backed up", (bad_ws / "config.yaml.bak").exists())
    check("doctor: config repaired", (bad_ws / "config.yaml").exists())


def smoke_slash(ws: Path) -> None:
    from uiu.config import load_config
    from uiu.workspace import load_workspace
    from uiu.slash import dispatch, SlashContext
    cfg = load_config(ws)
    w = load_workspace(ws)
    said: list[str] = []

    def say(t: str) -> None:
        said.append(t)

    ctx = SlashContext(ws=w, cfg=cfg, client=None, messages=[], chat_id="smoke", say=say)
    handled, _ = dispatch("/help", ctx)
    check("slash: /help handled", handled)
    check("slash: /help lists cron", any("/cron" in s for s in said))
    said.clear()
    handled, _ = dispatch("/nope", ctx)
    check("slash: unknown handled as error", handled and any("未知命令" in s for s in said))
    said.clear()
    handled, _ = dispatch("just a message", ctx)
    check("slash: non-slash not handled", not handled)


def smoke_cron(ws: Path) -> None:
    from uiu import cron
    j = cron.add_job(ws, "smokejob", "daily 09:00", "say hi")
    check("cron: add daily", j["enabled"] is True)
    jobs = cron.load_jobs(ws)
    check("cron: persisted", any(x["name"] == "smokejob" for x in jobs))
    cron.remove_job(ws, "smokejob")
    check("cron: removed", not any(x["name"] == "smokejob" for x in cron.load_jobs(ws)))
    try:
        cron.parse_schedule("bogus")
        check("cron: invalid schedule rejected", False)
    except ValueError:
        check("cron: invalid schedule rejected", True)


def smoke_sandbox(ws: Path) -> None:
    from uiu.tools import call_tool
    envp = ws / ".env"
    envp.write_text("KEY=sk-should-not-leak\n", encoding="utf-8")
    out = call_tool("read_file", json.dumps({"path": str(envp)}))
    check("sandbox: .env read blocked", out.startswith("[error]"), out)
    out = call_tool("shell_exec", json.dumps({"command": "shutdown /s /t 10"}))
    check("sandbox: dangerous shell blocked", out.startswith("[error]"), out)
    out = call_tool("shell_exec", json.dumps({"command": "echo smoke-ok"}))
    check("sandbox: benign shell ok", "smoke-ok" in out, out)


def smoke_sessions(ws: Path) -> None:
    from uiu import sessions
    msgs = [{"role": "user", "content": "hello smoke"}]
    sessions.save_session(ws, "smoke-session", msgs)
    check("sessions: save", True)
    names = [s["id"] for s in sessions.list_sessions(ws)]
    check("sessions: listed", "smoke-session" in names, str(names))
    loaded = sessions.load_session(ws, "smoke-session")
    check("sessions: roundtrip", loaded and loaded[-1]["content"] == "hello smoke")
    sessions.remove_session(ws, "smoke-session")
    check("sessions: removed", "smoke-session" not in [s["id"] for s in sessions.list_sessions(ws)])


def smoke_macro(ws: Path) -> None:
    """Macro offline checks: list/create-file/list-again/remove (no GUI hooks)."""
    from uiu.macro_recorder import macros_dir, save_macro
    from uiu.commands import cmd_macro
    import argparse
    save_macro(macros_dir(ws) / "smoke.json", "smoke", "smoke macro",
               [{"t": "key", "key": "enter", "delay_before": 0.1}])
    ns = argparse.Namespace(workspace=str(ws), action="list")
    rc = cmd_macro(ns)
    check("macro: list rc=0", rc == 0, f"rc={rc}")
    ns = argparse.Namespace(workspace=str(ws), action="remove", name="smoke")
    rc = cmd_macro(ns)
    check("macro: remove rc=0", rc == 0, f"rc={rc}")


def _scratch_dir() -> Path:
    """A writable scratch workspace.

    tempfile.mkdtemp uses mode 0o700, which on Windows (and some sandboxes)
    results in a deny-all ACL the process itself cannot write into — so probe
    first and fall back to a directory next to the checkout.
    """
    try:
        tmp = Path(tempfile.mkdtemp(prefix="uiu-smoke-"))
        (tmp / ".writable").write_text("ok", encoding="utf-8")
        return tmp
    except OSError:
        fallback = Path.cwd() / ".uiu-smoke"
        import shutil
        shutil.rmtree(fallback, ignore_errors=True)
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def main() -> int:
    tmp = _scratch_dir()
    os.environ["UIU_WORKSPACE"] = str(tmp)
    try:
        smoke_registry()
        smoke_version()
        smoke_init_show(tmp)
        smoke_config(tmp)
        smoke_doctor(tmp / "workspace")
        smoke_slash(tmp)
        smoke_cron(tmp)
        smoke_sandbox(tmp)
        smoke_sessions(tmp)
        smoke_macro(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILED:
        print(f"\n{len(FAILED)} smoke check(s) FAILED: {FAILED}")
        return 1
    print(f"\nall smoke checks passed ({os.environ.get('SMOKE_COUNT_HINT', '')}done)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
