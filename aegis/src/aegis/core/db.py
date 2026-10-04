"""SQLite helpers (CONTRACTS section 6.1). Each owner creates its own tables in `start()`.

`connect(path)` → new connection: WAL, `row_factory=sqlite3.Row`, `check_same_thread=False`,
`busy_timeout=5000`. Core-gateway's own table is `sessions`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, org_id TEXT, agent_id TEXT, member_id TEXT,
  source TEXT, started_at TEXT NOT NULL, last_seen TEXT NOT NULL, requests INTEGER NOT NULL DEFAULT 0);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection configured for concurrent gateway use."""
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_core_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(CORE_SCHEMA)


__all__ = ["CORE_SCHEMA", "connect", "ensure_core_tables"]
