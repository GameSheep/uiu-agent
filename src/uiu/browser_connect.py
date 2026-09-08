"""Default & Multi-Browser Takeover & CDP Connection Subsystem.

Enables seamless attachment to the user's everyday Chrome, Edge, Brave, and other Chromium browsers:
1. Zero re-login: Preserves all active cookies, SSO tokens, tabs, and user profiles.
2. Auto-detects system default browser from Windows registry (UserChoice) and paths.
3. Multi-browser scanner: Locates Google Chrome, Microsoft Edge, Brave, etc.
4. Smart Tab Management: find, switch, de-duplicate tabs, and bring tabs to front.
5. High-performance DOM data extraction: Extracts clean Markdown, structured tables, or raw HTML.
6. Attaches via Playwright `connect_over_cdp()` to control pages in real time.
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
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from .window_manager import ensure_default_desktop


def detect_default_system_browser() -> str:
    """Detect default web browser from Windows registry (UrlAssociations) or system settings.

    Returns: 'chrome' | 'edge' | 'brave' | 'firefox'
    """
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
            ) as key:
                prog_id, _ = winreg.QueryValueEx(key, "ProgId")
                prog_id_lower = str(prog_id).lower()
                if "chrome" in prog_id_lower:
                    return "chrome"
                elif "edge" in prog_id_lower:
                    return "edge"
                elif "brave" in prog_id_lower:
                    return "brave"
                elif "firefox" in prog_id_lower:
                    return "firefox"
        except Exception:
            pass
    return "chrome"


def detect_chrome_executable() -> str | None:
    """Find the path to the Google Chrome executable."""
    env_path = os.environ.get("CHROME_PATH") or os.environ.get("GOOGLE_CHROME_BIN")
    if env_path and Path(env_path).is_file():
        return env_path

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

    elif sys.platform == "darwin":
        mac_paths = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").expanduser(),
        ]
        for p in mac_paths:
            if p.is_file():
                return str(p)

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

    elif sys.platform == "darwin":
        p = Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
        if p.is_file():
            return str(p)

    for cmd in ["microsoft-edge", "msedge"]:
        found = shutil.which(cmd)
        if found:
            return found

    return None


def detect_brave_executable() -> str | None:
    """Find the path to the Brave browser executable."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and Path(val).is_file():
                    return val
        except Exception:
            pass

        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "BraveSoftware/Brave-Browser/Application/brave.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "BraveSoftware/Brave-Browser/Application/brave.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        ]
        for p in candidates:
            if p.is_file():
                return str(p)

    elif sys.platform == "darwin":
        p = Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
        if p.is_file():
            return str(p)

    for cmd in ["brave", "brave-browser"]:
        found = shutil.which(cmd)
        if found:
            return found

    return None


def detect_browser_executable(preferred: str = "auto") -> str | None:
    """Detect browser executable path by preference ('auto', 'chrome', 'edge', 'brave')."""
    p = preferred.lower().strip()
    if p == "auto":
        default_b = detect_default_system_browser()
        # Try default browser first, then fallbacks
        if default_b == "edge":
            return detect_edge_executable() or detect_chrome_executable() or detect_brave_executable()
        elif default_b == "brave":
            return detect_brave_executable() or detect_chrome_executable() or detect_edge_executable()
        return detect_chrome_executable() or detect_edge_executable() or detect_brave_executable()

    if p == "edge":
        return detect_edge_executable() or detect_chrome_executable()
    elif p == "brave":
        return detect_brave_executable() or detect_chrome_executable()
    return detect_chrome_executable() or detect_edge_executable()


def detect_browser_user_data_dir(browser: str = "auto") -> Path | None:
    """Locate user profile directory for Chrome, Edge, or Brave."""
    b = browser.lower().strip()
    if b == "auto":
        b = detect_default_system_browser()

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            return None
        base = Path(local_app_data)
        if b == "edge":
            p = base / "Microsoft" / "Edge" / "User Data"
        elif b == "brave":
            p = base / "BraveSoftware" / "Brave-Browser" / "User Data"
        else:
            p = base / "Google" / "Chrome" / "User Data"
        return p if p.exists() else None

    elif sys.platform == "darwin":
        if b == "edge":
            p = Path("~/Library/Application Support/Microsoft Edge").expanduser()
        elif b == "brave":
            p = Path("~/Library/Application Support/BraveSoftware/Brave-Browser").expanduser()
        else:
            p = Path("~/Library/Application Support/Google/Chrome").expanduser()
        return p if p.exists() else None

    else:
        if b == "edge":
            p = Path("~/.config/microsoft-edge").expanduser()
        elif b == "brave":
            p = Path("~/.config/BraveSoftware/Brave-Browser").expanduser()
        else:
            p = Path("~/.config/google-chrome").expanduser()
        return p if p.exists() else None


def detect_chrome_user_data_dir() -> Path | None:
    """Locate the default user profile directory for Google Chrome (alias for compatibility)."""
    return detect_browser_user_data_dir("chrome")


def detect_all_installed_browsers() -> list[dict[str, Any]]:
    """Scan and list all installed modern Chromium browsers and their live status."""
    browsers = []
    default_b = detect_default_system_browser()

    checks = [
        ("chrome", "Google Chrome", detect_chrome_executable),
        ("edge", "Microsoft Edge", detect_edge_executable),
        ("brave", "Brave Browser", detect_brave_executable),
    ]

    for key, display_name, finder in checks:
        exe = finder()
        if exe:
            user_data = detect_browser_user_data_dir(key)
            running = is_browser_process_running(key)
            browsers.append({
                "type": key,
                "name": display_name,
                "executable": exe,
                "user_data_dir": str(user_data) if user_data else None,
                "is_default": (key == default_b),
                "is_running": running,
            })
    return browsers


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
    b = browser_name.lower().strip()
    if b == "auto":
        b = detect_default_system_browser()

    target_map = {
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "brave": "brave.exe",
    }
    target = target_map.get(b, f"{b}.exe" if sys.platform == "win32" else b)

    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name")
            if name and name.lower() == target.lower():
                return True
    except Exception:
        pass
    return False


def launch_browser_with_cdp(
    port: int = 9222,
    browser: str = "auto",
    restore_session: bool = True,
    user_data_dir: str | Path | None = None,
    extra_args: list[str] | None = None,
) -> bool:
    """Launch user's native browser with remote debugging port enabled."""
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
    browser: str = "auto",
    auto_restart: bool = False,
) -> dict[str, Any]:
    """Ensure that the target browser is running with CDP enabled."""
    effective_browser = browser
    if browser == "auto":
        effective_browser = detect_default_system_browser()

    if is_cdp_ready(port=port):
        version_info = get_cdp_version_info(port=port)
        return {
            "ready": True,
            "action": "already_running",
            "browser": version_info.get("Browser", effective_browser),
            "port": port,
        }

    running = is_browser_process_running(effective_browser)
    if not running:
        ok = launch_browser_with_cdp(port=port, browser=effective_browser, restore_session=True)
        return {
            "ready": ok,
            "action": "launched",
            "port": port,
            "browser": effective_browser,
            "message": f"已成功以调试模式启动宿主浏览器 ({effective_browser}) 并恢复上次会话" if ok else f"启动浏览器 ({effective_browser}) 失败",
        }

    if auto_restart:
        try:
            import psutil
            target_map = {"chrome": "chrome.exe", "edge": "msedge.exe", "brave": "brave.exe"}
            target = target_map.get(effective_browser, f"{effective_browser}.exe")
            for proc in psutil.process_iter(["pid", "name"]):
                if proc.info.get("name") and proc.info["name"].lower() == target.lower():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            time.sleep(1.0)
            ok = launch_browser_with_cdp(port=port, browser=effective_browser, restore_session=True)
            return {
                "ready": ok,
                "action": "restarted",
                "port": port,
                "browser": effective_browser,
                "message": f"已平滑重挂载浏览器 ({effective_browser}) 并恢复所有标签页与会话状态" if ok else f"重启浏览器 ({effective_browser}) 挂载失败",
            }
        except Exception as e:
            return {"ready": False, "error": f"重挂载浏览器失败: {e}"}

    return {
        "ready": False,
        "action": "needs_cdp_port",
        "port": port,
        "browser": effective_browser,
        "message": (
            f"检测到 {effective_browser} 正在运行，但未开启远程调试端口 {port}。\n"
            f"请关闭浏览器后使用命令行启动：\n"
            f'  {effective_browser}.exe --remote-debugging-port={port} --restore-last-session\n'
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
    browser_type: str = "auto"

    def get_active_page(self) -> Page:
        """Ensure we return the current forefront active page."""
        try:
            pages = self.context.pages
            valid_pages = [p for p in pages if not p.url.startswith(("chrome-extension://", "devtools://", "edge://extensions"))]
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

    def find_tab(self, keyword_or_url: str) -> Page | None:
        """Find an existing tab matching a title or URL substring."""
        kw = keyword_or_url.strip().lower()
        if not kw:
            return None
        for p in reversed(self.context.pages):
            try:
                title = p.title().lower()
                url = p.url.lower()
                if kw in title or kw in url:
                    return p
            except Exception:
                continue
        return None

    def switch_tab(self, keyword_or_index: str | int) -> Page:
        """Switch to and focus a tab by title/URL keyword or 0-based index."""
        target_page: Page | None = None
        pages = self.context.pages

        if isinstance(keyword_or_index, int) or (isinstance(keyword_or_index, str) and keyword_or_index.strip().isdigit()):
            idx = int(keyword_or_index)
            if 0 <= idx < len(pages):
                target_page = pages[idx]
        else:
            target_page = self.find_tab(str(keyword_or_index))

        if not target_page:
            raise ValueError(f"未找到匹配的标签页: {keyword_or_index}")

        try:
            target_page.bring_to_front()
        except Exception:
            pass
        self.page = target_page
        return target_page

    def open_or_switch_tab(self, url: str, match_domain: bool = True) -> Page:
        """Open a URL, or if a tab on the same domain/URL is already open, focus it to avoid duplicate tabs."""
        url = url.strip()
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        if match_domain and domain:
            for p in reversed(self.context.pages):
                try:
                    p_domain = urlparse(p.url).netloc.lower()
                    if domain == p_domain:
                        p.bring_to_front()
                        if p.url.rstrip("/") != url.rstrip("/"):
                            p.goto(url)
                        self.page = p
                        return p
                except Exception:
                    continue

        return self.new_tab(url)

    def close_tab(self, keyword_or_index: str | int) -> bool:
        """Close a tab by index or title/URL keyword."""
        target: Page | None = None
        pages = self.context.pages

        if isinstance(keyword_or_index, int) or (isinstance(keyword_or_index, str) and keyword_or_index.strip().isdigit()):
            idx = int(keyword_or_index)
            if 0 <= idx < len(pages):
                target = pages[idx]
        else:
            target = self.find_tab(str(keyword_or_index))

        if target:
            try:
                target.close()
                self.get_active_page()
                return True
            except Exception:
                pass
        return False

    def extract_page_content(
        self,
        mode: str = "markdown",
        selector: str = "",
        max_chars: int = 5000,
    ) -> str:
        """Extract structured content (markdown, table, text, html) from the active page DOM."""
        p = self.get_active_page()
        mode = mode.lower().strip()

        if mode == "text":
            js = f"""(() => {{
                const root = {json.dumps(selector)} ? document.querySelector({json.dumps(selector)}) : document.body;
                return root ? root.innerText : '';
            }})()"""
            txt = str(p.evaluate(js) or "").strip()
            return txt[:max_chars]

        elif mode == "table":
            js = f"""(() => {{
                const tables = Array.from(document.querySelectorAll({json.dumps(selector)} || 'table'));
                const results = [];
                for (const t of tables) {{
                    const rows = [];
                    for (const tr of t.querySelectorAll('tr')) {{
                        const cells = Array.from(tr.querySelectorAll('th, td')).map(c => c.innerText.trim().replace(/\\s+/g, ' '));
                        if (cells.length > 0) rows.push(cells);
                    }}
                    if (rows.length > 0) results.push(rows);
                }}
                return results;
            }})()"""
            table_data = p.evaluate(js)
            if not table_data:
                return "(页面未检测到表格数据)"

            md_tables = []
            for t_idx, rows in enumerate(table_data, 1):
                if not rows:
                    continue
                headers = rows[0]
                lines = [f"### 表格 {t_idx}", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
                for r in rows[1:]:
                    padded = r + [""] * (len(headers) - len(r))
                    lines.append("| " + " | ".join(padded[:len(headers)]) + " |")
                md_tables.append("\n".join(lines))
            return "\n\n".join(md_tables)[:max_chars]

        elif mode == "html":
            js = f"""(() => {{
                const el = {json.dumps(selector)} ? document.querySelector({json.dumps(selector)}) : document.body;
                return el ? el.outerHTML : '';
            }})()"""
            html = str(p.evaluate(js) or "").strip()
            return html[:max_chars]

        else:
            # Default markdown mode: extract clean readable structure
            js = f"""(() => {{
                const root = {json.dumps(selector)} ? document.querySelector({json.dumps(selector)}) : document.body;
                if (!root) return '';
                
                // Clone and remove scripts/styles
                const clone = root.cloneNode(true);
                clone.querySelectorAll('script, style, noscript, svg, nav, footer').forEach(e => e.remove());

                let lines = [];
                for (const node of clone.querySelectorAll('h1, h2, h3, h4, h5, p, li, blockquote, pre')) {{
                    const tag = node.tagName.toLowerCase();
                    const text = node.innerText.trim().replace(/\\s+/g, ' ');
                    if (!text) continue;
                    if (tag === 'h1') lines.push('# ' + text);
                    else if (tag === 'h2') lines.push('## ' + text);
                    else if (tag === 'h3') lines.push('### ' + text);
                    else if (tag === 'h4') lines.push('#### ' + text);
                    else if (tag === 'li') lines.push('* ' + text);
                    else if (tag === 'blockquote') lines.push('> ' + text);
                    else lines.push(text);
                }}
                return lines.join('\\n\\n');
            }})()"""
            md = str(p.evaluate(js) or "").strip()
            if not md:
                md = str(p.evaluate("document.body.innerText") or "").strip()
            return md[:max_chars]

    def evaluate_script(self, script: str) -> Any:
        """Evaluate custom JavaScript expression in active page context."""
        return self.get_active_page().evaluate(script)

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


def attach_default_browser(
    host: str = "127.0.0.1",
    port: int = 9222,
    browser: str = "auto",
) -> BrowserSession:
    """Attach Playwright over CDP to the user's running Chrome/Edge/Brave instance."""
    global _GLOBAL_SESSION
    if _GLOBAL_SESSION is not None:
        try:
            if not _GLOBAL_SESSION.page.is_closed():
                return _GLOBAL_SESSION
        except Exception:
            pass
        _GLOBAL_SESSION = None

    if not is_cdp_ready(host=host, port=port):
        res = ensure_browser_with_cdp(port=port, browser=browser)
        if not res.get("ready"):
            raise ConnectionError(
                f"无法连接到浏览器调试端口 http://{host}:{port}。\n"
                f"{res.get('message', '请确认浏览器是否开启了 --remote-debugging-port=9222')}"
            )

    pw = sync_playwright().start()
    endpoint = f"http://{host}:{port}"
    pw_browser = pw.chromium.connect_over_cdp(endpoint)

    contexts = pw_browser.contexts
    if contexts:
        ctx = contexts[0]
    else:
        ctx = pw_browser.new_context()

    pages = ctx.pages
    if pages:
        active = pages[-1]
        for p in reversed(pages):
            if not p.url.startswith(("chrome-extension://", "devtools://", "edge://extensions")):
                active = p
                break
    else:
        active = ctx.new_page()

    session = BrowserSession(
        playwright=pw,
        browser=pw_browser,
        context=ctx,
        page=active,
        port=port,
        browser_type=browser,
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
