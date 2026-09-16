"""StatusBar: 底部状态条（模式 / agent / 上下文用量 / 计数 / 时钟）。

窄终端按宽度分档：先丢时钟，再丢会话名与工具计数，最后只留模式 + 模型 + 用量条。
"""

from __future__ import annotations

import time

from rich.table import Table
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from ..theme import glyph, palette


class StatusBar(Widget):
    """Compact status strip with a left info group and a right meta group."""

    mode: reactive[str] = reactive("idle")  # idle | running | error
    model: reactive[str] = reactive("-")
    turns: reactive[int] = reactive(0)
    ctx_pct: reactive[int] = reactive(0)
    tokens: reactive[int] = reactive(0)
    tools_n: reactive[int] = reactive(0)
    skills_n: reactive[int] = reactive(0)
    agent: reactive[str] = reactive("agent")
    session: reactive[str] = reactive("default")
    frame: reactive[int] = reactive(0)
    clock: reactive[str] = reactive("")
    elapsed: reactive[str] = reactive("")
    notice: reactive[str] = reactive("")
    toast: reactive[str] = reactive("")
    toast_kind: reactive[str] = reactive("info")   # info | error

    DEFAULT_CSS = """
    StatusBar {
        height: 2;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
        border-top: solid $panel-lighten-1;
    }
    """

    METER_CELLS = 12
    METER_CELLS_NARROW = 6

    # -- 宽度分档 ---------------------------------------------------------

    @staticmethod
    def _band(width: int) -> int:
        if width < 60:
            return 0     # 模式 + 模型 + 用量
        if width < 76:
            return 1     # + agent + 轮数
        if width < 88:
            return 2     # + 工具/技能
        if width < 104:
            return 3     # + 会话名
        return 4         # + 时钟

    def _meter(self, pal, cells: int) -> Text:
        filled = max(0, min(cells, round(self.ctx_pct / 100 * cells)))
        color = pal.success
        if self.ctx_pct >= 80:
            color = pal.error
        elif self.ctx_pct >= 55:
            color = pal.warning
        out = Text()
        out.append(glyph("meter_full") * filled, style=color)
        out.append(glyph("meter_empty") * (cells - filled), style=pal.boost or pal.panel)
        return out

    def _left(self, pal, band: int, cells: int) -> Text:
        t = Text()
        if self.mode == "running":
            spin = glyph("spinner")
            t.append(spin[self.frame % len(spin)] + " ", style=f"bold {pal.warning}")
            t.append("running", style=f"bold {pal.warning}")
            if self.elapsed:
                t.append(" " + self.elapsed, style=f"bold {pal.warning}")
        elif self.mode == "error":
            t.append(glyph("error") + " ", style=f"bold {pal.error}")
            t.append("error", style=f"bold {pal.error}")
        else:
            t.append(glyph("dot_idle") + " ", style=f"bold {pal.success}")
            t.append("idle", style="dim")
        t.append("  ")
        if band >= 1:
            t.append(self.agent or "agent", style=f"bold {pal.primary}")
            t.append(" " + glyph("sep") + " ", style="dim")
        t.append(self.model or "-", style=pal.foreground)
        if band >= 1:
            t.append("  ")
            t.append("turns ", style="dim")
            t.append(str(self.turns), style=pal.secondary)
        t.append("  ")
        if self.toast:
            color = pal.error if self.toast_kind == "error" else pal.accent
            t.append(self.toast, style=f"bold {color}")
            t.append("  ")
        if self.notice:
            t.append(self.notice, style=f"bold {pal.accent}")
            t.append("  ")
        t.append("ctx ", style="dim")
        t.append_text(self._meter(pal, cells))
        t.append(f" {self.ctx_pct}%", style="dim")
        if band >= 3 and self.tokens:
            tok = self.tokens
            shown = f"{tok / 1000:.1f}k" if tok >= 1000 else str(tok)
            t.append(f" ={shown}tok", style="dim")
        return t

    def _right(self, pal, band: int) -> Text:
        t = Text()
        if band >= 2:
            t.append("tools ", style="dim")
            t.append(str(self.tools_n), style=pal.secondary)
            t.append(" " + glyph("sep") + " ", style="dim")
            t.append("skills ", style="dim")
            t.append(str(self.skills_n), style=pal.secondary)
        if band >= 3:
            if band >= 2:
                t.append("  ")
            t.append(self.session or "default", style="dim")
        if band >= 4 and self.clock:
            if band >= 2:
                t.append("  ")
            t.append(self.clock, style="dim")
        return t

    def render(self) -> Table:
        pal = palette(self.app)
        try:
            width = self.size.width or 100
        except Exception:
            width = 100
        band = self._band(width)
        cells = self.METER_CELLS if width >= 76 else self.METER_CELLS_NARROW

        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1, no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        grid.add_row(self._left(pal, band, cells), self._right(pal, band))
        return grid

    # -- helpers ---------------------------------------------------------

    def set_ctx(self, chars: int, max_chars: int = 120_000) -> None:
        self.ctx_pct = min(99, int((chars or 0) / max(1, max_chars) * 100))

    def tick(self) -> None:
        """Advance the spinner / clock; called by the app's interval timer."""
        if self.mode == "running":
            self.frame = (self.frame + 1) % 10
        self.clock = time.strftime("%H:%M:%S")
