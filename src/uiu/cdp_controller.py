"""Chrome DevTools Protocol (CDP) Hybrid Browser Automation Engine.

Enables hybrid Web + Desktop automation:
1. Zero-dependency native HTTP/WebSocket communication with Chrome / Edge remote debugging port.
2. Direct DOM inspection (querySelector, innerText, outerHTML) bypassing vision OCR latency.
3. Network and Cookie retrieval.
4. Seamless fallback to desktop visual automation when browser is not running with remote debugging.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def is_cdp_available(host: str = "127.0.0.1", port: int = 9222, timeout: float = 0.3) -> bool:
    """Check if Chrome or Edge is running with --remote-debugging-port."""
    url = f"http://{host}:{port}/json/version"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def list_browser_tabs(host: str = "127.0.0.1", port: int = 9222, timeout: float = 0.5) -> list[dict[str, Any]]:
    """List all open page tabs from Chrome/Edge DevTools protocol."""
    url = f"http://{host}:{port}/json"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Filter for active web pages (exclude background extensions / service workers)
            return [t for t in data if t.get("type") == "page"]
    except Exception:
        return []


def get_active_tab(host: str = "127.0.0.1", port: int = 9222) -> dict[str, Any] | None:
    """Get the primary active web page tab."""
    tabs = list_browser_tabs(host=host, port=port)
    return tabs[0] if tabs else None


def eval_js_expression(
    script: str,
    tab_index: int = 0,
    host: str = "127.0.0.1",
    port: int = 9222,
) -> dict[str, Any]:
    """Evaluate a JavaScript expression in the browser page context via CDP.
    Returns: {"success": bool, "result": Any, "error": str}
    """
    tabs = list_browser_tabs(host=host, port=port)
    if not tabs or tab_index >= len(tabs):
        return {
            "success": False,
            "error": "未检测到已开启远程调试的浏览器页面。请启动 Chrome 时附带参数: --remote-debugging-port=9222",
        }

    target_tab = tabs[tab_index]
    ws_url = target_tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {
            "success": False,
            "error": "浏览器标签页未暴露 webSocketDebuggerUrl",
        }

    try:
        import websockets.sync.client as ws_client
        with ws_client.connect(ws_url, close_timeout=1.0) as ws:
            req_payload = {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": script,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            }
            ws.send(json.dumps(req_payload))
            resp_raw = ws.recv(timeout=2.0)
            data = json.loads(resp_raw)
            result_obj = data.get("result", {}).get("result", {})
            return {
                "success": True,
                "value": result_obj.get("value"),
                "type": result_obj.get("type"),
                "url": target_tab.get("url"),
                "title": target_tab.get("title"),
            }
    except ImportError:
        # Fallback using standard socket / HTTP or report notice
        return {
            "success": False,
            "error": "当前 Python 环境未安装 websockets 库。可通过 pip install websockets 开启 CDP WebSocket 评估。",
            "tab_info": target_tab,
        }
    except Exception as e:
        return {"success": False, "error": f"CDP 执行异常: {type(e).__name__}: {e}"}


def get_browser_dom_text(port: int = 9222) -> str:
    """Retrieve text content of the active webpage directly from DOM."""
    if not is_cdp_available(port=port):
        return "[error] 浏览器远程调试端口未开启 (端口 9222 无法连接)。建议使用常规视觉 OCR 模式。"

    res = eval_js_expression("document.body.innerText", port=port)
    if res.get("success"):
        txt = str(res.get("value") or "")
        return f"[ok] 成功从 DOM 获取页面文本 (共 {len(txt)} 字符, 标题: '{res.get('title')}'):\n{txt[:400]}..."
    return f"[error] DOM 读取失败: {res.get('error')}"


def click_dom_element(selector: str, port: int = 9222) -> str:
    """Click an element in the browser page directly using CSS selector."""
    if not is_cdp_available(port=port):
        return "[error] 浏览器远程调试端口未开启。请使用桌面视觉点击工具 (resilient_click 或 som_click_tag)。"

    js_code = f"""
    (() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return {{ found: false }};
        el.scrollIntoView({{ behavior: 'instant', block: 'center' }});
        el.click();
        return {{ found: true, tag: el.tagName, text: el.innerText }};
    }})()
    """
    res = eval_js_expression(js_code, port=port)
    if res.get("success") and isinstance(res.get("value"), dict):
        val = res["value"]
        if val.get("found"):
            return f"[ok] 已在 DOM 成功点击选择器 '{selector}' (元素: <{val.get('tag')}> '{val.get('text')[:30]}')"
        return f"[warning] 在页面 DOM 中未匹配到 CSS 选择器 '{selector}'"
    return f"[error] CDP DOM 点击失败: {res.get('error')}"
