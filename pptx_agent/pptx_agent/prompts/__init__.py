"""Prompt templates loaded as plain strings.

Keeping prompts in standalone .md files (instead of inline f-strings) makes
them easy to iterate on without rebuilding Python imports, and lets the
templates carry their own examples/format hints without escaping.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent


def load(name: str) -> str:
    """Read a prompt template by filename (without extension)."""
    path = _HERE / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()
