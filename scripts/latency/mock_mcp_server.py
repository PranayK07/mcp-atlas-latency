#!/usr/bin/env python3
"""Mock MCP server for latency benchmarking.

Implements:
- POST /list-tools
- POST /call-tool

Supported tool:
- filesystem_read_text_file
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _json_bytes(obj: object) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


DATA_ROOT = (
    Path(os.getenv("LATENCY_DATA_ROOT", ""))
    if os.getenv("LATENCY_DATA_ROOT")
    else _repo_root() / "services" / "agent-environment" / "data"
)

TOOL_NAME = "filesystem_read_text_file"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": "Read a UTF-8 text file from /data",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "head": {"type": "integer"},
        },
        "required": ["path"],
    },
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: object) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {}

        if self.path == "/list-tools":
            self._send(200, [TOOL_DEF])
            return

        if self.path == "/call-tool":
            tool_name = body.get("tool_name")
            tool_args = body.get("tool_args") or {}

            if tool_name != TOOL_NAME:
                self._send(400, [{"type": "text", "text": f"Unsupported tool: {tool_name}"}])
                return

            path = tool_args.get("path", "")
            head = tool_args.get("head")

            if not isinstance(path, str) or not path.startswith("/data/"):
                self._send(400, [{"type": "text", "text": "path must start with /data/"}])
                return

            file_path = DATA_ROOT / path.removeprefix("/data/")
            if not file_path.exists() or not file_path.is_file():
                self._send(404, [{"type": "text", "text": f"File not found: {path}"}])
                return

            text = file_path.read_text(encoding="utf-8")
            if isinstance(head, int) and head > 0:
                text = "\n".join(text.splitlines()[:head])

            self._send(200, [{"type": "text", "text": text}])
            return

        self._send(404, {"error": f"Unknown path: {self.path}"})

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401
        return


if __name__ == "__main__":
    host = os.getenv("LATENCY_MCP_HOST", "127.0.0.1")
    port = int(os.getenv("LATENCY_MCP_PORT", "1984"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"mock_mcp_server listening on http://{host}:{port} with data root: {DATA_ROOT}")
    server.serve_forever()
