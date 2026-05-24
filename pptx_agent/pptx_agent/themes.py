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

DEFAULT_THEME = "betopia"


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
    "betopia": Theme(
        name="betopia",
        label="Betopia (Warm)",
        mode="light",
        tokens={
            "ink": "#1f1b1a",
            "muted": "#8a8580",
            "bg": "#faf6f1",
            "panel": "#ffffff",
            "panel_alt": "#fbf6ef",
            "line": "#ede5dc",
            "accent": "#e96b2a",
            "accent_strong": "#a02e2e",
            "accent_soft": "#fce6d5",
            "warn": "#d98f1f",
            "danger": "#c95746",
            "shadow": "rgba(31,27,26,.06)",
            "radius": "14px",
            "font_display": _system_font("Inter"),
            "font_body": _system_font("Inter"),
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


# Catalog of html-ppt themes vendored under web/dist/static/html-ppt/themes/.
# Each entry maps the theme's filename (without .css) to a friendly label +
# light/dark mode. Source of truth is the file list itself — these labels
# are display only.
HTML_PPT_THEMES: dict[str, tuple[str, str]] = {
    "minimal-white": ("Minimal White", "light"),
    "editorial-serif": ("Editorial Serif", "light"),
    "soft-pastel": ("Soft Pastel", "light"),
    "sharp-mono": ("Sharp Mono", "light"),
    "arctic-cool": ("Arctic Cool", "light"),
    "sunset-warm": ("Sunset Warm", "light"),
    "catppuccin-latte": ("Catppuccin Latte", "light"),
    "catppuccin-mocha": ("Catppuccin Mocha", "dark"),
    "dracula": ("Dracula", "dark"),
    "tokyo-night": ("Tokyo Night", "dark"),
    "nord": ("Nord", "dark"),
    "solarized-light": ("Solarized Light", "light"),
    "gruvbox-dark": ("Gruvbox Dark", "dark"),
    "rose-pine": ("Rosé Pine", "dark"),
    "neo-brutalism": ("Neo Brutalism", "light"),
    "glassmorphism": ("Glassmorphism", "light"),
    "bauhaus": ("Bauhaus", "light"),
    "swiss-grid": ("Swiss Grid", "light"),
    "terminal-green": ("Terminal Green", "dark"),
    "xiaohongshu-white": ("Xiaohongshu White", "light"),
    "rainbow-gradient": ("Rainbow Gradient", "light"),
    "aurora": ("Aurora", "dark"),
    "blueprint": ("Blueprint", "dark"),
    "memphis-pop": ("Memphis Pop", "light"),
    "cyberpunk-neon": ("Cyberpunk Neon", "dark"),
    "y2k-chrome": ("Y2K Chrome", "light"),
    "retro-tv": ("Retro TV", "dark"),
    "japanese-minimal": ("Japanese Minimal", "light"),
    "vaporwave": ("Vaporwave", "dark"),
    "midcentury": ("Mid-century", "light"),
    "corporate-clean": ("Corporate Clean", "light"),
    "academic-paper": ("Academic Paper", "light"),
    "news-broadcast": ("News Broadcast", "dark"),
    "pitch-deck-vc": ("VC Pitch Deck", "dark"),
    "magazine-bold": ("Magazine Bold", "light"),
    "engineering-whiteprint": ("Engineering Whiteprint", "light"),
}

# Our 5 legacy theme names alias to the closest html-ppt theme so existing
# decks keep their look even after we swapped the rendering shell.
_LEGACY_ALIAS: dict[str, str] = {
    "betopia": "soft-pastel",
    "slate": "corporate-clean",
    "sand": "sunset-warm",
    "mono": "sharp-mono",
    "midnight": "dracula",
    "pitch": "pitch-deck-vc",
}

_FAMILY_THEME_CHOICES: dict[str, tuple[str, ...]] = {
    "pitch_deck": ("pitch", "midnight", "betopia"),
    "research_briefing": ("slate", "mono", "sand"),
    "market_analysis": ("slate", "midnight", "mono"),
    "case_study": ("sand", "betopia", "slate"),
    "product_overview": ("midnight", "betopia", "slate"),
    "report": ("slate", "betopia", "sand"),
}


def _stable_bucket(text: str, modulo: int) -> int:
    if modulo <= 0:
        return 0
    total = 0
    for index, char in enumerate(text or "", start=1):
        total += index * ord(char)
    return total % modulo


def resolve_theme_name(name: str | None) -> str:
    """Return a valid legacy or html-ppt theme name."""
    if not name:
        return DEFAULT_THEME
    candidate = str(name).strip()
    if candidate in THEMES or candidate in HTML_PPT_THEMES:
        return candidate
    if candidate in _LEGACY_ALIAS:
        return candidate
    return DEFAULT_THEME


def choose_theme_name(
    prompt: str,
    topic: str,
    family: str,
    requested: str | None = None,
) -> str:
    """Pick a deterministic theme for the deck.

    User-selected themes win. Otherwise, vary the deck's palette by family
    and prompt/topic so repeated offline runs do not collapse into the same
    visual treatment.
    """
    resolved = resolve_theme_name(requested)
    if requested and resolved != DEFAULT_THEME:
        return resolved

    choices = _FAMILY_THEME_CHOICES.get(str(family or "").strip(), _FAMILY_THEME_CHOICES["report"])
    idx = _stable_bucket(f"{topic}|{prompt}", len(choices))
    return choices[idx]


def html_ppt_theme_filename(name: str | None) -> str:
    """Resolve a theme name (legacy or html-ppt) to its CSS filename.

    Always returns a valid ``<name>.css`` string. Falls back to the
    default theme when ``name`` is None / unknown.
    """
    if not name:
        name = DEFAULT_THEME
    # html-ppt theme names map to their own file directly.
    if name in HTML_PPT_THEMES:
        return f"{name}.css"
    # Our legacy 5 alias to an html-ppt theme.
    if name in _LEGACY_ALIAS:
        return f"{_LEGACY_ALIAS[name]}.css"
    # Default fallback.
    default_name = _LEGACY_ALIAS.get(DEFAULT_THEME, DEFAULT_THEME)
    return f"{default_name}.css"


def get_theme(name: str | None) -> Theme:
    if name and name in THEMES:
        return THEMES[name]
    if name and name in HTML_PPT_THEMES:
        label, mode = HTML_PPT_THEMES[name]
        base = THEMES["midnight" if mode == "dark" else "slate"]
        return Theme(name=name, label=label, mode=mode, tokens=dict(base.tokens))
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
