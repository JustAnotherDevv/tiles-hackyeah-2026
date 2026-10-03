"""SQLite persistence for budget counters (write-behind) and burn-down samples.

All functions are synchronous and meant to be called via `asyncio.to_thread`. Tables are the
CONTRACTS section 6.1 DDL verbatim; reservations are never persisted.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

DDL = """
CREATE TABLE IF NOT EXISTS budget_usage (scope TEXT NOT NULL, window TEXT NOT NULL, window_start TEXT NOT NULL, dimension TEXT NOT NULL,
  used REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, PRIMARY KEY (scope, window, window_start, dimension));
CREATE TABLE IF NOT EXISTS budget_samples (ts TEXT NOT NULL, scope TEXT NOT NULL, dimension TEXT NOT NULL, window TEXT NOT NULL,
  used REAL NOT NULL, limit_value REAL);
CREATE INDEX IF NOT EXISTS ix_budget_samples_scope ON budget_samples(scope, dimension, window, ts);
"""

UsageRow = tuple[str, str, str, str, float, str]  # scope, window, window_start, dim, used, updated
SampleRow = tuple[str, str, str, str, float, float | None]  # ts, scope, dim, window, used, limit


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()


def is_empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) FROM budget_usage").fetchone()
    return int(row[0]) == 0


def load_current(
    conn: sqlite3.Connection, starts: Iterable[str], session_since: str | None = None
) -> list[UsageRow]:
    """Rows of the current calendar windows (given window_start values), all `total` rows and
    session rows updated since `session_since`."""
    starts = sorted(set(starts) | {"total"})
    marks = ",".join("?" for _ in starts)
    rows = list(
        conn.execute(
            f"SELECT scope, window, window_start, dimension, used, updated_at FROM budget_usage "
            f"WHERE window_start IN ({marks})",
            starts,
        )
    )
    if session_since is not None:
        rows += list(
            conn.execute(
                "SELECT scope, window, window_start, dimension, used, updated_at FROM budget_usage "
                "WHERE window = 'session' AND updated_at >= ?",
                (session_since,),
            )
        )
    return [(r[0], r[1], r[2], r[3], float(r[4]), r[5]) for r in rows]


def flush(conn: sqlite3.Connection, rows: list[UsageRow]) -> int:
    if not rows:
        return 0
    conn.executemany(
        "INSERT INTO budget_usage (scope, window, window_start, dimension, used, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(scope, window, window_start, dimension) "
        "DO UPDATE SET used = excluded.used, updated_at = excluded.updated_at",
        rows,
    )
    conn.commit()
    return len(rows)


def insert_samples(conn: sqlite3.Connection, rows: list[SampleRow]) -> int:
    if not rows:
        return 0
    conn.executemany(
        "INSERT INTO budget_samples (ts, scope, dimension, window, used, limit_value) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def query_samples(
    conn: sqlite3.Connection, scope: str, dimension: str, window: str, since: str
) -> list[tuple[str, float, float | None]]:
    return [
        (r[0], float(r[1]), None if r[2] is None else float(r[2]))
        for r in conn.execute(
            "SELECT ts, used, limit_value FROM budget_samples WHERE scope = ? AND dimension = ? "
            "AND window = ? AND ts >= ? ORDER BY ts",
            (scope, dimension, window, since),
        )
    ]


def wipe(conn: sqlite3.Connection, scope: str | None = None) -> None:
    if scope is None:
        conn.execute("DELETE FROM budget_usage")
        conn.execute("DELETE FROM budget_samples")
    else:
        conn.execute("DELETE FROM budget_usage WHERE scope = ?", (scope,))
        conn.execute("DELETE FROM budget_samples WHERE scope = ?", (scope,))
    conn.commit()


def prune_samples(conn: sqlite3.Connection, before: str) -> None:
    conn.execute("DELETE FROM budget_samples WHERE ts < ?", (before,))
    conn.commit()


__all__ = [
    "DDL",
    "ensure_schema",
    "flush",
    "insert_samples",
    "is_empty",
    "load_current",
    "prune_samples",
    "query_samples",
    "wipe",
]
