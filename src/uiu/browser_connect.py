"""Default Browser Takeover & CDP Connection Subsystem.

Enables seamless attachment to the user's everyday Chrome / Edge browser:
1. Zero re-login: Preserves all active cookies, SSO tokens, tabs, and profiles.
2. Auto-detects local Chrome/Edge executable and user profile directory on Windows/macOS/Linux.
3. Smooth CDP launch / restart with `--remote-debugging-port=9222 --restore-last-session`.
4. Attaches via Playwright `connect_over_cdp()` to control the active tab in real time.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from .window_manager import ensure_default_desktop


def detect_chrome_executable() -> str | None:
    """Find the path to the Google Chrome executable."""
    # 1. Environment variable override
    env_path = os.environ.get("CHROME_PATH") or os.environ.get("GOOGLE_CHROME_BIN")
    if env_path and Path(env_path).is_file():
        return env_path

    # 2. Windows registry & standard paths
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and Path(val).is_file():
                    return val
        except Exception:
            pass

        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
        for p in candidates:
            if p.is_file():
                return str(p)

    # 3. macOS standard paths
    elif sys.platform == "darwin":
        mac_paths = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").expanduser(),
        ]
        for p in mac_paths:
            if p.is_file():
                return str(p)

    # 4. Linux standard binaries
    for cmd in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "chrome"]:
        found = shutil.which(cmd)
        if found:
            return found

    return None


def detect_edge_executable() -> str | None:
    """Find the path to the Microsoft Edge executable."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and Path(val).is_file():
                    return val
        except Exception:
            pass

        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        ]
        for p in candidates:
            if p.is_file():
                return str(p)

    for cmd in ["microsoft-edge", "msedge"]:
        found = shutil.which(cmd)
        if found:
            return found

    return None


def detect_browser_executable(preferred: str = "chrome") -> str | None:
    """Detect preferred browser executable with fallback."""
    if preferred.lower() == "edge":
        return detect_edge_executable() or detect_chrome_executable()
    return detect_chrome_executable() or detect_edge_executable()


def detect_chrome_user_data_dir() -> Path | None:
    """Locate the default user profile directory for Google Chrome."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            p = Path(local_app_data) / "Google" / "Chrome" / "User Data"
            if p.exists():
                return p
    elif sys.platform == "darwin":
        p = Path("~/Library/Application Support/Google/Chrome").expanduser()
        if p.exists():
            return p
    else:
        p = Path("~/.config/google-chrome").expanduser()
        if p.exists():
            return p
    return None


def is_cdp_ready(host: str = "127.0.0.1", port: int = 9222, timeout: float = 0.5) -> bool:
    """Check whether Chrome/Edge remote debugging port is open and responding."""
    url = f"http://{host}:{port}/json/version"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_cdp_version_info(host: str = "127.0.0.1", port: int = 9222, timeout: float = 0.8) -> dict[str, Any]:
    """Fetch browser version and WebSocket debugging endpoint metadata from CDP."""
    url = f"http://{host}:{port}/json/version"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"CDP metadata request failed: {e}"}


def is_browser_process_running(browser_name: str = "chrome") -> bool:
    """Check if any browser process with the given name is currently active."""
    try:
        import psutil
        target_name = "chrome.exe" if browser_name.lower() == "chrome" else "msedge.exe"
        for proc in psutil.process_iter(["name"]):
            if proc.info["name"] and proc.info["name"].lower() == target_name.lower():
                return True
    except Exception:
        pass
    return False


def launch_browser_with_cdp(
    port: int = 9222,
    browser: str = "chrome",
    restore_session: bool = True,
    user_data_dir: str | Path | None = None,
    extra_args: list[str] | None = None,
) -> bool:
    """Launch user's native browser with remote debugging port enabled.

    Uses user's native profile and session restore flags to retain tabs and cookies.
    """
    exe = detect_browser_executable(preferred=browser)
    if not exe:
        return False

    args = [exe, f"--remote-debugging-port={port}"]
    if restore_session:
        args.append("--restore-last-session")
    if user_data_dir:
        args.append(f"--user-data-dir={user_data_dir}")
    if extra_args:
        args.extend(extra_args)

    ensure_default_desktop()

    try:
        if sys.platform == "win32":
            # Launch detached so the browser stays alive independently of the agent process
            subprocess.Popen(
                args,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                args,
                start_new_session=True,
                close_fds=True,
            )
        # Wait up to 5 seconds for CDP port to open
        t0 = time.time()
        while time.time() - t0 < 5.0:
            if is_cdp_ready(port=port):
                return True
            time.sleep(0.15)
    except Exception:
        return False

    return is_cdp_ready(port=port)


def ensure_browser_with_cdp(
    port: int = 9222,
    browser: str = "chrome",
    auto_restart: bool = False,
) -> dict[str, Any]:
    """Ensure that the user's browser is running with CDP enabled.

    If not running, launches it with session restore.
    If running without CDP:
      - If auto_restart=True: gracefully restarts Chrome with --restore-last-session.
      - If auto_restart=False: returns guidance prompting the user.
    """
    if is_cdp_ready(port=port):
        version_info = get_cdp_version_info(port=port)
        return {
            "ready": True,
            "action": "already_running",
            "browser": version_info.get("Browser", browser),
            "port": port,
        }

    running = is_browser_process_running(browser)
    if not running:
        # Browser is not running at all: launch with CDP and restore session
        ok = launch_browser_with_cdp(port=port, browser=browser, restore_session=True)
        return {
            "ready": ok,
            "action": "launched",
            "port": port,
            "message": "已成功以调试模式启动宿主浏览器并恢复上次会话" if ok else "启动浏览器失败",
        }

    # Browser is running, but port 9222 is closed
    if auto_restart:
        try:
            import psutil
            target = "chrome.exe" if browser.lower() == "chrome" else "msedge.exe"
            for proc in psutil.process_iter(["pid", "name"]):
                if proc.info["name"] and proc.info["name"].lower() == target.lower():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            time.sleep(1.0)
            ok = launch_browser_with_cdp(port=port, browser=browser, restore_session=True)
            return {
                "ready": ok,
                "action": "restarted",
                "port": port,
                "message": "已平滑重挂载浏览器并恢复所有标签页与会话状态" if ok else "重启浏览器挂载失败",
            }
        except Exception as e:
            return {"ready": False, "error": f"重挂载浏览器失败: {e}"}

    return {
        "ready": False,
        "action": "needs_cdp_port",
        "port": port,
        "message": (
            f"检测到 {browser} 正在运行，但未开启远程调试端口 {port}。\n"
            f"请关闭浏览器后使用快捷方式或命令行启动：\n"
            f'  chrome.exe --remote-debugging-port={port} --restore-last-session\n'
            f"或者设置 auto_restart=True 允许 Agent 平滑重挂载。"
        ),
    }


@dataclass
class BrowserSession:
    """Encapsulates an active Playwright CDP connection to the user's browser."""
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    port: int = 9222

    def get_active_page(self) -> Page:
        """Ensure we return the current forefront active page."""
        try:
            pages = self.context.pages
            # Filter out internal/extension pages
            valid_pages = [p for p in pages if not p.url.startswith(("chrome-extension://", "edge://extensions"))]
            if valid_pages:
                self.page = valid_pages[-1]
        except Exception:
            pass
        return self.page

    def new_tab(self, url: str = "") -> Page:
        """Open a new tab in the user's browser session."""
        new_page = self.context.new_page()
        if url:
            new_page.goto(url)
        self.page = new_page
        return new_page

    def list_tabs(self) -> list[dict[str, Any]]:
        """List all open pages with title, url, and index."""
        result = []
        for i, p in enumerate(self.context.pages):
            try:
                result.append({"index": i, "title": p.title(), "url": p.url})
            except Exception:
                result.append({"index": i, "title": "(closed)", "url": ""})
        return result

    def close(self) -> None:
        """Safely detach without terminating the user's browser."""
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self.playwright.stop()
        except Exception:
            pass


_GLOBAL_SESSION: BrowserSession | None = None


def attach_default_browser(host: str = "127.0.0.1", port: int = 9222) -> BrowserSession:
    """Attach Playwright over CDP to the user's running Chrome/Edge instance."""
    global _GLOBAL_SESSION
    if _GLOBAL_SESSION is not None:
        try:
            # Check if existing session page is still open and healthy
            if not _GLOBAL_SESSION.page.is_closed():
                return _GLOBAL_SESSION
        except Exception:
            pass
        _GLOBAL_SESSION = None

    if not is_cdp_ready(host=host, port=port):
        # Try to ensure browser
        res = ensure_browser_with_cdp(port=port)
        if not res.get("ready"):
            raise ConnectionError(
                f"无法连接到浏览器调试端口 http://{host}:{port}。\n"
                f"{res.get('message', '请确认 Chrome/Edge 是否开启了 --remote-debugging-port=9222')}"
            )

    pw = sync_playwright().start()
    endpoint = f"http://{host}:{port}"
    browser = pw.chromium.connect_over_cdp(endpoint)

    contexts = browser.contexts
    if contexts:
        ctx = contexts[0]
    else:
        ctx = browser.new_context()

    pages = ctx.pages
    if pages:
        # Pick the most relevant active page (ignore devtools / extensions if possible)
        active = pages[-1]
        for p in reversed(pages):
            if not p.url.startswith(("chrome-extension://", "devtools://", "edge://extensions")):
                active = p
                break
    else:
        active = ctx.new_page()

    session = BrowserSession(
        playwright=pw,
        browser=browser,
        context=ctx,
        page=active,
        port=port,
    )
    _GLOBAL_SESSION = session
    return session


def get_active_browser_session() -> BrowserSession | None:
    """Return currently cached active browser session if any."""
    global _GLOBAL_SESSION
    if _GLOBAL_SESSION is not None:
        try:
            if not _GLOBAL_SESSION.page.is_closed():
                return _GLOBAL_SESSION
        except Exception:
            pass
        _GLOBAL_SESSION = None
    return None


def disconnect_browser_session() -> None:
    """Detach the active Playwright session cleanly."""
    global _GLOBAL_SESSION
    if _GLOBAL_SESSION is not None:
        _GLOBAL_SESSION.close()
        _GLOBAL_SESSION = None


atexit.register(disconnect_browser_session)
