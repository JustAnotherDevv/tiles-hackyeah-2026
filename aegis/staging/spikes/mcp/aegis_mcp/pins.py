"""Trust-on-first-use pinning of MCP tool definitions (MCP-03, rug-pull defense).

Pins are keyed by the *catalog* server name (not by session or client), so a definition that
changes between two sessions, two clients or a proxy restart (with a persistent store) is
still caught. The hash covers the whole canonical tool object (name, title, description,
inputSchema, outputSchema, annotations, _meta): a change anywhere is a change.

State per server:
    pins        name -> Pin           approved definitions; calls allowed
    quarantine  name -> Quarantined   poisoned / changed / added-after-baseline; calls blocked
    baseline    set once a complete (last-page) tools/list was processed; tools appearing after
                that are "new_after_baseline" and need approval

In the gateway this becomes a SQLite table (server, tool, hash, definition_json, status,
approved_by, approved_at) behind the same methods, and `approve()` is wired to the
org approval flow (admin role) with the diff shown in the dashboard.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def tool_hash(tool: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(tool).encode("utf-8")).hexdigest()


def diff_tools(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Small, dashboard-friendly diff between two tool definitions."""
    changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    out: dict[str, Any] = {"changed_fields": changed}
    if "description" in changed:
        out["description_diff"] = list(difflib.unified_diff(
            (old.get("description") or "").splitlines(), (new.get("description") or "").splitlines(),
            "pinned", "current", lineterm="", n=0))[2:]
    old_props = set((old.get("inputSchema") or {}).get("properties", {}))
    new_props = set((new.get("inputSchema") or {}).get("properties", {}))
    if old_props != new_props:
        out["params_added"] = sorted(new_props - old_props)
        out["params_removed"] = sorted(old_props - new_props)
    return out


@dataclass
class Pin:
    hash: str
    definition: dict[str, Any]
    approved_by: str = "tofu"
    pinned_at: float = field(default_factory=time.time)


@dataclass
class Quarantined:
    reason: str  # poisoned | changed | new_after_baseline
    hash: str
    definition: dict[str, Any]
    findings: list[dict[str, str]] = field(default_factory=list)
    diff: dict[str, Any] = field(default_factory=dict)
    detected_at: float = field(default_factory=time.time)


class PinStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.pins: dict[str, dict[str, Pin]] = {}
        self.quarantine: dict[str, dict[str, Quarantined]] = {}
        self.baseline: set[str] = set()
        if self.path and self.path.exists():
            self._load()

    # -- queries ---------------------------------------------------------------------------

    def check(self, server: str, tool: dict[str, Any]) -> tuple[str, Pin | None, str]:
        """-> (status, pin, hash) where status is new | match | changed."""
        h = tool_hash(tool)
        pin = self.pins.get(server, {}).get(tool.get("name", ""))
        if pin is None:
            return "new", None, h
        return ("match" if pin.hash == h else "changed"), pin, h

    def callable_status(self, server: str, name: str) -> tuple[bool, str]:
        if q := self.quarantine.get(server, {}).get(name):
            return False, q.reason
        if name in self.pins.get(server, {}):
            return True, "pinned"
        return False, "unvetted"

    def input_schema(self, server: str, name: str) -> dict[str, Any] | None:
        pin = self.pins.get(server, {}).get(name)
        return None if pin is None else pin.definition.get("inputSchema")

    def has_baseline(self, server: str) -> bool:
        return server in self.baseline

    # -- mutations -------------------------------------------------------------------------

    def pin(self, server: str, tool: dict[str, Any], *, approved_by: str = "tofu") -> Pin:
        p = Pin(tool_hash(tool), tool, approved_by)
        self.pins.setdefault(server, {})[tool["name"]] = p
        self.quarantine.get(server, {}).pop(tool["name"], None)
        self._save()
        return p

    def quarantine_tool(self, server: str, name: str, record: Quarantined) -> None:
        self.quarantine.setdefault(server, {})[name] = record
        self._save()

    def mark_baseline(self, server: str) -> None:
        if server not in self.baseline:
            self.baseline.add(server)
            self._save()

    def approve(self, server: str, name: str, *, approved_by: str = "admin") -> Pin:
        """Accept the quarantined (latest seen) definition as the new pin."""
        q = self.quarantine.get(server, {}).get(name)
        if q is None:
            raise KeyError(f"{server}/{name} is not quarantined")
        return self.pin(server, q.definition, approved_by=approved_by)

    def reset(self, server: str | None = None) -> None:
        for d in (self.pins, self.quarantine):
            if server is None:
                d.clear()
            else:
                d.pop(server, None)
        if server is None:
            self.baseline.clear()
        else:
            self.baseline.discard(server)
        self._save()

    # -- views / persistence ---------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        servers = sorted(set(self.pins) | set(self.quarantine))
        return {
            s: {
                "baseline": s in self.baseline,
                "pinned": {n: {"hash": p.hash, "approved_by": p.approved_by} for n, p in self.pins.get(s, {}).items()},
                "quarantined": {n: {"reason": q.reason, "hash": q.hash, "diff": q.diff, "findings": q.findings}
                                for n, q in self.quarantine.get(s, {}).items()},
            }
            for s in servers
        }

    def _save(self) -> None:
        if not self.path:
            return
        data = {
            "pins": {s: {n: asdict(p) for n, p in d.items()} for s, d in self.pins.items()},
            "quarantine": {s: {n: asdict(q) for n, q in d.items()} for s, d in self.quarantine.items()},
            "baseline": sorted(self.baseline),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".pins-")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)  # atomic

    def _load(self) -> None:
        assert self.path is not None
        data = json.loads(self.path.read_text())
        self.pins = {s: {n: Pin(**p) for n, p in d.items()} for s, d in data.get("pins", {}).items()}
        self.quarantine = {s: {n: Quarantined(**q) for n, q in d.items()} for s, d in data.get("quarantine", {}).items()}
        self.baseline = set(data.get("baseline", []))
