from __future__ import annotations

import json
import mimetypes
import re
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import Settings
from .editor import apply_deck_patch, apply_slide_patch, recompute_citations
from .images import ImageBroker, guess_mime
from .pipeline import iter_pipeline_with_persist, run_pipeline_and_persist, write_deck_artifacts
from .pptx_writer import PptxWriter
from .regen import regenerate_slide
from .themes import DEFAULT_THEME, list_themes
from .utils import read_json


def run_server(settings: Settings) -> None:
    handler = _make_handler(settings)
    server = ThreadingHTTPServer((settings.host, settings.port), handler)
    url = f"http://{settings.host}:{settings.port}"
    print(f"Manus-style PPTX agent running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _CONTENT_TYPES:
        return _CONTENT_TYPES[suffix]
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _make_handler(settings: Settings):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ManusPptxAgent/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/api/themes":
                self._send_json({"default": DEFAULT_THEME, "themes": list_themes()})
                return
            if path == "/api/images":
                self._search_images(parsed.query)
                return
            if path.startswith("/api/jobs/") and path.endswith("/events.stream"):
                self._replay_events_sse(path)
                return
            if "/media/" in path and path.startswith("/api/jobs/"):
                self._serve_media(path)
                return
            if path.startswith("/api/jobs/"):
                self._serve_job_asset(path)
                return
            if path.startswith("/api/"):
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            if self._serve_static(path):
                return
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/generate":
                self._generate()
                return
            if parsed.path == "/api/generate/stream":
                self._generate_stream()
                return
            path = unquote(parsed.path)
            if path.startswith("/api/jobs/") and path.endswith("/images"):
                self._download_image(path)
                return
            if "/slides/" in path and path.endswith("/regenerate") and path.startswith("/api/jobs/"):
                self._regenerate_slide(path)
                return
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def do_PATCH(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if self._match_slide_patch(path):
                return
            if self._match_deck_patch(path):
                return
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"{self.address_string()} - {fmt % args}")

        def _search_images(self, query_string: str) -> None:
            from urllib.parse import parse_qs
            params = parse_qs(query_string)
            q = (params.get("q") or [""])[0].strip()
            try:
                n = max(1, min(24, int((params.get("n") or ["12"])[0])))
            except ValueError:
                n = 12
            if not q:
                self._send_json({"error": "Query 'q' is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                broker = ImageBroker(settings)
                results = broker.search(q, max_n=n)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc), "results": []})
                return
            self._send_json({
                "query": q,
                "provider": "searxng" if broker._searxng_urls() else "none",
                "results": [r.as_dict() for r in results],
            })

        def _regenerate_slide(self, path: str) -> None:
            # /api/jobs/<job_id>/slides/<n>/regenerate
            parts = path.strip("/").split("/")
            if len(parts) != 6 or parts[:2] != ["api", "jobs"] or parts[3] != "slides" or parts[5] != "regenerate":
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            job_id = parts[2]
            try:
                slide_number = int(parts[4])
            except ValueError:
                self._send_json({"error": "Slide number must be int."}, status=HTTPStatus.BAD_REQUEST)
                return
            job_dir = self._resolve_job_dir(job_id)
            if job_dir is None:
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                payload = self._read_json()
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"Bad JSON: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                return
            instruction = str(payload.get("instruction") or "").strip()
            refresh_research = bool(payload.get("refresh_research"))
            try:
                deck = read_json(job_dir / "deck.json")
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"deck.json unreadable: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            try:
                updated_slide = regenerate_slide(
                    deck, slide_number, instruction, settings,
                    refresh_research=refresh_research,
                )
                recompute_citations(deck)
                write_deck_artifacts(deck, job_dir)
            except KeyError:
                self._send_json({"error": "Slide not found."}, status=HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json({
                "job_id": job_id,
                "slide": updated_slide,
                "html_url": f"/api/jobs/{job_id}/slides.html",
                "download_url": f"/api/jobs/{job_id}/deck.pptx",
            })

        def _download_image(self, path: str) -> None:
            parts = path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "jobs"] or parts[3] != "images":
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            job_id = parts[2]
            job_dir = self._resolve_job_dir(job_id)
            if job_dir is None:
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                payload = self._read_json()
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"Bad JSON: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                return
            url = str(payload.get("url") or "").strip()
            if not url:
                self._send_json({"error": "url required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                meta = ImageBroker(settings).fetch_into_job(job_dir, url)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(meta)

        def _serve_media(self, path: str) -> None:
            # /api/jobs/<job_id>/media/<file>
            parts = path.strip("/").split("/")
            if len(parts) != 5 or parts[:2] != ["api", "jobs"] or parts[3] != "media":
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            job_id = parts[2]
            filename = parts[4]
            job_dir = self._resolve_job_dir(job_id)
            if job_dir is None:
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return
            candidate = (job_dir / "media" / filename).resolve()
            try:
                candidate.relative_to(job_dir.resolve())
            except ValueError:
                self._send_json({"error": "Invalid path."}, status=HTTPStatus.BAD_REQUEST)
                return
            if not candidate.is_file():
                self._send_json({"error": "Media not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._serve_file(candidate, guess_mime(candidate))

        def _resolve_job_dir(self, job_id: str):
            job_dir = (settings.output_dir / job_id).resolve()
            try:
                job_dir.relative_to(settings.output_dir.resolve())
            except ValueError:
                return None
            return job_dir if job_dir.exists() else None

        def _match_slide_patch(self, path: str) -> bool:
            parts = path.strip("/").split("/")
            if len(parts) != 5 or parts[:2] != ["api", "jobs"] or parts[3] != "slides":
                return False
            job_id = parts[2]
            try:
                slide_number = int(parts[4])
            except ValueError:
                self._send_json({"error": "Slide number must be int."}, status=HTTPStatus.BAD_REQUEST)
                return True
            job_dir = self._resolve_job_dir(job_id)
            if job_dir is None:
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return True
            try:
                payload = self._read_json()
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"Bad JSON: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                return True
            try:
                deck = read_json(job_dir / "deck.json")
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"deck.json unreadable: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return True
            try:
                updated_slide = apply_slide_patch(deck, slide_number, payload)
                recompute_citations(deck)
                write_deck_artifacts(deck, job_dir)
            except KeyError:
                self._send_json({"error": "Slide not found."}, status=HTTPStatus.NOT_FOUND)
                return True
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return True
            self._send_json({
                "job_id": job_id,
                "slide": updated_slide,
                "html_url": f"/api/jobs/{job_id}/slides.html",
                "download_url": f"/api/jobs/{job_id}/deck.pptx",
            })
            return True

        def _match_deck_patch(self, path: str) -> bool:
            parts = path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "jobs"] or parts[3] != "deck":
                return False
            job_id = parts[2]
            job_dir = self._resolve_job_dir(job_id)
            if job_dir is None:
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return True
            try:
                payload = self._read_json()
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"Bad JSON: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                return True
            try:
                deck = read_json(job_dir / "deck.json")
                apply_deck_patch(deck, payload)
                write_deck_artifacts(deck, job_dir)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return True
            self._send_json({
                "job_id": job_id,
                "title": deck.get("title"),
                "subtitle": deck.get("subtitle"),
                "theme": deck.get("theme"),
                "html_url": f"/api/jobs/{job_id}/slides.html",
            })
            return True

        def _generate(self) -> None:
            try:
                payload = self._read_json()
                prompt = str(payload.get("prompt") or "").strip()
                if not prompt:
                    self._send_json({"error": "Prompt is required."}, status=HTTPStatus.BAD_REQUEST)
                    return
                requested_count = payload.get("slide_count")
                explicit_count = int(requested_count) if requested_count else None
                theme = str(payload.get("theme") or "").strip() or None
                response = run_pipeline_and_persist(prompt, explicit_count, settings, theme=theme)
                self._send_json(response)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def _generate_stream(self) -> None:
            try:
                payload = self._read_json()
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"Bad JSON: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                return
            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                self._send_json({"error": "Prompt is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            requested_count = payload.get("slide_count")
            try:
                explicit_count = int(requested_count) if requested_count else None
            except (TypeError, ValueError):
                explicit_count = None
            theme = str(payload.get("theme") or "").strip() or None

            self._begin_sse()
            try:
                for event in iter_pipeline_with_persist(prompt, explicit_count, settings, theme=theme):
                    if not self._write_sse(event):
                        return
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._write_sse({"type": "error", "message": str(exc)})

        def _replay_events_sse(self, path: str) -> None:
            parts = path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "jobs"] or parts[3] != "events.stream":
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            job_id = parts[2]
            job_dir = (settings.output_dir / job_id).resolve()
            try:
                job_dir.relative_to(settings.output_dir.resolve())
            except ValueError:
                self._send_json({"error": "Invalid job."}, status=HTTPStatus.BAD_REQUEST)
                return
            events_path = job_dir / "events.jsonl"
            if not events_path.exists():
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return

            self._begin_sse()
            with events_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not self._write_sse(event):
                        return

        def _begin_sse(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.close_connection = True

        def _write_sse(self, event: dict) -> bool:
            ev_type = str(event.get("type") or "message")
            try:
                data = json.dumps(event, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                data = json.dumps({"type": "error", "message": "unserializable event"})
            chunk = f"event: {ev_type}\ndata: {data}\n\n".encode("utf-8")
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return False

        def _serve_static(self, path: str) -> bool:
            """Serve frontend assets. Prefer web/dist/ (Vite build); fall back to web/ (legacy)."""
            web_dist = settings.root / "web" / "dist"
            web_legacy = settings.root / "web"
            rel = path.lstrip("/") or "index.html"

            for base in (web_dist, web_legacy):
                if not base.exists():
                    continue
                candidate = (base / rel).resolve()
                try:
                    candidate.relative_to(base.resolve())
                except ValueError:
                    return False
                if candidate.is_file():
                    self._serve_file(candidate, _guess_content_type(candidate))
                    return True
                # SPA fallback: unknown path under built bundle → index.html
                if base == web_dist and rel != "index.html":
                    index_file = base / "index.html"
                    if index_file.is_file():
                        self._serve_file(index_file, "text/html; charset=utf-8")
                        return True
            return False

        def _serve_job_asset(self, path: str) -> None:
            parts = path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "jobs"]:
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            job_id = parts[2]
            asset = parts[3]
            job_dir = (settings.output_dir / job_id).resolve()
            try:
                job_dir.relative_to(settings.output_dir.resolve())
            except ValueError:
                self._send_json({"error": "Invalid job."}, status=HTTPStatus.BAD_REQUEST)
                return
            if not job_dir.exists():
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return

            if asset == "deck.pptx":
                deck = read_json(job_dir / "deck.json")
                pptx_path = job_dir / "deck.pptx"
                writer = PptxWriter()
                writer.set_job_dir(job_dir)
                writer.write(deck, pptx_path)
                self._serve_file(
                    pptx_path,
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    download_name=f"{deck['slug']}.pptx",
                )
                return

            allowed = {
                "slides.html": "text/html; charset=utf-8",
                "pitch_deck_structure.txt": "text/plain; charset=utf-8",
                "slide_content.md": "text/markdown; charset=utf-8",
                "sources.md": "text/markdown; charset=utf-8",
                "slide.md": "text/markdown; charset=utf-8",
                "layout_report.md": "text/markdown; charset=utf-8",
                "layout_report.json": "application/json; charset=utf-8",
                "deck.json": "application/json; charset=utf-8",
                "audit.json": "application/json; charset=utf-8",
                "quality.json": "application/json; charset=utf-8",
                "events.jsonl": "application/x-ndjson; charset=utf-8",
            }
            if asset in allowed:
                self._serve_file(job_dir / asset, allowed[asset])
                return
            # Per-slide HTML: slide-NN.html (zero-padded). Validate the
            # filename strictly so the resolved path can never escape job_dir.
            if re.fullmatch(r"slide-\d{2,3}\.html", asset):
                self._serve_file(job_dir / asset, "text/html; charset=utf-8")
                return
            self._send_json({"error": "Asset not found."}, status=HTTPStatus.NOT_FOUND)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length)
            if not data:
                return {}
            return json.loads(data.decode("utf-8"))

        def _serve_file(self, path: Path, content_type: str | None = None, download_name: str | None = None) -> None:
            if not path.exists() or not path.is_file():
                self._send_json({"error": "File not found."}, status=HTTPStatus.NOT_FOUND)
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            if download_name:
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler
