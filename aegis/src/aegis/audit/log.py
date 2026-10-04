"""Audit service: `create(rt) -> AuditService` implements `AuditSink` (CONTRACTS sections 3.2/3.3).

record(event):
  1. dump (`model_dump(mode="json", by_alias=True)`)
  2. enrich decision records: `data.redaction_spans` (+ lifted fp/preview), `data.otel`
  3. scrub (never-raw guard; `defaults.audit_content`)
  4. chain: seq = n+1, prev_hash = head, hash = sha256(prev + canonical(record - hash))
  5. persist: JSONL line -> HEAD.json -> audit_index row -> decisions projection (UPSERT)
  6. derived counters (approvals / policy / feed reloads) via rt.metrics
Never raises to callers: failures are logged, counted and the event is returned unchanged.

Intra-workstream extras: `head()`, `last_verify`, `annotate(decision_id, **cols)`,
`recent_detail(id)`, `system(kind, message, ...)`, `connection()`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from aegis.audit import index as idx
from aegis.audit.chain import ChainWriter, audit_files
from aegis.audit.privacy import elide_mutations, redaction_spans, scrub_event
from aegis.audit.verify import verify_dir
from aegis.core.types import AuditEvent, AuditVerifyResult, Identity, new_id
from aegis.metrics.otel import genai_attributes
from aegis.metrics.timing import iso_z, parse_since

log = logging.getLogger(__name__)

DETAIL_LRU = 500
REVERIFY_S = 300.0
HEAD_FLUSH_S = 0.25
PROJECT_BATCH_S = 0.02


def open_db(rt: Any, data_dir: Path) -> sqlite3.Connection:
    """rt.db() (core-gateway) or a local WAL connection to data/aegis.db."""
    conn: sqlite3.Connection | None = None
    db = getattr(rt, "db", None)
    if callable(db):
        try:
            conn = db()
        except Exception:
            log.warning("rt.db() failed; using a local connection")
            conn = None
    if conn is None:
        conn = idx.connect(data_dir / "aegis.db")
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.Error):
        conn.execute("PRAGMA busy_timeout=5000")
    return conn


class AuditService:
    """Hash-chained JSONL audit log + SQLite index/projection."""

    def __init__(self, rt: Any, *, audit_dir: Path | None = None, clock: Any = None) -> None:
        self.rt = rt
        settings = getattr(rt, "settings", None)
        self.data_dir = Path(getattr(settings, "data_dir", None) or "data")
        self.audit_dir = Path(audit_dir) if audit_dir else self.data_dir / "audit"
        self.test_mode = bool(getattr(settings, "test_mode", False))
        self.writer = ChainWriter(self.audit_dir, clock)
        self.writer.defer_head = True  # HEAD.json flushed HEAD_FLUSH_S after the last append
        self._head_timer: asyncio.TimerHandle | None = None
        self.last_verify: AuditVerifyResult | None = None
        self.log_only = False
        self.errors = 0
        self._lock = threading.Lock()  # chain writer (seq/hash/JSONL/HEAD)
        self._db_lock = threading.Lock()  # SQLite writer connection
        self._proj_q: list[tuple[dict[str, Any], Any]] = []
        self._drain_task: asyncio.Task[Any] | None = None
        self._conn: sqlite3.Connection | None = None
        self._started = False
        self._details: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._pending_annot: dict[str, dict[str, Any]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._last_sys_publish = 0.0

    # ------------------------------------------------------------------ lifecycle
    def _start_sync(self) -> list[str]:
        with self._lock, self._db_lock:
            if self._started:
                return []
            self.data_dir.mkdir(parents=True, exist_ok=True)
            locked = self.writer.open()
            self.log_only = not locked
            try:
                self._conn = open_db(self.rt, self.data_dir)
                with contextlib.suppress(sqlite3.Error):
                    self._conn.execute("PRAGMA synchronous=NORMAL")
                idx.ensure_schema(self._conn)
            except Exception:
                log.exception("audit index unavailable (JSONL chain still written)")
                self._conn = None
            self._started = True
            return list(self.writer.notes)

    async def start(self) -> None:
        notes = await asyncio.to_thread(self._start_sync)
        if self.log_only:
            self._publish_system(
                "error", "audit log locked by another process - log-only mode (no chain writes)"
            )
        if self.writer.head_ahead:
            self.last_verify = AuditVerifyResult(
                ok=False,
                records=self.writer.seq,
                head_hash=self.writer.head,
                broken_at_seq=self.writer.seq + 1,
                message=self.writer.head_ahead,
            )
        if self.test_mode:
            return
        kind = "audit.resumed" if self.writer.seq else "audit.started"
        await self.system(
            kind,
            f"audit log {kind.split('.')[1]} at seq {self.writer.seq}",
            notes=notes,
            log_only=self.log_only,
        )
        self._spawn(self._background())

    async def stop(self) -> None:
        if self._head_timer is not None:
            self._head_timer.cancel()
            self._head_timer = None
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            with contextlib.suppress(BaseException):
                await t
        self._tasks.clear()
        dt, self._drain_task = self._drain_task, None
        if dt is not None:
            dt.cancel()
            with contextlib.suppress(BaseException):
                await dt
        self._drain_task = None
        with contextlib.suppress(Exception):
            await self._drain()
        await asyncio.to_thread(self._stop_sync)

    def _stop_sync(self) -> None:
        with self._lock, self._db_lock:
            self.writer.close(fsync=True)
            if self._conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    self._conn.commit()
                    self._conn.close()
                self._conn = None
            self._started = False

    def _spawn(self, coro: Any) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _background(self) -> None:
        """Index rebuild (if DB wiped), startup verify, periodic re-verify."""
        try:
            await asyncio.to_thread(self._maybe_rebuild_index)
        except Exception:
            log.exception("audit index rebuild failed")
        while True:
            try:
                await self.verify()
            except Exception:
                log.exception("audit background verify failed")
            await asyncio.sleep(REVERIFY_S)

    # ------------------------------------------------------------------ helpers
    def _redactor(self) -> Any:
        return getattr(self.rt, "redactor", None)

    def _audit_content(self) -> bool:
        try:
            return bool(self.rt.policy.snapshot().doc.defaults.audit_content)
        except Exception:
            return False

    def _metrics(self) -> Any:
        return getattr(self.rt, "metrics", None)

    def _publish_system(self, level: str, message: str) -> None:
        bus = getattr(self.rt, "bus", None)
        if bus is None:
            return
        now = time.monotonic()
        if level != "info" and now - self._last_sys_publish < 10.0:
            return
        self._last_sys_publish = now
        with contextlib.suppress(Exception):
            bus.publish("system", {"level": level, "message": message, "component": "audit"})

    def head(self) -> dict[str, Any]:
        return {"seq": self.writer.seq, "hash": self.writer.head, "file": self.writer.file}

    def connection(self) -> sqlite3.Connection:
        """A fresh read connection (callers close it)."""
        return open_db(self.rt, self.data_dir)

    # ------------------------------------------------------------------ record
    def _prepare(self, event: AuditEvent) -> dict[str, Any]:
        d = event.model_dump(mode="json", by_alias=True)
        d.pop("hash", None)
        d.pop("prev_hash", None)
        d.pop("seq", None)
        data = d.get("data")
        if not isinstance(data, dict):
            data = d["data"] = {}
        if d.get("event_type") == "decision":
            if data.get("phase") == "outcome":
                data["otel"] = genai_attributes(
                    data.get("summary") or idx.summary_from_event(d), d.get("usage"), data
                )
            else:
                spans = redaction_spans(d)
                if spans:
                    data["redaction_spans"] = spans
                elide_mutations(data.get("detail"))
                summary = data.get("summary") if isinstance(data.get("summary"), dict) else None
                data["otel"] = genai_attributes(
                    summary or idx.summary_from_event(d), d.get("usage")
                )
        scrub_event(d, self._redactor(), self._audit_content())
        return d

    def _summary_detail(self, rec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        data = rec.get("data") or {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else None
        summary = dict(summary) if summary else idx.summary_from_event(rec)
        if not summary.get("id"):
            summary["id"] = rec.get("decision_id") or rec.get("event_id")
        detail = data.get("detail") if isinstance(data.get("detail"), dict) else None
        detail = (
            dict(detail)
            if detail
            else {
                "decisions": [],
                "redactions": rec.get("redactions") or [],
                "mutations": [],
                "usage": rec.get("usage"),
            }
        )
        detail.pop("wire", None)
        detail["audit_seq"] = rec.get("seq")
        detail["audit_hash"] = rec.get("hash")
        return summary, detail

    def _remember(self, rec: dict[str, Any]) -> None:
        """In-memory LRU so GET /api/decisions/{id} never misses a just-written decision."""
        if rec.get("event_type") != "decision" or (rec.get("data") or {}).get("phase") == "outcome":
            return
        summary, detail = self._summary_detail(rec)
        self._details[summary["id"]] = {**detail, **summary}
        self._details.move_to_end(summary["id"])
        while len(self._details) > DETAIL_LRU:
            self._details.popitem(last=False)

    def _append(self, d: dict[str, Any]) -> tuple[dict[str, Any], Any] | None:
        """Chain append (seq/prev_hash/hash + JSONL line). Fast: page-cache write, no SQLite."""
        with self._lock:
            if self.log_only or not self.writer.locked:
                log.info(
                    "audit (log-only) event_type=%s event_id=%s",
                    d.get("event_type"),
                    d.get("event_id"),
                )
                return None
            return self.writer.append_record(d)

    def _project_batch(self, items: list[tuple[dict[str, Any], Any]]) -> None:
        """SQLite side (audit_index + decisions projection) for a batch, one transaction."""
        with self._db_lock:
            if self._conn is None or not items:
                return
            try:
                if self._conn.isolation_level is None and not self._conn.in_transaction:
                    self._conn.execute("BEGIN")
                for rec, ap in items:
                    try:
                        self._project(rec, ap.file, ap.line, ap.offset, ap.length)
                    except sqlite3.Error:
                        log.exception("audit index write failed seq=%s", rec.get("seq"))
                self._conn.commit()
            except sqlite3.Error:
                log.exception("audit index batch failed (%d records)", len(items))
                with contextlib.suppress(sqlite3.Error):
                    self._conn.rollback()

    async def _drain(self) -> None:
        """Flush queued projection rows (AUD-20 batching: SQLite stays off the hot path)."""
        while self._proj_q:
            items, self._proj_q = self._proj_q, []
            await asyncio.to_thread(self._project_batch, items)

    async def _drain_later(self) -> None:
        try:
            await asyncio.sleep(PROJECT_BATCH_S)
            await self._drain()
        except asyncio.CancelledError:
            self._drain_task = None
            raise
        except Exception:
            log.exception("audit projection drain failed")
        self._drain_task = None
        if self._proj_q and self._started:  # appended while the last batch was being written
            self._drain_task = asyncio.get_running_loop().create_task(self._drain_later())

    def _project(self, rec: dict[str, Any], file: str, line: int, offset: int, length: int) -> None:
        assert self._conn is not None
        idx.insert_audit_index(self._conn, rec, file, line, offset, length)
        if rec.get("event_type") != "decision":
            return
        data = rec.get("data") or {}
        if data.get("phase") == "outcome":
            usage = rec.get("usage") or {}
            tokens = None
            if usage:
                tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
            idx.apply_outcome(
                self._conn,
                rec.get("decision_id") or "",
                cost_usd=usage.get("cost_usd") if usage else None,
                tokens=tokens,
                upstream_ms=data.get("upstream_ms"),
            )
            return
        summary, detail = self._summary_detail(rec)
        pending = self._pending_annot.pop(summary["id"], {})
        row = idx.decision_row(
            summary,
            detail,
            categories=idx.categories_of(detail),
            cost_avoided_usd=pending.get("cost_avoided_usd", 0.0),
            avoided_reason=pending.get("avoided_reason"),
        )
        idx.upsert_decision(self._conn, row)

    async def record(self, event: AuditEvent) -> AuditEvent:
        """Assign seq, chain hash, append JSONL, index in SQLite. Never raises to callers.

        The chain append happens inline (ordered, cheap); the SQLite projection is batched in a
        worker thread every PROJECT_BATCH_S (synchronous in test mode)."""
        try:
            if not self._started:
                await asyncio.to_thread(self._start_sync)
            d = self._prepare(event)
            out = self._append(d)
        except Exception:
            self.errors += 1
            log.exception("audit record failed event_type=%s", getattr(event, "event_type", "?"))
            m = self._metrics()
            with contextlib.suppress(Exception):
                if m is not None:
                    m.inc("aegis_audit_errors_total")
            self._publish_system("error", "audit write failed (see gateway log)")
            return event
        if out is None:
            return event
        rec, ap = out
        with contextlib.suppress(Exception):
            self._remember(rec)
        self._proj_q.append((rec, ap))
        if self.test_mode:
            await self._drain()
        elif self._drain_task is None:
            self._drain_task = asyncio.get_running_loop().create_task(self._drain_later())
        self._schedule_head_flush()
        m = self._metrics()
        if m is not None:
            hook = getattr(m, "on_audit_event", None)
            if hook is not None:
                with contextlib.suppress(Exception):
                    hook(rec)
        return event.model_copy(
            update={"seq": rec["seq"], "prev_hash": rec["prev_hash"], "hash": rec["hash"]}
        )

    def _schedule_head_flush(self) -> None:
        if self._head_timer is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.flush_head()
            return
        self._head_timer = loop.call_later(HEAD_FLUSH_S, self.flush_head)

    def flush_head(self) -> None:
        """Bring HEAD.json up to date with the chain (cheap; atomic tmp + rename)."""
        self._head_timer = None
        with self._lock:
            self.writer.flush_head()

    async def system(
        self,
        kind: str,
        message: str,
        *,
        level: str = "info",
        actor: Identity | None = None,
        publish: bool = False,
        **data: Any,
    ) -> AuditEvent:
        """Record a `system` audit event (optionally also a bus `system` toast)."""
        ev = AuditEvent(
            event_id=new_id("evt"),
            event_type="system",
            actor=actor,
            reason=message,
            data={"kind": kind, "level": level, "component": "audit", **data},
        )
        out = await self.record(ev)
        if publish:
            self._publish_system(level, message)
        return out

    # ------------------------------------------------------------------ annotate / details
    def _annotate_sync(self, decision_id: str, cols: dict[str, Any]) -> None:
        with self._db_lock:
            if self._conn is None:
                return
            try:
                if idx.annotate(self._conn, decision_id, **cols) == 0:
                    self._pending_annot.setdefault(decision_id, {}).update(cols)
                    while len(self._pending_annot) > 1000:
                        self._pending_annot.pop(next(iter(self._pending_annot)))
                self._conn.commit()
            except sqlite3.Error:
                log.exception("audit annotate failed decision_id=%s", decision_id)

    def annotate(self, decision_id: str, **cols: Any) -> None:
        """Fire-and-forget update of projection columns (e.g. cost_avoided_usd, avoided_reason)."""
        if not decision_id or not cols:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._annotate_sync(decision_id, cols)
            return
        self._spawn(asyncio.to_thread(self._annotate_sync, decision_id, cols))
        del loop

    def recent_detail(self, decision_id: str) -> dict[str, Any] | None:
        d = self._details.get(decision_id)
        return dict(d) if d is not None else None

    # ------------------------------------------------------------------ verify
    async def verify(self) -> AuditVerifyResult:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self.flush_head)
        try:
            res = await asyncio.to_thread(verify_dir, self.audit_dir)
        except Exception as exc:
            log.exception("audit verify failed")
            res = AuditVerifyResult(ok=False, message=f"verify failed: {exc}")
        if res.ok and self.writer.head_ahead:
            res = AuditVerifyResult(
                ok=False,
                records=res.records,
                head_hash=res.head_hash,
                files=res.files,
                broken_at_seq=res.records + 1,
                message=self.writer.head_ahead,
            )
        prev = self.last_verify
        self.last_verify = res
        m = self._metrics()
        if m is not None:
            with contextlib.suppress(Exception):
                m.set_gauge("aegis_audit_chain_ok", 1.0 if res.ok else 0.0)
        if not res.ok and (prev is None or prev.ok):
            log.error("audit chain verify failed: %s", res.message)
            self._publish_system("error", f"Audit chain broken: {res.message}")
        return res

    # ------------------------------------------------------------------ query
    def _query_sync(
        self,
        event_type: str | None,
        since: str | None,
        decision_id: str | None,
        limit: int,
        cursor: str | None,
        seq_from: int | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        conn = self.connection()
        try:
            idx.ensure_schema(conn)
            rows, nxt = idx.query_audit_rows(
                conn,
                event_type=event_type,
                since=since,
                decision_id=decision_id,
                limit=limit,
                cursor=cursor,
                seq_from=seq_from,
            )
        finally:
            conn.close()
        return idx.read_records(self.audit_dir, rows), nxt

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: Any = None,
        limit: int = 200,
        cursor: str | None = None,
        decision_id: str | None = None,
    ) -> tuple[list[AuditEvent], str | None]:
        since_dt = parse_since(since) if isinstance(since, str) else since
        since_s = iso_z(since_dt) if since_dt is not None else None
        limit = max(1, min(int(limit or 200), 1000))
        recs, nxt = await asyncio.to_thread(
            self._query_sync, event_type, since_s, decision_id, limit, cursor
        )
        out: list[AuditEvent] = []
        for r in recs:
            try:
                out.append(AuditEvent.model_validate(r))
            except Exception:
                log.debug("audit record failed validation seq=%s", r.get("seq"))
        return out, nxt

    async def query_raw(self, **kw: Any) -> tuple[list[dict[str, Any]], str | None]:
        """Like query() but returns the stored dicts verbatim (byte-faithful to the chain)."""
        since = kw.get("since")
        since_dt = parse_since(since) if isinstance(since, str) else since
        return await asyncio.to_thread(
            self._query_sync,
            kw.get("event_type"),
            iso_z(since_dt) if since_dt is not None else None,
            kw.get("decision_id"),
            max(1, min(int(kw.get("limit") or 100), 1000)),
            kw.get("cursor"),
            kw.get("seq_from"),
        )

    # ------------------------------------------------------------------ export
    def export(self, fmt: Literal["jsonl", "csv", "ocsf"], **filters: Any) -> AsyncIterator[bytes]:
        from aegis.audit.export import export_stream

        return export_stream(self.audit_dir, fmt, **filters)

    # ------------------------------------------------------------------ index rebuild
    def _maybe_rebuild_index(self) -> int:
        with self._db_lock:
            if self._conn is None:
                return 0
            count = self._conn.execute("SELECT COUNT(*) FROM audit_index").fetchone()[0]
        files = audit_files(self.audit_dir)
        if count or not files:
            return 0
        log.warning("audit index empty but %d chain files exist - rebuilding", len(files))
        import json

        n = 0
        for path in files:
            offset = 0
            with path.open("rb") as fh:
                for lineno, raw in enumerate(fh, 1):
                    length = len(raw)
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        offset += length
                        continue
                    with self._db_lock:
                        if self._conn is None:
                            return n
                        try:
                            self._project(rec, path.name, lineno, offset, length)
                        except sqlite3.Error:
                            log.exception("index rebuild row failed seq=%s", rec.get("seq"))
                        n += 1
                        if n % 500 == 0:
                            self._conn.commit()
                    offset += length
        with self._db_lock:
            if self._conn is not None:
                self._conn.commit()
        log.info("audit index rebuilt rows=%d", n)
        return n


def create(rt: Any) -> AuditService:
    """Factory used by core-gateway's Runtime (`aegis.audit.log:create`). Cheap, no I/O."""
    return AuditService(rt)


__all__ = ["AuditService", "create", "open_db"]
