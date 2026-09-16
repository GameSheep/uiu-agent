"""ChatView: 可滚动消息区。

渲染 user / assistant / tool / notice / error / thought 各类消息行。
assistant 行是就地更新的 Markdown，token 流式到达即渲染；已完成的行不重建。
底部自动跟随，用户上滚后停跟。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label, Markdown, Static

from ..theme import glyph, palette

# 角色 -> (字形, 中文名, 颜色键)
ROLE_META: dict[str, tuple[str, str, str]] = {
    "user": ("user", "你", "primary"),
    "assistant": ("agent", "agent", "accent"),
    "thought": ("thought", "思考", "secondary"),
    "notice": ("notice", "系统", "muted"),
    "error": ("error", "错误", "error"),
}


def _stamp() -> str:
    return datetime.now().strftime("%H:%M")


def _pal(widget: Any):
    """Palette for *widget*, safe to call before the widget is mounted."""
    try:
        return palette(widget.app)
    except Exception:
        from ..theme import DEFAULT_THEME, THEMES
        return THEMES[DEFAULT_THEME]


class Bubble(Widget):
    """单条消息：角色行 + 正文。"""

    def __init__(
        self,
        role: str,
        text: str,
        *,
        agent_name: str = "agent",
        kind: str = "md",
        who: str | None = None,
        meta: str | None = None,
    ) -> None:
        super().__init__()
        self.role = role
        self.agent_name = agent_name
        self._text = text
        self._kind = kind
        self._who_override = who
        self._meta_override = meta
        self._streaming = False
        self.stamp = _stamp()

    # -- rendering -------------------------------------------------------

    def _role_color(self, pal) -> str:
        _, _, key = ROLE_META.get(self.role, ("notice", self.role, "muted"))
        return {
            "primary": pal.primary,
            "accent": pal.accent,
            "secondary": pal.secondary,
            "error": pal.error,
            "muted": pal.panel,
        }.get(key, pal.panel)

    def head_text(self) -> Text:
        g, label, _ = ROLE_META.get(self.role, ("•", self.role, "muted"))
        who = self._who_override or (self.agent_name if self.role == "assistant" else label)
        pal = _pal(self)
        t = Text()
        t.append(glyph(g, "•") + " ", style=f"bold {self._role_color(pal)}")
        t.append(who, style=f"bold {pal.foreground}")
        if self._streaming and self.role == "assistant":
            t.append("  正在生成…", style="dim")
        return t

    def meta_text(self) -> Text:
        return Text(self._meta_override if self._meta_override is not None else self.stamp,
                    style="dim")

    def copyable(self) -> bool:
        """Only messages the user may want to take away get a copy affordance.

        Deliberately not text-dependent: streaming bubbles start empty and the
        button must already exist when the first token lands.
        """
        return self.role in ("assistant", "error")

    def compose(self) -> ComposeResult:
        if self.role != "notice":
            with Horizontal(classes="bubble-head"):
                yield Static(self.head_text(), classes="bubble-who")
                yield Static(self.meta_text(), classes="bubble-meta")
                if self.copyable():
                    yield Button(glyph("copy"), id="copy-btn", classes="copy-btn")
        yield self._body()

    def _body(self) -> Widget:
        if self._kind == "plain":
            return Static(Text(self._render_text()), id="md-body")
        return Markdown(self._render_text(), id="md-body")

    def _render_text(self) -> str:
        text = self._text
        if self._streaming:
            text = (text or "") + glyph("cursor")
        return text

    # -- updates ---------------------------------------------------------

    def _body_widget(self) -> Widget | None:
        try:
            return self.query_one("#md-body")
        except Exception:
            return None

    def update_content(self, text: str) -> None:
        self._text = text
        body = self._body_widget()
        if body is None:
            return
        try:
            if isinstance(body, Markdown):
                body.update(self._render_text())
            else:
                body.update(Text(self._render_text()))
        except Exception:
            pass

    def set_streaming(self, streaming: bool) -> None:
        if self._streaming == streaming:
            return
        self._streaming = streaming
        self.update_content(self._text)
        if self.role == "assistant":
            try:
                self.query_one(".bubble-who", Static).update(self.head_text())
            except Exception:
                pass

    def get_text(self) -> str:
        return self._text


class ToolRow(Bubble):
    """一次工具调用：折叠成一行，点一下展开完整返回。"""

    def __init__(
        self,
        name: str,
        ok: bool = True,
        preview: str = "",
        *,
        detail: str = "",
        seconds: float | None = None,
        args: str = "",
        agent_name: str = "agent",
        running: bool = False,
    ) -> None:
        super().__init__("notice", "", agent_name=agent_name)
        self.tool_name = name
        self.ok = ok
        self.preview = preview
        self.detail = detail or preview
        self.seconds = seconds
        self.args = args
        self.running = running
        self._frame = 0
        self._open = False
        self.add_class("-tool")
        self.add_class("-clickable")   # 整行可点，光标要提示出来

    def head_text(self) -> Text:
        pal = _pal(self)
        t = Text()
        t.append(glyph("tool") + " ", style=f"bold {pal.accent}")
        t.append(self.tool_name, style=f"bold {pal.foreground}")
        t.append("  ")
        if self.running:
            spin = glyph("spinner")
            t.append(spin[self._frame % len(spin)], style=f"bold {pal.warning}")
            t.append(" 运行中", style=pal.warning)
        else:
            color = pal.success if self.ok else pal.error
            t.append(glyph("ok") if self.ok else glyph("fail"), style=f"bold {color}")
        # 结果摘要紧跟工具名，meta 只留耗时/展开提示
        if self.running:
            if self.args:
                t.append("   " + self.args, style="dim")
        elif self.preview:
            t.append("   " + self.preview, style="dim")
        return t

    def meta_text(self) -> Text:
        if self.running:
            return Text("")
        bits: list[str] = []
        if self.seconds is not None:
            bits.append(f"{self.seconds:.1f}s")
        if self.detail and self.detail != self.preview:
            bits.append("[点击展开]")
        return Text("  ".join(bits), style="dim")

    MAX_DETAIL = 4000   # 展开的正文上限：超大工具返回不能拖垮渲染

    def _body_text(self) -> Text:
        body = Text()
        if self.args:
            body.append(glyph("arrow") + " 参数  ", style="bold")
            body.append(self.args + "\n", style="dim")
        detail = self.detail or ""
        if len(detail) > self.MAX_DETAIL:
            body.append(detail[: self.MAX_DETAIL], style="dim")
            body.append(f"\n… 已截断，完整返回共 {len(detail)} 字", style="dim italic")
        else:
            body.append(detail, style="dim")
        return body

    def compose(self) -> ComposeResult:
        with Horizontal(classes="bubble-head"):
            yield Static(self.head_text(), classes="bubble-who")
            yield Static(self.meta_text(), classes="bubble-meta")
        yield Static(self._body_text(), id="tool-detail", classes="tool-detail")

    def get_text(self) -> str:
        mark = "…" if self.running else (glyph("ok") if self.ok else glyph("fail"))
        return f"{glyph('tool')} {self.tool_name} {mark} {self.preview}"

    # -- live updates ----------------------------------------------------

    def _refresh(self) -> None:
        try:
            self.query_one(".bubble-who", Static).update(self.head_text())
            self.query_one(".bubble-meta", Static).update(self.meta_text())
            self.query_one("#tool-detail", Static).update(self._body_text())
        except Exception:
            pass

    def set_result(self, ok: bool, preview: str, *, detail: str = "",
                   seconds: float | None = None) -> None:
        self.ok = ok
        self.preview = preview
        self.detail = detail or preview
        self.seconds = seconds
        self.running = False
        self._refresh()

    def tick(self, frame: int) -> None:
        """Animate the spinner while the tool is in flight."""
        if not self.running:
            return
        self._frame = frame
        try:
            self.query_one(".bubble-who", Static).update(self.head_text())
        except Exception:
            pass

    def toggle(self) -> None:
        self._open = not self._open
        try:
            body = self.query_one("#tool-detail", Static)
            body.set_class(self._open, "-open")
        except Exception:
            pass

    def on_click(self) -> None:
        self.toggle()


class OutputRow(Bubble):
    """斜杠命令的输出：长输出折叠成一行，点一下展开。"""

    COLLAPSE_OVER_LINES = 12

    def __init__(self, command: str, text: str, *, agent_name: str = "agent",
                 lines: int | None = None) -> None:
        super().__init__("notice", text, agent_name=agent_name)
        self.add_class("-output")
        self.command = command or ""
        # 行数按原始输出算（正文外面可能包了代码围栏）
        self.lines = int(lines) if lines else text.count("\n") + 1
        self._open = True
        if self.lines > self.COLLAPSE_OVER_LINES:
            self.set_open(False)
            self.add_class("-clickable")
        else:
            self.set_class(True, "-open")

    def collapsible(self) -> bool:
        return self.lines > self.COLLAPSE_OVER_LINES

    def head_text(self) -> Text:
        pal = _pal(self)
        t = Text()
        t.append(glyph("prompt") + " ", style=f"bold {pal.accent}")
        t.append(self.command or "输出", style=f"bold {pal.foreground}")
        t.append(f"  {self.lines} 行", style="dim")
        return t

    def meta_text(self) -> Text:
        if not self.collapsible():
            return Text("")
        return Text("[点击收起]" if self._open else "[点击展开]", style="dim")

    def compose(self) -> ComposeResult:
        with Horizontal(classes="bubble-head"):
            yield Static(self.head_text(), classes="bubble-who")
            yield Static(self.meta_text(), classes="bubble-meta")
        yield self._body()

    def set_open(self, opened: bool) -> None:
        self._open = opened
        self.set_class(opened, "-open")
        try:
            self.query_one(".bubble-meta", Static).update(self.meta_text())
        except Exception:
            pass

    def on_click(self) -> None:
        if self.collapsible():
            self.set_open(not self._open)


class ThoughtRow(Bubble):
    """推理过程：流式时展开，结束后长文自动折叠成一行，点一下展开。"""

    COLLAPSE_OVER = 160   # 超过这个字数，思考结束后自动收起

    def __init__(self, *, agent_name: str = "agent") -> None:
        super().__init__("thought", "", agent_name=agent_name)
        self.add_class("-thought-row")
        self._done = False
        self._open = True
        self.set_class(True, "-open")   # CSS 默认隐藏正文，展开态靠 -open
        self._started = time.monotonic()
        self.elapsed = 0.0

    # -- head / meta -----------------------------------------------------

    def head_text(self) -> Text:
        pal = _pal(self)
        t = Text()
        t.append(glyph("thought") + " ", style=f"bold {pal.secondary}")
        if self._done:
            t.append("思考过程", style=f"bold {pal.foreground}")
            n = len(self.get_text() or "")
            if n:
                t.append(f"  {n} 字", style="dim")
            if self.elapsed:
                t.append(f"  " + glyph("sep") + f"  {self.elapsed:.1f}s", style="dim")
        else:
            t.append("思考中…", style=f"bold {pal.secondary}")
        return t

    def meta_text(self) -> Text:
        if self._done and (self.get_text() or "").strip():
            return Text("[点击收起]" if self._open else "[点击展开]", style="dim")
        return Text("")

    # -- behaviour -------------------------------------------------------

    def finish(self) -> None:
        self._done = True
        self.add_class("-clickable")
        self.elapsed = time.monotonic() - self._started
        if len(self.get_text() or "") > self.COLLAPSE_OVER:
            self.set_open(False)
        else:
            self._refresh()

    def set_open(self, opened: bool) -> None:
        self._open = opened
        self.set_class(opened, "-open")
        self._refresh()

    def _refresh(self) -> None:
        try:
            self.query_one(".bubble-who", Static).update(self.head_text())
            self.query_one(".bubble-meta", Static).update(self.meta_text())
        except Exception:
            pass

    def on_click(self) -> None:
        if self._done:
            self.set_open(not self._open)


class WelcomeBanner(Vertical):
    """空态首屏：品牌卡 + 能力徽章 + 建议起点。"""

    CAPABILITIES: list[tuple[str, str]] = [
        ("⚙", "68 工具"),
        ("◉", "屏幕 OCR"),
        ("⌘", "桌面控制"),
        ("⏱", "宏 / 定时"),
        ("✉", "消息渠道"),
        ("✦", "长期记忆"),
    ]

    def __init__(self, agent_name: str, *, version: str = "", tools_n: int = 0,
                 skills_n: int = 0, suggestions: list[tuple[str, str]] | None = None,
                 recent: dict[str, Any] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self.version = version
        self.tools_n = tools_n
        self.skills_n = skills_n
        self.suggestions = suggestions or []
        self.recent = recent or {}

    def _ago(self, updated: float) -> str:
        import time as _t
        if not updated:
            return ""
        delta = max(0, int(_t.time() - updated))
        if delta < 60:
            return "刚刚"
        if delta < 3600:
            return f"{delta // 60} 分钟前"
        if delta < 86400:
            return f"{delta // 3600} 小时前"
        return f"{delta // 86400} 天前"

    def has_recent(self) -> bool:
        return bool(self.recent.get("id"))

    def compose(self) -> ComposeResult:
        with Vertical(id="intro-panel"):
            with Horizontal(classes="intro-head"):
                with Horizontal(classes="intro-brand"):
                    yield Label(glyph("brand"), classes="brand-mark")
                    yield Label("uiu", classes="brand-word")
                    yield Label(self.agent_name, classes="brand-agent")
                yield Label(self._status(), classes="intro-status")
            yield Label(self._tagline(), classes="intro-tagline")
            self._caps = Horizontal(classes="cap-row")
            yield self._caps
            yield Label(glyph("sep") + " 输入 /help 看全部命令，Ctrl+E 打开命令面板",
                        classes="intro-foot")

        if self.has_recent():
            with Vertical(id="resume-card"):
                with Horizontal(classes="resume-head"):
                    yield Label(self._resume_line(), classes="resume-line")
                    yield Button("载入", id="resume-btn", classes="resume-btn")
                if self.recent.get("teaser"):
                    yield Label(self.recent["teaser"], classes="resume-teaser")

        yield Label("从这些开始", classes="section-title")
        try:
            width = self.app.size.width
        except Exception:
            width = 100
        self._per_row = 2 if width >= 78 else 1
        self._rows = []
        for _ in range(0, len(self.suggestions), self._per_row):
            row = Horizontal(classes="sug-row")
            self._rows.append(row)
            yield row

    async def on_mount(self) -> None:
        try:
            width = self.app.size.width
        except Exception:
            width = 100
        if width >= 86:
            chips = self.CAPABILITIES
        elif width >= 68:
            chips = self.CAPABILITIES[:4]
        else:
            chips = self.CAPABILITIES[:3]
        for icon, text in chips:
            await self._caps.mount(Label(icon + " " + text, classes="cap-chip"))
        per_row = getattr(self, "_per_row", 2) or 2
        for i, (title, _prompt) in enumerate(self.suggestions):
            row = self._rows[i // per_row] if i // per_row < len(self._rows) else None
            if row is None:
                continue
            await row.mount(
                Button(glyph("arrow") + " " + title, id=f"sug-{i}",
                       classes="suggestion-chip")
            )

    def _status(self) -> str:
        bits = ["已就绪"]
        if self.tools_n:
            bits.append(f"{self.tools_n} 工具")
        if self.skills_n:
            bits.append(f"{self.skills_n} 技能")
        if self.version:
            bits.append("v" + self.version)
        return "  ".join([glyph("sep")] + bits) + "  "

    async def set_context(self, *, version: str = "", tools_n: int = 0,
                          skills_n: int = 0) -> None:
        """Update the live counts shown in the banner card."""
        self.version = version or self.version
        self.tools_n = tools_n or self.tools_n
        self.skills_n = skills_n or self.skills_n
        try:
            self.query_one(".intro-status", Label).update(self._status())
        except Exception:
            pass

    def _tagline(self) -> str:
        return "你的个人 IP agent —— 常驻在这台电脑上，替你动手。"

    def _resume_line(self) -> str:
        r = self.recent
        bits = [glyph("arrow"), f"继续 {r.get('id')}"]
        if r.get("turns"):
            bits.append(f"{r['turns']} 轮")
        ago = self._ago(float(r.get("updated") or 0))
        if ago:
            bits.append(ago)
        return "  ".join(bits)


class ChatView(VerticalScroll):
    """Scrollable list of message bubbles (chat layout)."""

    class SuggestionPicked(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class ResumePicked(Message):
        """User asked to load a previously saved session from the banner."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class CopyRequested(Message):
        """User clicked the copy affordance on a message."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class ExpandRequested(Message):
        """User clicked the "earlier messages folded" bar."""

    DEFAULT_CSS = """
    ChatView {
        background: $background;
        padding: 1 0 0 0;
        scrollbar-size-vertical: 1;
    }
    ChatView Bubble {
        height: auto;
        width: 100%;
        margin: 0 0 1 0;
        padding: 0 1 0 1;
        border: none;
        background: transparent;
    }
    ChatView Bubble.-user {
        border-left: thick $primary;
        background: $panel-lighten-1 55%;
    }
    ChatView Bubble.-assistant {
        border-left: thick $accent;
    }
    ChatView Bubble.-thought {
        border-left: thick $secondary 60%;
        color: $text-muted;
    }
    ChatView Bubble.-thought .bubble-who,
    ChatView Bubble.-thought Markdown {
        color: $text-muted;
        text-style: italic;
    }
    ChatView Bubble.-thought-row .bubble-who {
        text-style: none;
    }
    ChatView Bubble.-thought-row Markdown {
        display: none;
    }
    ChatView Bubble.-thought-row.-open Markdown {
        display: block;
        height: auto;
    }
    ChatView Bubble.-error {
        border-left: thick $error;
        background: $error 12%;
    }
    ChatView Bubble.-notice {
        border-left: none;
        padding: 0 1 0 4;
        color: $text-muted;
    }
    ChatView .bubble-head {
        height: 1;
    }
    ChatView .bubble-head .bubble-who {
        width: 1fr;
        height: 1;
        text-style: bold;
    }
    ChatView .bubble-head .bubble-meta {
        width: auto;
        height: 1;
        color: $text-muted;
    }
    ChatView .copy-btn {
        width: 3;
        min-width: 0;
        height: 1;
        margin: 0 0 0 1;
        padding: 0;
        border: none !important;
        background: transparent !important;
        color: $text-muted !important;
    }
    ChatView .copy-btn:hover {
        background: $panel-lighten-1 !important;
        color: $text !important;
    }
    ChatView Markdown, ChatView Static {
        background: transparent;
        height: auto;
    }
    /* ---- markdown 排版（代码块 / 行内码 / 标题 / 引用 / 表格）---- */
    ChatView Markdown {
        padding: 0 0;
    }
    ChatView MarkdownFence {
        background: $panel;
        border-left: thick $accent 70%;
        margin: 0 0 1 0;
        padding: 0;
    }
    ChatView MarkdownFence > Label {
        padding: 0 1;
    }
    ChatView .code_inline {
        background: $primary 25% !important;
        color: $text !important;
    }
    ChatView MarkdownH1 {
        color: $primary;
        text-style: bold;
        margin: 1 0 0 0;
    }
    ChatView MarkdownH2 {
        color: $primary 90%;
        text-style: bold;
        margin: 1 0 0 0;
    }
    ChatView MarkdownH3, ChatView MarkdownH4, ChatView MarkdownH5, ChatView MarkdownH6 {
        color: $secondary;
        text-style: bold;
        margin: 1 0 0 0;
    }
    ChatView MarkdownBlockQuote {
        border-left: thick $secondary 60%;
        padding: 0 1;
        color: $text-muted;
    }
    ChatView MarkdownBullet {
        color: $accent;
    }
    ChatView MarkdownHorizontalRule {
        color: $panel-lighten-2;
    }
    ChatView .markdown-table--lines {
        color: $panel-lighten-2;
    }
    ChatView .markdown-table--header {
        color: $accent;
        text-style: bold;
    }
    ChatView Bubble.-tool {
        border-left: thick $panel-lighten-2;
        padding: 0 1 0 2;
    }
    ChatView Bubble.-tool .bubble-who {
        text-style: none;
    }
    ChatView Bubble.-clickable {
        pointer: pointer;
    }
    ChatView Bubble.-clickable:hover {
        background: $panel 55%;
    }
    ChatView .tool-detail {
        display: none;
        color: $text-muted;
        padding: 0 0 0 3;
    }
    ChatView .tool-detail.-open {
        display: block;
        height: auto;
    }
    /* ---- 空态 / 首屏 ---- */
    ChatView #empty-hint {
        height: auto;
        padding: 0 3 1 3;
    }
    ChatView #intro-panel {
        border: round $primary 45%;
        background: $panel;
        padding: 1 2;
        margin: 0 0 1 0;
        height: auto;
    }
    ChatView .intro-head {
        height: 1;
    }
    ChatView .intro-brand {
        width: 1fr;
        height: 1;
    }
    ChatView .intro-brand .brand-mark {
        width: auto;
        color: $accent;
        text-style: bold;
        padding: 0 1 0 0;
    }
    ChatView .intro-brand .brand-word {
        width: auto;
        color: $primary;
        text-style: bold;
        padding: 0 1 0 0;
    }
    ChatView .intro-brand .brand-agent {
        width: auto;
        color: $text;
        text-style: bold;
    }
    ChatView .intro-status {
        width: auto;
        height: 1;
        color: $text-muted;
    }
    ChatView .intro-tagline {
        color: $text-muted;
        margin: 0 0 1 0;
        height: auto;
    }
    ChatView .cap-row {
        height: 1;
    }
    ChatView .cap-chip {
        width: auto;
        height: 1;
        background: $panel-lighten-1;
        color: $text;
        padding: 0 1;
        margin: 0 1 0 0;
    }
    ChatView .intro-foot {
        color: $text-muted;
        margin: 1 0 0 0;
        height: auto;
    }
    ChatView .section-title {
        color: $text-muted;
        text-style: bold;
        margin: 0 0 1 0;
        height: 1;
    }
    ChatView .sug-row {
        height: auto;
    }
    ChatView Bubble.-output {
        border-left: thick $panel-lighten-2;
        padding: 0 1 0 2;
    }
    ChatView Bubble.-output .bubble-who {
        text-style: none;
    }
    ChatView Bubble.-output .bubble-meta:hover {
        color: $text;
    }
    ChatView Bubble.-output Markdown {
        display: none;
    }
    ChatView Bubble.-output.-open Markdown {
        display: block;
        height: auto;
    }
    ChatView #folded-hint {
        height: 1;
        color: $text-muted;
        text-align: center;
        background: $panel;
        margin: 0 0 1 0;
    }
    ChatView #folded-hint:hover {
        background: $panel-lighten-1;
        color: $text;
    }
    ChatView #resume-card {
        border: round $accent 45%;
        background: $panel;
        padding: 0 1;
        margin: 0 0 1 0;
        height: auto;
    }
    ChatView .resume-head {
        height: 1;
    }
    ChatView .resume-head .resume-line {
        width: 1fr;
        height: 1;
        color: $accent;
        text-style: bold;
    }
    ChatView .resume-head .resume-btn {
        width: auto;
        min-width: 0;
        height: 1;
        padding: 0 1;
        border: none !important;
        background: $accent 30% !important;
        color: $text !important;
    }
    ChatView .resume-head .resume-btn:hover {
        background: $accent 55% !important;
    }
    ChatView .resume-teaser {
        color: $text-muted;
        height: auto;
    }
    ChatView Bubble.-flash {
        background: $primary 35%;
    }
    ChatView Button.suggestion-chip {
        width: 1fr;
        height: 3;
        margin: 0 1 1 0;
        background: $panel-lighten-1 !important;
        border: round $panel-lighten-2 !important;
        color: $text !important;
        content-align: left middle;
        text-align: left;
        padding: 0 1;
    }
    ChatView Button.suggestion-chip:hover {
        background: $primary 30% !important;
        border: round $primary !important;
    }
    ChatView Button.suggestion-chip:focus {
        background: $primary 40% !important;
        border: round $primary !important;
        color: $text !important;
    }
    """

    SUGGESTIONS: list[tuple[str, str]] = [
        ("看看磁盘和内存占用", "帮我看看磁盘和内存占用"),
        ("列出我有哪些技能", "列出我有哪些技能"),
        ("写一个问候语 skill", "帮我写一个问候语 skill"),
        ("这个项目怎么用", "解释一下这个项目怎么用"),
    ]

    STREAM_INTERVAL = 0.08   # 流式 markdown 重排节流（秒）
    MAX_LIVE = 60            # 常驻渲染的消息行数（超出折叠最早的）
    PAGE = 60                # 每次「展开更早」多加载的行数
    MAX_RENDER = 400         # 手动展开的硬上限

    def __init__(self, agent_name: str = "agent", *,
                 recent: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self.recent = recent or {}
        self._stick = True
        self._active: Bubble | None = None
        self._active_thought: Bubble | None = None
        self._pending = ""
        self._flush_timer: Any = None
        self._unread = False
        self._folded = 0
        self._expanded = False
        self._loading = False
        self._suspend_top_load = False
        self._user_scrolled_up = False
        self.window = self.MAX_LIVE
        self._suggestion_prompts: dict[str, str] = {}
        self.version = ""
        self.tools_n = 0
        self.skills_n = 0

    async def on_mount(self) -> None:
        await self.show_empty_hint()

    def _mk_bubble(self, role: str, text: str) -> Bubble:
        b = Bubble(role, text, agent_name=self.agent_name)
        if role in ("user", "assistant", "notice", "error", "thought"):
            b.set_classes("-" + role)
        return b

    async def show_empty_hint(self) -> None:
        if self.query("#empty-hint"):
            return
        self._suggestion_prompts = {
            f"sug-{i}": prompt for i, (_title, prompt) in enumerate(self.SUGGESTIONS)
        }
        banner = WelcomeBanner(
            self.agent_name,
            version=self.version,
            tools_n=self.tools_n,
            skills_n=self.skills_n,
            suggestions=self.SUGGESTIONS,
            recent=self.recent,
            id="empty-hint",
        )
        await self.mount(banner)
        # 空态从顶部看起（窄终端首屏比视口高，跟随底部会看不到品牌卡）
        self._stick = False
        try:
            await self.scroll_home(animate=False)
        except Exception:
            pass

    async def clear_chat(self) -> None:
        for child in list(self.children):
            await child.remove()
        self._active = None
        self._active_thought = None
        self._folded = 0
        self.window = self.MAX_LIVE
        self._expanded = False
        await self.show_empty_hint()

    # -- 长会话折叠 ------------------------------------------------------

    def _rows(self) -> list[Any]:
        return [w for w in self.children
                if getattr(w, "id", "") not in ("empty-hint", "folded-hint")]

    async def _update_fold_hint(self) -> None:
        if self._folded <= 0:
            return
        if self.window >= self.MAX_RENDER:
            # 到硬上限就不能再装了——别假装还能点开
            text = (f"{glyph('arrow')} 更早的 {self._folded} 条消息已折叠  "
                    f"{glyph('sep')}  已达上限（{self.MAX_RENDER} 条）")
        else:
            step = min(self.PAGE, self._folded)
            text = (f"{glyph('arrow')} 更早的 {self._folded} 条消息已折叠  "
                    f"{glyph('sep')}  点击展开（再展开 {step} 条）")
        existing = self.query("#folded-hint")
        if existing:
            try:
                existing.first().update(text)
            except Exception:
                pass
            return
        hint = Static(text, id="folded-hint")
        try:
            await self.mount(hint, before=0)
        except Exception:
            try:
                await self.mount(hint)
            except Exception:
                pass

    def _cap(self) -> int:
        return self.window

    async def trim_to_cap(self) -> int:
        """Fold the oldest rows so the transcript stays cheap to scroll."""
        rows = self._rows()
        over = len(rows) - self._cap()
        if over <= 0:
            return 0
        victims = rows[:over]
        try:
            await self.remove_children(victims)
        except Exception:
            for w in victims:
                try:
                    await w.remove()
                except Exception:
                    pass
        self._folded += len(victims)
        await self._update_fold_hint()
        return len(victims)

    def fold_all(self) -> None:
        """Collapse everything back to the live window."""
        self._folded = 0
        for w in self.query("#folded-hint"):
            try:
                w.remove()
            except Exception:
                pass

    def on_click(self, event: Any) -> None:
        widget = getattr(event, "widget", None)
        if widget is not None and getattr(widget, "id", "") == "folded-hint":
            self.post_message(self.ExpandRequested())
            try:
                event.stop()
            except Exception:
                pass

    async def _remove_empty_hint(self) -> None:
        for child in list(self.children):
            if child.id == "empty-hint":
                await child.remove()

    def _owner_bubble(self, widget: Any) -> Bubble | None:
        node = getattr(widget, "parent", None)
        while node is not None and not isinstance(node, Bubble):
            node = getattr(node, "parent", None)
        return node if isinstance(node, Bubble) else None

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("copy-btn"):
            owner = self._owner_bubble(event.button)
            if owner is not None and (owner.get_text() or "").strip():
                self.post_message(self.CopyRequested(owner.get_text()))
            event.stop()
            return
        if event.button.id == "resume-btn":
            sid = str(self.recent.get("id") or "")
            if sid:
                self.post_message(self.ResumePicked(sid))
            event.stop()
            return
        if event.button.has_class("suggestion-chip"):
            text = self._suggestion_prompts.get(event.button.id or "", "")
            if text:
                self.post_message(self.SuggestionPicked(text))
            event.stop()

    # -- message rows ----------------------------------------------------

    async def add_user(self, text: str) -> None:
        self._stick = True
        await self._remove_empty_hint()
        await self.finish_thought()
        if not self._loading:
            # 新一轮开始是安全的整理点：把最早的消息折起来
            try:
                await self.trim_to_cap()
            except Exception:
                pass
        await self.mount(self._mk_bubble("user", text))
        await self._auto_scroll()

    async def add_output(self, text: str, command: str = "") -> OutputRow:
        """Slash-command output: one collapsible row instead of a wall of text.

        Command output is preformatted (aligned columns, one item per line), so
        it goes into a fenced block — markdown would otherwise reflow it into a
        single paragraph.
        """
        await self._remove_empty_hint()
        await self.finish_thought()
        body = text
        if "\u0060\u0060\u0060" not in text:
            body = "\u0060\u0060\u0060\n" + text.rstrip() + "\n\u0060\u0060\u0060"
        row = OutputRow(command, body, agent_name=self.agent_name,
                        lines=text.count("\n") + 1)
        await self.mount(row)
        await self._auto_scroll()
        return row

    async def add_notice(self, text: str) -> None:
        await self._remove_empty_hint()
        await self.finish_thought()
        await self.mount(self._mk_bubble("notice", text))
        await self._auto_scroll()

    async def add_error(self, message: str) -> None:
        await self._remove_empty_hint()
        await self.finish_thought()
        b = self._mk_bubble("error", message)
        b._kind = "plain"
        await self.mount(b)
        await self._auto_scroll()

    async def add_tool(self, name: str, ok: bool, preview: str, *,
                       detail: str = "", seconds: float | None = None,
                       args: str = "") -> ToolRow:
        await self._remove_empty_hint()
        await self.finish_thought()
        row = ToolRow(name, ok, preview, detail=detail, seconds=seconds,
                      args=args, agent_name=self.agent_name)
        await self.mount(row)
        await self._auto_scroll()
        return row

    async def add_tool_call(self, name: str, args: str = "") -> ToolRow:
        """Mount a tool row immediately so the call is visible while it runs."""
        await self._remove_empty_hint()
        await self.finish_thought()
        row = ToolRow(name, running=True, preview="", args=args,
                      agent_name=self.agent_name)
        await self.mount(row)
        await self._auto_scroll()
        return row

    def running_tool_rows(self) -> list[ToolRow]:
        return [w for w in self.query(ToolRow) if getattr(w, "running", False)]

    def message_bubbles(self) -> list[Bubble]:
        """Searchable transcript rows (conversation + folded command output)."""
        return [b for b in self.query(Bubble)
                if (b.role in ("user", "assistant", "error")
                    or isinstance(b, OutputRow))
                and (b.get_text() or "").strip()]

    def scroll_to_bubble(self, bubble: Bubble) -> None:
        """Jump to a message and flash it so the eye can find it."""
        self._stick = False
        try:
            self.scroll_to_widget(bubble, animate=False, top=True, immediate=True)
        except Exception:
            try:
                bubble.scroll_visible(animate=False, top=True)
            except Exception:
                pass
        try:
            bubble.add_class("-flash")
            self.set_timer(1.4, lambda: bubble.remove_class("-flash"))
        except Exception:
            pass

    async def load_transcript(self, messages: list[dict], *,
                              cap: int | None = None, stick: bool = True) -> int:
        """Re-render a saved conversation (used when switching sessions).

        Only the newest *cap* messages are mounted by default; older ones are
        represented by a clickable "folded" bar so long histories stay cheap.
        """
        rows: list[tuple[str, str]] = []
        for m in messages or []:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "user":
                rows.append(("user", str(content)))
            elif role == "assistant" and str(content).strip():
                rows.append(("assistant", str(content)))

        limit = self.window if cap is None else cap
        limit = max(self.MAX_LIVE, min(int(limit), self.MAX_RENDER))
        hidden = max(0, len(rows) - limit)
        shown = rows[hidden:]

        # 总是从空白重建，避免旧内容残留（会话切换 / 展开历史都走这条路径）；
        # 注意 clear_chat 会把 window 复位，所以要在它之后再写窗口大小
        await self.clear_chat()
        self.window = limit
        self._expanded = limit > self.MAX_LIVE
        # 整个重建过程都要压住「滚到顶自动加载」：中途 scroll_y 会归零
        self._loading = True
        self._suspend_top_load = True
        rendered = 0
        try:
            for role, text in shown:
                if role == "user":
                    await self.add_user(text)
                else:
                    await self.mount(self._mk_bubble("assistant", text))
                rendered += 1
            self._folded = hidden
            # 折叠条按需重建（展开后要能消失）
            for w in list(self.query("#folded-hint")):
                try:
                    await w.remove()
                except Exception:
                    pass
            if hidden:
                await self._update_fold_hint()
            if stick:
                self._stick = True
                await self._auto_scroll()
        finally:
            self._loading = False
            self._suspend_top_load = False
        return rendered

    # -- 滚动位置 / 窗口锚点 ---------------------------------------------

    def top_visible_index(self) -> int:
        """Index within the mounted rows of the row at the viewport top."""
        try:
            y = self.scroll_offset.y
        except Exception:
            return 0
        for i, w in enumerate(self._rows()):
            try:
                if w.region.y + w.region.height > y:
                    return i
            except Exception:
                continue
        return 0

    def row_count(self) -> int:
        return len(self._rows())

    def anchor_to_index(self, index: int) -> None:
        """Keep the row at *index* pinned to the top of the viewport (sync)."""
        rows = self._rows()
        if not rows:
            return
        index = max(0, min(int(index), len(rows) - 1))
        self._stick = False
        row = rows[index]
        try:
            self.scroll_to_widget(row, animate=False, top=True, immediate=True)
        except Exception:
            try:
                row.scroll_visible(animate=False, top=True)
            except Exception:
                pass

    def anchor_to_index_later(self, index: int) -> None:
        """Anchor after the next layout pass.

        Right after a rebuild the rows have no geometry yet, so scrolling them
        into view silently clamps to 0 — which would look like "user scrolled to
        the top" and re-trigger the auto-load. The guard therefore stays on until
        the anchored scroll has actually landed.
        """
        self._suspend_top_load = True

        def _land() -> None:
            try:
                self.anchor_to_index(index)
            finally:
                self._suspend_top_load = False

        try:
            self.call_after_refresh(_land)
        except Exception:
            _land()

    def scroll_offset_y(self) -> float:
        try:
            return float(self.scroll_offset.y)
        except Exception:
            return 0.0

    async def restore_scroll(self, y: float) -> None:
        """Restore a remembered offset once the content is laid out."""
        self._stick = False
        self._pending_restore = max(0.0, float(y))
        try:
            self.scroll_to(y=self._pending_restore, animate=False)
        except Exception:
            pass
        try:
            self.call_after_refresh(self._restore_scroll_now)
        except Exception:
            pass

    def _restore_scroll_now(self) -> None:
        try:
            self.scroll_to(y=getattr(self, "_pending_restore", 0.0), animate=False)
        except Exception:
            pass

    def watch_scroll_y(self, old_value: Any, new_value: Any) -> None:
        """Hitting the top with history still folded loads the previous page.

        Only *user* scrolls arm this (程序化滚动 / 重建过程中的 scroll_y 归零不触发），
        otherwise a rebuild that clamps to 0 would chain-load the whole history.
        """
        super().watch_scroll_y(old_value, new_value)
        if not self._user_scrolled_up:
            return
        if self._loading or self._suspend_top_load or self._folded <= 0:
            return
        try:
            if float(new_value) <= 2.0:
                self._suspend_top_load = True
                self._user_scrolled_up = False
                self.post_message(self.ExpandRequested())
        except Exception:
            pass

    # -- streaming -------------------------------------------------------

    async def begin_thought(self) -> None:
        # 先把引用挂上再做任何 await：否则流式文本/工具事件可能在挂载前插队，
        # 导致思考块出现在回答之后（消息顺序错乱）。
        if self._active_thought is not None:
            return
        row = ThoughtRow(agent_name=self.agent_name)
        self._active_thought = row
        await self._remove_empty_hint()
        await self.mount(row)
        await self._auto_scroll()

    async def stream_thought(self, delta: str) -> None:
        if self._active_thought is None:
            await self.begin_thought()
        row = self._active_thought
        if row is not None:
            row.update_content((row.get_text() or "") + delta)
        await self._auto_scroll()

    async def finish_thought(self) -> None:
        if self._active_thought is not None:
            try:
                self._active_thought.finish()
            except Exception:
                pass
            self._active_thought = None
            await self._auto_scroll()

    async def begin_assistant(self) -> None:
        if self._active is not None:
            return
        self._stick = True
        bubble = self._mk_bubble("assistant", "")
        bubble.set_streaming(True)
        self._active = bubble
        await self._remove_empty_hint()
        await self.finish_thought()
        # 思考块可能在挂载前被 finish_thought 收掉，重挂时以当前引用为准
        await self.mount(bubble)
        await self._auto_scroll()

    async def stream(self, delta: str) -> None:
        """Buffer tokens and repaint at most every STREAM_INTERVAL seconds.

        Full markdown re-layout on every token is what makes streaming look
        janky; batching keeps the text smooth without losing the live feel.
        """
        if self._active is None:
            await self.begin_assistant()     # 顺带收掉还在流式的思考块
        elif self._active_thought is not None:
            await self.finish_thought()
        self._pending += delta
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        if self._flush_timer is not None:
            return
        try:
            self._flush_timer = self.set_timer(self.STREAM_INTERVAL, self._flush)
        except Exception:
            self._flush()

    def _flush(self) -> None:
        self._flush_timer = None
        if not self._pending or self._active is None:
            return
        chunk, self._pending = self._pending, ""
        try:
            self._active.update_content((self._active.get_text() or "") + chunk)
        except Exception:
            pass
        self.call_after_refresh(self._scroll_to_end_now)

    async def finish_assistant(self) -> None:
        self._flush()
        await self.finish_thought()
        if self._active is not None:
            self._active.set_streaming(False)
        self._active = None
        await self._auto_scroll()

    # -- scrolling -------------------------------------------------------

    def unread(self) -> bool:
        """True when new content arrived while the user was scrolled up."""
        return self._unread

    async def scroll_to_bottom(self) -> None:
        self._stick = True
        self._unread = False
        try:
            await self.scroll_end(animate=False)
        except Exception:
            pass

    async def _auto_scroll(self) -> None:
        if not self._stick:
            self._unread = True
            return
        try:
            await self.scroll_end(animate=False)
        except Exception:
            pass
        # 新挂载的行要等一次 layout 之后才在虚拟高度里，补一次滚动避免新行被挡
        try:
            self.call_after_refresh(self._scroll_to_end_now)
        except Exception:
            pass

    def _scroll_to_end_now(self) -> None:
        if not self._stick:
            return
        try:
            self.scroll_end(animate=False)
        except Exception:
            pass

    def _on_scroll_up(self, event: Any = None) -> None:
        # 滚动条上箭头（ScrollUp 消息）也算用户滚动；Textual 自己的同名方法
        # 会在 MRO 里照样执行，这里只补充状态。
        self._stick = False
        self._user_scrolled_up = True

    def _on_scroll_down(self, event: Any = None) -> None:
        self._stick = True
        self._unread = False
        self._user_scrolled_up = False

    def on_mouse_scroll_up(self, event: Any) -> None:
        self._stick = False
        self._user_scrolled_up = True

    def on_mouse_scroll_down(self, event: Any) -> None:
        self._stick = True
        self._unread = False
