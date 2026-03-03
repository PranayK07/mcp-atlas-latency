#!/usr/bin/env python3
"""Run a latency benchmark matrix for tool calls and eval runs.

This script measures:
1) Direct tool call latency against MCP server /call-tool
2) End-to-end eval run latency against MCP completion service /v2/mcp_eval/run_agent

By default it expects local mock services:
- MCP server: http://127.0.0.1:1984
- LLM API base: http://127.0.0.1:4010/v1
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


ROOT = _repo_root()
AGENT_ENV_DIR = ROOT / "services" / "agent-environment"
MCP_EVAL_DIR = ROOT / "services" / "mcp_eval"


def _parse_int_list(value: str) -> list[int]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise ValueError("List cannot be empty")
    return [int(p) for p in parts]


def _post_json(url: str, payload: dict[str, Any], timeout: float = 120.0) -> tuple[float, int, bytes]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        status = resp.status
    elapsed = time.perf_counter() - start
    return elapsed, status, body


def _wait_for_health(url: str, timeout_s: float = 45.0) -> None:
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(0.2)
    raise RuntimeError(f"Health check failed for {url}: {last_err}")


def _start_mcp_eval(padding_chars: int, mcp_url: str, llm_base_url: str) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "HOST": "127.0.0.1",
            "PORT": "3000",
            "LLM_API_KEY": env.get("LLM_API_KEY", "dummy-key"),
            "LLM_BASE_URL": llm_base_url,
            "MCP_SERVER_URL": mcp_url,
            "PROMPT_PADDING_CHARS": str(padding_chars),
            "LOG_LEVEL": "WARNING",
        }
    )

    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "mcp_completion.main"],
        cwd=MCP_EVAL_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    _wait_for_health("http://127.0.0.1:3000/health", timeout_s=45.0)
    return proc


def _stop_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _adjust_files(multiplier: int) -> int:
    subprocess.run(
        ["python3", "adjust_latency_files.py", "--multiplier", str(multiplier)],
        cwd=AGENT_ENV_DIR,
        check=True,
    )
    csv_path = AGENT_ENV_DIR / "data" / "Barber Shop.csv"
    return csv_path.stat().st_size


def _summarize(samples: list[float]) -> dict[str, float]:
    return {
        "mean_s": statistics.mean(samples),
        "median_s": statistics.median(samples),
        "min_s": min(samples),
        "max_s": max(samples),
    }


def _write_csv(rows: list[dict[str, Any]], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "file_multiplier",
        "prompt_padding_chars",
        "file_size_bytes",
        "tool_mean_s",
        "tool_median_s",
        "tool_min_s",
        "tool_max_s",
        "eval_mean_s",
        "eval_median_s",
        "eval_min_s",
        "eval_max_s",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "file_multiplier": row["file_multiplier"],
                    "prompt_padding_chars": row["prompt_padding_chars"],
                    "file_size_bytes": row["file_size_bytes"],
                    "tool_mean_s": row["tool"]["mean_s"],
                    "tool_median_s": row["tool"]["median_s"],
                    "tool_min_s": row["tool"]["min_s"],
                    "tool_max_s": row["tool"]["max_s"],
                    "eval_mean_s": row["eval"]["mean_s"],
                    "eval_median_s": row["eval"]["median_s"],
                    "eval_min_s": row["eval"]["min_s"],
                    "eval_max_s": row["eval"]["max_s"],
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run latency matrix benchmark")
    parser.add_argument(
        "--file-multipliers",
        default=os.getenv("LATENCY_FILE_MULTIPLIERS", "1,300"),
        help="Comma-separated list, e.g. 1,300",
    )
    parser.add_argument(
        "--prompt-padding-chars",
        default=os.getenv("LATENCY_PROMPT_PADDING_CHARS", "0,20000"),
        help="Comma-separated list, e.g. 0,20000",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=int(os.getenv("LATENCY_REPEATS", "3")),
        help="Measured repetitions per matrix cell",
    )
    parser.add_argument(
        "--mcp-url",
        default=os.getenv("LATENCY_MCP_SERVER_URL", "http://127.0.0.1:1984"),
    )
    parser.add_argument(
        "--llm-base-url",
        default=os.getenv("LATENCY_LLM_BASE_URL", "http://127.0.0.1:4010/v1"),
    )
    parser.add_argument(
        "--output-json",
        default="latency_results/benchmark_matrix_output.json",
    )
    parser.add_argument(
        "--output-csv",
        default="latency_results/benchmark_matrix_output.csv",
    )

    args = parser.parse_args()
    file_multipliers = _parse_int_list(args.file_multipliers)
    prompt_padding_values = _parse_int_list(args.prompt_padding_chars)

    matrix = [
        {"file_multiplier": mult, "prompt_padding_chars": pad}
        for mult in file_multipliers
        for pad in prompt_padding_values
    ]

    tool_payload = {
        "tool_name": "filesystem_read_text_file",
        "tool_args": {"path": "/data/Barber Shop.csv"},
    }
    eval_payload = {
        "model": "openai/mock-model",
        "messages": [
            {
                "role": "user",
                "content": "What is the first word of the file at /data/Barber Shop.csv?",
            }
        ],
        "enabledTools": ["filesystem_read_text_file"],
        "maxTurns": 5,
    }

    results: list[dict[str, Any]] = []

    try:
        for row in matrix:
            mult = row["file_multiplier"]
            pad = row["prompt_padding_chars"]

            file_size = _adjust_files(mult)
            proc = _start_mcp_eval(pad, args.mcp_url, args.llm_base_url)
            try:
                # Warm-up
                _post_json(f"{args.mcp_url}/call-tool", tool_payload, timeout=60)
                _post_json("http://127.0.0.1:3000/v2/mcp_eval/run_agent", eval_payload, timeout=180)

                tool_samples: list[float] = []
                eval_samples: list[float] = []

                for _ in range(args.repeats):
                    t, status, _ = _post_json(f"{args.mcp_url}/call-tool", tool_payload, timeout=60)
                    if status != 200:
                        raise RuntimeError(f"tool call returned non-200: {status}")
                    tool_samples.append(t)

                    t, status, body = _post_json(
                        "http://127.0.0.1:3000/v2/mcp_eval/run_agent",
                        eval_payload,
                        timeout=300,
                    )
                    if status != 200:
                        raise RuntimeError(f"eval run returned non-200: {status} body={body[:500]!r}")
                    parsed = json.loads(body.decode("utf-8"))
                    if not isinstance(parsed, list) or not parsed:
                        raise RuntimeError(f"unexpected eval response: {parsed!r}")
                    eval_samples.append(t)

                result = {
                    "file_multiplier": mult,
                    "prompt_padding_chars": pad,
                    "file_size_bytes": file_size,
                    "tool": _summarize(tool_samples),
                    "eval": _summarize(eval_samples),
                    "tool_samples_s": tool_samples,
                    "eval_samples_s": eval_samples,
                }
                results.append(result)
                print(
                    f"completed mult={mult}, pad={pad} | "
                    f"tool_median={result['tool']['median_s']:.6f}s | "
                    f"eval_median={result['eval']['median_s']:.6f}s"
                )
            finally:
                _stop_proc(proc)
    finally:
        _adjust_files(1)

    out_json = ROOT / args.output_json
    out_csv = ROOT / args.output_csv
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"repeats": args.repeats, "results": results}, indent=2), encoding="utf-8")
    _write_csv(results, out_csv)

    print(f"wrote {out_json}")
    print(f"wrote {out_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
