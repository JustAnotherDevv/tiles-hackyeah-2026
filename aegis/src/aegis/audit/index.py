"""SQLite side of the audit log: `audit_index` (seq -> file/line/offset) and the `decisions`
projection behind GET /api/decisions and /api/stats (CONTRACTS section 6.1 + additive G4 columns).

All functions are synchronous and take a `sqlite3.Connection`; callers run them in a thread.
Only audit-metrics reads/writes these tables (rule 7.1-5).
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from aegis.metrics.timing import iso_z, to_utc

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS audit_index (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, ts TEXT NOT NULL, event_type TEXT NOT NULL,
  request_id TEXT, decision_id TEXT, action TEXT, control_id TEXT, actor TEXT, file TEXT NOT NULL, line INTEGER NOT NULL, hash TEXT NOT NULL,
  offset INTEGER, length INTEGER);
CREATE INDEX IF NOT EXISTS ix_audit_index_type ON audit_index(event_type, seq);
CREATE INDEX IF NOT EXISTS ix_audit_index_decision ON audit_index(decision_id);
CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, ts TEXT NOT NULL, request_id TEXT, org_id TEXT, team_id TEXT, member_id TEXT,
  agent_id TEXT, session_id TEXT, source TEXT, kind TEXT, surface TEXT, direction TEXT, dest_name TEXT, dest_class TEXT, model TEXT,
  tool_name TEXT, action_type TEXT, amount_usd REAL, action TEXT NOT NULL, control_id TEXT, reason TEXT, score REAL, latency_ms REAL,
  upstream_ms REAL, cost_usd REAL, tokens INTEGER, redaction_count INTEGER NOT NULL DEFAULT 0, entities_json TEXT NOT NULL DEFAULT '[]',
  policy_version INTEGER, feed_serial INTEGER, degraded INTEGER NOT NULL DEFAULT 0, dry_run INTEGER NOT NULL DEFAULT 0,
  summary_json TEXT NOT NULL, detail_json TEXT,
  cost_avoided_usd REAL NOT NULL DEFAULT 0, avoided_reason TEXT, categories_json TEXT NOT NULL DEFAULT '[]',
  synthetic INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_decisions_ts      ON decisions(ts);
CREATE INDEX IF NOT EXISTS ix_decisions_action  ON decisions(action, ts);
CREATE INDEX IF NOT EXISTS ix_decisions_control ON decisions(control_id, ts);
CREATE INDEX IF NOT EXISTS ix_decisions_agent   ON decisions(agent_id, ts);
CREATE INDEX IF NOT EXISTS ix_decisions_synth   ON decisions(synthetic, ts);
"""

_ADDITIVE = {
    "decisions": {
        "cost_avoided_usd": "REAL NOT NULL DEFAULT 0",
        "avoided_reason": "TEXT",
        "categories_json": "TEXT NOT NULL DEFAULT '[]'",
        "synthetic": "INTEGER NOT NULL DEFAULT 0",
    },
    "audit_index": {"offset": "INTEGER", "length": "INTEGER"},
}

DECISION_COLS = [
    "id",
    "ts",
    "request_id",
    "org_id",
    "team_id",
    "member_id",
    "agent_id",
    "session_id",
    "source",
    "kind",
    "surface",
    "direction",
    "dest_name",
    "dest_class",
    "model",
    "tool_name",
    "action_type",
    "amount_usd",
    "action",
    "control_id",
    "reason",
    "score",
    "latency_ms",
    "upstream_ms",
    "cost_usd",
    "tokens",
    "redaction_count",
    "entities_json",
    "policy_version",
    "feed_serial",
    "degraded",
    "dry_run",
    "summary_json",
    "detail_json",
    "categories_json",
    "synthetic",
    "cost_avoided_usd",
    "avoided_reason",
]
_PRESERVE_ON_CONFLICT = {"id", "cost_avoided_usd", "avoided_reason", "synthetic"}
_COALESCE_ON_CONFLICT = {"cost_usd", "tokens", "upstream_ms"}


def connect(path: Path | str) -> sqlite3.Connection:
    """Fallback connection when no rt.db() exists (CLI / tests)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    for table, cols in _ADDITIVE.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, decl in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.commit()


# ------------------------------------------------------------------ write side
def _principal(actor: dict[str, Any] | None) -> str | None:
    if not actor:
        return None
    if actor.get("agent_id"):
        return f"agent:{actor['agent_id']}"
    if actor.get("member_id"):
        return f"member:{actor['member_id']}"
    return None


def insert_audit_index(
    conn: sqlite3.Connection, d: dict[str, Any], file: str, line: int, offset: int, length: int
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO audit_index (seq, event_id, ts, event_type, request_id, decision_id,"
        " action, control_id, actor, file, line, hash, offset, length)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            d.get("seq"),
            d.get("event_id"),
            iso_z(d.get("ts")),
            d.get("event_type"),
            d.get("request_id"),
            d.get("decision_id"),
            d.get("action"),
            d.get("control_id"),
            _principal(d.get("actor")),
            file,
            line,
            d.get("hash"),
            offset,
            length,
        ),
    )


def summary_from_event(d: dict[str, Any]) -> dict[str, Any]:
    """DecisionSummary-shaped dict built from AuditEvent top-level fields (pipeline sent none)."""
    reds = d.get("redactions") or []
    usage = d.get("usage") or {}
    tokens = None
    if usage:
        tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    return {
        "id": d.get("decision_id") or d.get("event_id"),
        "ts": d.get("ts"),
        "request_id": d.get("request_id") or "",
        "action": d.get("action") or "allow",
        "kind": d.get("kind") or "model_call",
        "surface": d.get("surface") or "model.request",
        "direction": d.get("direction") or "out",
        "destination": d.get("destination") or {"name": "unknown", "dest_class": "remote"},
        "model": d.get("model"),
        "tool_name": d.get("tool_name"),
        "action_type": d.get("action_type"),
        "amount_usd": d.get("amount_usd"),
        "identity": d.get("actor") or {"org_id": "default", "role": "agent"},
        "session_id": d.get("session_id") or "default",
        "source": (d.get("data") or {}).get("source") or "proxy",
        "control_id": d.get("control_id"),
        "reason": d.get("reason") or "",
        "score": d.get("score"),
        "threshold": d.get("threshold"),
        "controls": d.get("controls") or [],
        "redaction_count": len(reds),
        "entities": sorted(
            {r.get("entity") for r in reds if isinstance(r, dict) and r.get("entity")}
        ),
        "approval_id": None,
        "latency_ms": d.get("latency_ms") or 0.0,
        "upstream_ms": None,
        "policy_version": d.get("policy_version") or 0,
        "feed_serial": d.get("feed_serial"),
        "degraded": False,
        "cost_usd": usage.get("cost_usd") if usage else None,
        "tokens": tokens,
        "preview": "",
        "dry_run": False,
    }


def categories_of(detail: dict[str, Any] | None) -> list[str]:
    cats: set[str] = set()
    for dec in (detail or {}).get("decisions") or []:
        if not isinstance(dec, dict):
            continue
        if dec.get("action") in (None, "allow") and dec.get("mode") != "monitor":
            continue
        for f in dec.get("findings") or []:
            if isinstance(f, dict) and f.get("category"):
                cats.add(str(f["category"]))
    return sorted(cats)


def decision_row(
    summary: dict[str, Any],
    detail: dict[str, Any] | None,
    *,
    categories: Iterable[str] = (),
    synthetic: bool = False,
    cost_avoided_usd: float = 0.0,
    avoided_reason: str | None = None,
) -> dict[str, Any]:
    ident = summary.get("identity") or {}
    dest = summary.get("destination") or {}
    return {
        "id": summary["id"],
        "ts": iso_z(summary.get("ts")),
        "request_id": summary.get("request_id"),
        "org_id": ident.get("org_id"),
        "team_id": ident.get("team_id"),
        "member_id": ident.get("member_id"),
        "agent_id": ident.get("agent_id"),
        "session_id": summary.get("session_id"),
        "source": summary.get("source"),
        "kind": summary.get("kind"),
        "surface": summary.get("surface"),
        "direction": summary.get("direction"),
        "dest_name": dest.get("name"),
        "dest_class": dest.get("dest_class"),
        "model": summary.get("model"),
        "tool_name": summary.get("tool_name"),
        "action_type": summary.get("action_type"),
        "amount_usd": summary.get("amount_usd"),
        "action": summary.get("action") or "allow",
        "control_id": summary.get("control_id"),
        "reason": summary.get("reason"),
        "score": summary.get("score"),
        "latency_ms": summary.get("latency_ms"),
        "upstream_ms": summary.get("upstream_ms"),
        "cost_usd": summary.get("cost_usd"),
        "tokens": summary.get("tokens"),
        "redaction_count": int(summary.get("redaction_count") or 0),
        "entities_json": json.dumps(summary.get("entities") or []),
        "policy_version": summary.get("policy_version"),
        "feed_serial": summary.get("feed_serial"),
        "degraded": 1 if summary.get("degraded") else 0,
        "dry_run": 1 if summary.get("dry_run") else 0,
        "summary_json": json.dumps(summary, separators=(",", ":"), default=str),
        "detail_json": json.dumps(detail, separators=(",", ":"), default=str)
        if detail is not None
        else None,
        "categories_json": json.dumps(sorted(set(categories))),
        "synthetic": 1 if synthetic else 0,
        "cost_avoided_usd": float(cost_avoided_usd or 0.0),
        "avoided_reason": avoided_reason,
    }


def _upsert_sql() -> str:
    cols = ", ".join(DECISION_COLS)
    qs = ", ".join("?" for _ in DECISION_COLS)
    sets = []
    for c in DECISION_COLS:
        if c in _PRESERVE_ON_CONFLICT:
            continue
        if c in _COALESCE_ON_CONFLICT:
            sets.append(f"{c}=COALESCE(excluded.{c}, decisions.{c})")
        else:
            sets.append(f"{c}=excluded.{c}")
    return f"INSERT INTO decisions ({cols}) VALUES ({qs}) ON CONFLICT(id) DO UPDATE SET {', '.join(sets)}"


UPSERT_SQL = _upsert_sql()
INSERT_IGNORE_SQL = (
    f"INSERT OR IGNORE INTO decisions ({', '.join(DECISION_COLS)}) "
    f"VALUES ({', '.join('?' for _ in DECISION_COLS)})"
)


def upsert_decision(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(UPSERT_SQL, [row[c] for c in DECISION_COLS])


def insert_decisions(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    conn.executemany(INSERT_IGNORE_SQL, [[r[c] for c in DECISION_COLS] for r in rows])


def annotate(conn: sqlite3.Connection, decision_id: str, **cols: Any) -> int:
    allowed = {k: v for k, v in cols.items() if k in DECISION_COLS and k != "id"}
    if not allowed:
        return 0
    sets = ", ".join(f"{k}=?" for k in allowed)
    cur = conn.execute(f"UPDATE decisions SET {sets} WHERE id=?", [*allowed.values(), decision_id])
    return cur.rowcount


def apply_outcome(
    conn: sqlite3.Connection,
    decision_id: str,
    *,
    cost_usd: float | None,
    tokens: int | None,
    upstream_ms: float | None,
) -> int:
    """Outcome phase (R1): usage/cost/upstream time land on the decision row + summary_json."""
    cur = conn.execute(
        "UPDATE decisions SET cost_usd=COALESCE(?, cost_usd), tokens=COALESCE(?, tokens),"
        " upstream_ms=COALESCE(?, upstream_ms),"
        " summary_json=json_set(summary_json, '$.cost_usd', COALESCE(?, json_extract(summary_json,'$.cost_usd')),"
        "   '$.tokens', COALESCE(?, json_extract(summary_json,'$.tokens')),"
        "   '$.upstream_ms', COALESCE(?, json_extract(summary_json,'$.upstream_ms')))"
        " WHERE id=?",
        (cost_usd, tokens, upstream_ms, cost_usd, tokens, upstream_ms, decision_id),
    )
    return cur.rowcount


# ------------------------------------------------------------------ read side
def encode_cursor(*parts: Any) -> str:
    return base64.urlsafe_b64encode("|".join(str(p) for p in parts).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> list[str] | None:
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        return base64.urlsafe_b64decode(cursor + pad).decode().split("|")
    except Exception:
        return None


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def query_decisions(
    conn: sqlite3.Connection,
    *,
    action: str | None = None,
    control_id: str | None = None,
    kind: str | None = None,
    surface: str | None = None,
    agent_id: str | None = None,
    team_id: str | None = None,
    member_id: str | None = None,
    since: str | None = None,
    q: str | None = None,
    include_synthetic: bool = True,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    where: list[str] = []
    args: list[Any] = []
    for col, val in (
        ("action", action),
        ("kind", kind),
        ("surface", surface),
        ("agent_id", agent_id),
        ("team_id", team_id),
        ("member_id", member_id),
    ):
        vals = _csv(val)
        if vals:
            where.append(f"{col} IN ({', '.join('?' for _ in vals)})")
            args.extend(vals)
    if control_id:
        where.append(
            "(control_id = ? OR EXISTS (SELECT 1 FROM json_each(decisions.summary_json, '$.controls') c"
            " WHERE json_extract(c.value, '$.control_id') = ?))"
        )
        args.extend([control_id, control_id])
    if since:
        where.append("ts >= ?")
        args.append(since)
    if q:
        like = f"%{q}%"
        where.append(
            "(id LIKE ? OR reason LIKE ? OR tool_name LIKE ? OR model LIKE ? OR agent_id LIKE ?"
            " OR member_id LIKE ? OR control_id LIKE ? OR json_extract(summary_json,'$.preview') LIKE ?)"
        )
        args.extend([like] * 8)
    if not include_synthetic:
        where.append("synthetic = 0")
    cur_parts = decode_cursor(cursor)
    # tie-break same-ms rows by insertion order (rowid), not by the random tail of the id
    if cur_parts and len(cur_parts) == 2 and cur_parts[1].isdigit():
        where.append("(ts < ? OR (ts = ? AND rowid < ?))")
        args.extend([cur_parts[0], cur_parts[0], int(cur_parts[1])])
    elif cur_parts and len(cur_parts) == 2:  # legacy ts|id cursor
        where.append("(ts < ? OR (ts = ? AND id < ?))")
        args.extend([cur_parts[0], cur_parts[0], cur_parts[1]])
    sql = "SELECT id, ts, summary_json, synthetic, rowid FROM decisions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC, rowid DESC LIMIT ?"
    args.append(limit + 1)
    rows = conn.execute(sql, args).fetchall()
    items: list[dict[str, Any]] = []
    for r in rows[:limit]:
        try:
            items.append(json.loads(r[2]))
        except ValueError:
            continue
    nxt = encode_cursor(rows[limit - 1][1], rows[limit - 1][4]) if len(rows) > limit else None
    return items, nxt


def get_decision(conn: sqlite3.Connection, decision_id: str) -> dict[str, Any] | None:
    r = conn.execute(
        "SELECT summary_json, detail_json, synthetic FROM decisions WHERE id=?", (decision_id,)
    ).fetchone()
    if r is None:
        return None
    try:
        summary = json.loads(r[0])
    except ValueError:
        summary = {}
    detail: dict[str, Any] = {}
    if r[1]:
        try:
            detail = json.loads(r[1])
        except ValueError:
            detail = {}
    out = {**detail, **summary}
    for key in ("decisions", "redactions", "mutations"):
        out[key] = detail.get(key) or []
    out["usage"] = detail.get("usage")
    out["audit_seq"] = detail.get("audit_seq")
    out["audit_hash"] = detail.get("audit_hash")
    out.setdefault("wire", None)
    return out


def query_audit_rows(
    conn: sqlite3.Connection,
    *,
    event_type: str | None = None,
    since: str | None = None,
    decision_id: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
    seq_from: int | None = None,
) -> tuple[list[sqlite3.Row], str | None]:
    where: list[str] = []
    args: list[Any] = []
    if event_type:
        types = _csv(event_type)
        ors = []
        for t in types:
            if t.endswith("*"):
                ors.append("event_type LIKE ?")
                args.append(t[:-1] + "%")
            else:
                ors.append("event_type = ?")
                args.append(t)
        where.append("(" + " OR ".join(ors) + ")")
    if since:
        where.append("ts >= ?")
        args.append(since)
    if decision_id:
        where.append("decision_id = ?")
        args.append(decision_id)
    if seq_from is not None:  # A-54: jump to an old record (page starts at seq_from, newest first)
        where.append("seq <= ?")
        args.append(int(seq_from))
    cur_parts = decode_cursor(cursor)
    if cur_parts:
        try:
            where.append("seq < ?")
            args.append(int(cur_parts[0]))
        except ValueError:
            pass
    sql = "SELECT seq, file, line, offset, length FROM audit_index"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY seq DESC LIMIT ?"
    args.append(limit + 1)
    rows = conn.execute(sql, args).fetchall()
    nxt = encode_cursor(rows[limit - 1][0]) if len(rows) > limit else None
    return rows[:limit], nxt


def read_records(audit_dir: Path, rows: Iterable[Any]) -> list[dict[str, Any]]:
    """Read JSONL records by (file, line, offset, length); falls back to a line scan."""
    out: list[dict[str, Any]] = []
    handles: dict[str, Any] = {}
    try:
        for r in rows:
            seq, file, line, offset, length = r[0], r[1], r[2], r[3], r[4]
            rec = None
            fh = handles.get(file)
            if fh is None:
                try:
                    fh = handles[file] = (audit_dir / file).open("rb")
                except OSError:
                    continue
            if offset is not None and length:
                fh.seek(offset)
                raw = fh.read(length)
                try:
                    rec = json.loads(raw)
                except ValueError:
                    rec = None
            if rec is None or rec.get("seq") != seq:
                fh.seek(0)
                for i, raw in enumerate(fh, 1):
                    if i == line:
                        try:
                            rec = json.loads(raw)
                        except ValueError:
                            rec = None
                        break
            if rec is not None:
                out.append(rec)
    finally:
        for fh in handles.values():
            fh.close()
    return out


def count_audit(conn: sqlite3.Connection) -> tuple[int, str | None]:
    r = conn.execute("SELECT COUNT(*), MAX(seq) FROM audit_index").fetchone()
    if not r or not r[0]:
        return 0, None
    h = conn.execute("SELECT hash FROM audit_index WHERE seq=?", (r[1],)).fetchone()
    return int(r[0]), (h[0] if h else None)


def to_ts(value: Any) -> str | None:
    dt = to_utc(value)
    return iso_z(dt) if dt else None


__all__ = [
    "DDL",
    "annotate",
    "apply_outcome",
    "categories_of",
    "connect",
    "count_audit",
    "decision_row",
    "decode_cursor",
    "encode_cursor",
    "ensure_schema",
    "get_decision",
    "insert_audit_index",
    "insert_decisions",
    "query_audit_rows",
    "query_decisions",
    "read_records",
    "summary_from_event",
    "upsert_decision",
]
