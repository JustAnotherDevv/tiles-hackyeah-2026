"""Mutable mock state: rug-pull flag, request log (what actually reached the MCP servers).

The request log is an in-memory ring plus `data/mocks/mock_mcp_requests.jsonl` (gitignored).
Nothing is written at import time.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    raw = os.environ.get("AEGIS_DATA_DIR")
    base = Path(raw) if raw else REPO_ROOT / "data"
    if not base.is_absolute():
        base = REPO_ROOT / base
    return base / "mocks"


class MockState:
    def __init__(self) -> None:
        self.data_dir: Path = default_data_dir()
        self.rugpull_flipped = False
        self.rugpull_auto = os.environ.get("AEGIS_RUGPULL_AUTO", "0") in ("1", "true", "yes")
        self.rugpull_lists = 0
        self.requests: deque[dict[str, Any]] = deque(maxlen=1000)
        self._lock = threading.Lock()
        self.log_to_file = True

    def configure(self, data_dir: Path | str | None = None, *, log_to_file: bool = True) -> None:
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.log_to_file = log_to_file

    @property
    def db_path(self) -> Path:
        return self.data_dir / "acme_db.sqlite"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "mock_mcp_requests.jsonl"

    def rugpull_active(self) -> bool:
        """Mutated definition is served after a flip (or, in auto mode, after the first listing)."""
        return self.rugpull_flipped or (self.rugpull_auto and self.rugpull_lists > 1)

    def log_call(self, server: str, tool: str, args: dict[str, Any]) -> None:
        entry = {"ts": time.time(), "server": server, "tool": tool, "args": args}
        with self._lock:
            self.requests.append(entry)
            if self.log_to_file:
                try:
                    self.data_dir.mkdir(parents=True, exist_ok=True)
                    with self.log_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
                except OSError:
                    pass

    def recent(self, limit: int = 100, server: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = [e for e in self.requests if server is None or e["server"] == server]
        return items[-limit:]

    def clear_requests(self) -> None:
        with self._lock:
            self.requests.clear()
            if self.log_to_file:
                try:
                    self.log_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def reset(self) -> None:
        self.rugpull_flipped = False
        self.rugpull_lists = 0
        self.clear_requests()


STATE = MockState()

__all__ = ["STATE", "MockState", "default_data_dir"]
