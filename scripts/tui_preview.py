#!/usr/bin/env python
"""Render headless previews of the uiu TUI (design review / regression eyeballing).

Usage:
    python scripts/tui_preview.py                 # all states -> docs/preview
    python scripts/tui_preview.py --only welcome  # one state
    python scripts/tui_preview.py --svg-only      # skip PNG rasterising

The app runs under textual's test harness with a stub client and a fake turn
runner, so no model or network is involved. Each state is written as SVG; when
Pillow is installed we also rasterise a PNG next to it.

Note: the headless driver reports a 256-colour terminal, so the exported SVG is
grayscale-ish. Layout and typography are faithful; colours are not.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from uiu.app import UiuApp  # noqa: E402
from uiu.app.messages import (  # noqa: E402
    TextChunk,
    ThoughtChunk,
    ToolCallEvent,
    ToolResultEvent,
    TurnDone,
)
from uiu.workspace import Workspace  # noqa: E402


class _StubClient:
    """Stands in for the LLM client; the fake runner never calls it."""


THOUGHT = (
    "先拆一下问题：用户想知道磁盘和内存占用。\n\n"
    "1. 先看 C 盘剩余空间；\n"
    "2. 再看内存使用率，80% 以上要提醒；\n"
    "3. 给一句结论和下一步建议。"
)

ANSWER = (
    "## 体检结果\n\n"
    "一切正常，关键指标如下：\n\n"
    "- CPU 占用 **12%**\n"
    "- 内存 41.2GB / 51.2GB\n\n"
    "| 项目 | 用量 | 状态 |\n|---|---|---|\n| CPU | 12% | 良好 |\n| 内存 | 80% | 偏高 |\n\n"
    "\u0060\u0060\u0060python\n"
    "def hello(name):\n"
    '    return f"hi {name}"\n'
    "\u0060\u0060\u0060\n"
)


def _make_ws(root: Path) -> Workspace:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md"):
        (root / name).write_text("# " + name, encoding="utf-8")
    return Workspace(root=root, soul="soul", identity="id", user="user",
                     memory="mem", skills=[])


def _runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
    import time
    emit(ThoughtChunk(THOUGHT))
    emit(ToolCallEvent("system_info", {}))
    time.sleep(0.05)
    emit(ToolResultEvent("system_info", "[ok] C 盘剩余 890GB · 内存 80%"))
    emit(TextChunk(ANSWER))
    emit(TurnDone("done", 1.6))


async def _boot(scratch: Path, *, recent: bool = True, theme: str = "uiu-dark"):
    shutil.rmtree(scratch, ignore_errors=True)
    ws = _make_ws(scratch)
    if recent:
        from uiu import sessions as S
        S.save_session(ws.root, "周报整理", [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "把上季度的周报表格整理成一张汇总表"},
            {"role": "assistant", "content": "好的，我先读一下表格。"},
        ])
    return UiuApp(_StubClient(), ws, model="deepseek-chat", cfg=None, app_cfg=None,
                  turn_runner=_runner, theme_name=theme)


async def _ask(app, pilot, text: str) -> None:
    composer = app.query_one("#composer")
    composer.focus_input()
    await pilot.press(*list(text))
    await pilot.press("enter")
    await pilot.pause(1.2)


def _states() -> dict:
    async def welcome(app, pilot, out):
        await pilot.pause(0.4)
        return app.export_screenshot()

    async def conversation(app, pilot, out):
        await _ask(app, pilot, "看看磁盘内存")
        return app.export_screenshot()

    async def help_overlay(app, pilot, out):
        await pilot.press("f1")
        await pilot.pause(0.5)
        return app.export_screenshot()

    async def palette(app, pilot, out):
        await pilot.press("ctrl+e")
        await pilot.pause(0.5)
        return app.export_screenshot()

    async def sessions(app, pilot, out):
        await pilot.press("ctrl+x")
        await pilot.pause(0.5)
        return app.export_screenshot()

    async def usage(app, pilot, out):
        await pilot.press("ctrl+u")
        await pilot.pause(0.5)
        return app.export_screenshot()

    async def status(app, pilot, out):
        await app._send("/status")
        await pilot.pause(0.5)
        return app.export_screenshot()

    async def search(app, pilot, out):
        await _ask(app, pilot, "看看磁盘内存")
        await pilot.press("ctrl+r")
        await pilot.pause(0.5)
        await pilot.press(*list("磁盘"))
        await pilot.pause(0.4)
        return app.export_screenshot()

    async def narrow(app, pilot, out):
        await _ask(app, pilot, "看看磁盘内存")
        await pilot.resize_terminal(80, 28)
        await pilot.pause(0.6)
        return app.export_screenshot()

    async def output(app, pilot, out):
        await app._send("/help")
        await pilot.pause(0.8)
        await app._send("/tools")
        await pilot.pause(0.8)
        return app.export_screenshot()

    async def history(app, pilot, out):
        msgs = []
        for i in range(46):
            msgs.append({"role": "user", "content": f"第 {i} 轮：帮我看一下服务 {i} 的状态"})
            msgs.append({"role": "assistant", "content": f"服务 {i} 运行正常，延迟 12ms。"})
        from uiu.app.widgets import ChatView
        chat = app.query_one("#chat", ChatView)
        app._messages = list(msgs)
        await chat.load_transcript(msgs)
        for _ in range(80):
            if chat.query("#folded-hint") and chat.row_count() >= ChatView.MAX_LIVE:
                break
            await pilot.pause(0.25)
        chat._stick = False
        chat.scroll_to(y=0, animate=False)
        await pilot.pause(0.8)
        return app.export_screenshot()

    return {
        "welcome": (welcome, (118, 36)),
        "conversation": (conversation, (118, 36)),
        "narrow": (narrow, (118, 36)),
        "output": (output, (118, 36)),
        "history": (history, (118, 36)),
        "help": (help_overlay, (118, 36)),
        "palette": (palette, (118, 36)),
        "sessions": (sessions, (118, 36)),
        "usage": (usage, (118, 36)),
        "status": (status, (118, 36)),
        "search": (search, (118, 36)),
    }


# --------------------------------------------------------------------------
# optional rasterising (Pillow)
# --------------------------------------------------------------------------

CELL, LINE, FONT_SIZE = 12.2, 24.4, 20


def _svg_to_png(svg: str, png: Path, cols: int, rows: int) -> bool:
    try:
        import unicodedata

        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False

    styles: dict[str, str] = {}
    for m in re.finditer(r"\.([\w-]+)\s*\{([^}]*)\}", svg):
        fill = re.search(r"fill:\s*([^;]+)", m.group(2))
        if fill:
            styles[m.group(1)] = fill.group(1).strip()

    marker = re.search(
        r'<g transform="translate\(([-\d.]+),\s*([-\d.]+)\)"\s+clip-path', svg)
    if marker:
        dx, dy = float(marker.group(1)), float(marker.group(2))
        body = svg[marker.start():]
    else:
        dx = dy = 0.0
        body = svg.split("</defs>", 1)[-1]

    fonts = {}
    for key, name in (("sym", "seguisym.ttf"), ("cjk", "msyh.ttc"), ("mono", "consola.ttf")):
        try:
            fonts[key] = ImageFont.truetype(f"C:/Windows/Fonts/{name}", FONT_SIZE)
        except Exception:
            fonts[key] = ImageFont.load_default()

    def unescape(s: str) -> str:
        return (s.replace("&#160;", " ").replace("&amp;", "&").replace("&lt;", "<")
                 .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))

    texts, rects = [], []
    for m in re.finditer(r"<(text|rect)\b([^>]*?)(/>|>(.*?)</\1>)", body, re.S):
        tag, attrs, _close, inner = m.group(1), m.group(2), m.group(3), m.group(4)

        def attr(name: str, attrs: str = attrs) -> str | None:
            hit = re.search(name + r'="([^"]*)"', attrs)
            return hit.group(1) if hit else None

        classes = (attr("class") or "").split()
        fill = attr("fill") or (styles.get(classes[-1]) if classes else None)
        if tag == "rect":
            rects.append((float(attr("x") or 0), float(attr("y") or 0),
                          float(attr("width") or 0), float(attr("height") or 0), fill))
        elif tag == "text" and inner is not None:
            texts.append((float(attr("x") or 0), float(attr("y") or 0),
                          unescape(inner), fill))

    img = Image.new("RGB", (int(cols * CELL + dx + 2 * CELL),
                            int(rows * LINE + dy + CELL)), "#0b1016")
    draw = ImageDraw.Draw(img)
    for x, y, w, h, fill in rects:
        if w > 0 and h > 0:
            draw.rectangle([(x + dx), (y + dy), (x + w + dx) - 1, (y + h + dy) - 1],
                           fill=fill or "#000000")
    for x, y, text, fill in texts:
        cx = (round(x / CELL) * CELL + dx)
        top = y + dy - FONT_SIZE + 2
        for ch in text:
            if ch == "\n":
                continue
            wide = unicodedata.east_asian_width(ch) in ("W", "F")
            font = fonts["cjk"] if wide else fonts["sym"]
            cellw = CELL * (2 if wide else 1)
            draw.text((cx + 1 if wide else cx, top), ch, font=font,
                      fill=fill or "#cccccc")
            cx += cellw
    img.save(png)
    return True


# --------------------------------------------------------------------------


async def _render(name: str, fn, size, out_dir: Path, want_png: bool) -> Path:
    app = await _boot(out_dir / "_scratch")
    async with app.run_test(size=size) as pilot:
        svg = await fn(app, pilot, out_dir)
    svg_path = out_dir / f"{name}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    if want_png:
        _svg_to_png(svg, out_dir / f"{name}.png", size[0], size[1])
    return svg_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="render headless uiu TUI previews")
    ap.add_argument("--out", default=str(ROOT / "docs" / "preview"))
    ap.add_argument("--only", default="", help="render a single state by name")
    ap.add_argument("--svg-only", action="store_true", help="skip PNG rasterising")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    states = _states()
    names = [args.only] if args.only else list(states)
    for name in names:
        if name not in states:
            print(f"unknown state: {name}（可选：{', '.join(states)}）", file=sys.stderr)
            return 2
        fn, size = states[name]
        path = asyncio.run(_render(name, fn, size, out_dir, not args.svg_only))
        print(f"[ok] {path}")
    shutil.rmtree(out_dir / "_scratch", ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
