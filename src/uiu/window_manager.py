"""Universal Window & Process Manager — Win10/Win11 Enhanced."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import time
import winreg
from pathlib import Path

# Enable Per-Monitor DPI Awareness so screen coords & clicks match physical pixels on Win10/Win11
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def ensure_default_desktop() -> bool:
    """Attach the calling thread to the interactive 'default' desktop on Windows.
    Prevents empty window lists and failed screenshots in background service/agent threads.
    """
    try:
        import win32service
        import win32con
        hdesk = win32service.OpenDesktop("default", 0, False, win32con.MAXIMUM_ALLOWED)
        if hdesk:
            res = ctypes.windll.user32.SetThreadDesktop(int(hdesk))
            return bool(res)
    except Exception:
        pass
    return False


def list_visible_windows() -> list[dict]:
    import win32gui
    import win32process

    ensure_default_desktop()
    windows = []

    def _enum_callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return
        rect = win32gui.GetWindowRect(hwnd)
        if (rect[2] - rect[0]) <= 10 or (rect[3] - rect[1]) <= 10:
            return

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        windows.append({
            "hwnd": hwnd,
            "title": title,
            "pid": pid,
            "rect": rect,
            "is_minimized": bool(win32gui.IsIconic(hwnd)),
        })

    win32gui.EnumWindows(_enum_callback, None)
    return windows


def find_window(title_keyword: str) -> dict | None:
    keyword = title_keyword.lower().strip()
    for win in list_visible_windows():
        if keyword in win["title"].lower():
            return win
    return None


def focus_window(hwnd: int) -> str:
    """Focus and bring window to topmost foreground, bypassing Win10/Win11 lock."""
    import win32api
    import win32con
    import win32gui
    import win32process

    ensure_default_desktop()

    try:
        # Restore if minimized
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        time.sleep(0.1)

        # Allow SetForegroundWindow on Windows 10/11
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:
            pass

        # Simulate Alt key tap to reset Windows foreground lock timer
        try:
            VK_MENU = 0x12
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        except Exception:
            pass

        fg = win32gui.GetForegroundWindow()
        cur_tid = win32api.GetCurrentThreadId()
        fg_tid, _ = win32process.GetWindowThreadProcessId(int(fg or 0))
        target_tid, _ = win32process.GetWindowThreadProcessId(int(hwnd))

        attached = []
        for tid in (fg_tid, target_tid):
            if tid and tid != cur_tid:
                try:
                    if win32process.AttachThreadInput(cur_tid, tid, True):
                        attached.append(tid)
                except Exception:
                    pass

        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            for tid in attached:
                try:
                    win32process.AttachThreadInput(cur_tid, tid, False)
                except Exception:
                    pass

        time.sleep(0.2)
        return f"[ok] 窗口 {hwnd} 已置顶前台"
    except Exception as e:
        return f"[error] 激活窗口失败: {type(e).__name__}: {e}"


def set_window_state(hwnd: int, action: str) -> str:
    import win32con
    import win32gui

    action = action.lower().strip()
    action_map = {
        "maximize": win32con.SW_MAXIMIZE,
        "minimize": win32con.SW_MINIMIZE,
        "restore": win32con.SW_RESTORE,
    }

    try:
        if action == "close":
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            return f"[ok] 已发送关闭指令到窗口 {hwnd}"
        if action in action_map:
            win32gui.ShowWindow(hwnd, action_map[action])
            time.sleep(0.2)
            return f"[ok] 窗口 {hwnd} 状态已设为 {action}"
        return f"[error] 不支持的操作类型: {action}"
    except Exception as e:
        return f"[error] 调整窗口状态失败: {type(e).__name__}: {e}"


# Shell meta characters: forbid command chaining/injection while allowing safe Windows paths
_SHELL_META = set("&|<>^`$(){};\"'\n\r\t")


def launch_application(target: str) -> str:
    """Launch a program / open a file / open a URL. No shell involved.

    Validation: non-empty, length-bounded, no shell metacharacters; URLs must
    use an http(s) scheme (mirrors open_url's guardrail).
    """
    target = (target or "").strip()
    if not target:
        return "[error] target 不能为空"
    if len(target) > 2000:
        return "[error] target 过长"
    if any(ch in _SHELL_META for ch in target):
        return "[error] target 含非法字符（shell 元字符），已拒绝"
    low = target.lower()
    if low.startswith(("javascript:", "data:", "vbscript:", "file:", "about:")):
        return "[error] 不支持的 URL scheme（仅 http/https）"
    try:
        os.startfile(target)
        time.sleep(0.8)
        return f"[ok] 启动命令已触发: {target}"
    except OSError:
        return f"[error] 启动应用失败: 无法打开 {target!r}"
    except Exception as e:
        return f"[error] 启动应用失败: {type(e).__name__}: {e}"


# Common Windows App Aliases mapping names to executable/protocol names
COMMON_APP_ALIASES: dict[str, list[str]] = {
    "微信": ["WeChat.exe", "Weixin.exe", "微信.lnk", "WeChatAppEx.exe"],
    "wechat": ["WeChat.exe", "Weixin.exe", "WeChat.lnk", "WeChatAppEx.exe"],
    "weixin": ["Weixin.exe", "WeChat.exe", "微信.lnk"],
    "chrome": ["chrome.exe", "Google Chrome.lnk"],
    "谷歌浏览器": ["chrome.exe", "Google Chrome.lnk"],
    "edge": ["msedge.exe", "Microsoft Edge.lnk"],
    "msedge": ["msedge.exe", "Microsoft Edge.lnk"],
    "qq": ["QQ.exe", "QQ.lnk"],
    "outlook": ["OUTLOOK.EXE", "Outlook.lnk"],
    "word": ["WINWORD.EXE", "Word.lnk"],
    "excel": ["EXCEL.EXE", "Excel.lnk"],
    "ppt": ["POWERPNT.EXE", "PowerPoint.lnk"],
    "powerpoint": ["POWERPNT.EXE", "PowerPoint.lnk"],
    "notepad": ["notepad.exe", "记事本.lnk"],
    "记事本": ["notepad.exe", "记事本.lnk"],
    "calc": ["calc.exe"],
    "计算器": ["calc.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "terminal": ["wt.exe", "Windows Terminal.lnk"],
    "终端": ["wt.exe", "Windows Terminal.lnk"],
    "code": ["Code.exe", "Visual Studio Code.lnk"],
    "vscode": ["Code.exe", "Visual Studio Code.lnk"],
    "explorer": ["explorer.exe"],
    "资源管理器": ["explorer.exe"],
    "taskmgr": ["taskmgr.exe"],
    "任务管理器": ["taskmgr.exe"],
    "feishu": ["Feishu.exe", "飞书.lnk"],
    "飞书": ["Feishu.exe", "飞书.lnk"],
    "dingtalk": ["DingTalk.exe", "钉钉.lnk"],
    "钉钉": ["DingTalk.exe", "钉钉.lnk"],
    "wework": ["WXWork.exe", "企业微信.lnk"],
    "企业微信": ["WXWork.exe", "企业微信.lnk"],
    "settings": ["ms-settings:"],
    "设置": ["ms-settings:"],
}


def _find_installed_app(name_or_keyword: str) -> str | None:
    """Find installed application executable path on Windows across multiple sources."""
    name_clean = name_or_keyword.strip()
    name_lower = name_clean.lower()

    # 1. Direct path exists
    if os.path.isfile(name_clean):
        return name_clean

    # Check direct which
    w = shutil.which(name_clean)
    if w:
        return w

    # Candidate names to look for
    candidates = [name_clean]
    if not name_lower.endswith(".exe"):
        candidates.append(f"{name_clean}.exe")
    if name_lower in COMMON_APP_ALIASES:
        candidates.extend(COMMON_APP_ALIASES[name_lower])

    for c in candidates:
        if c.startswith("ms-") or c.endswith(":"):
            return c  # Protocol handler like ms-settings:

    # 2. Check App Paths in Windows Registry
    for cand in candidates:
        cand_exe = cand if cand.lower().endswith(".exe") else f"{cand}.exe"
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                sub = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{cand_exe}"
                with winreg.OpenKey(root, sub) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val and os.path.exists(val.strip('"')):
                        return val.strip('"')
            except Exception:
                pass

    # 3. Check Start Menu Shortcuts (exact match first, ignore uninstallers)
    start_dirs = [
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"),
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        start_dirs.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")

    exact_lnk = None
    fuzzy_lnk = None
    for cand in candidates:
        pattern = cand.replace(".exe", "").replace(".lnk", "").lower()
        for sdir in start_dirs:
            if not sdir.exists():
                continue
            for lnk in sdir.rglob("*.lnk"):
                stem_low = lnk.stem.lower()
                if "卸载" in stem_low or "uninstall" in stem_low:
                    continue
                if stem_low == pattern:
                    exact_lnk = str(lnk)
                    break
                elif pattern in stem_low and fuzzy_lnk is None:
                    fuzzy_lnk = str(lnk)
            if exact_lnk:
                break
        if exact_lnk:
            return exact_lnk

    # 4. Check Windows Registry Uninstall entries for InstallLocation
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
            r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ):
            try:
                with winreg.OpenKey(root, sub) as key:
                    num_subkeys, _, _ = winreg.QueryInfoKey(key)
                    for i in range(num_subkeys):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as sk:
                                try:
                                    disp, _ = winreg.QueryValueEx(sk, "DisplayName")
                                except Exception:
                                    disp = ""
                                if not disp:
                                    continue
                                for cand in candidates:
                                    key_word = cand.replace(".exe", "").replace(".lnk", "").lower()
                                    if key_word == disp.lower() or key_word in disp.lower():
                                        # Try DisplayIcon or InstallLocation
                                        try:
                                            icon, _ = winreg.QueryValueEx(sk, "DisplayIcon")
                                            icon_path = icon.split(",")[0].strip('"')
                                            if os.path.exists(icon_path) and icon_path.lower().endswith(".exe"):
                                                return icon_path
                                        except Exception:
                                            pass
                                        try:
                                            loc, _ = winreg.QueryValueEx(sk, "InstallLocation")
                                            loc_clean = loc.strip('"')
                                            if loc_clean and os.path.isdir(loc_clean):
                                                for cand_exe in candidates:
                                                    if cand_exe.lower().endswith(".exe"):
                                                        test_p = os.path.join(loc_clean, cand_exe)
                                                        if os.path.exists(test_p):
                                                            return test_p
                                                for root_p, _, files in os.walk(loc_clean):
                                                    for f in files:
                                                        if f.lower().endswith(".exe") and ("uninstall" not in f.lower()):
                                                            return os.path.join(root_p, f)
                                        except Exception:
                                            pass
                        except Exception:
                            continue
            except Exception:
                pass

    if fuzzy_lnk:
        return fuzzy_lnk

    return None


def open_or_focus_app(app_name_or_path: str) -> str:
    """Open an application or bring it to the foreground if already running.

    - If running: restores and focuses the window immediately.
    - If not running: locates the executable/shortcut/protocol and launches it,
      then waits for the window to appear and focuses it.
    """
    app = (app_name_or_path or "").strip()
    if not app:
        return "[error] app_name_or_path 不能为空"

    # 1. First check if any open window matches
    keywords = [app.lower()]
    if app.lower() in COMMON_APP_ALIASES:
        for a in COMMON_APP_ALIASES[app.lower()]:
            keywords.append(a.replace(".exe", "").replace(".lnk", "").lower())

    for win in list_visible_windows():
        title_low = win["title"].lower()
        if any(k in title_low for k in keywords):
            focus_window(win["hwnd"])
            return f"[ok] 软件已在运行，已置顶到前台: '{win['title']}' (HWND: {win['hwnd']})"

    # 2. Not running, search and launch
    target = _find_installed_app(app)
    if not target:
        # Fallback to direct launch_application if it might be a system command like 'calc' or URL
        launch_res = launch_application(app)
        if launch_res.startswith("[ok]"):
            time.sleep(1.0)
            win = find_window(app)
            if win:
                focus_window(win["hwnd"])
            return f"[ok] 已触发启动: {app}"
        return f"[error] 未找到软件 '{app}'（已检索运行窗口、系统 PATH、注册表 App Paths 及开始菜单）"

    # Launch found target
    try:
        if target.startswith("ms-") or target.endswith(":"):
            os.startfile(target)
        elif target.lower().endswith(".lnk"):
            os.startfile(target)
        else:
            subprocess.Popen([target], shell=False)
    except Exception as e:
        return f"[error] 启动 '{target}' 失败: {e}"

    # Wait up to 3.5 seconds for window to appear and focus
    start_t = time.time()
    while time.time() - start_t < 3.5:
        time.sleep(0.4)
        for win in list_visible_windows():
            title_low = win["title"].lower()
            if any(k in title_low for k in keywords):
                focus_window(win["hwnd"])
                return f"[ok] 软件已启动并置顶到前台: '{win['title']}' ({target})"

    return f"[ok] 软件已启动: {target}（窗口可能正在后台加载）"