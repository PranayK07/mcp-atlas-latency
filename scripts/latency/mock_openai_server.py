#!/usr/bin/env python3
"""Mock OpenAI-compatible chat completions server for latency benchmarking.

Implements:
- POST /v1/chat/completions
- POST /chat/completions

Latency model:
- sleep_s = LATENCY_LLM_FIXED_SLEEP_S + (prompt_chars / LATENCY_LLM_CHARS_PER_SECOND)
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _json_bytes(obj: object) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _total_chars(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += len(content)
    return total


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: object) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            self._send(404, {"error": {"message": f"Unknown path: {self.path}"}})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            req = {}

        messages = req.get("messages") or []
        prompt_chars = _total_chars(messages)

        fixed_sleep = float(os.getenv("LATENCY_LLM_FIXED_SLEEP_S", "0.03"))
        chars_per_second = float(os.getenv("LATENCY_LLM_CHARS_PER_SECOND", "40000"))
        sleep_s = fixed_sleep + (prompt_chars / chars_per_second)
        time.sleep(max(0.0, sleep_s))

        saw_tool_result = any(m.get("role") == "tool" for m in messages)

        if not saw_tool_result:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "filesystem_read_text_file",
                            "arguments": json.dumps({"path": "/data/Barber Shop.csv"}),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {
                "role": "assistant",
                "content": "The first word is Customer.",
            }
            finish_reason = "stop"

        response = {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.get("model", "openai/mock-model"),
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": max(1, prompt_chars // 4),
                "completion_tokens": 32,
                "total_tokens": max(1, prompt_chars // 4) + 32,
            },
        }
        self._send(200, response)

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401
        return


if __name__ == "__main__":
    host = os.getenv("LATENCY_LLM_HOST", "127.0.0.1")
    port = int(os.getenv("LATENCY_LLM_PORT", "4010"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"mock_openai_server listening on http://{host}:{port}")
    server.serve_forever()
