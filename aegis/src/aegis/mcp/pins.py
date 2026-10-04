"""Trust-on-first-use pinning of MCP tool definitions (control MCP-03), backed by SQLite.

Ported from staging/spikes/mcp/aegis_mcp/pins.py (same `tool_hash` / `diff_tools`).

Pins are keyed by the *catalog* server name (not session or client), so a definition that
changes between sessions, clients or gateway restarts is still caught. The hash covers the whole
canonical tool object.

Per (server, tool):
    pin        the approved definition (calls allowed)            -> `mcp_tools` (contract table)
    candidate  the latest UNAPPROVED definition, with a reason:     -> `mcp_tool_candidates`
               poisoned | changed | new_after_baseline | manual
Per server: baseline (a complete listing was processed), last list/error, stale flag
                                                                    -> `mcp_server_state`

Hot-path reads are dict lookups on the in-memory cache; writes update the cache at once and are
persisted write-through (serialized by one asyncio.Lock, executed with asyncio.to_thread).
"""

from __future__ import annotations

import asyncio
import copy
import difflib
import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

TABLES_SQL = """
CREATE TABLE IF NOT EXISTS mcp_tools (server TEXT NOT NULL, tool TEXT NOT NULL, hash TEXT NOT NULL,
  definition_json TEXT NOT NULL, status TEXT NOT NULL, reasons_json TEXT NOT NULL DEFAULT '[]',
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, approved_by TEXT, PRIMARY KEY (server, tool));
CREATE TABLE IF NOT EXISTS mcp_tool_candidates (server TEXT NOT NULL, tool TEXT NOT NULL, hash TEXT NOT NULL,
  definition_json TEXT NOT NULL, reason TEXT NOT NULL, findings_json TEXT NOT NULL DEFAULT '[]',
  diff_json TEXT NOT NULL DEFAULT '{}', approval_id TEXT, detected_at TEXT NOT NULL,
  PRIMARY KEY (server, tool));
CREATE TABLE IF NOT EXISTS mcp_server_state (server TEXT PRIMARY KEY, baseline_at TEXT, last_list_at TEXT,
  last_error TEXT, last_error_at TEXT, stale INTEGER NOT NULL DEFAULT 0);
"""

CANDIDATE_REASONS = ("poisoned", "changed", "new_after_baseline", "manual")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def tool_hash(tool: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(tool).encode("utf-8")).hexdigest()


def diff_tools(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Small, dashboard-friendly diff between two tool definitions."""
    changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    out: dict[str, Any] = {"changed_fields": changed}
    if "description" in changed:
        out["description_diff"] = list(
            difflib.unified_diff(
                (old.get("description") or "").splitlines(),
                (new.get("description") or "").splitlines(),
                "pinned",
                "current",
                lineterm="",
                n=0,
            )
        )[2:]
    old_props = set((old.get("inputSchema") or {}).get("properties", {}) or {})
    new_props = set((new.get("inputSchema") or {}).get("properties", {}) or {})
    if old_props != new_props:
        out["params_added"] = sorted(new_props - old_props)
        out["params_removed"] = sorted(old_props - new_props)
    return out


def diff_summary(diff: dict[str, Any]) -> str:
    parts: list[str] = []
    if diff.get("params_added"):
        parts.append("params added: " + ", ".join(diff["params_added"]))
    if diff.get("params_removed"):
        parts.append("params removed: " + ", ".join(diff["params_removed"]))
    fields = [f for f in diff.get("changed_fields", []) if f != "inputSchema" or not parts]
    if fields:
        parts.append("changed: " + ", ".join(fields))
    return "; ".join(parts) or "definition changed"


@dataclass
class PinRecord:
    hash: str
    definition: dict[str, Any]
    approved_by: str = "tofu"
    first_seen: str = field(default_factory=_now)
    last_seen: str = field(default_factory=_now)


@dataclass
class Candidate:
    reason: str  # poisoned | changed | new_after_baseline | manual
    hash: str
    definition: dict[str, Any]
    findings: list[dict[str, Any]] = field(default_factory=list)
    diff: dict[str, Any] = field(default_factory=dict)
    approval_id: str | None = None
    detected_at: str = field(default_factory=_now)


@dataclass
class PinCheck:
    """Pin status of a listed tool (published as `Interaction.meta["mcp.pin"]`)."""

    status: str  # new | match | changed | quarantined
    hash: str
    pinned_hash: str | None = None
    baseline: bool = False
    reason: str | None = None
    approval_id: str | None = None
    approved_by: str | None = None

    def as_meta(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "hash": self.hash,
            "pinned_hash": self.pinned_hash,
            "baseline": self.baseline,
            "reason": self.reason,
            "approval_id": self.approval_id,
            "approved_by": self.approved_by,
        }


@dataclass
class CallableStatus:
    """Callability of a tool for `tools/call` (published as `meta["mcp.pin"]` on mcp.call)."""

    status: str  # pinned | changed | quarantined | pending | unvetted
    reason: str | None = None
    approval_id: str | None = None
    pinned_hash: str | None = None
    hash: str | None = None

    def as_meta(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "approval_id": self.approval_id,
            "pinned_hash": self.pinned_hash,
            "hash": self.hash,
        }


@dataclass
class ServerState:
    baseline_at: str | None = None
    last_list_at: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    stale: bool = False


class PinStore:
    """SQLite-backed pin store with an in-memory cache. `connect=None` = memory only (tests)."""

    def __init__(self, connect: Callable[[], sqlite3.Connection] | None = None) -> None:
        self._connect = connect
        self.pins: dict[str, dict[str, PinRecord]] = {}
        self.candidates: dict[str, dict[str, Candidate]] = {}
        self.first_seen: dict[tuple[str, str], str] = {}
        self.last_seen: dict[tuple[str, str], str] = {}
        self.servers: dict[str, ServerState] = {}
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[str, str | None], Any]] = []
        self.loaded = False

    # ------------------------------------------------------------------ lifecycle
    async def load(self) -> None:
        """Create tables and load everything into memory."""
        if self._connect is None:
            self.loaded = True
            return
        await asyncio.to_thread(self._load_sync)
        self.loaded = True

    def _load_sync(self) -> None:
        assert self._connect is not None
        con = self._connect()
        try:
            con.executescript(TABLES_SQL)
            con.commit()
            for r in con.execute("SELECT * FROM mcp_tools"):
                server, tool = r["server"], r["tool"]
                self.first_seen[(server, tool)] = r["first_seen"]
                self.last_seen[(server, tool)] = r["last_seen"]
                if r["approved_by"]:
                    self.pins.setdefault(server, {})[tool] = PinRecord(
                        r["hash"],
                        json.loads(r["definition_json"]),
                        r["approved_by"],
                        r["first_seen"],
                        r["last_seen"],
                    )
            for r in con.execute("SELECT * FROM mcp_tool_candidates"):
                self.candidates.setdefault(r["server"], {})[r["tool"]] = Candidate(
                    r["reason"],
                    r["hash"],
                    json.loads(r["definition_json"]),
                    json.loads(r["findings_json"] or "[]"),
                    json.loads(r["diff_json"] or "{}"),
                    r["approval_id"],
                    r["detected_at"],
                )
                self.first_seen.setdefault((r["server"], r["tool"]), r["detected_at"])
                self.last_seen.setdefault((r["server"], r["tool"]), r["detected_at"])
            for r in con.execute("SELECT * FROM mcp_server_state"):
                self.servers[r["server"]] = ServerState(
                    r["baseline_at"],
                    r["last_list_at"],
                    r["last_error"],
                    r["last_error_at"],
                    bool(r["stale"]),
                )
        finally:
            con.close()

    def on_change(self, callback: Callable[[str, str | None], Any]) -> None:
        """Register `callback(server, tool_or_None)` invoked after every pin change."""
        self._listeners.append(callback)

    def _changed(self, server: str, tool: str | None) -> None:
        for cb in list(self._listeners):
            try:
                cb(server, tool)
            except Exception:
                log.exception("pin listener failed server=%s tool=%s", server, tool)

    # ------------------------------------------------------------------ reads (sync, cached)
    def get(self, server: str, name: str) -> tuple[PinRecord | None, Candidate | None]:
        return self.pins.get(server, {}).get(name), self.candidates.get(server, {}).get(name)

    def has_baseline(self, server: str) -> bool:
        st = self.servers.get(server)
        return bool(st and st.baseline_at)

    def check(self, server: str, tool: dict[str, Any]) -> PinCheck:
        """Pin status of a listed tool definition: new | match | changed | quarantined."""
        name = str(tool.get("name", ""))
        h = tool_hash(tool)
        pin, cand = self.get(server, name)
        baseline = self.has_baseline(server)
        approval = cand.approval_id if cand else None
        approved_by = pin.approved_by if pin else None
        if cand and cand.reason == "manual":
            return PinCheck(
                "quarantined",
                h,
                pin.hash if pin else None,
                baseline,
                "manual",
                approval,
                approved_by,
            )
        if pin:
            status = "match" if pin.hash == h else "changed"
            reason = cand.reason if cand else None
            return PinCheck(status, h, pin.hash, baseline, reason, approval, approved_by)
        if cand and cand.reason == "poisoned":
            return PinCheck("quarantined", h, None, baseline, "poisoned", approval)
        if cand and cand.reason == "new_after_baseline":
            return PinCheck("new", h, None, True, "new_after_baseline", approval)
        # never seen before: "new after baseline" only applies to tools we have no record of
        seen = (server, name) in self.first_seen
        return PinCheck("new", h, None, baseline and not seen, None, None)

    def callable_status(self, server: str, name: str) -> CallableStatus:
        pin, cand = self.get(server, name)
        if cand and cand.reason == "manual":
            return CallableStatus(
                "quarantined", "manual", cand.approval_id, pin.hash if pin else None, cand.hash
            )
        if pin and cand and cand.reason == "changed":
            return CallableStatus("changed", "changed", cand.approval_id, pin.hash, cand.hash)
        if pin and cand and cand.reason == "poisoned":
            return CallableStatus("quarantined", "poisoned", cand.approval_id, pin.hash, cand.hash)
        if pin:
            return CallableStatus("pinned", None, None, pin.hash, pin.hash)
        if cand and cand.reason == "poisoned":
            return CallableStatus("quarantined", "poisoned", cand.approval_id, None, cand.hash)
        if cand:
            return CallableStatus("pending", cand.reason, cand.approval_id, None, cand.hash)
        return CallableStatus("unvetted")

    def input_schema(self, server: str, name: str) -> dict[str, Any] | None:
        pin = self.pins.get(server, {}).get(name)
        if pin is not None:
            return pin.definition.get("inputSchema")
        cand = self.candidates.get(server, {}).get(name)
        return None if cand is None else cand.definition.get("inputSchema")

    def view_status(self, server: str, name: str) -> str:
        """McpToolView.status: approved | pending | quarantined | changed."""
        pin, cand = self.get(server, name)
        if cand is None:
            return "approved" if pin else "pending"
        if cand.reason in ("manual", "poisoned"):
            return "quarantined"
        if cand.reason == "changed":
            return "changed"
        return "pending"

    def reasons(self, server: str, name: str) -> list[str]:
        pin, cand = self.get(server, name)
        out: list[str] = []
        if cand is None and pin is not None:
            out.append(
                "pinned (trust on first use)"
                if pin.approved_by == "tofu"
                else f"approved by {pin.approved_by}"
            )
        if cand is not None:
            if cand.reason == "poisoned":
                rules = sorted({str(f.get("rule")) for f in cand.findings if f.get("rule")})
                out.append("tool poisoning indicators" + (f": {', '.join(rules)}" if rules else ""))
            elif cand.reason == "changed":
                out.append("definition changed since pinned (possible rug pull)")
                out.append(diff_summary(cand.diff))
            elif cand.reason == "new_after_baseline":
                out.append("tool appeared after the server's tool set was pinned")
            elif cand.reason == "manual":
                out.append(
                    "quarantined by admin"
                    + (
                        f": {cand.findings[0].get('reason')}"
                        if cand.findings and cand.findings[0].get("reason")
                        else ""
                    )
                )
            if cand.approval_id:
                out.append(f"approval {cand.approval_id} pending")
        return out

    def is_overridden(self, server: str, name: str, h: str) -> str | None:
        pin = self.pins.get(server, {}).get(name)
        if pin and pin.hash == h and pin.approved_by.startswith("override:"):
            return pin.approved_by.split(":", 1)[1]
        return None

    def tool_names(self, server: str) -> list[str]:
        names = set(self.pins.get(server, {})) | set(self.candidates.get(server, {}))
        return sorted(names)

    def known_servers(self) -> set[str]:
        return set(self.pins) | set(self.candidates) | set(self.servers)

    def pinned_tools(self) -> dict[str, set[str]]:
        return {s: set(d) for s, d in self.pins.items()}

    def display_definition(self, server: str, name: str) -> dict[str, Any]:
        """Approved pin if one exists, otherwise the latest seen definition."""
        pin, cand = self.get(server, name)
        if pin:
            return pin.definition
        return cand.definition if cand else {}

    def display_hash(self, server: str, name: str) -> str:
        pin, cand = self.get(server, name)
        if cand and cand.reason in ("changed", "new_after_baseline", "poisoned"):
            return cand.hash
        return pin.hash if pin else (cand.hash if cand else "")

    # ------------------------------------------------------------------ writes (async)
    def _seen(self, server: str, name: str) -> None:
        now = _now()
        self.first_seen.setdefault((server, name), now)
        self.last_seen[(server, name)] = now

    async def pin(
        self, server: str, tool: dict[str, Any], *, approved_by: str = "tofu"
    ) -> PinRecord:
        name = str(tool["name"])
        self._seen(server, name)
        rec = PinRecord(
            tool_hash(tool),
            copy.deepcopy(tool),
            approved_by,
            self.first_seen[(server, name)],
            self.last_seen[(server, name)],
        )
        self.pins.setdefault(server, {})[name] = rec
        self.candidates.get(server, {}).pop(name, None)
        await self._persist(server, name)
        self._changed(server, name)
        return rec

    async def set_candidate(
        self,
        server: str,
        tool: dict[str, Any],
        *,
        reason: str,
        findings: list[dict[str, Any]] | None = None,
        diff: dict[str, Any] | None = None,
        approval_id: str | None = None,
    ) -> Candidate:
        name = str(tool["name"])
        self._seen(server, name)
        prev = self.candidates.get(server, {}).get(name)
        h = tool_hash(tool)
        keep_approval = approval_id or (prev.approval_id if prev and prev.hash == h else None)
        cand = Candidate(
            reason, h, copy.deepcopy(tool), list(findings or []), dict(diff or {}), keep_approval
        )
        if prev and prev.hash == h:
            cand.detected_at = prev.detected_at
        self.candidates.setdefault(server, {})[name] = cand
        await self._persist(server, name)
        self._changed(server, name)
        return cand

    async def quarantine(
        self,
        server: str,
        tool: dict[str, Any] | str,
        *,
        reason: str = "poisoned",
        findings: list[dict[str, Any]] | None = None,
    ) -> Candidate:
        """Quarantine a listed definition (poisoned) or, by name, an existing tool (manual)."""
        if isinstance(tool, str):
            pin, cand = self.get(server, tool)
            definition = (cand.definition if cand else None) or (
                pin.definition if pin else {"name": tool}
            )
        else:
            definition = tool
        return await self.set_candidate(server, definition, reason=reason, findings=findings)

    async def set_approval(self, server: str, name: str, approval_id: str | None) -> None:
        cand = self.candidates.get(server, {}).get(name)
        if cand is None:
            return
        cand.approval_id = approval_id
        await self._persist(server, name)

    async def clear_candidate(self, server: str, name: str) -> None:
        if self.candidates.get(server, {}).pop(name, None) is not None:
            await self._persist(server, name)
            self._changed(server, name)

    async def approve(
        self,
        server: str,
        name: str,
        *,
        expected_hash: str | None = None,
        approved_by: str = "admin",
    ) -> PinRecord:
        """Accept the candidate (latest seen) definition as the new pin. With `expected_hash`,
        refuse if the candidate changed meanwhile (approval was for a different definition)."""
        pin, cand = self.get(server, name)
        if cand is None:
            if pin is None:
                raise KeyError(f"{server}/{name} is unknown")
            if expected_hash and pin.hash != expected_hash:
                raise ValueError("candidate changed")
            return pin
        if expected_hash and cand.hash != expected_hash:
            raise ValueError("candidate changed")
        return await self.pin(server, cand.definition, approved_by=approved_by)

    async def touch(self, server: str, name: str) -> None:
        self._seen(server, name)

    async def mark_baseline(self, server: str) -> None:
        st = self.servers.setdefault(server, ServerState())
        st.last_list_at = _now()
        st.stale = False
        if not st.baseline_at:
            st.baseline_at = st.last_list_at
        await self._persist_server(server)

    async def set_server_error(self, server: str, error: str | None) -> None:
        st = self.servers.setdefault(server, ServerState())
        st.last_error = error
        st.last_error_at = _now() if error else st.last_error_at
        await self._persist_server(server)

    async def set_stale(self, server: str, stale: bool = True) -> None:
        st = self.servers.setdefault(server, ServerState())
        st.stale = stale
        await self._persist_server(server)

    async def reset(self, server: str | None = None) -> None:
        if server is None:
            self.pins.clear()
            self.candidates.clear()
            self.servers.clear()
            self.first_seen.clear()
            self.last_seen.clear()
        else:
            self.pins.pop(server, None)
            self.candidates.pop(server, None)
            self.servers.pop(server, None)
            for key in [k for k in self.first_seen if k[0] == server]:
                self.first_seen.pop(key, None)
                self.last_seen.pop(key, None)
        if self._connect is not None:
            async with self._lock:
                await asyncio.to_thread(self._reset_sync, server)
        self._changed(server or "*", None)

    # ------------------------------------------------------------------ persistence
    def _row(self, server: str, name: str) -> tuple[Any, ...] | None:
        pin, cand = self.get(server, name)
        if pin is None and cand is None:
            return None
        definition = pin.definition if pin else cand.definition  # type: ignore[union-attr]
        h = pin.hash if pin else cand.hash  # type: ignore[union-attr]
        return (
            server,
            name,
            h,
            canonical_json(definition),
            self.view_status(server, name),
            json.dumps(self.reasons(server, name)),
            self.first_seen.get((server, name), _now()),
            self.last_seen.get((server, name), _now()),
            pin.approved_by if pin else None,
        )

    async def _persist(self, server: str, name: str) -> None:
        if self._connect is None:
            return
        row = self._row(server, name)
        cand = self.candidates.get(server, {}).get(name)
        crow = (
            None
            if cand is None
            else (
                server,
                name,
                cand.hash,
                canonical_json(cand.definition),
                cand.reason,
                json.dumps(cand.findings, default=str),
                json.dumps(cand.diff, default=str),
                cand.approval_id,
                cand.detected_at,
            )
        )
        async with self._lock:
            await asyncio.to_thread(self._persist_sync, server, name, row, crow)

    def _persist_sync(
        self, server: str, name: str, row: tuple[Any, ...] | None, crow: tuple[Any, ...] | None
    ) -> None:
        assert self._connect is not None
        con = self._connect()
        try:
            if row is None:
                con.execute("DELETE FROM mcp_tools WHERE server=? AND tool=?", (server, name))
            else:
                con.execute("INSERT OR REPLACE INTO mcp_tools VALUES (?,?,?,?,?,?,?,?,?)", row)
            if crow is None:
                con.execute(
                    "DELETE FROM mcp_tool_candidates WHERE server=? AND tool=?", (server, name)
                )
            else:
                con.execute(
                    "INSERT OR REPLACE INTO mcp_tool_candidates VALUES (?,?,?,?,?,?,?,?,?)", crow
                )
            con.commit()
        except sqlite3.Error:
            log.exception("pin persist failed server=%s tool=%s", server, name)
        finally:
            con.close()

    async def _persist_server(self, server: str) -> None:
        if self._connect is None:
            return
        st = self.servers.get(server) or ServerState()
        row = (
            server,
            st.baseline_at,
            st.last_list_at,
            st.last_error,
            st.last_error_at,
            int(st.stale),
        )
        async with self._lock:
            await asyncio.to_thread(self._persist_server_sync, row)

    def _persist_server_sync(self, row: tuple[Any, ...]) -> None:
        assert self._connect is not None
        con = self._connect()
        try:
            con.execute("INSERT OR REPLACE INTO mcp_server_state VALUES (?,?,?,?,?,?)", row)
            con.commit()
        except sqlite3.Error:
            log.exception("server state persist failed server=%s", row[0])
        finally:
            con.close()

    def _reset_sync(self, server: str | None) -> None:
        assert self._connect is not None
        con = self._connect()
        try:
            for table in ("mcp_tools", "mcp_tool_candidates", "mcp_server_state"):
                if server is None:
                    con.execute(f"DELETE FROM {table}")
                else:
                    con.execute(f"DELETE FROM {table} WHERE server=?", (server,))
            con.commit()
        finally:
            con.close()


__all__ = [
    "CallableStatus",
    "Candidate",
    "PinCheck",
    "PinRecord",
    "PinStore",
    "ServerState",
    "canonical_json",
    "diff_summary",
    "diff_tools",
    "tool_hash",
]
