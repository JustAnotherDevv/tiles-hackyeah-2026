#!/usr/bin/env python3
"""Aegis overhead / throughput benchmark -> reports/bench.json (owner: redteam-eval-perf).

    uv run --frozen python scripts/bench.py [--quick] [--target spawn|inproc|URL] [--modes deterministic,semantic]

Thin wrapper: the implementation lives in tests/bench/ (see `--help`).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.bench.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
