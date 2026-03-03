# Latency Benchmark Repro Guide (`latency.md`)

This guide reproduces a benchmark matrix for:

1. Direct MCP tool call latency (`/call-tool`)
2. End-to-end eval run latency (`/v2/mcp_eval/run_agent`)

It is designed for a fresh clone and does **not** require real LLM/API keys in the default mock setup.

## What this benchmark varies

- `FILE_SIZE_MULTIPLIER`: inflates CSV size via `services/agent-environment/adjust_latency_files.py`
- `PROMPT_PADDING_CHARS`: inflates prompt length via `services/mcp_eval/mcp_completion/prompt_padding.py`

## 1. Fresh clone setup

```bash
git clone <your-repo-url> mcp-atlas-latency
cd mcp-atlas-latency
cp env.template .env
```

Install required CLIs if needed:
- `python3` (3.10+)
- `uv`

Install `mcp_eval` dependencies:

```bash
cd services/mcp_eval
uv sync
cd ../..
```

## 2. Configure `.env` for latency benchmarking

`env.template` now includes a latency section with these defaults:

```dotenv
PROMPT_PADDING_CHARS=0
FILE_SIZE_MULTIPLIER=1
LATENCY_FILE_MULTIPLIERS=1,300
LATENCY_PROMPT_PADDING_CHARS=0,20000
LATENCY_REPEATS=3
LATENCY_MCP_SERVER_URL=http://127.0.0.1:1984
LATENCY_LLM_BASE_URL=http://127.0.0.1:4010/v1
```

For default mock benchmark mode, no API keys are required.

## 3. Start local mock services (Terminal A + B)

Terminal A:

```bash
python3 scripts/latency/mock_mcp_server.py
```

Terminal B:

```bash
python3 scripts/latency/mock_openai_server.py
```

Keep both running.

## 4. Run the matrix benchmark (Terminal C)

```bash
python3 scripts/latency/run_latency_matrix.py
```

This will:
- run all combinations of `LATENCY_FILE_MULTIPLIERS x LATENCY_PROMPT_PADDING_CHARS`
- warm up each cell once
- collect `LATENCY_REPEATS` measured samples per cell
- restore data files to multiplier `1` at the end

Outputs:
- `latency_results/benchmark_matrix_output.json`
- `latency_results/benchmark_matrix_output.csv`

## 5. Recreate the timing table with deltas

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

obj = json.loads(Path('latency_results/benchmark_matrix_output.json').read_text())
rows = obj['results']
base = next(r for r in rows if r['file_multiplier'] == 1 and r['prompt_padding_chars'] == 0)
base_tool = base['tool']['median_s']
base_eval = base['eval']['median_s']

print('| file mult | padding | file size (bytes) | tool median (s) | tool delta | eval median (s) | eval delta |')
print('|---:|---:|---:|---:|---:|---:|---:|')
for r in rows:
    t = r['tool']['median_s']
    e = r['eval']['median_s']
    print(
        f"| {r['file_multiplier']} | {r['prompt_padding_chars']} | {r['file_size_bytes']} "
        f"| {t:.6f} | {t - base_tool:+.6f} ({(t/base_tool):.2f}x) "
        f"| {e:.6f} | {e - base_eval:+.6f} ({(e/base_eval):.2f}x) |"
    )
PY
```

## 6. Example table from a validated run

This was generated on this repository with:
- `LATENCY_FILE_MULTIPLIERS=1,300`
- `LATENCY_PROMPT_PADDING_CHARS=0,20000`
- `LATENCY_REPEATS=3`

| file mult | padding | file size (bytes) | tool median (s) | tool delta | eval median (s) | eval delta |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 1076 | 0.000591 | +0.000000 (1.00x) | 0.118022 | +0.000000 (1.00x) |
| 1 | 20000 | 1076 | 0.001065 | +0.000474 (1.80x) | 1.113546 | +0.995524 (9.44x) |
| 300 | 0 | 296189 | 0.002638 | +0.002047 (4.46x) | 7.501713 | +7.383691 (63.56x) |
| 300 | 20000 | 296189 | 0.003541 | +0.002950 (5.99x) | 8.519938 | +8.401916 (72.19x) |

## 7. Run different multipliers/paddings

You can override the defaults by exporting env vars or via CLI args.

Environment variable example:

```bash
export LATENCY_FILE_MULTIPLIERS=1,10,100,300
export LATENCY_PROMPT_PADDING_CHARS=0,5000,20000
export LATENCY_REPEATS=5
python3 scripts/latency/run_latency_matrix.py
```

CLI arg example:

```bash
python3 scripts/latency/run_latency_matrix.py \
  --file-multipliers 1,10,100,300 \
  --prompt-padding-chars 0,5000,20000 \
  --repeats 5
```

## 8. Cleanup

Stop mock servers with `Ctrl+C` in Terminal A and B.

If needed, reset local data files explicitly:

```bash
python3 services/agent-environment/adjust_latency_files.py --multiplier 1
```

## Notes

- These numbers are expected to vary by machine.
- The mock path gives stable, reproducible deltas without external provider variability.
- If you want to benchmark real providers, point `LLM_BASE_URL`/`LLM_API_KEY` and `LATENCY_LLM_BASE_URL` to your real endpoint and keep the same matrix process.
