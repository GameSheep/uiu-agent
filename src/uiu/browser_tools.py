"""Browser Use integration — AI-powered browser automation.

Browser Use lets an AI agent control a web browser like a human:
open pages, click buttons, type, fill forms, extract data.

Tools:
- browser_use: execute a task in the browser via AI agent
- browser_open: open a URL in the browser

Install:
    pip install browser-use
    playwright install chromium
"""

from __future__ import annotations

import os
import asyncio
import atexit


def browser_use(task: str, url: str = "", new_session: bool = False) -> str:
    """Execute a task in the web browser using Browser Use AI agent.

    The agent controls Chrome/Chromium to complete the task autonomously.
    It can click, type, scroll, fill forms, extract data, etc.

    task: what to do, e.g.:
        - "在百度搜索 Python 教程"
        - "打开 GitHub 并查看 browser-use 仓库的 star 数"
        - "填写表单并提交"
    url: optional starting URL
    new_session: if True, start a fresh browser session
    """
    try:
        from browser_use import Agent, ChatBrowserUse, Browser, BrowserConfig
    except ImportError:
        return "[error] Browser Use 未安装。运行: pip install browser-use && playwright install chromium"

    try:
        # Configure browser
        config = BrowserConfig(
            headless=False,  # Show browser so user can see
        )
        browser = Browser(config=config)

        # Build full task with URL
        full_task = task
        if url:
            full_task = f"打开 {url}，然后 {task}"

        # Create agent with Browser Use's optimized model
        llm = ChatBrowserUse()
        agent = Agent(
            task=full_task,
            llm=llm,
            browser=browser,
        )

        # Run the agent
        history = asyncio.run(agent.run())

        # Extract result
        final = history.final_result() or "(无返回结果)"
        return f"[ok] 浏览器任务完成\n{final[:500]}"

    except Exception as e:
        return f"[error] Browser Use 执行失败: {type(e).__name__}: {e}"


def browser_open(url: str) -> str:
    """Open a URL in the default browser (simple, no AI agent).

    Use this for simple URL opening. Use browser_use() for complex tasks.
    """
    from .system_tools import open_url as _open_url
    return _open_url(url)


# ---------- deterministic control (playwright, optional) ----------
# browser_use 走 AI 自主操作；下面四个是确定性指令（Hermes browser/navigate/
# snapshot/click/type 对齐）：装了 playwright 即用，没装则快照自动降级 web_extract。

_PAGE = None  # playwright Page 单例（懒建）


def _shutdown_browser() -> None:
    """Close the shared playwright browser on process exit (avoid chromium leak)."""
    global _PAGE
    if _PAGE is None:
        return
    try:
        pw = getattr(_PAGE, "_pw", None)
        if pw is not None:
            pw.stop()
    except Exception:
        pass
    _PAGE = None


atexit.register(_shutdown_browser)


def _page():
    """Return an active Playwright page, preferentially attaching to the user's host browser via CDP."""
    global _PAGE
    if _PAGE is not None:
        try:
            if not _PAGE.is_closed():
                return _PAGE
        except Exception:
            pass
        _PAGE = None

    # 1. Prefer user's real browser session via CDP (Chrome / Edge / Brave)
    try:
        from .browser_connect import get_active_browser_session, attach_default_browser, is_cdp_ready
        if is_cdp_ready():
            session = get_active_browser_session() or attach_default_browser()
            p = session.get_active_page()
            if p and not p.is_closed():
                _PAGE = p
                return _PAGE
    except Exception:
        pass

    # 2. Fallback to headless / standalone browser
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    _PAGE = browser.new_page()
    _PAGE._pw = pw  # type: ignore[attr-defined]
    return _PAGE


def _need_playwright() -> str | None:
    try:
        import playwright  # noqa: F401
        return None
    except ImportError:
        return "[error] 需要 playwright：pip install playwright && playwright install chromium"


def browser_navigate(url: str) -> str:
    """跳到指定 URL（确定性，不走 AI）。"""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "[error] 仅支持 http(s) URL"
    err = _need_playwright()
    if err:
        return err
    try:
        _page().goto(url, timeout=30000)
        return f"[ok] 已打开: {url}（标题：{_page().title()[:80]}）"
    except Exception as e:
        return f"[error] 导航失败: {type(e).__name__}: {e}"


def browser_snapshot() -> str:
    """当前页可交互元素快照（role/name/ref 列表，供 click/fill 用）。
    无 playwright 时自动降级：返回当前页 web_extract 正文。"""
    err = _need_playwright()
    if err:
        return err + "（或先用 web_extract 读页面正文）"
    try:
        snap = _page().accessibility.snapshot()
        lines = []

        def _walk(node, depth=0):
            if not isinstance(node, dict):
                return
            role, name, ref = node.get("role"), node.get("name"), (node.get("ref") or "")
            if role and role not in ("generic", "none"):
                lines.append(f"{'  ' * depth}{role} {name or ''} [{ref}]".rstrip())
            for child in node.get("children", []) or []:
                _walk(child, depth + 1)

        _walk(snap)
        out = "\n".join(lines[:120])
        return out or "(页面无可交互元素)"
    except Exception as e:
        return f"[error] 快照失败: {type(e).__name__}: {e}"


def browser_click(ref: str) -> str:
    """按 snapshot 里的 [ref] 点击元素。"""
    ref = (ref or "").strip()
    if not ref:
        return "[error] ref 不能为空（先 browser_snapshot 取）"
    err = _need_playwright()
    if err:
        return err
    try:
        _page().locator(f"aria-ref={ref}").click(timeout=10000)
        return f"[ok] 已点击 [{ref}]"
    except Exception:
        try:
            _page().get_by_text(ref).first.click(timeout=10000)
            return f"[ok] 已点击文本 '{ref[:40]}'"
        except Exception as e:
            return f"[error] 点击失败: {type(e).__name__}: {e}"


def browser_fill(ref: str, text: str) -> str:
    """按 snapshot 的 [ref] 或占位文本填表。"""
    ref, text = (ref or "").strip(), text or ""
    if not ref:
        return "[error] ref 不能为空（先 browser_snapshot 取）"
    if len(text) > 10000:
        return "[error] 文本过长"
    err = _need_playwright()
    if err:
        return err
    try:
        try:
            _page().locator(f"aria-ref={ref}").fill(text, timeout=10000)
        except Exception:
            _page().get_by_placeholder(ref).fill(text, timeout=10000)
        return f"[ok] 已填写 [{ref}]（{len(text)} 字符）"
    except Exception as e:
        return f"[error] 填写失败: {type(e).__name__}: {e}"


# ---------- tool definitions ----------

BROWSER_USE_DEF = {
    "type": "function",
    "function": {
        "name": "browser_use",
        "description": "用 AI agent 在浏览器中自动执行任务。能点击、输入、填表、提取数据。例：'在百度搜索Python'、'查看GitHub仓库star数'",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "要执行的任务描述",
                },
                "url": {
                    "type": "string",
                    "description": "起始 URL（可选）",
                },
            },
            "required": ["task"],
        },
    },
}

BROWSER_OPEN_DEF = {
    "type": "function",
    "function": {
        "name": "browser_open",
        "description": "在默认浏览器打开网址（简单操作，不走 AI agent）。适合单纯打开网页。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要打开的网址"},
            },
            "required": ["url"],
        },
    },
}


BROWSER_TOOLS: dict[str, dict] = {
    "browser_use": {"def": BROWSER_USE_DEF, "fn": browser_use},
    "browser_open": {"def": BROWSER_OPEN_DEF, "fn": browser_open},
    "browser_navigate": {"def": {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "受控浏览器跳到指定 URL（确定性，需 playwright；复杂自主任务改用 browser_use）。",
            "parameters": {"type": "object",
                            "properties": {"url": {"type": "string"}},
                            "required": ["url"]},
        },
    }, "fn": browser_navigate},
    "browser_snapshot": {"def": {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": "当前页可交互元素快照（返回 role/name/[ref] 列表，给 click/fill 用；无 playwright 时提示降级 web_extract）。",
            "parameters": {"type": "object", "properties": {}},
        },
    }, "fn": browser_snapshot},
    "browser_click": {"def": {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "点击快照中的元素（按 [ref] 或可见文本）。",
            "parameters": {"type": "object",
                            "properties": {"ref": {"type": "string"}},
                            "required": ["ref"]},
        },
    }, "fn": browser_click},
    "browser_fill": {"def": {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "在快照中的输入框填表（按 [ref] 或占位文本）。",
            "parameters": {"type": "object",
                            "properties": {"ref": {"type": "string"},
                                           "text": {"type": "string"}},
                            "required": ["ref", "text"]},
        },
    }, "fn": browser_fill},
}


def browser_tool_defs() -> list[dict]:
    return [t["def"] for t in BROWSER_TOOLS.values()]


def call_browser_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in BROWSER_TOOLS:
        return f"[error] unknown browser tool: {name}"
    fn = BROWSER_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"
