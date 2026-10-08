"""Local HTTP API used by the browser extension and the CLI.

Only loopback, and only from a browser extension or a non-browser client:
a normal web page must not be able to drive the reader (and spend the key).
- Requests with an Origin header are accepted only from moz-extension:// or
  chrome-extension:// origins (browsers always send Origin on cross-site POST).
- POST bodies must be application/json, which a web page can't send
  cross-origin without a CORS preflight that we never approve.
- The Host header must be 127.0.0.1/localhost (blocks DNS rebinding).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol

ALLOWED_ORIGIN_PREFIXES = ("moz-extension://", "chrome-extension://")
MAX_BODY = 512 * 1024
MAX_SEGMENTS = 500


class Controller(Protocol):
    """Thread-safe facade over the app; called from server threads."""

    def read(self, segments: list[dict]) -> str: ...
    def control(self, action: str) -> None: ...
    def update_settings(self, data: dict) -> dict: ...
    def status(self) -> dict: ...


ACTIONS = {"pause", "resume", "toggle", "stop", "next"}


def parse_segments(body: dict) -> list[dict]:
    """Accept {"text": "..."} or {"segments": [{"id": "...", "text": "..."}]}."""
    if "segments" in body:
        raw = body["segments"]
        if not isinstance(raw, list) or not raw or len(raw) > MAX_SEGMENTS:
            raise ValueError("segments deve ser uma lista não vazia")
        segments = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ValueError("cada segmento precisa de 'text'")
            seg_id = str(item.get("id", i))
            if item["text"].strip():
                segments.append({"id": seg_id, "text": item["text"]})
    elif isinstance(body.get("text"), str):
        segments = [{"id": "0", "text": body["text"]}] if body["text"].strip() else []
    else:
        raise ValueError("envie 'text' ou 'segments'")
    if not segments:
        raise ValueError("texto vazio")
    return segments


def make_handler(controller: Controller):
    class Handler(BaseHTTPRequestHandler):
        server_version = "leitor-voz"

        def log_message(self, *args):  # keep the terminal quiet
            pass

        # -- helpers --

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            return origin is None or origin.startswith(ALLOWED_ORIGIN_PREFIXES)

        def _reply(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            origin = self.headers.get("Origin")
            if origin and origin.startswith(ALLOWED_ORIGIN_PREFIXES):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        def _guard(self) -> bool:
            port = self.server.server_address[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                self._reply(403, {"error": "host não permitido"})
                return False
            if not self._origin_ok():
                self._reply(403, {"error": "origem não permitida"})
                return False
            return True

        def _json_body(self) -> dict:
            ctype = self.headers.get("Content-Type", "").split(";")[0].strip()
            if ctype != "application/json":
                raise ValueError("Content-Type deve ser application/json")
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("corpo grande demais")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("JSON deve ser um objeto")
            return data

        # -- routes --

        def do_OPTIONS(self):
            if not self._guard():
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"] or "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            if not self._guard():
                return
            if self.path == "/status":
                self._reply(200, controller.status())
            else:
                self._reply(404, {"error": "rota desconhecida"})

        def do_POST(self):
            if not self._guard():
                return
            try:
                body = self._json_body()
                if self.path == "/read":
                    reading_id = controller.read(parse_segments(body))
                    self._reply(200, {"reading_id": reading_id})
                elif self.path == "/control":
                    action = body.get("action")
                    if action not in ACTIONS:
                        raise ValueError(f"ação deve ser uma de {sorted(ACTIONS)}")
                    controller.control(action)
                    self._reply(200, {"ok": True})
                elif self.path == "/settings":
                    self._reply(200, controller.update_settings(body))
                else:
                    self._reply(404, {"error": "rota desconhecida"})
            except (ValueError, TypeError) as exc:
                self._reply(400, {"error": str(exc)})

    return Handler


class ApiServer:
    def __init__(self, controller: Controller, port: int):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(controller))
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
