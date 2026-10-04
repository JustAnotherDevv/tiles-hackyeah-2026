"""SQLite persistence for approval requests (DDL verbatim from CONTRACTS section 6.1).

One connection + a threading lock; single-row operations are sub-millisecond (WAL) and run inline,
list/count queries are cheap too (indexed, <= a few hundred rows in a demo).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from aegis.core.types import ApprovalRequest, ApprovalVote, Identity

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, team_id TEXT, kind TEXT NOT NULL, action_type TEXT NOT NULL,
  status TEXT NOT NULL, title TEXT NOT NULL, summary TEXT, requester_json TEXT NOT NULL, requester_member_id TEXT, requester_agent_id TEXT,
  amount_usd REAL, resource TEXT, labels_json TEXT NOT NULL DEFAULT '{}', payload_json TEXT NOT NULL DEFAULT '{}', fingerprint TEXT NOT NULL,
  required_role TEXT NOT NULL, two_person INTEGER NOT NULL DEFAULT 0, rule_id TEXT, votes_json TEXT NOT NULL DEFAULT '[]',
  decided_by_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, expires_at TEXT, decided_at TEXT, request_id TEXT,
  decision_id TEXT, control_id TEXT, uses INTEGER NOT NULL DEFAULT 0, max_uses INTEGER NOT NULL DEFAULT 1, execution_json TEXT);
CREATE INDEX IF NOT EXISTS ix_approvals_status ON approvals(status, created_at);
CREATE INDEX IF NOT EXISTS ix_approvals_fp     ON approvals(fingerprint, status);
"""

COLUMNS = (
    "id", "org_id", "team_id", "kind", "action_type", "status", "title", "summary",
    "requester_json", "requester_member_id", "requester_agent_id", "amount_usd", "resource",
    "labels_json", "payload_json", "fingerprint", "required_role", "two_person", "rule_id",
    "votes_json", "decided_by_json", "created_at", "expires_at", "decided_at", "request_id",
    "decision_id", "control_id", "uses", "max_uses", "execution_json",
)
STATUSES = ("pending", "approved", "denied", "expired", "cancelled")


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def to_row(req: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": req.id,
        "org_id": req.org_id,
        "team_id": req.team_id,
        "kind": req.kind,
        "action_type": req.action_type,
        "status": req.status,
        "title": req.title,
        "summary": req.summary,
        "requester_json": _dumps(req.requester.model_dump(mode="json")),
        "requester_member_id": req.requester.member_id,
        "requester_agent_id": req.requester.agent_id,
        "amount_usd": req.amount_usd,
        "resource": req.resource,
        "labels_json": _dumps(req.labels),
        "payload_json": _dumps(req.payload),
        "fingerprint": req.fingerprint,
        "required_role": req.required_role,
        "two_person": 1 if req.two_person else 0,
        "rule_id": req.rule_id,
        "votes_json": _dumps([v.model_dump(mode="json") for v in req.votes]),
        "decided_by_json": _dumps(req.decided_by),
        "created_at": iso(req.created_at),
        "expires_at": iso(req.expires_at),
        "decided_at": iso(req.decided_at),
        "request_id": req.request_id,
        "decision_id": req.decision_id,
        "control_id": req.control_id,
        "uses": req.uses,
        "max_uses": req.max_uses,
        "execution_json": _dumps(req.execution) if req.execution is not None else None,
    }


def from_row(row: Any) -> ApprovalRequest:
    r = dict(row)
    return ApprovalRequest(
        id=r["id"],
        org_id=r["org_id"],
        team_id=r["team_id"],
        kind=r["kind"],
        action_type=r["action_type"],
        title=r["title"],
        summary=r["summary"],
        requester=Identity.model_validate(json.loads(r["requester_json"] or "{}")),
        amount_usd=r["amount_usd"],
        resource=r["resource"],
        labels=json.loads(r["labels_json"] or "{}"),
        payload=json.loads(r["payload_json"] or "{}"),
        fingerprint=r["fingerprint"],
        required_role=r["required_role"],
        two_person=bool(r["two_person"]),
        rule_id=r["rule_id"],
        votes=[ApprovalVote.model_validate(v) for v in json.loads(r["votes_json"] or "[]")],
        status=r["status"],
        created_at=parse_dt(r["created_at"]) or datetime.now(UTC),
        expires_at=parse_dt(r["expires_at"]),
        decided_at=parse_dt(r["decided_at"]),
        decided_by=json.loads(r["decided_by_json"] or "[]"),
        request_id=r["request_id"],
        decision_id=r["decision_id"],
        control_id=r["control_id"],
        uses=int(r["uses"] or 0),
        max_uses=int(r["max_uses"] or 1),
        execution=json.loads(r["execution_json"]) if r["execution_json"] else None,
    )


class ApprovalStore:
    """Thin DAO over the `approvals` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(DDL)
            self.conn.commit()

    @classmethod
    def in_memory(cls) -> ApprovalStore:
        return cls(sqlite3.connect(":memory:", check_same_thread=False))

    def close(self) -> None:
        with self.lock:
            try:
                self.conn.close()
            except Exception:  # pragma: no cover - defensive
                pass

    # -------------------------------------------------------------- writes
    def insert(self, req: ApprovalRequest) -> None:
        row = to_row(req)
        cols = ", ".join(COLUMNS)
        marks = ", ".join("?" for _ in COLUMNS)
        with self.lock:
            self.conn.execute(
                f"INSERT INTO approvals ({cols}) VALUES ({marks})", [row[c] for c in COLUMNS]
            )
            self.conn.commit()

    def update(self, req: ApprovalRequest) -> None:
        row = to_row(req)
        sets = ", ".join(f"{c} = ?" for c in COLUMNS if c != "id")
        with self.lock:
            self.conn.execute(
                f"UPDATE approvals SET {sets} WHERE id = ?",
                [row[c] for c in COLUMNS if c != "id"] + [req.id],
            )
            self.conn.commit()

    # -------------------------------------------------------------- reads
    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return from_row(row) if row else None

    def list(
        self, *, status: str | None = None, kind: str | None = None, limit: int = 200
    ) -> list[ApprovalRequest]:
        sql = "SELECT * FROM approvals"
        where: list[str] = []
        args: list[Any] = []
        if status and status != "all":
            where.append("status = ?")
            args.append(status)
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 5000)))
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [from_row(r) for r in rows]

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(STATUSES, 0)
        with self.lock:
            for row in self.conn.execute("SELECT status, COUNT(*) AS n FROM approvals GROUP BY status"):
                if row["status"] in out:
                    out[row["status"]] = int(row["n"])
        return out

    def count_all(self) -> int:
        with self.lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0])

    def by_fingerprint(self, fp: str, status: str) -> list[ApprovalRequest]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM approvals WHERE fingerprint = ? AND status = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 20",
                (fp, status),
            ).fetchall()
        return [from_row(r) for r in rows]

    def pending_count(self, *, member_id: str | None = None, agent_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM approvals WHERE status = 'pending'"
        args: list[Any] = []
        if agent_id:
            sql += " AND requester_agent_id = ?"
            args.append(agent_id)
        elif member_id:
            sql += " AND requester_agent_id IS NULL AND requester_member_id = ?"
            args.append(member_id)
        with self.lock:
            return int(self.conn.execute(sql, args).fetchone()[0])

    def due_for_expiry(self, now: datetime) -> list[ApprovalRequest]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM approvals WHERE status = 'pending' AND expires_at IS NOT NULL "
                "AND expires_at <= ?",
                (iso(now),),
            ).fetchall()
        return [from_row(r) for r in rows]


__all__ = ["COLUMNS", "DDL", "STATUSES", "ApprovalStore", "from_row", "iso", "parse_dt", "to_row"]
