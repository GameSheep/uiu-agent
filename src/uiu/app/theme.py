"""uiu TUI 设计令牌（design tokens）与主题。

视觉常量集中在这里：色板、字形（glyph）、间距。新增一套配色只需往
PALETTES 里加一条 Palette —— widget 全部通过 palette(app) 取色，
主题切换后重新渲染即生效。

对外接口：
    register_themes(app)  -> 把 PALETTES 注册进 textual App
    palette(app)          -> 当前 Palette（未知主题回退默认）
    glyph(name)           -> 统一的界面字形
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from textual.theme import Theme

DEFAULT_THEME = "uiu-dark"
CUSTOM_THEME = "uiu-custom"

# config.yaml 里 tui.colors 可以覆盖这些字段
COLOR_FIELDS = ("primary", "secondary", "accent", "success", "warning", "error",
                "foreground", "background", "surface", "panel", "boost")

# --------------------------------------------------------------------------
# 字形：整个 UI 只用这一张表，避免各处硬编码 symbol
# --------------------------------------------------------------------------

GLYPHS: dict[str, str] = {
    "brand": "◆",
    "user": "❯",
    "agent": "✦",
    "thought": "✻",
    "tool": "⚙",
    "notice": "·",
    "error": "✖",
    "ok": "✓",
    "fail": "✗",
    "dot": "●",
    "dot_idle": "○",
    "meter_full": "█",
    "meter_empty": "░",
    "sep": "·",
    "arrow": "›",
    "cursor": "▍",
    "copy": "⧉",
    "spinner": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏",
    "prompt": "❯",
    "hint": "↵",
}

# 布局常量
GUTTER = 2          # 消息左侧缩进
BODY_PAD = 1        # 气泡内边距


def glyph(name: str, default: str = "·") -> str:
    return GLYPHS.get(name, default)


# --------------------------------------------------------------------------
# 色板
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """A complete color scheme for the TUI."""

    name: str
    label: str
    tagline: str
    primary: str
    secondary: str
    accent: str
    success: str
    warning: str
    error: str
    foreground: str
    background: str
    surface: str
    panel: str
    boost: str
    dark: bool = True

    def to_theme(self) -> Theme:
        return Theme(
            name=self.name,
            primary=self.primary,
            secondary=self.secondary,
            accent=self.accent,
            success=self.success,
            warning=self.warning,
            error=self.error,
            foreground=self.foreground,
            background=self.background,
            surface=self.surface,
            panel=self.panel,
            boost=self.boost,
            dark=self.dark,
        )


PALETTES: tuple[Palette, ...] = (
    Palette(
        name="uiu-dark",
        label="uiu Dark",
        tagline="深墨底 + 天青强调色（默认）",
        primary="#4C9AFF",
        secondary="#9A7BFF",
        accent="#37D6C4",
        success="#45D483",
        warning="#F5B759",
        error="#FF6B6B",
        foreground="#DCE6F2",
        background="#0B1016",
        surface="#101823",
        panel="#141E2B",
        boost="#1B2837",
    ),
    Palette(
        name="uiu-mono",
        label="uiu Mono",
        tagline="近乎黑白，只留一点琥珀",
        primary="#D8DEE9",
        secondary="#9AA5B1",
        accent="#F0B429",
        success="#7FB069",
        warning="#F0B429",
        error="#E06C75",
        foreground="#E5E9F0",
        background="#0D0D0F",
        surface="#141417",
        panel="#191A1E",
        boost="#22242A",
    ),
    Palette(
        name="uiu-neon",
        label="uiu Neon",
        tagline="霓虹紫粉，赛博味道",
        primary="#C77DFF",
        secondary="#FF6EC7",
        accent="#4DE1FF",
        success="#4BE38A",
        warning="#FFB85C",
        error="#FF5C8A",
        foreground="#F0E6FF",
        background="#0C0713",
        surface="#150C22",
        panel="#1D1030",
        boost="#2A1745",
    ),
    Palette(
        name="uiu-solar",
        label="uiu Solar",
        tagline="浅色纸感，白天用",
        primary="#2F6FEB",
        secondary="#8250DF",
        accent="#0E8A7D",
        success="#1A7F37",
        warning="#B26B00",
        error="#C0392B",
        foreground="#1F2328",
        background="#F7F5F0",
        surface="#FFFFFF",
        panel="#EFEAE0",
        boost="#E3DCCC",
        dark=False,
    ),
)

THEMES: dict[str, Palette] = {p.name: p for p in PALETTES}


def theme_names() -> list[str]:
    return [p.name for p in PALETTES]


def register_themes(app: Any) -> None:
    """Register every palette on *app* (idempotent, never fatal)."""
    for p in PALETTES:
        try:
            app.register_theme(p.to_theme())
        except Exception:
            pass


def palette_from_config(app_cfg: Any) -> Palette | None:
    """Build a custom palette from tui.colors in config.yaml (or None).

    Every field is optional: the base is the configured theme, so users can
    tweak one accent without redefining the whole scheme.
    """
    try:
        tui = getattr(app_cfg, "tui", {}) or {}
        overrides = tui.get("colors") or {}
        if not isinstance(overrides, dict) or not overrides:
            return None
        base = THEMES.get(str(tui.get("theme") or DEFAULT_THEME), THEMES[DEFAULT_THEME])
        values = {f: str(overrides.get(f) or getattr(base, f)) for f in COLOR_FIELDS}
        dark = bool(overrides.get("dark", base.dark))
        return replace(base, name=CUSTOM_THEME, label="uiu Custom",
                       tagline="来自 config.yaml 的 tui.colors", dark=dark, **values)
    except Exception:
        return None


def palette(app: Any) -> Palette:
    """Return the palette backing the app's active theme."""
    name = getattr(app, "theme", None)
    if isinstance(name, str):
        if name in THEMES:
            return THEMES[name]
        custom = getattr(app, "_uiu_custom_palette", None)
        if custom is not None and name == getattr(custom, "name", ""):
            return custom
    try:
        current = app.current_theme
        if current is not None and getattr(current, "name", "") in THEMES:
            return THEMES[current.name]
    except Exception:
        pass
    return THEMES[DEFAULT_THEME]
