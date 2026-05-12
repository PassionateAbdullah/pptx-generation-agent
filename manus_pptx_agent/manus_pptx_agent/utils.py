from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime
from pathlib import Path


def slugify(value: str, fallback: str = "deck") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug[:80] or fallback


def timestamp_id(title: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slugify(title)}"


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def escape_html(value: object) -> str:
    return html.escape(str(value), quote=True)


def read_json(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    import json

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

