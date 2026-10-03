"""Aggregations behind GET /api/stats (StatsResponse), the SSE `stats` tick (StatsTick),
GET /api/stats/posture (posture score) and `control_rollup()` (public helper for policy-engine).

SQL runs over the `decisions` projection in a worker thread; results are cached 2 s per
(window, synthetic). Spend today / org budget % / local compute are ledger-authoritative for live
traffic (+ the flagged synthetic history when it is included).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from aegis.audit.log import open_db
from aegis.metrics.perf import ACTIONS, PerfTracker, semantic_status
from aegis.metrics.timing import WINDOWS, bucket_starts, epoch_iso, iso_z, utc_now

log = logging.getLogger(__name__)

DEST_CLASSES = ("local", "remote", "third_party")
_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
CACHE_S = 2.0


def _perf(rt: Any) -> PerfTracker:
    return getattr(getattr(rt, "metrics", None), "perf", None) or PerfTracker()


def _data_dir(rt: Any) -> Any:
    from pathlib import Path

    return Path(getattr(getattr(rt, "settings", None), "data_dir", None) or "data")


def _conn(rt: Any) -> sqlite3.Connection:
    return open_db(rt, _data_dir(rt))


# ------------------------------------------------------------------ SQL part (sync)
def _sql_stats(conn: sqlite3.Connection, window: str, include_synth: bool, now: datetime) -> dict[str, Any]:
    span, step = WINDOWS[window]
    starts, step = bucket_starts(window, now)
    since = iso_z(datetime.fromtimestamp(starts[0], UTC))
    syn = 1 if include_synth else 0
    flt = "ts >= ? AND (? = 1 OR synthetic = 0)"
    dflt = "d.ts >= ? AND (? = 1 OR d.synthetic = 0)"
    args = (since, syn)

    buckets = {s: {"ts": epoch_iso(s), **{a: 0 for a in ACTIONS}, "spend_usd": 0.0, "tokens": 0} for s in starts}
    for b, action, n, cost, tok in conn.execute(
        f"SELECT (CAST(strftime('%s', ts) AS INTEGER) / {step}) * {step} AS b, action, COUNT(*),"
        f" COALESCE(SUM(cost_usd), 0), COALESCE(SUM(tokens), 0) FROM decisions WHERE {flt}"
        " GROUP BY b, action",
        args,
    ):
        row = buckets.get(int(b))
        if row is None:
            continue
        if action in ACTIONS:
            row[action] += int(n)
        row["spend_usd"] = round(row["spend_usd"] + float(cost), 6)
        row["tokens"] += int(tok)

    kpi_since = iso_z(now - timedelta(seconds=span))
    kargs = (kpi_since, syn)
    counts = {a: 0 for a in ACTIONS}
    total = 0
    for action, n in conn.execute(f"SELECT action, COUNT(*) FROM decisions WHERE {flt} GROUP BY action", kargs):
        total += int(n)
        if action in counts:
            counts[action] += int(n)
    agg = conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0), COALESCE(SUM(tokens),0), COALESCE(SUM(cost_avoided_usd),0),"
        f" COUNT(DISTINCT agent_id) FROM decisions WHERE {flt}",
        kargs,
    ).fetchone()
    local_tokens = conn.execute(
        f"SELECT COALESCE(SUM(tokens),0) FROM decisions WHERE {flt} AND dest_class='local' AND kind='model_call'",
        kargs,
    ).fetchone()[0]

    # by_control: every control hit recorded in the summary (+ primary when no hit list)
    ctl: dict[str, dict[str, Any]] = {}
    for cid, act, mode, n in conn.execute(
        "SELECT json_extract(c.value,'$.control_id'), json_extract(c.value,'$.action'),"
        " json_extract(c.value,'$.mode'), COUNT(*) FROM decisions d, json_each(d.summary_json,'$.controls') c"
        f" WHERE {dflt} GROUP BY 1, 2, 3",
        kargs,
    ):
        if not cid:
            continue
        e = ctl.setdefault(cid, {"control_id": cid, "family": cid.split("-")[0], "hits": 0, "blocks": 0, "redacts": 0})
        e["hits"] += int(n)
        if mode != "monitor":
            if act == "block":
                e["blocks"] += int(n)
            elif act == "redact":
                e["redacts"] += int(n)
    for cid, act, n in conn.execute(
        "SELECT control_id, action, COUNT(*) FROM decisions WHERE "
        f"{flt} AND control_id IS NOT NULL AND json_array_length(summary_json,'$.controls') = 0"
        " GROUP BY 1, 2",
        kargs,
    ):
        e = ctl.setdefault(cid, {"control_id": cid, "family": cid.split("-")[0], "hits": 0, "blocks": 0, "redacts": 0})
        e["hits"] += int(n)
        if act == "block":
            e["blocks"] += int(n)
        elif act == "redact":
            e["redacts"] += int(n)
    by_control = sorted(ctl.values(), key=lambda x: (-x["hits"], x["control_id"]))[:15]

    by_category = [
        {"category": c, "count": int(n)}
        for c, n in conn.execute(
            f"SELECT c.value, COUNT(*) FROM decisions d, json_each(d.categories_json) c WHERE {dflt}"
            " GROUP BY 1 ORDER BY 2 DESC",
            kargs,
        )
        if c
    ]
    dest = {d: {"dest_class": d, "count": 0, "redactions": 0} for d in DEST_CLASSES}
    for dc, n, reds in conn.execute(
        f"SELECT dest_class, COUNT(*), COALESCE(SUM(redaction_count),0) FROM decisions WHERE {flt} GROUP BY 1",
        kargs,
    ):
        if dc in dest:
            dest[dc]["count"] += int(n)
            dest[dc]["redactions"] += int(reds)
    by_entity = [
        {"entity": e, "count": int(n)}
        for e, n in conn.execute(
            f"SELECT e.value, COUNT(*) FROM decisions d, json_each(d.entities_json) e WHERE {dflt}"
            " GROUP BY 1 ORDER BY 2 DESC LIMIT 15",
            kargs,
        )
        if e
    ]
    top_agents = [
        {"agent_id": a, "requests": int(n), "blocks": int(b or 0), "spend_usd": round(float(s or 0), 6)}
        for a, n, b, s in conn.execute(
            "SELECT agent_id, COUNT(*), SUM(CASE WHEN action='block' THEN 1 ELSE 0 END), SUM(cost_usd)"
            f" FROM decisions WHERE {flt} AND agent_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8",
            kargs,
        )
    ]
    midnight = iso_z(now.replace(hour=0, minute=0, second=0, microsecond=0))
    today = {
        int(s): float(c)
        for s, c in conn.execute(
            "SELECT synthetic, COALESCE(SUM(cost_usd),0) FROM decisions WHERE ts >= ? GROUP BY 1", (midnight,)
        )
    }
    degraded_recent = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE ts >= ? AND synthetic = 0 AND degraded = 1",
        (iso_z(now - timedelta(minutes=5)),),
    ).fetchone()[0]
    return {
        "timeseries": [buckets[s] for s in starts],
        "counts": counts,
        "total": total,
        "spend": float(agg[0]),
        "tokens": int(agg[1]),
        "avoided": float(agg[2]),
        "agents": int(agg[3]),
        "local_tokens": int(local_tokens or 0),
        "by_control": by_control,
        "by_category": by_category,
        "by_destination": [dest[d] for d in DEST_CLASSES],
        "by_entity": by_entity,
        "top_agents": top_agents,
        "today_live": today.get(0, 0.0),
        "today_synth": today.get(1, 0.0) if include_synth else 0.0,
        "degraded_recent": int(degraded_recent or 0),
    }


def sql_stats(rt: Any, window: str, include_synth: bool, now: datetime | None = None) -> dict[str, Any]:
    conn = _conn(rt)
    try:
        return _sql_stats(conn, window, include_synth, now or utc_now())
    finally:
        conn.close()


# ------------------------------------------------------------------ service pulls (async)
async def _guard(coro: Any, timeout: float = 0.3) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout)
    except Exception:
        return None


async def org_id(rt: Any) -> str | None:
    org = getattr(rt, "org", None)
    if org is None:
        return None
    o = await _guard(org.org())
    return getattr(o, "id", None)


async def ledger_today(rt: Any) -> dict[str, float]:
    """{'used_usd', 'limit_usd', 'pct', 'compute_s'} for the org day window (ledger-authoritative)."""
    out = {"used_usd": 0.0, "limit_usd": 0.0, "pct": 0.0, "compute_s": 0.0}
    ledger = getattr(rt, "ledger", None)
    if ledger is None:
        return out
    oid = await org_id(rt)
    statuses = await _guard(ledger.status(f"org:{oid}" if oid else None))
    if not statuses:
        statuses = await _guard(ledger.status())
    for st in statuses or []:
        try:
            if st.scope_type != "org" or st.window != "day":
                continue
            if st.dimension == "usd":
                out["used_usd"] = float(st.used)
                out["limit_usd"] = float(st.limit)
                out["pct"] = float(st.pct)
            elif st.dimension == "compute_s":
                out["compute_s"] = float(st.used)
        except Exception:
            continue
    return out


async def approvals_counts(rt: Any, since: datetime) -> tuple[int, int]:
    approvals = getattr(rt, "approvals", None)
    if approvals is None:
        return 0, 0
    pending = await _guard(approvals.list_requests(status="pending"))
    every = await _guard(approvals.list_requests(limit=1000))
    decided = 0
    for a in every or []:
        try:
            if a.decided_at is not None and a.decided_at >= since:
                decided += 1
        except Exception:
            continue
    return len(pending or []), decided


def feed_ok(rt: Any) -> bool:
    try:
        return rt.feed.status().status in {"ok", "seed"}
    except Exception:
        return True


def verify_ok(rt: Any) -> bool:
    lv = getattr(getattr(rt, "audit", None), "last_verify", None)
    return True if lv is None else bool(lv.ok)


async def build_stats(rt: Any, window: str = "24h", include_synth: bool = True,
                      now: datetime | None = None) -> dict[str, Any]:
    """StatsResponse (CONTRACTS section 5.5) with exactly the frozen keys."""
    if window not in WINDOWS:
        raise ValueError(f"bad window {window!r}")
    key = (id(rt), window, include_synth)
    hit = _CACHE.get(key)
    if now is None and hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    now = now or utc_now()
    sql = await asyncio.to_thread(sql_stats, rt, window, include_synth, now)
    span = WINDOWS[window][0]
    led = await ledger_today(rt)
    pending, decided = await approvals_counts(rt, now - timedelta(seconds=span))
    perf = _perf(rt)
    ov = perf.overhead_ms()
    sem = semantic_status(rt)
    spend_today = max(led["used_usd"], sql["today_live"]) + sql["today_synth"]
    if led["limit_usd"] > 0:
        pct = spend_today / led["limit_usd"] * 100.0
    else:
        pct = led["pct"]
    local_compute = led["compute_s"] or round(sql["local_tokens"] / 50.0, 1)
    degraded = bool(
        (sem.get("degraded") and sem.get("mode") != "off")
        or sql["degraded_recent"] > 0
        or not feed_ok(rt)
        or not verify_ok(rt)
    )
    kpis = {
        "requests": sql["total"],
        "allowed": sql["counts"]["allow"],
        "logged": sql["counts"]["log"],
        "redacted": sql["counts"]["redact"],
        "blocked": sql["counts"]["block"],
        "approvals_pending": pending,
        "approvals_decided": decided,
        "spend_usd": round(sql["spend"], 4),
        "spend_today_usd": round(spend_today, 4),
        "org_budget_used_pct": round(pct, 2),
        "tokens": sql["tokens"],
        "local_compute_s": round(float(local_compute), 1),
        "cost_avoided_usd": round(sql["avoided"], 4),
        "active_agents": sql["agents"],
        "p50_overhead_ms": ov["p50"],
        "p95_overhead_ms": ov["p95"],
        "degraded": degraded,
    }
    resp = {
        "window": window,
        "generated_at": iso_z(now),
        "kpis": kpis,
        "timeseries": sql["timeseries"],
        "by_control": sql["by_control"],
        "by_category": sql["by_category"],
        "by_destination": sql["by_destination"],
        "by_entity": sql["by_entity"],
        "top_agents": sql["top_agents"],
    }
    _CACHE[key] = (time.monotonic(), resp)
    if len(_CACHE) > 32:
        _CACHE.pop(next(iter(_CACHE)))
    return resp


# ------------------------------------------------------------------ SSE tick (memory only)
class TickState:
    """Values refreshed slowly (spend every 10 s, approvals every 5 s) for the 2 s tick."""

    def __init__(self) -> None:
        self.spend_today = 0.0
        self.pending = 0
        self._spend_at = 0.0
        self._pending_at = 0.0

    async def refresh(self, rt: Any, include_synth: bool = True) -> None:
        now = time.monotonic()
        if now - self._spend_at >= 10.0:
            self._spend_at = now
            with contextlib.suppress(Exception):
                led = await ledger_today(rt)
                midnight = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
                today = await asyncio.to_thread(_today_spend, rt, midnight, include_synth)
                self.spend_today = round(max(led["used_usd"], today[0]) + today[1], 4)
        if now - self._pending_at >= 5.0:
            self._pending_at = now
            approvals = getattr(rt, "approvals", None)
            if approvals is not None:
                items = await _guard(approvals.list_requests(status="pending"))
                if items is not None:
                    self.pending = len(items)


def _today_spend(rt: Any, midnight: datetime, include_synth: bool) -> tuple[float, float]:
    conn = _conn(rt)
    try:
        rows = dict(
            conn.execute(
                "SELECT synthetic, COALESCE(SUM(cost_usd),0) FROM decisions WHERE ts >= ? GROUP BY 1",
                (iso_z(midnight),),
            ).fetchall()
        )
    except sqlite3.Error:
        rows = {}
    finally:
        conn.close()
    return float(rows.get(0, 0.0)), float(rows.get(1, 0.0)) if include_synth else 0.0


def build_stats_tick(rt: Any, state: TickState | None = None) -> dict[str, Any]:
    """StatsTick (CONTRACTS section 5.5) from memory only."""
    perf = _perf(rt)
    ov = perf.overhead_ms()
    return {
        "ts": iso_z(),
        "rps": perf.rps(60.0),
        "decisions_1m": perf.decisions_1m(),
        "spend_today_usd": state.spend_today if state else 0.0,
        "approvals_pending": state.pending if state else 0,
        "p50_overhead_ms": ov["p50"],
        "p95_overhead_ms": ov["p95"],
    }


# ------------------------------------------------------------------ control rollup (G9)
async def control_rollup(rt: Any, window_s: int = 86400) -> dict[str, dict[str, Any]]:
    """{control_id: {"hits", "blocks", "p95_ms"}} over live (non-synthetic) decisions."""

    def _q() -> dict[str, dict[str, Any]]:
        conn = _conn(rt)
        out: dict[str, dict[str, Any]] = {}
        try:
            for cid, act, mode, n in conn.execute(
                "SELECT json_extract(c.value,'$.control_id'), json_extract(c.value,'$.action'),"
                " json_extract(c.value,'$.mode'), COUNT(*) FROM decisions d,"
                " json_each(d.summary_json,'$.controls') c WHERE d.ts >= ? AND d.synthetic = 0 GROUP BY 1,2,3",
                (iso_z(utc_now() - timedelta(seconds=window_s)),),
            ):
                if not cid:
                    continue
                e = out.setdefault(cid, {"hits": 0, "blocks": 0, "p95_ms": None})
                e["hits"] += int(n)
                if act == "block" and mode != "monitor":
                    e["blocks"] += int(n)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
        return out

    out = await asyncio.to_thread(_q)
    for cid, p95 in _perf(rt).control_p95().items():
        out.setdefault(cid, {"hits": 0, "blocks": 0, "p95_ms": None})["p95_ms"] = p95
    return out


# ------------------------------------------------------------------ posture (G2)
FEED_SCORES = {"ok": 1.0, "seed": 0.7, "rejected": 0.6, "unreachable": 0.5, "stale": 0.4, "disabled": 0.0}


def _grade(score: int) -> str:
    for threshold, grade in ((95, "A"), (90, "A-"), (85, "B+"), (80, "B"), (70, "C")):
        if score >= threshold:
            return grade
    return "D"


async def posture(rt: Any, primer: dict[str, Any] | None = None) -> dict[str, Any]:
    comps: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    policy_version = 0
    snap = None
    with contextlib.suppress(Exception):
        snap = rt.policy.snapshot()
        policy_version = int(snap.version)

    # controls (35)
    if snap is not None and snap.controls:
        reg = getattr(rt, "controls", None)
        total, acc, monitor, off = 0, 0.0, 0, 0
        for cid, cfg in sorted(snap.controls.items()):
            if cid.startswith("A2A-"):
                continue
            total += 1
            implemented = True
            if reg is not None:
                with contextlib.suppress(Exception):
                    implemented = reg.get(cid) is not None
            if not cfg.enabled or cfg.mode == "off" or not implemented:
                off += 1
                why = "not implemented" if implemented is False and cfg.enabled else "disabled"
                sev = "high" if cid.split("-")[0] in {"DLP", "INJ", "EXE", "SIG"} else "medium"
                findings.append({"severity": sev, "message": f"{cid} {why} (policy v{policy_version})",
                                 "control_id": cid, "link": "/ui/governance/policy"})
            elif cfg.mode == "monitor":
                monitor += 1
                acc += 0.5
            else:
                acc += 1.0
        score = acc / total if total else 0.0
        comps.append({"id": "controls", "label": "Controls enabled & enforcing", "weight": 35,
                      "score": round(score, 3), "value": f"{total - off - monitor}/{total} enforcing"
                      + (f", {monitor} monitor" if monitor else ""),
                      "status": "ok" if score >= 0.9 else "warn" if score >= 0.6 else "error"})
    else:
        comps.append({"id": "controls", "label": "Controls enabled & enforcing", "weight": 35,
                      "score": 0.0, "value": "no policy loaded", "status": "error"})
        findings.append({"severity": "critical", "message": "no policy snapshot available",
                         "control_id": None, "link": "/ui/governance/policy"})

    # self-tests (20) - from the primer cache; excluded when unknown
    if primer and primer.get("tests_total"):
        passed, total_t = int(primer.get("tests_passed", 0)), int(primer["tests_total"])
        s = passed / total_t
        comps.append({"id": "selftests", "label": "Inline policy tests passing", "weight": 20,
                      "score": round(s, 3), "value": f"{passed}/{total_t} passing",
                      "status": "ok" if s >= 0.95 else "warn" if s >= 0.8 else "error"})
        if passed < total_t:
            findings.append({"severity": "medium", "message": f"{total_t - passed} inline policy tests failing",
                             "control_id": None, "link": "/ui/security/coverage"})

    # feed (15)
    fstatus = "disabled"
    serial = None
    with contextlib.suppress(Exception):
        fs = rt.feed.status()
        fstatus, serial = fs.status, fs.serial
    fscore = FEED_SCORES.get(fstatus, 0.0)
    comps.append({"id": "feed", "label": "Threat feed freshness", "weight": 15, "score": fscore,
                  "value": f"{fstatus}" + (f" · serial {serial}" if serial is not None else ""),
                  "status": "ok" if fscore >= 0.9 else "warn" if fscore >= 0.4 else "off" if fstatus == "disabled" else "error"})
    if fstatus not in {"ok", "seed"}:
        findings.append({"severity": "medium" if fstatus != "rejected" else "high",
                         "message": f"threat feed {fstatus}", "control_id": None, "link": "/ui/security/threats"})

    # audit (15)
    lv = getattr(getattr(rt, "audit", None), "last_verify", None)
    if lv is None:
        comps.append({"id": "audit", "label": "Audit chain integrity", "weight": 15, "score": 1.0,
                      "value": "not verified yet", "status": "warn"})
    else:
        comps.append({"id": "audit", "label": "Audit chain integrity", "weight": 15,
                      "score": 1.0 if lv.ok else 0.0,
                      "value": f"chain OK ({lv.records} records)" if lv.ok else (lv.message or "broken"),
                      "status": "ok" if lv.ok else "error"})
        if not lv.ok:
            findings.append({"severity": "critical",
                             "message": f"audit chain broken at seq {lv.broken_at_seq}" if lv.broken_at_seq else (lv.message or "audit chain broken"),
                             "control_id": None, "link": "/ui/security/audit"})

    # models (10)
    sem = semantic_status(rt)
    mscore = 0.5 if sem.get("degraded") else 1.0
    comps.append({"id": "models", "label": "Detection models healthy", "weight": 10, "score": mscore,
                  "value": f"{sem.get('mode')}" + (" · degraded (heuristic fallback)" if sem.get("degraded") else ""),
                  "status": "ok" if mscore == 1.0 else "warn"})
    if sem.get("degraded"):
        findings.append({"severity": "low", "message": "semantic models degraded (heuristic fallback active)",
                         "control_id": None, "link": "/ui/system/health"})

    # governance (5)
    g = 0.0
    if snap is not None:
        g = 0.5 * bool(snap.doc.approvals.rules) + 0.5 * bool(snap.doc.budgets.limits)
    comps.append({"id": "governance", "label": "Approvals & budgets configured", "weight": 5, "score": g,
                  "value": "rules + limits" if g == 1.0 else "partial" if g else "not configured",
                  "status": "ok" if g == 1.0 else "warn"})

    wsum = sum(c["weight"] for c in comps)
    score = round(100 * sum(c["weight"] * c["score"] for c in comps) / wsum) if wsum else 0
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda f: sev_rank.get(f["severity"], 9))
    return {
        "generated_at": iso_z(),
        "score": score,
        "grade": _grade(score),
        "policy_version": policy_version,
        "feed_serial": serial,
        "components": comps,
        "findings": findings[:20],
    }


__all__ = ["TickState", "build_stats", "build_stats_tick", "control_rollup", "posture", "sql_stats"]
