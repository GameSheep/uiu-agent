"""HeaderBar: 顶栏品牌条（品牌 / agent / 模型 / 工作区 / 计数）。

窄终端（<74 列）自动收成单行，<96 列时省略版本号与会话名。
"""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from ..theme import glyph, palette


class HeaderBar(Widget):
    """Application header shown above the message area."""

    agent: reactive[str] = reactive("agent")
    model: reactive[str] = reactive("-")
    ws: reactive[str] = reactive("")
    tools_n: reactive[int] = reactive(0)
    skills_n: reactive[int] = reactive(0)
    version: reactive[str] = reactive("")
    session: reactive[str] = reactive("default")
    compact: reactive[bool] = reactive(False)

    NARROW = 74
    TIGHT = 96

    DEFAULT_CSS = """
    HeaderBar {
        height: 3;
        background: $panel;
        color: $text;
        padding: 0 1;
        border-bottom: solid $panel-lighten-1;
    }
    """

    def on_resize(self, event: object) -> None:
        try:
            width = int(getattr(event, "size").width)
        except Exception:
            return
        narrow = width < self.NARROW
        if narrow != self.compact:
            self.compact = narrow
        try:
            self.styles.height = 2 if narrow else 3
        except Exception:
            pass

    def _short_ws(self, width: int) -> str:
        ws = self.ws or ""
        if len(ws) <= width:
            return ws
        return "…" + ws[-(width - 1):]

    def render(self) -> Table:
        pal = palette(self.app)
        try:
            width = self.size.width or 100
        except Exception:
            width = 100

        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="right", no_wrap=True)

        brand = Text()
        brand.append(glyph("brand") + " ", style=f"bold {pal.accent}")
        brand.append("uiu", style=f"bold {pal.primary}")
        if width >= self.NARROW:
            brand.append("  ")
            brand.append(self.agent or "agent", style=f"bold {pal.foreground}")

        model = Text()
        model.append(self.model or "-", style=pal.secondary)

        if self.compact or width < self.NARROW:
            grid.add_row(brand, model)
            return grid

        left_bottom = Text(self._short_ws(max(16, width // 3)), style="dim")

        right_bottom = Text()
        right_bottom.append(f"{self.tools_n} 工具", style="dim")
        right_bottom.append(f"  {glyph('sep')}  ", style="dim")
        right_bottom.append(f"{self.skills_n} 技能", style="dim")
        if width >= self.TIGHT:
            right_bottom.append(f"  {glyph('sep')}  ", style="dim")
            right_bottom.append(f"v{self.version}", style="dim")
            right_bottom.append(f"  {glyph('sep')}  ", style="dim")
            right_bottom.append(self.session, style=f"dim {pal.accent}")

        grid.add_row(brand, model)
        grid.add_row(left_bottom, right_bottom)
        return grid
