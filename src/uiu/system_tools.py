"""System management tools — shutdown, system info, network, clipboard, browser.

补齐桌面控制之外的系统级操作：
- system_info   系统信息（CPU/内存/电池/磁盘）
- shutdown      关机/重启/注销（需确认）
- check_network 网络连通性
- clipboard_get / clipboard_set 剪贴板
- open_url      打开网址/搜索
- take_screenshot 截屏保存
"""

from __future__ import annotations

import time


# ---------- system info ----------

def system_info() -> str:
    """CPU / memory / disk / battery / uptime info."""
    import platform
    lines = [f"系统: {platform.system()} {platform.release()} ({platform.machine()})"]
    # CPU
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        lines.append(f"CPU: {cpu}%")
        lines.append(f"内存: {mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB ({mem.percent}%)")
        # disk
        for part in psutil.disk_partitions()[:3]:
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(f"磁盘 {part.mountpoint}: {usage.free // (1024**3)}GB 可用 / {usage.total // (1024**3)}GB")
            except Exception:
                continue
        # battery
        try:
            batt = psutil.sensors_battery()
            if batt:
                lines.append(f"电池: {batt.percent}%{'（充电中）' if batt.power_plugged else ''}")
        except Exception:
            pass
        # uptime
        import time as _t
        boot = psutil.boot_time()
        up_secs = int(_t.time() - boot)
        lines.append(f"开机时长: {up_secs // 3600}小时{up_secs % 3600 // 60}分钟")
    except ImportError:
        lines.append("(装 psutil 可显示更多信息)")
    return "\n".join(lines)


# ---------- shutdown / reboot ----------

def shutdown(action: str = "shutdown") -> str:
    """shutdown / restart / logout (注销) / sleep (睡眠). Requires user confirm."""
    import subprocess
    action = action.lower()
    cmds = {
        "shutdown": ["shutdown", "/s", "/t", "10"],
        "restart": ["shutdown", "/r", "/t", "10"],
        "logout": ["shutdown", "/l"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "hibernate": ["shutdown", "/h"],
    }
    if action not in cmds:
        return f"[error] 动作: shutdown/restart/logout/sleep/hibernate"
    try:
        r = subprocess.run(cmds[action], capture_output=True, timeout=15)
        return f"[ok] 已执行 {action}（10 秒后生效，可 shutdown /a 取消）" if r.returncode == 0 else f"[error] {r.stderr.decode(errors='replace')[:200]}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


# ---------- network ----------

def check_network(host: str = "www.baidu.com") -> str:
    """Ping a host to check connectivity. Default: baidu (China-friendly)."""
    import subprocess
    import platform
    param = "-n" if platform.system().lower() == "windows" else "-c"
    try:
        r = subprocess.run(
            ["ping", param, "2", host],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0:
            # extract latency
            import re
            m = re.search(r"[时间|time][=<]([0-9]+)ms", r.stdout, re.I)
            latency = f" 延迟 {m.group(1)}ms" if m else ""
            return f"[ok] 网络连通 {host}{latency}"
        return f"[error] 无法访问 {host}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


# ---------- clipboard ----------

def clipboard_get() -> str:
    """Read clipboard text content."""
    try:
        import pyperclip
        return f"剪贴板内容: {pyperclip.paste()[:500] or '(空)'}"
    except ImportError:
        # fallback: powershell
        import subprocess
        r = subprocess.run(
            ["powershell", "-command", "Get-Clipboard -Raw"],
            capture_output=True, text=True, timeout=10,
        )
        return f"剪贴板内容: {r.stdout.strip()[:500] or '(空)'}"


def clipboard_set(text: str) -> str:
    """Write text to clipboard."""
    if len(text) > 100_000:
        return "[error] 文本过长（>100KB）"
    try:
        import pyperclip
        pyperclip.copy(text)
        return f"[ok] 已复制到剪贴板（{len(text)} 字符）"
    except ImportError:
        import subprocess
        # stdin 管道，避免把 text 拼进命令行（命令注入）
        r = subprocess.run(
            ["powershell", "-NoProfile", "-command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
            input=text,
            capture_output=True, text=True, timeout=10,
        )
        return "[ok] 已复制到剪贴板" if r.returncode == 0 else f"[error] 复制失败: {r.stderr.strip()[:200]}"


# ---------- browser / url ----------

def open_url(url: str) -> str:
    """Open a URL in default browser. If no scheme, treat as search."""
    import webbrowser
    url = (url or "").strip()
    if len(url) > 2000:
        return "[error] URL 过长"
    low = url.lower()
    if low.startswith(("javascript:", "data:", "vbscript:", "file:", "about:")):
        return "[error] 不支持的 URL scheme（仅 http/https/搜索词）"
    if not url.startswith(("http://", "https://")):
        # no dot → treat as search query
        if "." not in url.split("/")[0]:
            import urllib.parse
            url = f"https://www.baidu.com/s?wd={urllib.parse.quote(url)}"
        else:
            url = "https://" + url
    try:
        webbrowser.open(url)
    except Exception as e:
        return f"[error] 打开失败: {type(e).__name__}: {e}"
    return f"[ok] 已在浏览器打开: {url}"


# ---------- screenshot ----------

def take_screenshot(path: str = "") -> str:
    """Take a screenshot and save to a file (default: Desktop/截图_时间.png)."""
    import pyautogui
    from pathlib import Path
    if not path:
        desk = _desktop()
        path = str(desk / f"截图_{time.strftime('%Y%m%d_%H%M%S')}.png")
    else:
        from ._sandbox import check_path
        ok, msg, p = check_path(path, for_write=True)
        if not ok:
            return msg
        if p is not None and p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            return "[error] 截图仅支持 .png/.jpg"
        path = str(p) if p is not None else path
    try:
        img = pyautogui.screenshot()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
    except Exception as e:
        return f"[error] 截图失败: {type(e).__name__}: {e}"
    return f"[ok] 截图已保存: {path}"


def _desktop() -> Path:
    """Real desktop path (registry + fallbacks)."""
    from pathlib import Path
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            val, _ = winreg.QueryValueEx(k, "Desktop")
            p = Path(val)
            if p.is_dir():
                return p
    except Exception:
        pass
    home = Path.home()
    for cand in (home / "Desktop", home / "桌面", home / "OneDrive" / "Desktop", home / "OneDrive" / "桌面"):
        if cand.is_dir():
            return cand
    return home


# ---------- tool definitions ----------

SYSTEM_INFO_DEF = {
    "type": "function",
    "function": {
        "name": "system_info",
        "description": "查看系统信息：CPU/内存/磁盘/电池/开机时长。用户问'电脑卡不卡/内存多大/还有多少电'时用。",
        "parameters": {"type": "object", "properties": {}},
    },
}

SHUTDOWN_DEF = {
    "type": "function",
    "function": {
        "name": "shutdown",
        "description": "关机/重启/注销/睡眠。危险操作，必须先跟用户确认！",
        "parameters": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["shutdown", "restart", "logout", "sleep"]}},
            "required": ["action"],
        },
    },
}

CHECK_NETWORK_DEF = {
    "type": "function",
    "function": {
        "name": "check_network",
        "description": "检查网络连通性（ping）。用户说'网通不通'时用。",
        "parameters": {
            "type": "object",
            "properties": {"host": {"type": "string", "description": "ping 的主机（默认 baidu.com）"}},
        },
    },
}

CLIPBOARD_GET_DEF = {
    "type": "function",
    "function": {
        "name": "clipboard_get",
        "description": "读取剪贴板内容。用户问'我复制了什么'时用。",
        "parameters": {"type": "object", "properties": {}},
    },
}

CLIPBOARD_SET_DEF = {
    "type": "function",
    "function": {
        "name": "clipboard_set",
        "description": "把文字写入剪贴板。",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
}

OPEN_URL_DEF = {
    "type": "function",
    "function": {
        "name": "open_url",
        "description": "在默认浏览器打开网址，或搜索（输入无网址的文本会搜索）。如'打开哔哩哔哩'、'搜索今天的新闻'。",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "网址或搜索词"}},
            "required": ["url"],
        },
    },
}

TAKE_SCREENSHOT_DEF = {
    "type": "function",
    "function": {
        "name": "take_screenshot",
        "description": "截屏保存为图片（默认保存到桌面）。用户说'截个图'时用。",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "保存路径（可选）"}},
        },
    },
}


# ---------- clock ----------

def get_time() -> str:
    """Current local date/time (weekday in Chinese). Prefer over shell `date`."""
    import datetime
    now = datetime.datetime.now().astimezone()
    week = "一二三四五六日"[now.weekday()]
    return now.strftime(f"%Y-%m-%d %H:%M:%S 周{week}（%Z）")


GET_TIME_DEF = {
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "看当前时间/日期/星期。用户问'几点了/今天周几'时用，别用 shell 查时间。",
        "parameters": {"type": "object", "properties": {}},
    },
}


# ---------- software inventory & updates ----------

def software_inventory(filter_keyword: str = "", check_updates: bool = True, limit: int = 30) -> str:
    """List installed software, version, and latest available version via registry & winget."""
    import winreg
    import subprocess
    import re

    filter_clean = (filter_keyword or "").strip().lower()
    limit = max(1, min(int(limit or 30), 100))

    # 1. Read installed apps from registry
    installed = {}
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
            r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ):
            try:
                with winreg.OpenKey(root, sub) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sk:
                                disp = winreg.QueryValueEx(sk, "DisplayName")[0]
                                if not disp or disp.startswith("KB") or "Update for" in disp or "Security Update" in disp:
                                    continue
                                ver = ""
                                try:
                                    ver = winreg.QueryValueEx(sk, "DisplayVersion")[0]
                                except Exception:
                                    pass
                                pub = ""
                                try:
                                    pub = winreg.QueryValueEx(sk, "Publisher")[0]
                                except Exception:
                                    pass
                                if filter_clean and filter_clean not in disp.lower():
                                    continue
                                installed[disp] = {"version": ver, "publisher": pub}
                        except Exception:
                            continue
            except Exception:
                continue

    # 2. Check winget upgrades if requested
    winget_upgrades = {}
    if check_updates:
        try:
            r = subprocess.run(
                ["winget", "upgrade", "--include-unknown"],
                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
            )
            lines = r.stdout.splitlines()
            sep_idx = -1
            for idx, line in enumerate(lines):
                if line.startswith("---"):
                    sep_idx = idx
                    break
            if sep_idx != -1:
                for line in lines[sep_idx + 1:]:
                    parts = re.split(r"\s{2,}", line.strip())
                    if len(parts) >= 4:
                        name, pkg_id, cur_ver, avail_ver = parts[0], parts[1], parts[2], parts[3]
                        winget_upgrades[name.lower()] = {
                            "name": name, "id": pkg_id, "current": cur_ver, "latest": avail_ver
                        }
        except Exception:
            pass

    # 3. Build report
    matched_items = []
    for disp, info in sorted(installed.items(), key=lambda x: x[0].lower()):
        cur_v = info["version"] or "(未知)"
        latest_v = "-"
        status = "已是最新"

        # Check if matched in winget upgrades
        disp_low = disp.lower()
        for w_low, w_info in winget_upgrades.items():
            if w_low in disp_low or disp_low in w_low:
                latest_v = w_info["latest"]
                status = f"可升级至 {latest_v}"
                break

        matched_items.append((disp, cur_v, latest_v, status))

    # Also add any winget items not in registry if filtering matches
    for w_low, w_info in winget_upgrades.items():
        if filter_clean and filter_clean not in w_low:
            continue
        if not any(w_low in item[0].lower() or item[0].lower() in w_low for item in matched_items):
            matched_items.append((w_info["name"], w_info["current"], w_info["latest"], f"可升级至 {w_info['latest']} (winget)"))

    total_count = len(matched_items)
    display_items = matched_items[:limit]

    out = [
        f"### [系统软件统计] (共检索到 {total_count} 款软件，{len(winget_upgrades)} 款可升级)",
        "",
        "| 软件名称 | 当前版本 | 最新版本 | 升级状态 |",
        "| --- | --- | --- | --- |",
    ]
    for name, c_ver, l_ver, st in display_items:
        out.append(f"| {name} | {c_ver} | {l_ver} | {st} |")

    if total_count > limit:
        out.append(f"\n*(仅显示前 {limit} 款，可提供 filter_keyword 进行精确筛选)*")

    return "\n".join(out)


SOFTWARE_INVENTORY_DEF = {
    "type": "function",
    "function": {
        "name": "software_inventory",
        "description": "统计本机安装的系统软件、当前版本，并通过 winget 检查是否有最新版本及升级状态。",
        "parameters": {
            "type": "object",
            "properties": {
                "filter_keyword": {"type": "string", "description": "软件名称筛选关键字（如 'chrome', 'wechat', 'python'）"},
                "check_updates": {"type": "boolean", "description": "是否联网检查最新可用版本（默认 True）", "default": True},
                "limit": {"type": "integer", "description": "最多显示几款软件（默认 30）", "default": 30},
            },
        },
    },
}


SYSTEM_TOOLS: dict[str, dict] = {
    "get_time": {"def": GET_TIME_DEF, "fn": get_time},
    "system_info": {"def": SYSTEM_INFO_DEF, "fn": system_info},
    "software_inventory": {"def": SOFTWARE_INVENTORY_DEF, "fn": software_inventory},
    "shutdown": {"def": SHUTDOWN_DEF, "fn": shutdown},
    "check_network": {"def": CHECK_NETWORK_DEF, "fn": check_network},
    "clipboard_get": {"def": CLIPBOARD_GET_DEF, "fn": clipboard_get},
    "clipboard_set": {"def": CLIPBOARD_SET_DEF, "fn": clipboard_set},
    "open_url": {"def": OPEN_URL_DEF, "fn": open_url},
    "take_screenshot": {"def": TAKE_SCREENSHOT_DEF, "fn": take_screenshot},
}


def system_tool_defs() -> list[dict]:
    return [t["def"] for t in SYSTEM_TOOLS.values()]


def call_system_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in SYSTEM_TOOLS:
        return f"[error] unknown system tool: {name}"
    fn = SYSTEM_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"