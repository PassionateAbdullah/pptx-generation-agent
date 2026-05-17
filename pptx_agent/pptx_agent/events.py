from __future__ import annotations

import time
import urllib.parse
from typing import Any

PHASE_RESEARCH = "research"
PHASE_OUTLINE = "outline"
PHASE_CONTENT = "content"
PHASE_RENDER = "render"
PHASE_EXPORT = "export"


def make_event(type_: str, **fields: Any) -> dict[str, Any]:
    return {"type": type_, "ts": time.time(), **fields}


def favicon_url(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    netloc = urllib.parse.urlparse(url).netloc
    if not netloc:
        return ""
    return f"https://www.google.com/s2/favicons?domain={netloc}&sz=32"


_NEWS_HOSTS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com",
    "wsj.com", "washingtonpost.com", "ft.com", "bloomberg.com",
    "theguardian.com", "economist.com", "npr.org", "cnn.com", "cnbc.com",
    "forbes.com", "axios.com", "politico.com", "aljazeera.com",
    "techcrunch.com", "wired.com", "theverge.com", "arstechnica.com",
    "msn.com", "yahoo.com",
}
_REFERENCE_HOSTS = {"wikipedia.org", "britannica.com", "stackoverflow.com"}
_ACADEMIC_HOSTS = {"arxiv.org", "scholar.google.com", "semanticscholar.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"}
_SOCIAL_HOSTS = {"twitter.com", "x.com", "facebook.com", "reddit.com", "linkedin.com", "instagram.com", "tiktok.com", "youtube.com"}


def domain_of(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    netloc = urllib.parse.urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def trust_tier(url: str) -> str:
    """Return one of: gov, edu, academic, news, reference, social, blog, unknown."""
    netloc = domain_of(url)
    if not netloc:
        return "unknown"
    parts = netloc.split(".")
    tld = parts[-1] if parts else ""
    second = parts[-2] if len(parts) >= 2 else ""

    if tld == "gov" or netloc.endswith(".gov") or second == "gov":
        return "gov"
    if tld == "edu" or netloc.endswith(".edu"):
        return "edu"
    if netloc in _ACADEMIC_HOSTS or any(netloc.endswith("." + h) for h in _ACADEMIC_HOSTS):
        return "academic"
    if netloc in _NEWS_HOSTS or any(netloc.endswith("." + h) for h in _NEWS_HOSTS):
        return "news"
    if netloc in _REFERENCE_HOSTS or any(netloc.endswith("." + h) for h in _REFERENCE_HOSTS):
        return "reference"
    if netloc in _SOCIAL_HOSTS or any(netloc.endswith("." + h) for h in _SOCIAL_HOSTS):
        return "social"
    if "blog" in netloc or "medium.com" in netloc or "substack.com" in netloc:
        return "blog"
    return "unknown"
