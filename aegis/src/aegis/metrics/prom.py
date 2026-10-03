"""Metrics service: `create(rt) -> MetricsService` implements `MetricsSink` (CONTRACTS 3.2/6.4).

Private `CollectorRegistry` per service (no duplicate-registration issues across app instances).
Metric names are exactly the CONTRACTS section 6.4 `aegis_*` set, plus audit extras
(`aegis_audit_records_total{event_type}`, `aegis_audit_errors_total`, `aegis_audit_chain_ok`).

Label guard: values that look like request/session/... ids or are longer than 80 chars become
`other`; each metric is capped at 500 label sets. Approval / policy / feed reload counters are
DERIVED from audit events (`on_audit_event`), so owners only write their audit events; direct
`inc()` calls on those names are ignored (no double counting).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
from collections.abc import Mapping
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from aegis.metrics.cost import estimate_avoided
from aegis.metrics.perf import PerfTracker

log = logging.getLogger(__name__)

OVERHEAD_BUCKETS = (0.0002, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
CONTROL_BUCKETS = (
    0.0001,
    0.0002,
    0.0005,
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
)
UPSTREAM_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)

_ID_LIKE = re.compile(r"^(req|dec|int|apr|evt|res|ses)_")
MAX_LABEL_SETS = 500
DERIVED = {"aegis_approvals_total", "aegis_policy_reloads_total", "aegis_feed_reloads_total"}


def guard_label(value: Any) -> str:
    s = "" if value is None else str(value)
    if _ID_LIKE.match(s) or len(s) > 80:
        return "other"
    return s or "none"


def _norm_name(name: str) -> str:
    n = name if name.startswith("aegis_") else f"aegis_{name}"
    return n


class MetricsService:
    """Prometheus registry + PerfTracker. All observe_* methods are cheap and never raise."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt
        self.registry = CollectorRegistry(auto_describe=True)
        self.perf = PerfTracker()
        self._lock = threading.Lock()
        self._label_sets: dict[str, set[tuple[str, ...]]] = {}
        self._dynamic: dict[str, Any] = {}
        self.outcome_seen = False  # R1 outcome audit events observed -> cost from them
        r = self.registry
        self.requests = Counter(
            "aegis_requests_total",
            "Pipeline evaluations by final action",
            ["surface", "source", "action"],
            registry=r,
        )
        self.decisions = Counter(
            "aegis_decisions_total",
            "Control decisions",
            ["control_id", "action", "mode"],
            registry=r,
        )
        self.control_duration = Histogram(
            "aegis_control_duration_seconds",
            "Control evaluation time",
            ["control_id", "kind"],
            buckets=CONTROL_BUCKETS,
            registry=r,
        )
        self.overhead = Histogram(
            "aegis_gateway_overhead_seconds",
            "Gateway overhead by phase",
            ["phase"],
            buckets=OVERHEAD_BUCKETS,
            registry=r,
        )
        self.upstream = Histogram(
            "aegis_upstream_duration_seconds",
            "Upstream call time",
            ["provider"],
            buckets=UPSTREAM_BUCKETS,
            registry=r,
        )
        self.tokens = Counter(
            "aegis_tokens_total",
            "Tokens by provider/model/type",
            ["provider", "model", "type"],
            registry=r,
        )
        self.cost = Counter(
            "aegis_cost_usd_total", "AI cost (USD)", ["team", "agent", "provider"], registry=r
        )
        self.cost_avoided = Counter(
            "aegis_cost_avoided_usd_total", "Estimated cost avoided (USD)", ["reason"], registry=r
        )
        self.redactions = Counter(
            "aegis_redactions_total",
            "Redactions by entity and destination",
            ["entity", "dest_class"],
            registry=r,
        )
        self.budget_util = Gauge(
            "aegis_budget_utilization_ratio",
            "Budget used / limit",
            ["scope_type", "scope", "dimension"],
            registry=r,
        )
        self.approvals = Counter(
            "aegis_approvals_total",
            "Approval lifecycle (derived from audit)",
            ["kind", "outcome"],
            registry=r,
        )
        self.approvals_pending = Gauge("aegis_approvals_pending", "Pending approvals", registry=r)
        self.signature_hits = Counter(
            "aegis_signature_hits_total", "Threat-feed signature hits", ["signature_id"], registry=r
        )
        self.loop_detections = Counter(
            "aegis_loop_detections_total", "Loop detections", ["detector"], registry=r
        )
        self.killswitch = Gauge("aegis_killswitch_active", "Active kill-switch scopes", registry=r)
        self.policy_version = Gauge("aegis_policy_version", "Applied policy version", registry=r)
        self.policy_reloads = Counter(
            "aegis_policy_reloads_total",
            "Policy reloads (derived from audit)",
            ["result"],
            registry=r,
        )
        self.feed_serial = Gauge("aegis_feed_serial", "Applied threat-feed serial", registry=r)
        self.feed_reloads = Counter(
            "aegis_feed_reloads_total", "Feed reloads (derived from audit)", ["result"], registry=r
        )
        self.semantic_degraded = Gauge(
            "aegis_semantic_degraded", "Semantic engine degraded (1/0)", registry=r
        )
        self.audit_records = Counter(
            "aegis_audit_records_total", "Audit records written", ["event_type"], registry=r
        )
        self.audit_errors = Counter("aegis_audit_errors_total", "Audit write failures", registry=r)
        self.audit_chain_ok = Gauge(
            "aegis_audit_chain_ok", "Last audit verify result (1 ok / 0 broken)", registry=r
        )
        self._families: dict[str, Any] = {
            "aegis_requests_total": self.requests,
            "aegis_decisions_total": self.decisions,
            "aegis_tokens_total": self.tokens,
            "aegis_cost_usd_total": self.cost,
            "aegis_cost_avoided_usd_total": self.cost_avoided,
            "aegis_redactions_total": self.redactions,
            "aegis_budget_utilization_ratio": self.budget_util,
            "aegis_approvals_pending": self.approvals_pending,
            "aegis_signature_hits_total": self.signature_hits,
            "aegis_loop_detections_total": self.loop_detections,
            "aegis_killswitch_active": self.killswitch,
            "aegis_policy_version": self.policy_version,
            "aegis_feed_serial": self.feed_serial,
            "aegis_semantic_degraded": self.semantic_degraded,
            "aegis_audit_records_total": self.audit_records,
            "aegis_audit_errors_total": self.audit_errors,
            "aegis_audit_chain_ok": self.audit_chain_ok,
        }

    # ------------------------------------------------------------------ helpers
    def _labels(self, metric: Any, name: str, values: list[Any]) -> Any:
        vals = tuple(guard_label(v) for v in values)
        with self._lock:
            seen = self._label_sets.setdefault(name, set())
            if vals not in seen:
                if len(seen) >= MAX_LABEL_SETS:
                    vals = tuple("other" for _ in vals)
                seen.add(vals)
        return metric.labels(*vals)

    def _control_kind(self, control_id: str) -> str:
        reg = getattr(self.rt, "controls", None)
        if reg is not None:
            try:
                c = reg.get(control_id)
                if c is not None:
                    return str(getattr(c, "kind", "deterministic"))
            except Exception:
                pass
        return "deterministic"

    # ------------------------------------------------------------------ MetricsSink
    def observe_verdict(self, ctx: Any, interaction: Any, verdict: Any) -> None:
        try:
            self._observe_verdict(ctx, interaction, verdict)
        except Exception:
            log.exception("observe_verdict failed")

    def _observe_verdict(self, ctx: Any, interaction: Any, verdict: Any) -> None:
        action = str(getattr(verdict, "action", "allow"))
        self._labels(
            self.requests,
            "requests",
            [
                getattr(interaction, "surface", None),
                getattr(ctx, "source", None),
                action,
            ],
        ).inc()
        self.observe_controls(ctx, verdict, primer=False)
        dest_class = getattr(getattr(interaction, "destination", None), "dest_class", None)
        for red in getattr(verdict, "redactions", None) or []:
            self._labels(self.redactions, "redactions", [red.entity, dest_class]).inc()
        for dec in getattr(verdict, "decisions", None) or []:
            for f in getattr(dec, "findings", None) or []:
                cat = getattr(f, "category", None)
                if cat == "signature":
                    sid = (getattr(f, "meta", None) or {}).get("signature_id") or f.detector
                    self._labels(self.signature_hits, "sig", [sid]).inc()
                elif cat == "loop":
                    self._labels(self.loop_detections, "loop", [f.detector]).inc()
        lat = float(getattr(verdict, "latency_ms", 0.0) or 0.0)
        if lat > 0:
            self.overhead.labels("pipeline").observe(lat / 1000.0)
            self.perf.add_overhead("pipeline", lat)
        self.perf.add_decision(action)
        usd, reason = estimate_avoided(self.rt, interaction, verdict)
        if usd > 0 and reason:
            self._labels(self.cost_avoided, "avoided", [reason]).inc(usd)
            audit = getattr(self.rt, "audit", None)
            annotate = getattr(audit, "annotate", None)
            if annotate is not None and getattr(verdict, "id", None):
                with contextlib.suppress(Exception):
                    annotate(verdict.id, cost_avoided_usd=usd, avoided_reason=reason)

    def observe_controls(self, ctx: Any, verdict: Any, *, primer: bool = True) -> int:
        """Per-control latency: ctx.timings["ctl.<ID>"] (R2) else decision.latency_ms."""
        n = 0
        timings: Mapping[str, float] = getattr(ctx, "timings", None) or {}
        seen: set[str] = set()
        for key, ms in timings.items():
            if not key.startswith("ctl."):
                continue
            cid = key[4:]
            seen.add(cid)
            self._observe_control(cid, float(ms))
            n += 1
        for dec in getattr(verdict, "decisions", None) or []:
            cid = getattr(dec, "control_id", None)
            if not cid:
                continue
            if not primer:
                self._labels(self.decisions, "decisions", [cid, dec.action, dec.mode]).inc()
            if cid not in seen:
                seen.add(cid)
                self._observe_control(cid, float(getattr(dec, "latency_ms", 0.0) or 0.0))
                n += 1
        if primer:
            self.perf.primer_samples += n
        return n

    def _observe_control(self, cid: str, ms: float) -> None:
        kind = self._control_kind(cid)
        self._labels(self.control_duration, "ctl", [cid, kind]).observe(max(ms, 0.0) / 1000.0)
        self.perf.add_control(cid, max(ms, 0.0), kind)

    def observe_upstream(
        self, provider: str, model: str | None, seconds: float, usage: Any = None
    ) -> None:
        try:
            self._labels(self.upstream, "upstream", [provider]).observe(max(float(seconds), 0.0))
            self.perf.add_upstream(provider, model, float(seconds) * 1000.0)
            if usage is not None:
                for typ, attr in (
                    ("input", "input_tokens"),
                    ("output", "output_tokens"),
                    ("cache_read", "cache_read_tokens"),
                    ("cache_write", "cache_write_tokens"),
                ):
                    v = int(getattr(usage, attr, 0) or 0)
                    if v:
                        self._labels(self.tokens, "tokens", [provider, model, typ]).inc(v)
                cost = float(getattr(usage, "cost_usd", 0.0) or 0.0)
                if cost > 0 and not self.outcome_seen:
                    self._labels(self.cost, "cost", ["unknown", "unknown", provider]).inc(cost)
        except Exception:
            log.exception("observe_upstream failed")

    def observe_overhead(self, phase: str, seconds: float) -> None:
        try:
            self._labels(self.overhead, "overhead", [phase]).observe(max(float(seconds), 0.0))
            self.perf.add_overhead(str(phase), float(seconds) * 1000.0)
        except Exception:
            log.exception("observe_overhead failed")

    def inc(self, name: str, labels: Mapping[str, str] | None = None, value: float = 1.0) -> None:
        try:
            n = _norm_name(name)
            if not n.endswith("_total") and n + "_total" in self._families | {
                d: None for d in DERIVED
            }:
                n += "_total"
            if n in DERIVED:
                log.debug("derived counter %s ignored (derived from audit events)", n)
                return
            metric = self._families.get(n) or self._dynamic_metric(n, "counter", labels)
            if not isinstance(metric, Counter):
                return
            self._apply(metric, n, labels).inc(value)
        except Exception:
            log.debug("metrics inc failed name=%s", name, exc_info=True)

    def set_gauge(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        try:
            n = _norm_name(name)
            metric = self._families.get(n) or self._dynamic_metric(n, "gauge", labels)
            if not isinstance(metric, Gauge):
                return
            self._apply(metric, n, labels).set(value)
        except Exception:
            log.debug("metrics set_gauge failed name=%s", name, exc_info=True)

    def _apply(self, metric: Any, name: str, labels: Mapping[str, str] | None) -> Any:
        names = list(getattr(metric, "_labelnames", ()) or ())
        if not names:
            return metric
        lab = labels or {}
        return self._labels(metric, name, [lab.get(k) for k in names])

    def _dynamic_metric(self, name: str, typ: str, labels: Mapping[str, str] | None) -> Any:
        with self._lock:
            m = self._dynamic.get(name)
            if m is not None:
                return m
            label_names = sorted((labels or {}).keys())
            base = name[:-6] if typ == "counter" and name.endswith("_total") else name
            try:
                if typ == "counter":
                    m = Counter(base, f"{name} (dynamic)", label_names, registry=self.registry)
                else:
                    m = Gauge(name, f"{name} (dynamic)", label_names, registry=self.registry)
            except ValueError:
                return None
            self._dynamic[name] = m
            return m

    def render(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST

    # ------------------------------------------------------------------ derived from audit
    def on_audit_event(self, rec: dict[str, Any]) -> None:
        try:
            et = str(rec.get("event_type") or "")
            self._labels(self.audit_records, "audit", [et]).inc()
            data = rec.get("data") or {}
            if et.startswith("approval."):
                appr = data.get("approval") if isinstance(data.get("approval"), dict) else {}
                kind = (
                    data.get("approval_kind")
                    or appr.get("kind")
                    or (
                        data.get("kind")
                        if data.get("kind")
                        in {"action", "config_change", "budget_raise", "mcp_pin"}
                        else None
                    )
                    or "action"
                )
                if et == "approval.created":
                    outcome = "requested"
                elif et == "approval.decided":
                    outcome = str(
                        data.get("status") or appr.get("status") or rec.get("action") or "decided"
                    )
                    outcome = {"allow": "approved", "block": "denied"}.get(outcome, outcome)
                else:
                    outcome = et.split(".", 1)[1]
                self._labels(self.approvals, "approvals", [kind, outcome]).inc()
            elif et.startswith("policy."):
                result = {
                    "policy.applied": "ok",
                    "policy.rejected": "rejected",
                    "policy.rollback": "rollback",
                }.get(et, et)
                self._labels(self.policy_reloads, "policy", [result]).inc()
                ver = data.get("version") or rec.get("policy_version")
                if et != "policy.rejected" and isinstance(ver, int):
                    self.policy_version.set(ver)
            elif et.startswith("feed."):
                result = "ok" if et == "feed.updated" else "rejected"
                self._labels(self.feed_reloads, "feed", [result]).inc()
                serial = data.get("serial") or rec.get("feed_serial")
                if et == "feed.updated" and isinstance(serial, int):
                    self.feed_serial.set(serial)
            elif et == "decision" and data.get("phase") == "outcome":
                self.outcome_seen = True
                usage = rec.get("usage") or {}
                cost = float(usage.get("cost_usd") or 0.0)
                if cost > 0:
                    actor = rec.get("actor") or {}
                    provider = (
                        data.get("provider")
                        or (rec.get("destination") or {}).get("provider")
                        or "unknown"
                    )
                    self._labels(
                        self.cost,
                        "cost",
                        [
                            actor.get("team_id") or "unknown",
                            actor.get("agent_id") or actor.get("member_id") or "unknown",
                            provider,
                        ],
                    ).inc(cost)
        except Exception:
            log.debug("on_audit_event failed", exc_info=True)

    # ------------------------------------------------------------------ scrape-time gauges
    async def refresh_gauges(self, rt: Any | None = None, timeout_s: float = 0.25) -> None:
        rt = rt or self.rt

        async def _guard(coro: Any) -> Any:
            try:
                return await asyncio.wait_for(coro, timeout_s)
            except Exception:
                return None

        approvals = getattr(rt, "approvals", None)
        if approvals is not None:
            items = await _guard(approvals.list_requests(status="pending"))
            if items is not None:
                self.approvals_pending.set(len(items))
        try:
            snap = rt.policy.snapshot()
            self.policy_version.set(int(snap.version))
            ks = snap.doc.budgets.kill_switch
            self.killswitch.set(
                int(bool(ks.global_))
                + len(ks.teams)
                + len(ks.members)
                + len(ks.agents)
                + len(ks.sessions)
            )
        except Exception:
            pass
        try:
            serial = rt.feed.serial
            if serial is not None:
                self.feed_serial.set(int(serial))
        except Exception:
            pass
        try:
            self.semantic_degraded.set(1.0 if (rt.semantic.status() or {}).get("degraded") else 0.0)
        except Exception:
            pass
        ledger = getattr(rt, "ledger", None)
        if ledger is not None:
            statuses = await _guard(ledger.status())
            best: dict[tuple[str, str, str], float] = {}
            for st in statuses or []:
                try:
                    if st.scope_type not in {"org", "team", "member", "agent"} or not st.limit:
                        continue
                    key = (st.scope_type, st.scope, st.dimension)
                    ratio = (float(st.used) + float(st.reserved)) / float(st.limit)
                    best[key] = max(best.get(key, 0.0), ratio)
                except Exception:
                    continue
            for (stype, scope, dim), ratio in best.items():
                self._labels(self.budget_util, "budget", [stype, scope, dim]).set(round(ratio, 4))


def create(rt: Any) -> MetricsService:
    """Factory used by core-gateway's Runtime (`aegis.metrics.prom:create`). Cheap, no I/O."""
    return MetricsService(rt)


__all__ = ["MetricsService", "create", "guard_label"]
