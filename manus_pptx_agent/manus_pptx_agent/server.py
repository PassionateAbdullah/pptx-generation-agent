from __future__ import annotations

import json
import mimetypes
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import Settings
from .html_renderer import render_full_html, render_preview_fragment
from .planner import (
    build_deck,
    deck_structure_text,
    extract_slide_count,
    extract_topic,
    slide_content_markdown,
)
from .pptx_writer import PptxWriter
from .research import Researcher
from .utils import read_json, timestamp_id, write_json


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


def _make_handler(settings: Settings):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ManusPptxAgent/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/":
                self._serve_file(settings.root / "web" / "index.html", "text/html; charset=utf-8")
                return
            if path in {"/app.js", "/styles.css"}:
                content_type = "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
                self._serve_file(settings.root / "web" / path.lstrip("/"), content_type)
                return
            if path.startswith("/api/jobs/"):
                self._serve_job_asset(path)
                return
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/generate":
                self._generate()
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
                slide_count = extract_slide_count(prompt, explicit_count)
                topic = extract_topic(prompt)

                research = Researcher(settings).run(prompt, topic)
                deck, planner_logs = build_deck(prompt, slide_count, research, settings)
                logs = research["logs"] + planner_logs + ["Rendering HTML preview."]

                job_id = timestamp_id(deck["title"])
                job_dir = settings.output_dir / job_id
                job_dir.mkdir(parents=True, exist_ok=True)

                structure = deck_structure_text(deck)
                markdown = slide_content_markdown(deck)
                html = render_full_html(deck)

                write_json(job_dir / "deck.json", deck)
                (job_dir / "pitch_deck_structure.txt").write_text(structure, encoding="utf-8")
                (job_dir / "slide_content.md").write_text(markdown, encoding="utf-8")
                (job_dir / "slides.html").write_text(html, encoding="utf-8")

                logs.append("Saved structure, slide notes, and HTML preview.")
                logs.append("PPTX will be generated when Download PPTX is clicked.")

                self._send_json(
                    {
                        "job_id": job_id,
                        "title": deck["title"],
                        "slide_count": deck["slide_count"],
                        "slides": [
                            {
                                "number": slide["number"],
                                "title": slide["title"],
                                "subtitle": slide["subtitle"],
                            }
                            for slide in deck["slides"]
                        ],
                        "sources": research.get("sources", []),
                        "logs": logs,
                        "structure": structure,
                        "slide_content": markdown,
                        "preview_html": render_preview_fragment(deck),
                        "download_url": f"/api/jobs/{job_id}/deck.pptx",
                        "html_url": f"/api/jobs/{job_id}/slides.html",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

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
                "deck.json": "application/json; charset=utf-8",
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

