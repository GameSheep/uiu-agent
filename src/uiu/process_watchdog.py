"""Process Health Watchdog & Frozen Window Auto-Revival Engine.

Inspired by OSWorld and Appium Self-Healing.
Monitors process responsiveness via Win32 IsHungAppWindow and resource consumption via psutil.
Automatically revives or restarts hung/deadlocked applications to ensure unstopped autonomy.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from typing import Any


def is_window_hung(hwnd: int) -> bool:
    """Check if a window is unresponsive (Windows white ghosting / Not Responding state)."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        return bool(ctypes.windll.user32.IsHungAppWindow(int(hwnd)))
    except Exception:
        return False


def ping_window_message_queue(hwnd: int, timeout_ms: int = 500) -> bool:
    """Send a benign WM_NULL message to verify whether the window's message pump is processing events."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        # SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        res = ctypes.windll.user32.SendMessageTimeoutW(
            int(hwnd),
            0x0000,  # WM_NULL
            0,
            0,
            0x0002,  # SMTO_ABORTIFHUNG
            int(timeout_ms),
            ctypes.byref(result),
        )
        return bool(res)
    except Exception:
        return False


def get_window_process_info(hwnd: int) -> dict[str, Any]:
    """Retrieve process PID, executable path, CPU%, and Memory usage for a window handle."""
    if not hwnd:
        return {}

    try:
        import win32process
        import psutil

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid or pid <= 4:
            return {"pid": pid, "is_system": True}

        proc = psutil.Process(pid)
        mem_mb = round(proc.memory_info().rss / (1024 * 1024), 2)
        cpu_pct = round(proc.cpu_percent(interval=0.05), 1)

        try:
            exe = proc.exe()
        except Exception:
            exe = ""

        try:
            cmdline = proc.cmdline()
        except Exception:
            cmdline = []

        return {
            "pid": pid,
            "name": proc.name(),
            "exe": exe,
            "cmdline": cmdline,
            "memory_mb": mem_mb,
            "cpu_percent": cpu_pct,
            "status": proc.status(),
            "is_system": False,
        }
    except Exception as e:
        return {"error": str(e)}


def check_app_health(target: int | str) -> dict[str, Any]:
    """Comprehensive health diagnostic for a window / app."""
    from .layout_manager import _resolve_hwnd

    hwnd = _resolve_hwnd(target)
    if not hwnd:
        return {
            "target": target,
            "found": False,
            "is_hung": False,
            "message": f"未找到目标应用窗口: {target}",
        }

    import win32gui
    title = win32gui.GetWindowText(hwnd)
    hung = is_window_hung(hwnd)
    responsive = ping_window_message_queue(hwnd, timeout_ms=300)
    pinfo = get_window_process_info(hwnd)

    return {
        "target": target,
        "hwnd": hwnd,
        "title": title,
        "found": True,
        "is_hung": hung or (not responsive),
        "is_message_pump_alive": responsive,
        "process": pinfo,
        "status": "hung" if (hung or not responsive) else "healthy",
    }


def revive_or_restart_app(
    target: int | str,
    force_restart: bool = False,
    max_wait_seconds: float = 5.0,
) -> str:
    """Attempt to revive a hung window, or cleanly restart it if permanently deadlocked."""
    health = check_app_health(target)
    if not health.get("found"):
        return f"[error] 未能定位目标应用: {target}"

    hwnd = health["hwnd"]
    title = health["title"]
    pinfo = health.get("process", {})
    pid = pinfo.get("pid")
    exe = pinfo.get("exe")

    # 1. If healthy and not forced, return immediately
    if not health.get("is_hung") and not force_restart:
        return f"[ok] 应用 '{title}' (PID={pid}) 当前处于健康活跃状态，无需复活或重启。"

    # 2. Gentle message pump poke if hung
    if not force_restart:
        for _ in range(3):
            time.sleep(0.3)
            if ping_window_message_queue(hwnd, timeout_ms=500):
                return f"[ok] 应用 '{title}' 已通过消息队列激活成功复活，恢复响应。"

    # 3. Permanent deadlock: terminate and restart
    if not exe or not os.path.exists(exe):
        return f"[error] 应用 '{title}' 假死，但无法获取其可执行文件路径 (exe={exe})，无法自动重启。"

    try:
        import psutil
        if pid and pid > 4:
            p = psutil.Process(pid)
            p.terminate()
            try:
                p.wait(timeout=2.0)
            except Exception:
                p.kill()

        time.sleep(0.5)

        # Relaunch process
        cmdline = pinfo.get("cmdline") or [exe]
        subprocess.Popen(cmdline)

        # Wait for new window to spawn
        t0 = time.perf_counter()
        from .window_manager import find_window
        new_win = None
        while time.perf_counter() - t0 < max_wait_seconds:
            time.sleep(0.5)
            new_win = find_window(title)
            if new_win:
                break

        return (
            f"[ok] 已成功重启假死应用 '{title}'!\n"
            f"原 PID={pid} 已终止，已通过 {exe} 启动新实例 (新窗口状态: {'就绪' if new_win else '启动中'})"
        )
    except Exception as e:
        return f"[error] 重启应用失败: {type(e).__name__}: {e}"
