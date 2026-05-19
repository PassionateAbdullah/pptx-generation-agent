"""Image search + fetch.

Free, local-first image sourcing for slide ``image`` blocks. Queries SearXNG
``categories=images`` for stock imagery. Skips third-party API providers
(Unsplash, etc.) so the agent runs without keys. AI image generation is
deliberately deferred — phase 9 is about stock photography, which covers
most pitch-deck needs.

The downloader stores images under ``output/<job>/media/<hash>.<ext>`` so
they are part of the job artifact tree and can be served via the existing
``/api/jobs/<id>/media/<file>`` static handler.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings


def _is_private_address(host: str) -> bool:
    """SSRF guard: reject hostnames resolving to private / link-local / loopback
    IPs and known cloud-metadata endpoints.

    Used before any server-side image fetch so a user-supplied URL cannot
    probe internal infrastructure or the metadata service.
    """
    if not host:
        return True
    host_l = host.lower()
    if host_l in {"localhost", "metadata.google.internal", "metadata"}:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%", 1)[0])
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
        # Block AWS / GCP / Azure metadata service IP.
        if str(ip) in {"169.254.169.254", "169.254.170.2", "fd00:ec2::254"}:
            return True
    return False


@dataclass
class ImageResult:
    title: str
    url: str
    thumbnail_url: str
    source: str
    width: int = 0
    height: int = 0
    mime: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "thumbnail_url": self.thumbnail_url,
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "mime": self.mime,
        }


_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_MIME_TO_EXT = {v: k for k, v in _EXT_TO_MIME.items()}

_MAX_BYTES = 4_500_000  # 4.5 MB cap — avoid runaway downloads
_ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class ImageBroker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # -- Search -----------------------------------------------------------

    def search(self, query: str, max_n: int = 12) -> list[ImageResult]:
        query = (query or "").strip()
        if not query:
            return []
        provider = self._resolve_provider()
        if provider == "searxng":
            try:
                return self._search_searxng(query, max_n)
            except Exception:  # noqa: BLE001
                return []
        return []

    def _resolve_provider(self) -> str:
        provider = (self.settings.search_provider or "auto").lower()
        if provider in {"auto", "searxng"} and self._searxng_urls():
            return "searxng"
        return "none"

    def _searxng_urls(self) -> list[str]:
        raw = self.settings.searxng_url or ""
        urls = [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]
        return urls

    def _search_searxng(self, query: str, max_n: int) -> list[ImageResult]:
        errors: list[str] = []
        for base in self._searxng_urls():
            url = f"{base}/search?" + urllib.parse.urlencode({
                "q": query,
                "format": "json",
                "categories": "images",
                "safesearch": "0",
                "language": "en",
            })
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "ManusPptxAgent/0.1",
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as response:
                    import json
                    data = json.loads(response.read().decode("utf-8", errors="replace"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{base}: {exc}")
                continue
            results: list[ImageResult] = []
            for item in data.get("results", []):
                src = item.get("img_src") or item.get("url")
                if not src:
                    continue
                thumb = item.get("thumbnail_src") or item.get("thumbnail") or src
                results.append(
                    ImageResult(
                        title=str(item.get("title") or "")[:160],
                        url=str(src),
                        thumbnail_url=str(thumb),
                        source=str(item.get("source") or item.get("engine") or ""),
                        width=int(item.get("img_width") or 0),
                        height=int(item.get("img_height") or 0),
                    )
                )
                if len(results) >= max_n:
                    break
            if results:
                return results
        if errors:
            raise RuntimeError("; ".join(errors[:3]))
        return []

    # -- Download into job media dir -------------------------------------

    def fetch_into_job(self, job_dir: Path, url: str) -> dict[str, Any]:
        """Download ``url`` into ``job_dir/media/`` and return metadata.

        Returns ``{filename, local_url, mime, size, sha}``. Raises on HTTP
        failure or unsupported MIME. Rejects URLs targeting private,
        loopback, link-local, or cloud-metadata addresses (SSRF guard).
        """
        if not url.startswith(("http://", "https://")):
            raise ValueError("Image URL must be http(s)://")

        parsed = urllib.parse.urlparse(url)
        if _is_private_address(parsed.hostname or ""):
            raise RuntimeError("Refused: image URL resolves to a private / loopback / metadata address.")

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ManusPptxAgent/0.1",
                "Accept": "image/*",
            },
        )
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Image fetch failed: {exc.reason}") from exc

        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type not in _ALLOWED_MIMES:
            raise RuntimeError(f"Unsupported image mime: {content_type or 'unknown'}")

        raw = response.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise RuntimeError(f"Image too large (> {_MAX_BYTES // 1_000_000} MB)")

        media_dir = job_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        sha = hashlib.sha1(raw).hexdigest()[:16]
        ext = _MIME_TO_EXT.get(content_type, ".bin")
        filename = f"{sha}{ext}"
        path = media_dir / filename
        if not path.exists():
            path.write_bytes(raw)

        return {
            "filename": filename,
            "local_url": f"/api/jobs/{job_dir.name}/media/{filename}",
            "mime": content_type,
            "size": len(raw),
            "sha": sha,
            "source_url": url,
        }


_LOCAL_URL_RE = re.compile(r"^/api/jobs/([^/]+)/media/([^/]+)$")


def resolve_local_image(job_dir: Path, src: str) -> Path | None:
    """Return absolute path if ``src`` references a downloaded media file in
    this job. Returns None for external URLs or invalid references."""
    if not src:
        return None
    match = _LOCAL_URL_RE.match(src)
    if not match:
        return None
    if match.group(1) != job_dir.name:
        return None
    candidate = (job_dir / "media" / match.group(2)).resolve()
    try:
        candidate.relative_to(job_dir.resolve())
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


def guess_mime(path: Path) -> str:
    return _EXT_TO_MIME.get(path.suffix.lower(), "application/octet-stream")
