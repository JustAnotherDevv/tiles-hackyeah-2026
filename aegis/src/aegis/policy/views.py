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


#: per-control test evidence from the last self-test report, cached by (path, mtime)
_EVIDENCE_CACHE: dict[str, Any] = {"key": None, "value": None}


def _case_controls(case: dict[str, Any]) -> list[str]:
    """Controls a passing case is credited to: the deciding control when it is one of the expected
    ones (a list = any of), else every expected control."""
    exp = case.get("control")
    exp_l = [str(x) for x in exp] if isinstance(exp, list) else ([str(exp)] if exp else [])
    got = case.get("got_control")
    if got and str(got) in exp_l:
        return [str(got)]
    return exp_l


def test_evidence(rt: Any) -> dict[str, Any] | None:
    """Per-control core-test evidence from `<reports_dir>/results.json` (schema aegis.selftest/1).

    Returns `{"generated_at", "git_sha", "mode", "controls": {cid: {attack_pass, benign_pass, fail}}}`
    or None when no report exists / it is unreadable. Only `tier: core` cases count; an attack case
    counts for a control only when it passed with the right action AND that control decided it.
    """
    try:
        from aegis.metrics.perf import reports_dir

        path = reports_dir(rt) / "results.json"
        st = path.stat()
    except Exception:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if _EVIDENCE_CACHE["key"] == key:
        return _EVIDENCE_CACHE["value"]
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        cases = list(data.get("cases") or [])
    except Exception:
        log.warning("coverage: self-test report unreadable at %s", path)
        return None
    per: dict[str, dict[str, int]] = {}
    for c in cases:
        if not isinstance(c, dict) or (c.get("tier") or "core") != "core":
            continue
        outcome, pol = str(c.get("outcome") or ""), str(c.get("polarity") or "")
        if outcome == "fail":
            for cid in _case_controls(c):
                per.setdefault(cid, {"attack_pass": 0, "benign_pass": 0, "fail": 0})["fail"] += 1
            continue
        if pol == "attack" and outcome == "pass":
            for cid in _case_controls(c):
                per.setdefault(cid, {"attack_pass": 0, "benign_pass": 0, "fail": 0})["attack_pass"] += 1
        elif pol == "benign" and outcome in ("pass", "pass_other"):
            exp = c.get("control")
            for cid in [str(x) for x in exp] if isinstance(exp, list) else ([str(exp)] if exp else []):
                per.setdefault(cid, {"attack_pass": 0, "benign_pass": 0, "fail": 0})["benign_pass"] += 1
    value = {
        "generated_at": data.get("generated_at"),
        "git_sha": data.get("git_sha"),
        "mode": data.get("mode"),
        "controls": per,
    }
    _EVIDENCE_CACHE.update(key=key, value=value)
    return value


#: control states, best first (an item takes the best state among its mapped controls)
_STATE_ORDER = ("covered", "enforced_failing", "enforced_untested", "monitor", "not_implemented", "disabled")
_STATE_TEXT = {
    "covered": "enforced and tested (passing core attack case)",
    "enforced_failing": "enforced, but a core test case is failing",
    "enforced_untested": "enforced, untested (no passing core attack case in the last self-test)",
    "monitor": "monitor only (would-decide, never enforces)",
    "not_implemented": "configured but not implemented",
    "disabled": "disabled",
}


def control_state(rt: Any, snap: PolicySnapshot, cid: str, evidence: dict[str, Any] | None) -> str:
    """Honest per-control state for coverage: covered requires enabled + enforce + implemented +
    >=1 passing core attack case attributed to the control + no failing core case."""
    cfg = snap.controls.get(cid)
    if cfg is None or not cfg.enabled or cfg.mode == "off":
        return "disabled"
    if _registry(rt).get(cid) is None:
        return "not_implemented"
    if cfg.mode == "monitor":
        return "monitor"
    ev = ((evidence or {}).get("controls") or {}).get(cid) or {}
    if ev.get("fail"):
        return "enforced_failing"
    if ev.get("attack_pass", 0) >= 1:
        return "covered"
    return "enforced_untested"


def coverage(rt: Any, snap: PolicySnapshot) -> dict[str, Any]:
    """`/api/coverage`. An item is **covered** only when at least one control mapped to it (policy
    `owasp:` tags) is enabled, enforcing, implemented AND has a passing core attack test case in the
    latest self-test report (`reports/results.json`) with no failing core case. Enforced controls
    without that evidence make the item **partial** (`detail: enforced_untested`), monitor-only
    controls make it **partial** (`detail: monitor`), disabled-only items are **disabled**, items
    without any mapped control are **uncovered**. `status` keeps the 4-value contract enum; the
    additive keys `detail`, `reason`, `enforcing`, `tested` and per-control `control_states` say why.
    """
    reg = _registry(rt)
    evidence = test_evidence(rt)
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

    states: dict[str, str] = {}

    def state(cid: str) -> str:
        if cid not in states:
            states[cid] = control_state(rt, snap, cid, evidence)
        return states[cid]

    fws: list[dict[str, Any]] = []
    for fw in frameworks():
        items = []
        for it in fw.get("items") or []:
            iid = str(it.get("id"))
            ctls = sorted(set(by_item.get(iid, [])), key=catalog.sort_key)
            platform = PLATFORM_COVERAGE.get(iid, [])
            cstates = {c: state(c) for c in ctls}
            if platform and not ctls:
                status, detail = "covered", "platform"
            elif not ctls:
                status, detail = "uncovered", "no_control"
            else:
                best = min(cstates.values(), key=_STATE_ORDER.index)
                detail = best
                status = ("covered" if best == "covered" else
                          "disabled" if best == "disabled" else "partial")
            enforcing = [c for c, s in cstates.items() if s in ("covered", "enforced_failing", "enforced_untested")]
            tested = [c for c, s in cstates.items() if s == "covered"]
            if detail == "platform":
                reason = "covered by platform features: " + ", ".join(platform)
            elif detail == "no_control":
                reason = "no control is mapped to this item"
            elif status == "covered":
                reason = "enforced and tested by " + ", ".join(tested)
            else:
                reason = _STATE_TEXT.get(detail, detail) + (": " + ", ".join(
                    c for c, s in cstates.items() if s == detail) if cstates else "")
                if detail in ("enforced_untested",) and evidence is None:
                    reason += " (no self-test report found; run `make test`)"
            items.append({"id": iid, "name": it.get("name") or iid, "status": status, "controls": ctls + platform,
                          "detail": detail, "reason": reason, "enforcing": enforcing, "tested": tested,
                          "control_states": cstates})
        fws.append({"id": fw.get("id"), "name": fw.get("name"), "items": items})
    return {
        "frameworks": fws,
        "evidence": {
            "source": "reports/results.json" if evidence is not None else None,
            "generated_at": (evidence or {}).get("generated_at"),
            "git_sha": (evidence or {}).get("git_sha"),
            "rule": "covered = mapped control enabled + enforce + implemented + >=1 passing core attack case"
                    " (attributed to it) + no failing core case in the latest self-test",
        },
    }
