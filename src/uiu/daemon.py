"""Daemon — Background service & scheduled task runner for uiu.

Allows uiu to run silently in the background after installation:
- `uiu daemon run`: foreground execution of the 60s cron tick loop (useful for testing/logs)
- `uiu daemon start`: spawns a detached, zero-window background process (pythonw on Windows)
- `uiu daemon stop`: terminates the running background daemon process
- `uiu daemon status`: inspects PID, process health, and upcoming scheduled tasks
- `uiu daemon install-autostart`: sets up Windows Startup script for boot persistence
- `uiu daemon uninstall-autostart`: removes the autostart entry
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import cron


def daemon_dir() -> Path:
    d = Path.home() / ".uiu"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pid_path() -> Path:
    return daemon_dir() / "daemon.pid"


def log_path() -> Path:
    return daemon_dir() / "daemon.log"


def _is_pid_running(pid: int) -> bool:
    """Check whether a given PID is currently active."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def get_daemon_pid() -> int | None:
    p = pid_path()
    if not p.exists():
        return None
    try:
        pid = int(p.read_text(encoding="utf-8").strip())
        if _is_pid_running(pid):
            return pid
        # Stale PID file
        p.unlink(missing_ok=True)
        return None
    except Exception:
        return None


def run_daemon(workspace: Path, interval: int = 60, stop_event=None) -> None:
    """Run the cron tick loop indefinitely in the current process."""
    ws = Path(workspace).resolve()
    pid = os.getpid()
    pid_path().write_text(str(pid), encoding="utf-8")
    
    with open(log_path(), "a", encoding="utf-8") as log:
        log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] [daemon] Started (PID {pid}, ws: {ws})\n")
        log.flush()

    try:
        while True:
            if stop_event and stop_event.is_set():
                break
            try:
                ran = cron.tick(ws)
                if ran:
                    with open(log_path(), "a", encoding="utf-8") as log:
                        for out in ran:
                            log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [cron] Ran job -> {out}\n")
                        log.flush()
            except Exception as e:
                with open(log_path(), "a", encoding="utf-8") as log:
                    log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [daemon error] {e}\n")
                    log.flush()

            if stop_event:
                if stop_event.wait(interval):
                    break
            else:
                time.sleep(interval)
    finally:
        pid_path().unlink(missing_ok=True)
        with open(log_path(), "a", encoding="utf-8") as log:
            log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [daemon] Stopped\n")
            log.flush()


def start_daemon(workspace: Path) -> tuple[bool, str]:
    """Start uiu daemon in the background with zero visible console window."""
    existing = get_daemon_pid()
    if existing:
        return False, f"守护进程已在运行中 (PID: {existing})"

    ws = Path(workspace).resolve()
    cmd = [sys.executable, "-m", "uiu.main", "daemon", "run", "--workspace", str(ws)]

    # On Windows, try pythonw.exe to prevent terminal window popping up
    if sys.platform == "win32":
        py_dir = Path(sys.executable).parent
        pythonw = py_dir / "pythonw.exe"
        if pythonw.exists():
            cmd[0] = str(pythonw)

        # DETACHED_PROCESS = 0x00000008, CREATE_NO_WINDOW = 0x08000000
        creationflags = 0x00000008 | 0x08000000
        log_f = open(log_path(), "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=log_f,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    else:
        log_f = open(log_path(), "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=log_f,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

    # Allow a brief moment to write PID
    time.sleep(0.5)
    pid = proc.pid
    pid_path().write_text(str(pid), encoding="utf-8")
    return True, f"后台守护进程已启动 (PID: {pid})，日志记录于: {log_path()}"


def stop_daemon() -> tuple[bool, str]:
    """Stop the running background daemon."""
    pid = get_daemon_pid()
    if not pid:
        pid_path().unlink(missing_ok=True)
        return False, "守护进程未运行"

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as e:
        return False, f"终止守护进程失败 (PID {pid}): {e}"

    pid_path().unlink(missing_ok=True)
    return True, f"后台守护进程已停止 (PID: {pid})"


def status_daemon(workspace: Path) -> dict[str, Any]:
    """Inspect daemon status and scheduled jobs."""
    ws = Path(workspace).resolve()
    pid = get_daemon_pid()
    jobs = cron.load_jobs(ws)
    return {
        "running": pid is not None,
        "pid": pid,
        "log_path": str(log_path()),
        "workspace": str(ws),
        "total_jobs": len(jobs),
        "enabled_jobs": len([j for j in jobs if j.get("enabled")]),
        "jobs": jobs,
    }


def _get_windows_startup_dir() -> Path | None:
    """Retrieve Windows Startup folder."""
    if sys.platform != "win32":
        return None
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    startup = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    if startup.exists():
        return startup
    return None


def install_autostart(workspace: Path) -> tuple[bool, str]:
    """Set up auto-start on Windows login so cron tasks run automatically."""
    startup_dir = _get_windows_startup_dir()
    if not startup_dir:
        return False, "当前系统不支持或未找到 Windows 自启目录"

    ws = Path(workspace).resolve()
    py_dir = Path(sys.executable).parent
    pythonw = py_dir / "pythonw.exe"
    exe = str(pythonw if pythonw.exists() else sys.executable)

    vbs_path = startup_dir / "uiu-agent-daemon.vbs"
    # VBScript launches pythonw invisibly with zero window
    vbs_content = (
        f'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run """{exe}"" -m uiu.main daemon run --workspace ""{ws}""", 0, False\n'
    )
    try:
        vbs_path.write_text(vbs_content, encoding="utf-8")
        return True, f"已成功注册 Windows 开机自启: {vbs_path}"
    except Exception as e:
        return False, f"注册自启失败: {e}"


def uninstall_autostart() -> tuple[bool, str]:
    """Remove Windows auto-start entry."""
    startup_dir = _get_windows_startup_dir()
    if not startup_dir:
        return False, "当前系统不支持或未找到 Windows 自启目录"

    vbs_path = startup_dir / "uiu-agent-daemon.vbs"
    if vbs_path.exists():
        try:
            vbs_path.unlink()
            return True, "已成功移除开机自启项目"
        except Exception as e:
            return False, f"删除自启文件失败: {e}"
    return True, "未检测到已注册的自启项目"
