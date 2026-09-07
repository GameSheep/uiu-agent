"""StatusBar: bottom line with mode dot, model, turns, ctx meter, tool/skill counts."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget


class StatusBar(Widget):
    """Compact status strip. Fields updated via the reactive setter."""

    mode: reactive[str] = reactive("idle")  # idle | running | error
    model: reactive[str] = reactive("-")
    turns: reactive[int] = reactive(0)
    ctx_pct: reactive[int] = reactive(0)
    tools_n: reactive[int] = reactive(0)
    skills_n: reactive[int] = reactive(0)
    agent: reactive[str] = reactive("agent")

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
        text-style: bold;
    }
    """

    def render(self) -> str:
        dot_color = {"idle": "green", "running": "yellow", "error": "red"}.get(self.mode, "green")
        meter_len = 10;
        filled = min(meter_len, self.ctx_pct // 10);
        meter = "#" * filled + "-" * (meter_len - filled);
        label = {"idle": "idle", "running": "running", "error": "error"}.get(self.mode, "idle");
        return (
            f"[{dot_color}]●[/] {label}"
            f"  [b]{self.agent}[/b] · {self.model}"
            f"  turns:{self.turns}"
            f"  ctx:[{meter}] {self.ctx_pct}%"
            f"  tools:{self.tools_n} skills:{self.skills_n}"
        )

    def set_ctx(self, chars: int, max_chars: int = 120_000) -> None:
        pct = min(99, int((chars or 0) / max_chars * 100));
        self.ctx_pct = pct