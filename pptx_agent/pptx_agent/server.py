from __future__ import annotations

import json
import mimetypes
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import Settings
from .pipeline import iter_pipeline_with_persist, run_pipeline_and_persist
from .pptx_writer import PptxWriter
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
            if path.startswith("/api/jobs/") and path.endswith("/events.stream"):
                self._replay_events_sse(path)
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
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"{self.address_string()} - {fmt % args}")

        def _generate(self) -> None:
            try:
                payload = self._read_json()
                prompt = str(payload.get("prompt") or "").strip()
                if not prompt:
                    self._send_json({"error": "Prompt is required."}, status=HTTPStatus.BAD_REQUEST)
                    return
                requested_count = payload.get("slide_count")
                explicit_count = int(requested_count) if requested_count else None
                response = run_pipeline_and_persist(prompt, explicit_count, settings)
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

            self._begin_sse()
            try:
                for event in iter_pipeline_with_persist(prompt, explicit_count, settings):
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
                PptxWriter().write(deck, pptx_path)
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
                "deck.json": "application/json; charset=utf-8",
                "events.jsonl": "application/x-ndjson; charset=utf-8",
            }
            if asset not in allowed:
                self._send_json({"error": "Asset not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._serve_file(job_dir / asset, allowed[asset])

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

