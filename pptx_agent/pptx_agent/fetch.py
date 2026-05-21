"""Generic full-page fetcher.

Mirrors the ``fetch_url`` shape the developer prototyped (httpx async)
but stays on stdlib so the project carries no new third-party deps. The
public contract is the same: pass a URL + ``max_chars``, get back clean
readable text or a ``[fetch_url error: ...]`` string the caller can log
or surface to the UI.

Used by:
  - ``research.Researcher._fetch_source_excerpt`` for initial enrichment.
  - ``slide_edit._run_targeted_research`` to deep-fetch the top hit of
    a focused query when the snippet alone is too thin.

stdlib only: ``urllib.request`` / ``html.parser``.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from html import unescape
from html.parser import HTMLParser
from typing import Tuple

log = logging.getLogger("pptx_agent.fetch")

_FETCH_TIMEOUT = 12.0           # seconds — same ballpark as dev's httpx version
_MAX_RESPONSE_BYTES = 4_000_000  # 4 MB read cap; ignore pages bigger than this
_MAX_CHARS_CEILING = 10_000      # hard ceiling matches dev's contract


_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)


class _HTMLTextExtractor(HTMLParser):
    """Strip tags, drop scripts/styles, collapse whitespace."""

    _SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._parts.append(text)

    def text(self) -> str:
        return " ".join(self._parts)


# Site-chrome / cookie / nav phrases that leak into stripped text. These
# end up in research excerpts and downstream the claim miner treats them
# as factual content. Drop any sentence that contains one of these.
_BOILERPLATE_PATTERNS = [
    re.compile(r"\b(?:sign\s*in|sign\s*up|log\s*in|register|create\s+account)\b", re.I),
    re.compile(r"\bdownload\s+(?:free|now|the\s+app|pdf)\b", re.I),
    re.compile(r"\b(?:read\s+more|show\s+more|see\s+more|click\s+here|learn\s+more)\b", re.I),
    re.compile(r"\b(?:toggle\s+navigation|skip\s+to\s+content|main\s+menu)\b", re.I),
    re.compile(r"\b(?:accept\s+(?:all\s+)?cookies?|cookie\s+policy|cookie\s+settings|gdpr|privacy\s+policy)\b", re.I),
    re.compile(r"\b(?:subscribe(?:\s+to)?|newsletter|follow\s+us)\b", re.I),
    re.compile(r"\b(?:upload|share\s+this|copy\s+link|print\s+page)\b", re.I),
    re.compile(r"\b(?:all\s+rights\s+reserved|terms\s+of\s+(?:use|service)|powered\s+by)\b", re.I),
    re.compile(r"\b(?:0\s+ratings?|0%\s+found|0\s+comments?)\b", re.I),
    re.compile(r"\b(?:related\s+(?:topics?|articles?)|recommended\s+for\s+you|you\s+may\s+also\s+like)\b", re.I),
    re.compile(r"\b(?:home|about|contact|search)\s*\|", re.I),
]
_MIN_SENT_LEN = 30
_MAX_SENT_LEN = 600


def _drop_boilerplate(text: str) -> str:
    """Walk sentences and drop anything that looks like nav/cookie/upload UI.

    HTML text-extraction pulls every visible string, including buttons,
    cookie banners, "Sign in", "Download free for 30 days", "Toggle
    navigation", and ratings widgets. Without this filter those fragments
    end up in `excerpt`, then the claim miner promotes them to slide
    titles. Drop them here so research stays factual.
    """
    if not text:
        return ""
    # Split on sentence boundaries OR newlines OR pipe-separators (nav).
    parts = re.split(r"(?<=[.!?])\s+|\n+|\s+\|\s+", text)
    kept: list[str] = []
    for part in parts:
        s = part.strip()
        if not s:
            continue
        if len(s) < _MIN_SENT_LEN:
            # Short menu-label fragments — skip.
            if not re.search(r"\d", s):
                continue
        if len(s) > _MAX_SENT_LEN:
            # Probably a giant unsplit paragraph; keep but truncate.
            s = s[:_MAX_SENT_LEN]
        if any(p.search(s) for p in _BOILERPLATE_PATTERNS):
            continue
        # Lines that are >30% non-letter characters are usually UI gunk.
        letters = sum(c.isalpha() for c in s)
        if letters * 10 < len(s) * 6:
            continue
        kept.append(s)
    return " ".join(kept)


def _strip_html(raw: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw)
    except Exception:  # noqa: BLE001 — never let a malformed page crash the run
        log.warning("HTML parser failure; falling back to unescape-only")
        return _drop_boilerplate(" ".join(unescape(raw).split()))
    return _drop_boilerplate(" ".join(parser.text().split()))


def fetch_url(url: str, max_chars: int = 6000) -> str:
    """Fetch readable text content of a URL.

    Returns the extracted text (prefixed with the source URL) or a
    structured ``[fetch_url ...]`` error string. Never raises. Mirrors the
    developer's ``async def fetch_url`` contract exactly so callers can
    treat both implementations the same way.
    """
    if not isinstance(url, str) or not url:
        return "[fetch_url error: empty url]"
    parsed_scheme = url.split("://", 1)[0].lower() if "://" in url else ""
    if parsed_scheme not in {"http", "https"}:
        return f"[fetch_url error: only http/https URLs supported, got '{parsed_scheme}']"

    cap = min(max(int(max_chars), 500), _MAX_CHARS_CEILING)

    # Skip obvious binary extensions before opening a socket.
    lower_url = url.lower().split("?", 1)[0]
    if lower_url.endswith(
        (".pdf", ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx",
         ".zip", ".rar", ".7z", ".png", ".jpg", ".jpeg", ".gif", ".webp",
         ".mp4", ".mov", ".avi", ".mp3")
    ):
        return f"[fetch_url: skipped binary extension url '{url}']"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                return f"[fetch_url HTTP {status}: {url}]"
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type and "text/plain" not in content_type:
                return f"[fetch_url: unsupported content type '{content_type}' — only HTML/text supported]"
            charset = response.headers.get_content_charset() or "utf-8"
            raw_bytes = response.read(_MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as exc:
        return f"[fetch_url HTTP {exc.code}: {url}]"
    except urllib.error.URLError as exc:
        return f"[fetch_url network error: {exc.reason}]"
    except TimeoutError:
        return f"[fetch_url timeout after {int(_FETCH_TIMEOUT)}s: {url}]"
    except Exception as exc:  # noqa: BLE001
        log.warning("fetch_url unexpected error for %s: %s", url, exc)
        return f"[fetch_url error: {exc}]"

    raw = raw_bytes.decode(charset, errors="replace")
    text = _strip_html(raw) if "text/html" in content_type else raw.strip()
    if not text:
        return f"[fetch_url: no readable content found at {url}]"

    if len(text) > cap:
        text = text[:cap] + f"\n\n[... content truncated at {cap} chars from {url} ...]"
    return f"Full content from {url}:\n\n{text}"


def fetch_url_body(url: str, max_chars: int = 6000) -> Tuple[str, str | None]:
    """Same as ``fetch_url`` but returns ``(body, error)``.

    Useful for the research enrichment pass which wants to overwrite a
    source's ``excerpt`` only when the fetch produced real content, and
    surface the error reason to the event stream when it didn't.
    """
    out = fetch_url(url, max_chars=max_chars)
    if out.startswith("[fetch_url"):
        return "", out
    # Strip the ``Full content from {url}:\n\n`` prefix so callers can store
    # just the body in their excerpt field.
    prefix = f"Full content from {url}:\n\n"
    body = out[len(prefix):] if out.startswith(prefix) else out
    return body, None


__all__ = ["fetch_url", "fetch_url_body"]
