"""Synchronous SQLite layer for org-rbac (call via `asyncio.to_thread`).

Contract tables (CONTRACTS section 6.1, verbatim) + org-rbac-private `org_meta` and
`org_changes` (plan 08 contract gap G7). Plaintext keys are never stored: only
`hmac_hex(key, purpose="apikey")`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from aegis.core.types import Agent, Identity, Member, Org, Team, utcnow
from aegis.org.models import KeyRecord, OrgChange, SeedBundle

DDL = """
CREATE TABLE IF NOT EXISTS orgs    (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS teams   (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT, color TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS members (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, team_id TEXT, name TEXT NOT NULL, email TEXT,
  role TEXT NOT NULL CHECK (role IN ('owner','admin','member')), title TEXT, avatar_url TEXT, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS agents  (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, team_id TEXT, owner_member_id TEXT, name TEXT NOT NULL,
  kind TEXT NOT NULL, description TEXT, profile TEXT, allowed_models_json TEXT NOT NULL DEFAULT '["*"]',
  allowed_tools_json TEXT NOT NULL DEFAULT '["*"]', denied_tools_json TEXT NOT NULL DEFAULT '[]', max_destination TEXT,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, last_seen TEXT, meta_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS api_keys (key_id TEXT PRIMARY KEY, principal TEXT NOT NULL, key_hmac TEXT UNIQUE NOT NULL, scopes_json TEXT NOT NULL DEFAULT '[]',
  created_by TEXT, created_at TEXT, expires_at TEXT, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS org_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS org_changes (id TEXT PRIMARY KEY, op TEXT NOT NULL, action_type TEXT NOT NULL,
  target_type TEXT NOT NULL, target_id TEXT, patch_json TEXT NOT NULL, before_json TEXT NOT NULL DEFAULT '{}',
  requested_by_json TEXT NOT NULL, approval_id TEXT, required_role TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','applied','denied','expired','cancelled','failed')),
  created_at TEXT NOT NULL, decided_at TEXT, expires_at TEXT, result_json TEXT);
CREATE INDEX IF NOT EXISTS ix_org_changes_status ON org_changes(status, created_at);
"""

ORG_TABLES = ("api_keys", "agents", "members", "teams", "orgs", "org_meta", "org_changes")


def connect(path: str | Path) -> sqlite3.Connection:
    """Standalone connection (CLI without a Runtime): WAL, Row factory."""
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:  # pragma: no cover
        pass
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(DDL)
    conn.commit()


def org_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM orgs").fetchone()[0])


# ---------------------------------------------------------------- conversions


def _ts(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _dt(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _l(text: Any, default: Any) -> Any:
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else row


def member_from_row(row: Any) -> Member:
    r = _row(row)
    return Member(
        id=r["id"],
        org_id=r["org_id"],
        team_id=r["team_id"],
        name=r["name"],
        email=r["email"],
        role=r["role"],
        title=r["title"],
        avatar_url=r["avatar_url"],
        active=bool(r["active"]),
        created_at=_dt(r["created_at"]) or utcnow(),
        meta=_l(r["meta_json"], {}),
    )


def agent_from_row(row: Any) -> Agent:
    r = _row(row)
    return Agent(
        id=r["id"],
        org_id=r["org_id"],
        team_id=r["team_id"],
        owner_member_id=r["owner_member_id"],
        name=r["name"],
        kind=r["kind"],
        description=r["description"],
        profile=r["profile"],
        allowed_models=_l(r["allowed_models_json"], ["*"]),
        allowed_tools=_l(r["allowed_tools_json"], ["*"]),
        denied_tools=_l(r["denied_tools_json"], []),
        max_destination=r["max_destination"],
        active=bool(r["active"]),
        created_at=_dt(r["created_at"]) or utcnow(),
        last_seen=_dt(r["last_seen"]),
        meta=_l(r["meta_json"], {}),
    )


def team_from_row(row: Any) -> Team:
    r = _row(row)
    return Team(
        id=r["id"],
        org_id=r["org_id"],
        name=r["name"],
        description=r["description"],
        color=r["color"],
        meta=_l(r["meta_json"], {}),
    )


def key_from_row(row: Any) -> KeyRecord:
    r = _row(row)
    return KeyRecord(
        key_id=r["key_id"],
        principal=r["principal"],
        key_hmac=r["key_hmac"],
        scopes=_l(r["scopes_json"], []),
        created_by=r["created_by"],
        created_at=_dt(r["created_at"]),
        expires_at=_dt(r["expires_at"]),
        revoked_at=_dt(r["revoked_at"]),
    )


def change_from_row(row: Any) -> OrgChange:
    r = _row(row)
    return OrgChange(
        id=r["id"],
        op=r["op"],
        action_type=r["action_type"],
        target_type=r["target_type"],
        target_id=r["target_id"],
        patch=_l(r["patch_json"], {}),
        before=_l(r["before_json"], {}),
        requested_by=Identity.model_validate(_l(r["requested_by_json"], {})),
        approval_id=r["approval_id"],
        required_role=r["required_role"],
        status=r["status"],
        created_at=_dt(r["created_at"]) or utcnow(),
        decided_at=_dt(r["decided_at"]),
        expires_at=_dt(r["expires_at"]),
        result=_l(r["result_json"], None),
    )


# ---------------------------------------------------------------- writes


def upsert_member(conn: sqlite3.Connection, m: Member) -> None:
    conn.execute(
        "INSERT INTO members (id, org_id, team_id, name, email, role, title, avatar_url, active, "
        "created_at, meta_json) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "org_id=excluded.org_id, team_id=excluded.team_id, name=excluded.name, "
        "email=excluded.email, role=excluded.role, title=excluded.title, "
        "avatar_url=excluded.avatar_url, active=excluded.active, meta_json=excluded.meta_json",
        (
            m.id,
            m.org_id,
            m.team_id,
            m.name,
            m.email,
            m.role,
            m.title,
            m.avatar_url,
            int(m.active),
            _ts(m.created_at),
            _j(m.meta),
        ),
    )


def upsert_agent(conn: sqlite3.Connection, a: Agent) -> None:
    conn.execute(
        "INSERT INTO agents (id, org_id, team_id, owner_member_id, name, kind, description, "
        "profile, allowed_models_json, allowed_tools_json, denied_tools_json, max_destination, "
        "active, created_at, last_seen, meta_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET org_id=excluded.org_id, team_id=excluded.team_id, "
        "owner_member_id=excluded.owner_member_id, name=excluded.name, kind=excluded.kind, "
        "description=excluded.description, profile=excluded.profile, "
        "allowed_models_json=excluded.allowed_models_json, "
        "allowed_tools_json=excluded.allowed_tools_json, "
        "denied_tools_json=excluded.denied_tools_json, max_destination=excluded.max_destination, "
        "active=excluded.active, meta_json=excluded.meta_json",
        (
            a.id,
            a.org_id,
            a.team_id,
            a.owner_member_id,
            a.name,
            a.kind,
            a.description,
            a.profile,
            _j(a.allowed_models),
            _j(a.allowed_tools),
            _j(a.denied_tools),
            a.max_destination,
            int(a.active),
            _ts(a.created_at),
            _ts(a.last_seen),
            _j(a.meta),
        ),
    )


def insert_key(conn: sqlite3.Connection, k: KeyRecord) -> None:
    conn.execute(
        "INSERT INTO api_keys (key_id, principal, key_hmac, scopes_json, created_by, created_at, "
        "expires_at, revoked_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            k.key_id,
            k.principal,
            k.key_hmac,
            _j(k.scopes),
            k.created_by,
            _ts(k.created_at),
            _ts(k.expires_at),
            _ts(k.revoked_at),
        ),
    )


def revoke_key(conn: sqlite3.Connection, key_id: str, when: datetime) -> None:
    conn.execute(
        "UPDATE api_keys SET revoked_at=? WHERE key_id=? AND revoked_at IS NULL",
        (_ts(when), key_id),
    )


def set_key_hmac(conn: sqlite3.Connection, key_id: str, key_hmac: str) -> None:
    conn.execute("UPDATE api_keys SET key_hmac=? WHERE key_id=?", (key_hmac, key_id))


def touch_last_seen(conn: sqlite3.Connection, items: list[tuple[str, datetime]]) -> None:
    conn.executemany(
        "UPDATE agents SET last_seen=? WHERE id=?", [(_ts(ts), agent_id) for agent_id, ts in items]
    )


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO org_meta (key, value_json) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
        (key, _j(value)),
    )


def get_meta(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        r["key"]: _l(r["value_json"], None)
        for r in conn.execute("SELECT key, value_json FROM org_meta")
    }


def apply_seed(
    conn: sqlite3.Connection,
    bundle: SeedBundle,
    *,
    reset: bool = False,
    hmac_fn: Callable[..., str] | None = None,
) -> None:
    """Write the whole bundle in one transaction (reset = wipe the org-rbac tables first)."""
    if hmac_fn is None:
        from aegis.org.compat import hmac_hex as hmac_fn
    create_tables(conn)
    now = utcnow()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if reset:
            for table in ORG_TABLES:
                conn.execute(f"DELETE FROM {table}")
        conn.execute(
            "INSERT OR REPLACE INTO orgs (id, name, created_at) VALUES (?,?,?)",
            (bundle.org.id, bundle.org.name, _ts(now)),
        )
        for t in bundle.teams:
            conn.execute(
                "INSERT OR REPLACE INTO teams (id, org_id, name, description, color, meta_json) "
                "VALUES (?,?,?,?,?,?)",
                (t.id, t.org_id, t.name, t.description, t.color, _j(t.meta)),
            )
        for m in bundle.members:
            upsert_member(conn, m)
        for a in bundle.agents:
            upsert_agent(conn, a)
        for k in bundle.keys:
            conn.execute("DELETE FROM api_keys WHERE key_id=?", (k.key_id,))
            insert_key(
                conn,
                KeyRecord(
                    key_id=k.key_id,
                    principal=k.principal,
                    key_hmac=hmac_fn(k.plaintext, purpose="apikey"),
                    scopes=k.scopes,
                    created_by=k.created_by,
                    created_at=k.created_at,
                    expires_at=k.expires_at,
                    revoked_at=k.revoked_at,
                ),
            )
        set_meta(conn, "seed_version", bundle.seed_version)
        set_meta(conn, "seed_sha256", bundle.sha256)
        set_meta(conn, "seeded_at", _ts(now))
        set_meta(conn, "hmac_canary", hmac_fn("aegis-org-canary", purpose="apikey"))
        set_meta(conn, "seed_key_ids", [k.key_id for k in bundle.keys])
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def insert_change(conn: sqlite3.Connection, c: OrgChange) -> None:
    conn.execute(
        "INSERT INTO org_changes (id, op, action_type, target_type, target_id, patch_json, "
        "before_json, requested_by_json, approval_id, required_role, status, created_at, "
        "decided_at, expires_at, result_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            c.id,
            c.op,
            c.action_type,
            c.target_type,
            c.target_id,
            _j(c.patch),
            _j(c.before),
            _j(c.requested_by.model_dump(mode="json")),
            c.approval_id,
            c.required_role,
            c.status,
            _ts(c.created_at),
            _ts(c.decided_at),
            _ts(c.expires_at),
            _j(c.result) if c.result is not None else None,
        ),
    )


def update_change(conn: sqlite3.Connection, c: OrgChange) -> None:
    conn.execute(
        "UPDATE org_changes SET approval_id=?, required_role=?, status=?, decided_at=?, "
        "expires_at=?, result_json=?, target_id=? WHERE id=?",
        (
            c.approval_id,
            c.required_role,
            c.status,
            _ts(c.decided_at),
            _ts(c.expires_at),
            _j(c.result) if c.result is not None else None,
            c.target_id,
            c.id,
        ),
    )


def get_change(conn: sqlite3.Connection, change_id: str) -> OrgChange | None:
    row = conn.execute("SELECT * FROM org_changes WHERE id=?", (change_id,)).fetchone()
    return change_from_row(row) if row else None


def list_changes(
    conn: sqlite3.Connection, status: str | None = None, limit: int = 200
) -> list[OrgChange]:
    if status:
        rows = conn.execute(
            "SELECT * FROM org_changes WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM org_changes ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [change_from_row(r) for r in rows]


# ---------------------------------------------------------------- reads


def load_all(conn: sqlite3.Connection) -> dict[str, Any]:
    """Everything the in-memory cache needs (members/agents in rowid = seed order)."""
    org_row = conn.execute("SELECT * FROM orgs ORDER BY rowid LIMIT 1").fetchone()
    return {
        "org": Org(id=org_row["id"], name=org_row["name"]) if org_row else None,
        "teams": [team_from_row(r) for r in conn.execute("SELECT * FROM teams ORDER BY rowid")],
        "members": [
            member_from_row(r) for r in conn.execute("SELECT * FROM members ORDER BY rowid")
        ],
        "agents": [agent_from_row(r) for r in conn.execute("SELECT * FROM agents ORDER BY rowid")],
        "keys": [key_from_row(r) for r in conn.execute("SELECT * FROM api_keys ORDER BY rowid")],
        "meta": get_meta(conn),
    }


__all__ = [
    "DDL",
    "ORG_TABLES",
    "apply_seed",
    "connect",
    "create_tables",
    "get_change",
    "insert_change",
    "insert_key",
    "list_changes",
    "load_all",
    "org_count",
    "revoke_key",
    "set_meta",
    "touch_last_seen",
    "update_change",
    "upsert_agent",
    "upsert_member",
]
