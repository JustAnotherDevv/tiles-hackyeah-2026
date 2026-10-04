"""Streaming audit exports: jsonl (raw chain lines), csv (flattened), ocsf (one event per line).

Filters: `from`/`to` (ISO or relative "24h"), `action`, `control_id` (primary or any hit),
`agent_id`, `event_type` (trailing `*` allowed). Files are preselected by the date in their name.
JSONL lines are byte-identical to the chain, so every exported record re-verifies on its own.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from aegis.audit.chain import audit_files
from aegis.audit.ocsf import to_ocsf
from aegis.metrics.timing import parse_since, to_utc

CHUNK = 64 * 1024

CSV_COLUMNS = [
    "seq",
    "ts",
    "event_type",
    "event_id",
    "request_id",
    "decision_id",
    "session_id",
    "principal",
    "org_id",
    "team_id",
    "member_id",
    "agent_id",
    "kind",
    "surface",
    "direction",
    "dest_name",
    "dest_class",
    "model",
    "tool_name",
    "action_type",
    "amount_usd",
    "resource",
    "action",
    "control_id",
    "controls",
    "reason",
    "score",
    "threshold",
    "redaction_count",
    "entities",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "policy_version",
    "feed_serial",
    "prev_hash",
    "hash",
]
_CSV_DANGER = ("=", "+", "-", "@", "\t", "\r")

MEDIA_TYPES = {"jsonl": "application/x-ndjson", "csv": "text/csv", "ocsf": "application/x-ndjson"}
EXTENSIONS = {"jsonl": "jsonl", "csv": "csv", "ocsf": "ocsf.jsonl"}


class Filters:
    def __init__(self, **f: Any) -> None:
        self.start = _dt(f.get("from") or f.get("from_") or f.get("start"))
        self.end = _dt(f.get("to") or f.get("end"))
        self.actions = _set(f.get("action"))
        self.control_id = f.get("control_id") or None
        self.agent_id = f.get("agent_id") or None
        self.event_types = _set(f.get("event_type"))

    @property
    def empty(self) -> bool:
        return not (
            self.start
            or self.end
            or self.actions
            or self.control_id
            or self.agent_id
            or self.event_types
        )

    def file_ok(self, path: Path) -> bool:
        stem = path.name[len("audit-") : -len(".jsonl")]
        if self.start and stem < self.start.strftime("%Y%m%d"):
            return False
        return not (self.end and stem > self.end.strftime("%Y%m%d"))

    def match(self, rec: dict[str, Any]) -> bool:
        if self.start or self.end:
            ts = to_utc(rec.get("ts"))
            if ts is None:
                return False
            if self.start and ts < self.start:
                return False
            if self.end and ts > self.end:
                return False
        if self.event_types:
            et = rec.get("event_type") or ""
            if not any(
                et.startswith(t[:-1]) if t.endswith("*") else et == t for t in self.event_types
            ):
                return False
        if self.actions and (rec.get("action") or "") not in self.actions:
            return False
        if self.agent_id and ((rec.get("actor") or {}).get("agent_id") != self.agent_id):
            return False
        if self.control_id:
            hits = {c.get("control_id") for c in rec.get("controls") or [] if isinstance(c, dict)}
            summary = (rec.get("data") or {}).get("summary") or {}
            if isinstance(summary, dict):
                hits |= {
                    c.get("control_id")
                    for c in summary.get("controls") or []
                    if isinstance(c, dict)
                }
            if rec.get("control_id") != self.control_id and self.control_id not in hits:
                return False
        return True


def _dt(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    return parse_since(v) if isinstance(v, str) else to_utc(v)


def _set(v: Any) -> set[str]:
    if not v:
        return set()
    if isinstance(v, (list, tuple, set)):
        return {str(x) for x in v if x}
    return {s.strip() for s in str(v).split(",") if s.strip()}


def _guard(v: Any) -> Any:
    if isinstance(v, str) and v.startswith(_CSV_DANGER):
        return "'" + v
    return v


def csv_row(rec: dict[str, Any]) -> list[Any]:
    data = rec.get("data") or {}
    s = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    actor = rec.get("actor") or s.get("identity") or {}
    dest = rec.get("destination") or s.get("destination") or {}
    usage = rec.get("usage") or {}
    controls = rec.get("controls") or s.get("controls") or []
    principal = (
        f"agent:{actor['agent_id']}"
        if actor.get("agent_id")
        else f"member:{actor['member_id']}"
        if actor.get("member_id")
        else ""
    )
    entities = s.get("entities") or sorted(
        {
            r.get("entity")
            for r in rec.get("redactions") or []
            if isinstance(r, dict) and r.get("entity")
        }
    )
    row = {
        "seq": rec.get("seq"),
        "ts": rec.get("ts"),
        "event_type": rec.get("event_type"),
        "event_id": rec.get("event_id"),
        "request_id": rec.get("request_id"),
        "decision_id": rec.get("decision_id"),
        "session_id": rec.get("session_id") or s.get("session_id"),
        "principal": principal,
        "org_id": actor.get("org_id"),
        "team_id": actor.get("team_id"),
        "member_id": actor.get("member_id"),
        "agent_id": actor.get("agent_id"),
        "kind": rec.get("kind") or s.get("kind"),
        "surface": rec.get("surface") or s.get("surface"),
        "direction": rec.get("direction") or s.get("direction"),
        "dest_name": dest.get("name"),
        "dest_class": dest.get("dest_class"),
        "model": rec.get("model") or s.get("model"),
        "tool_name": rec.get("tool_name") or s.get("tool_name"),
        "action_type": rec.get("action_type") or s.get("action_type"),
        "amount_usd": rec.get("amount_usd")
        if rec.get("amount_usd") is not None
        else s.get("amount_usd"),
        "resource": rec.get("resource"),
        "action": rec.get("action"),
        "control_id": rec.get("control_id"),
        "controls": ";".join(
            f"{c.get('control_id')}:{c.get('action')}" for c in controls if isinstance(c, dict)
        ),
        "reason": rec.get("reason"),
        "score": rec.get("score"),
        "threshold": rec.get("threshold"),
        "redaction_count": len(rec.get("redactions") or []) or s.get("redaction_count") or 0,
        "entities": ";".join(str(e) for e in entities),
        "latency_ms": rec.get("latency_ms"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cost_usd": usage.get("cost_usd") if usage else s.get("cost_usd"),
        "policy_version": rec.get("policy_version"),
        "feed_serial": rec.get("feed_serial"),
        "prev_hash": rec.get("prev_hash"),
        "hash": rec.get("hash"),
    }
    return [_guard(row[c]) for c in CSV_COLUMNS]


def iter_export(audit_dir: Path, fmt: str, **filters: Any) -> Iterator[bytes]:
    """Synchronous generator of output chunks (~64 KB)."""
    if fmt not in MEDIA_TYPES:
        raise ValueError(f"unknown export format {fmt!r} (jsonl|csv|ocsf)")
    flt = Filters(**filters)
    buf = io.StringIO() if fmt == "csv" else None
    writer = csv.writer(buf) if buf is not None else None
    out = bytearray()
    if writer is not None and buf is not None:
        writer.writerow(CSV_COLUMNS)
        out += buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate()
    for path in audit_files(audit_dir):
        if not flt.file_ok(path):
            continue
        with path.open("rb") as fh:
            for raw in fh:
                if not raw.endswith(b"\n"):
                    break  # torn line of the live file
                if fmt == "jsonl" and flt.empty:
                    out += raw
                else:
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        continue
                    if not flt.match(rec):
                        continue
                    if fmt == "jsonl":
                        out += raw
                    elif fmt == "ocsf":
                        out += (
                            json.dumps(
                                to_ocsf(rec), separators=(",", ":"), ensure_ascii=False, default=str
                            )
                            + "\n"
                        ).encode("utf-8")
                    else:
                        assert writer is not None and buf is not None
                        writer.writerow(csv_row(rec))
                        out += buf.getvalue().encode("utf-8")
                        buf.seek(0)
                        buf.truncate()
                if len(out) >= CHUNK:
                    yield bytes(out)
                    out.clear()
    if out:
        yield bytes(out)


async def export_stream(audit_dir: Path, fmt: str, **filters: Any) -> AsyncIterator[bytes]:
    """Async wrapper: file reading/serialization happens in a worker thread, chunk by chunk."""
    gen = iter_export(audit_dir, fmt, **filters)
    sentinel = object()
    while True:
        chunk = await asyncio.to_thread(next, gen, sentinel)
        if chunk is sentinel:
            break
        yield chunk  # type: ignore[misc]


__all__ = [
    "CSV_COLUMNS",
    "EXTENSIONS",
    "MEDIA_TYPES",
    "Filters",
    "csv_row",
    "export_stream",
    "iter_export",
]
