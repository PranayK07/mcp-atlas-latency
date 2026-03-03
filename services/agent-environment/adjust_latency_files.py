"""
Utility to adjust local data file sizes to emulate different MCP tool latencies.

This script operates on the CSV files in the `data/` directory that are mounted
into the Docker container at `/data`. It enlarges these files by repeating their
rows, which increases the amount of data processed by local MCP servers such as
the filesystem server.

Usage (from `services/agent-environment`):

    # One-time backup of originals and 10x larger files
    python adjust_latency_files.py --multiplier 10

    # Or use the environment variable (takes precedence over the default)
    FILE_SIZE_MULTIPLIER=5 python adjust_latency_files.py

This script is idempotent with respect to the originals: it always reads from
`data/original/<filename>` if present, falling back to the current file only
the first time to create the backup.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable


DATA_DIR = Path(__file__).resolve().parent / "data"
BACKUP_DIR = DATA_DIR / "original"


def _iter_csv_files() -> Iterable[Path]:
    for path in DATA_DIR.glob("*.csv"):
        # Skip any backup copies
        if path.parent == BACKUP_DIR:
            continue
        yield path


def _ensure_backup(src: Path) -> Path:
    """
    Ensure there is a backup of `src` under BACKUP_DIR and return the backup path.
    """
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = BACKUP_DIR / src.name
    if not backup_path.exists():
        backup_path.write_bytes(src.read_bytes())
    return backup_path


def _resize_file(src: Path, multiplier: int) -> None:
    """
    Resize `src` by repeating its non-header rows `multiplier` times.

    The header row is kept as-is. Content is duplicated so that simple operations
    such as "first word of the file" or aggregations over rows still behave
    consistently while increasing total file size.
    """
    backup_path = _ensure_backup(src)
    text = backup_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines:
        return

    header, *rows = lines

    if multiplier <= 1 or not rows:
        new_lines = [header] + rows
    else:
        new_lines = [header] + rows * multiplier

    src.write_text("".join(new_lines), encoding="utf-8")


def adjust_files(multiplier: int) -> None:
    if multiplier < 1:
        raise ValueError("multiplier must be >= 1")

    csv_files = list(_iter_csv_files())
    if not csv_files:
        return

    for path in csv_files:
        _resize_file(path, multiplier)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Adjust local CSV file sizes in `data/` to emulate different MCP tool "
            "latencies by repeating rows."
        )
    )
    parser.add_argument(
        "--multiplier",
        type=int,
        default=None,
        help=(
            "Number of times to repeat the non-header rows in each CSV. "
            "If not provided, FILE_SIZE_MULTIPLIER env var is used, "
            "falling back to 1 (no change)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    env_multiplier = os.getenv("FILE_SIZE_MULTIPLIER")
    if args.multiplier is not None:
        multiplier = args.multiplier
    elif env_multiplier is not None:
        try:
            multiplier = int(env_multiplier)
        except ValueError:
            raise ValueError(
                f"Invalid FILE_SIZE_MULTIPLIER value: {env_multiplier!r} "
                "– expected integer"
            )
    else:
        multiplier = 1

    adjust_files(multiplier)


if __name__ == "__main__":
    main()

