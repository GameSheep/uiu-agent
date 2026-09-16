"""Design-token sanity: every built-in palette must be readable and parseable."""

from __future__ import annotations

import pytest


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.strip().lstrip("#")
    assert len(value) == 6, f"expected #RRGGBB, got {color!r}"
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _luminance(color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio (1..21)."""
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def test_palettes_are_well_formed():
    from uiu.app.theme import COLOR_FIELDS, PALETTES, THEMES, theme_names

    assert len(PALETTES) >= 4
    assert set(THEMES) == set(theme_names())
    for p in PALETTES:
        assert p.name.startswith("uiu-"), p.name
        assert p.label and p.tagline
        for field in COLOR_FIELDS:
            value = getattr(p, field)
            _rgb(value)          # raises if malformed
        # dark/light flag matches the background
        assert (p.dark is True) == (_luminance(p.background) < 0.5), p.name


def test_every_theme_has_readable_text():
    """Body text must clear WCAG AA (4.5:1) on the chat background."""
    from uiu.app.theme import PALETTES

    for p in PALETTES:
        ratio = contrast(p.foreground, p.background)
        assert ratio >= 4.5, f"{p.name}: foreground/background only {ratio:.2f}:1"
        # the accent is used for headings/labels — should also be legible
        accent = contrast(p.accent, p.background)
        assert accent >= 3.0, f"{p.name}: accent/background only {accent:.2f}:1"


def test_panels_are_distinguishable_from_background():
    from uiu.app.theme import PALETTES

    for p in PALETTES:
        # surface/panel/boost are the layered backgrounds; they must not collapse
        for field in ("surface", "panel", "boost"):
            assert getattr(p, field) != p.background, f"{p.name}.{field}"
        assert len({p.surface, p.panel, p.boost}) == 3, f"{p.name}: layers collapse"


def test_theme_objects_build_for_textual():
    from textual.theme import Theme

    from uiu.app.theme import PALETTES

    for p in PALETTES:
        theme = p.to_theme()
        assert isinstance(theme, Theme)
        assert theme.name == p.name
        assert theme.primary is not None and theme.background is not None


def test_custom_palette_inherits_and_overrides():
    from uiu.app.theme import CUSTOM_THEME, DEFAULT_THEME, THEMES, palette_from_config

    class _Cfg:
        tui = {"theme": "uiu-solar", "colors": {"primary": "#123456"}}

    derived = palette_from_config(_Cfg())
    assert derived is not None
    assert derived.name == CUSTOM_THEME
    assert derived.primary == "#123456"
    base = THEMES["uiu-solar"]
    assert derived.background == base.background, "untouched slots inherit"
    assert derived.dark == base.dark
    assert palette_from_config(None) is None
