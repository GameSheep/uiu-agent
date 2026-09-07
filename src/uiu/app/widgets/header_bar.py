"""HeaderBar: top strip with agent name, model, workspace, tool/skill summary."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget


class HeaderBar(Widget):
    """Application header shown above the message area."""

    agent: reactive[str] = reactive("agent");
    model: reactive[str] = reactive("-");
    ws: reactive[str] = reactive("");
    tools_n: reactive[int] = reactive(0);
    skills_n: reactive[int] = reactive(0);
    version: reactive[str] = reactive("");

    DEFAULT_CSS = """
    HeaderBar {
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    """

    def render(self) -> str:
        return f"  {self.agent} · {self.model}  —  {self.ws}   [dim]tools {self.tools_n} · skills {self.skills_n}[/dim]  [dim]uiu {self.version}[/dim]";