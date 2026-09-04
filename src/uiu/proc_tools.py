"""后台进程：proc_run（后台起）/ proc_log / proc_kill / proc_list。

对齐 Hermes terminal/process 的最小版：输出落 workspace/logs/proc_<id>.log，
内存表 + 日志文件双轨（重启后列表可从日志重建存在性）。
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

_PROCS: dict[str, dict] = {}
_SEQ = 0


def _logs_dir() -> Path:
    d = Path.cwd() / "workspace" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _next_id() -> str:
    global _SEQ
    _SEQ += 1
    return f"p{_SEQ}-{int(time.time()) % 100000}"


def proc_run(command: str, cwd: str | None = None) -> str:
    """后台运行命令，立即返回 proc id（输出进日志文件）。"""
    from ._sandbox import check_command, check_cwd
    ok, msg = check_command(command)
    if not ok:
        return msg
    ok, msg = check_cwd(cwd)
    if not ok:
        return msg
    pid = _next_id()
    log = _logs_dir() / f"proc_{pid}.log"
    try:
        fh = open(log, "w", encoding="utf-8", errors="replace")
        p = subprocess.Popen(
            command, shell=True, cwd=cwd or os.getcwd(),
            stdout=fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        return f"[error] 启动失败: {type(e).__name__}: {e}"
    _PROCS[pid] = {"pid": pid, "command": command, "os_pid": p.pid,
                   "handle": p, "log": str(log), "started": time.time()}
    return f"[ok] {pid} 已后台启动（os pid {p.pid}，日志 {log}）"


def proc_log(pid: str, tail: int = 50) -> str:
    """读后台进程日志尾部。"""
    info = _PROCS.get(pid or "")
    log = Path(info["log"]) if info else _logs_dir() / f"proc_{pid}.log"
    if not log.exists():
        return f"[error] 未知 proc: {pid}"
    try:
        tail = max(1, min(int(tail or 50), 500))
    except (TypeError, ValueError):
        return "[error] tail 须为数字"
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    status = ""
    if info and info["handle"].poll() is not None:
        status = f"（已退出，exit={info['handle'].returncode}）"
    elif info:
        status = "（运行中）"
    body = "\n".join(lines[-tail:]) or "(暂无输出)"
    return f"{pid}{status}:\n{body}"


def proc_kill(pid: str) -> str:
    """终止后台进程。"""
    info = _PROCS.get(pid or "")
    if info is None:
        return f"[error] 未知 proc: {pid}"
    h = info["handle"]
    if h.poll() is not None:
        return f"[ok] {pid} 已退出（exit={h.returncode}）"
    try:
        h.terminate()
        try:
            h.wait(timeout=5)
        except subprocess.TimeoutExpired:
            h.kill()
        return f"[ok] {pid} 已终止"
    except Exception as e:
        return f"[error] 终止失败: {type(e).__name__}: {e}"


def proc_list() -> str:
    """列出本进程内的后台任务。"""
    if not _PROCS:
        return "(无后台任务)"
    lines = []
    for pid, info in _PROCS.items():
        rc = info["handle"].poll()
        st = f"exit={rc}" if rc is not None else "运行中"
        lines.append(f"  {pid} [{st}] {info['command'][:80]}")
    return "\n".join(lines)


PROC_RUN_DEF = {
    "type": "function",
    "function": {
        "name": "proc_run",
        "description": "后台运行耗时命令（立即返回，不阻塞）。查日志用 proc_log，结束用 proc_kill。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "description": "工作目录（可选）"},
            },
            "required": ["command"],
        },
    },
}

PROC_LOG_DEF = {
    "type": "function",
    "function": {
        "name": "proc_log",
        "description": "读后台任务日志尾部。",
        "parameters": {
            "type": "object",
            "properties": {
                "pid": {"type": "string", "description": "proc_run 返回的 id"},
                "tail": {"type": "integer", "description": "尾部行数（默认50）"},
            },
            "required": ["pid"],
        },
    },
}

PROC_KILL_DEF = {
    "type": "function",
    "function": {
        "name": "proc_kill",
        "description": "终止后台任务。",
        "parameters": {"type": "object", "properties": {"pid": {"type": "string"}}, "required": ["pid"]},
    },
}

PROC_LIST_DEF = {
    "type": "function",
    "function": {
        "name": "list_procs",
        "description": "列出后台任务。",
        "parameters": {"type": "object", "properties": {}},
    },
}

PROC_TOOLS: dict[str, dict] = {
    "proc_run": {"def": PROC_RUN_DEF, "fn": proc_run},
    "proc_log": {"def": PROC_LOG_DEF, "fn": proc_log},
    "proc_kill": {"def": PROC_KILL_DEF, "fn": proc_kill},
    "list_procs": {"def": PROC_LIST_DEF, "fn": proc_list},
}


def proc_tool_defs() -> list[dict]:
    return [t["def"] for t in PROC_TOOLS.values()]
