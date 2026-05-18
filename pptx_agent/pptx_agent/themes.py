"""Theme registry.

A theme is a named set of CSS-variable values + font stack + mode (light/dark).
The HTML renderer emits one ``:root[data-theme="..."]`` block per registered
theme; switching is a single attribute toggle on the root element. The PPTX
writer will read the same token dict in phase 7 so HTML preview and PPTX
export match.

Tokens (all themes must define every key):

    ink            primary text
    muted          secondary text
    bg             page background
    panel          slide / card surface
    panel_alt      nested surface (metric cards, callouts)
    line           border lines
    accent         primary brand accent (eyebrows, charts, links)
    accent_strong  pressed / hover accent
    accent_soft    accent tint for backgrounds (e.g. callouts)
    warn           amber tone
    danger         coral / red tone
    shadow         box-shadow rgba string
    radius         border-radius for slides / blocks
    font_display   font-family for headings
    font_body      font-family for body text
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_THEME = "slate"


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    mode: str  # "light" | "dark"
    tokens: dict[str, str]


def _system_font(extra: str = "") -> str:
    base = (
        "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "
        '"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
    )
    if extra:
        return f"{extra}, {base}"
    return base


def _serif() -> str:
    return (
        '"Source Serif Pro", "Iowan Old Style", "Apple Garamond", '
        'Georgia, "Times New Roman", serif'
    )


def _mono() -> str:
    return (
        '"JetBrains Mono", "SF Mono", Menlo, Consolas, '
        '"Liberation Mono", monospace'
    )


THEMES: dict[str, Theme] = {
    "slate": Theme(
        name="slate",
        label="Slate (Light)",
        mode="light",
        tokens={
            "ink": "#17202a",
            "muted": "#53606d",
            "bg": "#f3f6f8",
            "panel": "#ffffff",
            "panel_alt": "#fbfcfd",
            "line": "#d9e0e6",
            "accent": "#087c7c",
            "accent_strong": "#055f5f",
            "accent_soft": "#e2f1f0",
            "warn": "#d98f1f",
            "danger": "#c95746",
            "shadow": "rgba(23,32,42,.08)",
            "radius": "10px",
            "font_display": _system_font("Inter"),
            "font_body": _system_font("Inter"),
        },
    ),
    "midnight": Theme(
        name="midnight",
        label="Midnight (Dark)",
        mode="dark",
        tokens={
            "ink": "#e7ecf3",
            "muted": "#8a97a8",
            "bg": "#070b12",
            "panel": "#0f1620",
            "panel_alt": "#141d29",
            "line": "#1f2a3a",
            "accent": "#3aa0ff",
            "accent_strong": "#62b6ff",
            "accent_soft": "#0b2236",
            "warn": "#f1b948",
            "danger": "#ef6b5a",
            "shadow": "rgba(0,0,0,.45)",
            "radius": "12px",
            "font_display": _system_font("Inter"),
            "font_body": _system_font("Inter"),
        },
    ),
    "sand": Theme(
        name="sand",
        label="Sand (Warm)",
        mode="light",
        tokens={
            "ink": "#2a221a",
            "muted": "#7a6a55",
            "bg": "#f6efe2",
            "panel": "#fff9ec",
            "panel_alt": "#fbf4e0",
            "line": "#e3d6b8",
            "accent": "#a4632a",
            "accent_strong": "#7e4717",
            "accent_soft": "#f3e1c6",
            "warn": "#c98a2a",
            "danger": "#b2462e",
            "shadow": "rgba(106,76,33,.14)",
            "radius": "12px",
            "font_display": _serif(),
            "font_body": _system_font("Inter"),
        },
    ),
    "mono": Theme(
        name="mono",
        label="Mono (Editorial)",
        mode="light",
        tokens={
            "ink": "#0c0c0c",
            "muted": "#5b5b5b",
            "bg": "#ffffff",
            "panel": "#ffffff",
            "panel_alt": "#f4f4f4",
            "line": "#1a1a1a",
            "accent": "#0c0c0c",
            "accent_strong": "#000000",
            "accent_soft": "#e9e9e9",
            "warn": "#7a7a7a",
            "danger": "#0c0c0c",
            "shadow": "rgba(0,0,0,.06)",
            "radius": "0px",
            "font_display": _serif(),
            "font_body": _mono(),
        },
    ),
    "pitch": Theme(
        name="pitch",
        label="Pitch (Navy + Gold)",
        mode="dark",
        tokens={
            "ink": "#f3ecd2",
            "muted": "#b3aa90",
            "bg": "#0a1530",
            "panel": "#101f44",
            "panel_alt": "#0b1838",
            "line": "#1f2f55",
            "accent": "#d8b25a",
            "accent_strong": "#f0c771",
            "accent_soft": "#1a2954",
            "warn": "#d8b25a",
            "danger": "#e07a5b",
            "shadow": "rgba(0,0,0,.5)",
            "radius": "10px",
            "font_display": _serif(),
            "font_body": _system_font("Inter"),
        },
    ),
}


def get_theme(name: str | None) -> Theme:
    if name and name in THEMES:
        return THEMES[name]
    return THEMES[DEFAULT_THEME]


def list_themes(include_tokens: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in THEMES.values():
        row: dict[str, Any] = {
            "name": t.name,
            "label": t.label,
            "mode": t.mode,
            "accent": t.tokens["accent"],
            "bg": t.tokens["bg"],
        }
        if include_tokens:
            row["tokens"] = dict(t.tokens)
        rows.append(row)
    return rows


def _var(token: str) -> str:
    return f"--{token.replace('_', '-')}"


def theme_css_block(theme: Theme, selector: str | None = None) -> str:
    sel = selector or f':root[data-theme="{theme.name}"]'
    lines = [f"{sel} {{"]
    for key, value in theme.tokens.items():
        lines.append(f"  {_var(key)}: {value};")
    lines.append(f"  color-scheme: {'dark' if theme.mode == 'dark' else 'light'};")
    lines.append("}")
    return "\n".join(lines)


def all_theme_css() -> str:
    """Render every registered theme as a CSS block plus a default-root block."""
    default = THEMES[DEFAULT_THEME]
    blocks = [theme_css_block(default, ":root")]
    for theme in THEMES.values():
        blocks.append(theme_css_block(theme))
    return "\n".join(blocks)
