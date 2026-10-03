"""Read models for the dashboard: /api/controls (ControlView) and /api/coverage (CoverageResponse).

`DecisionStats` keeps a 24 h rolling window of control hits from the bus `decision` events
(backfilled once, best effort, from the audit log) for hits_24h / blocks_24h / p95_ms.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from aegis.core.policy_schema import PolicySnapshot
from aegis.policy import catalog

log = logging.getLogger(__name__)

WINDOW_S = 24 * 3600
FRAMEWORKS_PATH = Path(__file__).resolve().parent / "data" / "frameworks.yaml"
#: framework items covered by platform features rather than a control
PLATFORM_COVERAGE: dict[str, list[str]] = {"MCP08:2025": ["AUDIT"]}


@lru_cache(maxsize=1)
def frameworks() -> list[dict[str, Any]]:
    try:
        data = yaml.safe_load(FRAMEWORKS_PATH.read_text(encoding="utf-8")) or {}
        return list(data.get("frameworks") or [])
    except Exception:
        log.exception("frameworks.yaml unreadable")
        return []


class DecisionStats:
    def __init__(self, rt: Any):
        self.rt = rt
        self._hits: dict[str, deque[tuple[float, str, float]]] = {}
        self._task: asyncio.Task[Any] | None = None

    def add_summary(self, summary: dict[str, Any], ts: float | None = None) -> None:
        now = ts or time.time()
        for hit in summary.get("controls") or []:
            cid = hit.get("control_id") if isinstance(hit, dict) else getattr(hit, "control_id", None)
            if not cid:
                continue
            action = (hit.get("action") if isinstance(hit, dict) else getattr(hit, "action", "")) or ""
            lat = (hit.get("latency_ms") if isinstance(hit, dict) else getattr(hit, "latency_ms", 0.0)) or 0.0
            self._hits.setdefault(cid, deque(maxlen=20000)).append((now, str(action), float(lat)))

    def get(self, cid: str) -> tuple[int, int, float | None]:
        dq = self._hits.get(cid)
        if not dq:
            return 0, 0, None
        cutoff = time.time() - WINDOW_S
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        if not dq:
            return 0, 0, None
        lats = sorted(x[2] for x in dq)
        p95 = lats[min(len(lats) - 1, round(0.95 * (len(lats) - 1)))]
        return len(dq), sum(1 for x in dq if x[1] == "block"), round(p95, 2)

    async def _backfill(self) -> None:
        audit = getattr(self.rt, "audit", None)
        q = getattr(audit, "query", None)
        if not callable(q):
            return
        try:
            events, _ = await q(event_type="decision", limit=1000)
        except Exception:
            return
        cutoff = time.time() - WINDOW_S
        for ev in events or []:
            try:
                ts = ev.ts.timestamp()
                if ts < cutoff:
                    continue
                summary = (ev.data or {}).get("summary") or {"controls": [c.model_dump() for c in ev.controls]}
                self.add_summary(summary, ts)
            except Exception:
                continue

    async def _run(self) -> None:
        await self._backfill()
        bus = getattr(self.rt, "bus", None)
        sub = getattr(bus, "subscribe", None)
        if not callable(sub):
            return
        while True:
            try:
                async for msg in sub({"decision"}):
                    data = msg.data if hasattr(msg, "data") else msg
                    if isinstance(data, dict) and not data.get("dry_run"):
                        self.add_summary(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("decision stats subscriber failed - restarting")
                await asyncio.sleep(1.0)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run(), name="aegis-policy-stats")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None


def _registry(rt: Any) -> dict[str, Any]:
    reg = getattr(rt, "controls", None)
    try:
        return {c.id: c for c in (reg.all() if reg is not None else [])}
    except Exception:
        return {}


def _surfaces(ctl: Any, entry: catalog.CatalogEntry | None) -> list[str]:
    applies = getattr(ctl, "applies_to", None)
    surf = sorted(getattr(applies, "surfaces", None) or [])
    if surf:
        return surf
    if entry is not None and entry.surfaces:
        return list(entry.surfaces)
    return []


def control_views(rt: Any, snap: PolicySnapshot, stats: DecisionStats | None = None) -> list[dict[str, Any]]:
    reg = _registry(rt)
    ids = set(catalog.CATALOG) | set(reg) | set(snap.controls)
    out: list[dict[str, Any]] = []
    for cid in sorted(ids, key=catalog.sort_key):
        cfg = snap.controls.get(cid)
        ctl = reg.get(cid)
        entry = catalog.get(cid)
        hits, blocks, p95 = stats.get(cid) if stats is not None else (0, 0, None)
        kind = str(getattr(ctl, "kind", None) or (entry.kind if entry else "deterministic"))
        owasp = list((cfg.owasp if cfg and cfg.owasp else None) or getattr(ctl, "owasp", None) or
                     (list(entry.owasp) if entry else []))
        out.append({
            "id": cid,
            "family": getattr(ctl, "family", None) or (entry.family if entry else catalog.family_of(cid)),
            "name": (cfg.name if cfg and cfg.name else None) or getattr(ctl, "name", None) or (entry.name if entry else cid),
            "kind": kind if kind in ("deterministic", "semantic", "hybrid", "stateful") else "deterministic",
            "owner": entry.owner if entry else "custom",
            "enabled": bool(cfg.enabled) if cfg else False,
            "mode": cfg.mode if cfg else "off",
            "action": cfg.action if cfg else (entry.default_action if entry else "block"),
            "threshold": cfg.threshold if cfg else None,
            "severity": cfg.severity if cfg else "medium",
            "owasp": owasp,
            "surfaces": _surfaces(ctl, entry),
            "implemented": ctl is not None,
            "hits_24h": hits,
            "blocks_24h": blocks,
            "p95_ms": p95,
            # additive (harmless extra keys)
            "configured": cfg is not None,
            "fail_mode": cfg.fail_mode if cfg else None,
            "adherence_pct": cfg.adherence_pct if cfg else None,
            "tests": len(cfg.tests) if cfg else 0,
            "reserved": bool(entry.reserved) if entry else False,
        })
    return out


def coverage(rt: Any, snap: PolicySnapshot) -> dict[str, Any]:
    reg = _registry(rt)
    by_item: dict[str, list[str]] = {}
    for cid in set(catalog.CATALOG) | set(reg) | set(snap.controls):
        cfg = snap.controls.get(cid)
        entry = catalog.get(cid)
        if entry is not None and entry.reserved and cfg is None:
            continue
        owasp = (cfg.owasp if cfg and cfg.owasp else None) or getattr(reg.get(cid), "owasp", None) or (
            list(entry.owasp) if entry else [])
        for item in owasp:
            by_item.setdefault(str(item), []).append(cid)

    def state(cid: str) -> str:
        cfg = snap.controls.get(cid)
        if cfg is None or not cfg.enabled or cfg.mode == "off":
            return "disabled"
        if reg.get(cid) is None or cfg.mode == "monitor":
            return "partial"
        return "covered"

    fws: list[dict[str, Any]] = []
    for fw in frameworks():
        items = []
        for it in fw.get("items") or []:
            iid = str(it.get("id"))
            ctls = sorted(set(by_item.get(iid, [])), key=catalog.sort_key)
            platform = PLATFORM_COVERAGE.get(iid, [])
            if platform and not ctls:
                status = "covered"
            elif not ctls:
                status = "uncovered"
            else:
                states = {state(c) for c in ctls}
                status = "covered" if "covered" in states else "partial" if "partial" in states else "disabled"
            items.append({"id": iid, "name": it.get("name") or iid, "status": status, "controls": ctls + platform})
        fws.append({"id": fw.get("id"), "name": fw.get("name"), "items": items})
    return {"frameworks": fws}
