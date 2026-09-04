"""联网检索：web_search（DuckDuckGo，无 key 零依赖）+ web_extract（正文抽取）."""

from __future__ import annotations

import html as _html
import re
import urllib.parse
import urllib.request


def _http(url: str, data: bytes | None = None, timeout: int = 20, max_bytes: int = 512 * 1024) -> tuple[bytes, str]:
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) uiu/0.1",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        chunks, total = [], 0
        while True:
            blk = resp.read(65536)
            if not blk:
                break
            total += len(blk)
            if total > max_bytes:
                break
            chunks.append(blk)
        ctype = resp.headers.get("Content-Type", "")
        return b"".join(chunks), ctype


def web_search(query: str, count: int = 5) -> str:
    """DuckDuckGo lite 搜索，无需 key。"""
    query = (query or "").strip()
    if not query:
        return "[error] query 不能为空"
    if len(query) > 500:
        return "[error] query 过长"
    try:
        count = max(1, min(int(count or 5), 10))
    except (TypeError, ValueError):
        return "[error] count 须为数字"
    try:
        data = urllib.parse.urlencode({"q": query}).encode()
        raw, _ = _http("https://lite.duckduckgo.com/lite/", data=data, timeout=20)
        text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        return f"[error] 搜索失败: {type(e).__name__}: {e}"
    # lite 页：result-link 锚点 + 紧随的 snippet（单/双引号、属性顺序都不固定，逐个锚点解析）
    results = []
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", text, re.S | re.I):
        attrs, title = m.group(1), m.group(2)
        if "result-link" not in attrs:
            continue
        hm = re.search(r"""href=['"]([^'"]+)['"]""", attrs)
        if hm:
            results.append((hm.group(1), title))
    snips = re.findall(r"""class=['"]result-snippet['"][^>]*>(.*?)</td>""", text, re.S | re.I)

    def _clean(s: str) -> str:
        s = re.sub(r"<[^>]+>", "", s)
        return _html.unescape(s).strip()

    if not results:
        return f"(无结果: {query})"
    out = []
    for i, (href, title) in enumerate(results[:count]):
        snip = _clean(snips[i]) if i < len(snips) else ""
        out.append(f"{i + 1}. {_clean(title)}\n   {href}" + (f"\n   {snip[:200]}" if snip else ""))
    return "\n".join(out)


def web_extract(url: str, max_chars: int = 8000) -> str:
    """抓页面并抽正文（去标签/脚本），只收 http(s)，防 file/data/内网 SSRF 放大。"""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "[error] 仅支持 http(s) URL"
    if len(url) > 2000:
        return "[error] URL 过长"
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1") or host.startswith(("10.", "192.168.", "172.")):
        return "[error] 内网地址拒绝抓取"
    try:
        max_chars = max(500, min(int(max_chars or 8000), 30000))
    except (TypeError, ValueError):
        return "[error] max_chars 须为数字"
    try:
        raw, ctype = _http(url, timeout=20)
    except Exception as e:
        return f"[error] 抓取失败: {type(e).__name__}: {e}"
    if "html" not in ctype and b"<html" not in raw[:2000].lower():
        try:
            return raw.decode("utf-8", errors="replace")[:max_chars]
        except Exception as e:
            return f"[error] 解码失败: {e}"
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…（已截断，共 {len(text)} 字符）"
    return text or "(页面无正文)"


WEB_SEARCH_DEF = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "联网搜索（DuckDuckGo，无需配置）。查资料/新闻/文档时用，返回标题+链接+摘要。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "count": {"type": "integer", "description": "结果数（默认5，最多10）"},
            },
            "required": ["query"],
        },
    },
}

WEB_EXTRACT_DEF = {
    "type": "function",
    "function": {
        "name": "web_extract",
        "description": "抓取网页正文（自动去导航/广告标签）。读搜索结果、文档页面时用。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "description": "最多字符（默认8000）"},
            },
            "required": ["url"],
        },
    },
}

WEB_TOOLS: dict[str, dict] = {
    "web_search": {"def": WEB_SEARCH_DEF, "fn": web_search},
    "web_extract": {"def": WEB_EXTRACT_DEF, "fn": web_extract},
}


def web_tool_defs() -> list[dict]:
    return [t["def"] for t in WEB_TOOLS.values()]
