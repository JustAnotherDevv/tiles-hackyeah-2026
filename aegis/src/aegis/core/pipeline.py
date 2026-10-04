"""The policy pipeline (`rt.pipeline`, CONTRACTS section 3.5 — every control relies on it).

`evaluate(ctx, interaction, policy=None, dry_run=False)`:
 1 snapshot pin · 2 select (registered ∩ policy, enabled, mode≠off, applies_to, scope) ·
 3 enrich (sequential) · 4 deterministic/stateful (sequential, per-control timeout; a task that
 already finished is always used) · 5 semantic/hybrid (concurrent; skipped after an enforce
 block) · 6 fail modes · 7 monitor mode · 8 combine (precedence, primary tie-break) ·
 9 approvals (pre-approved → allow; request; wait) · 10 transform (redactor.apply + mutations) ·
 11 record (WireView LRU, audit, metrics, bus `decision`).

Any internal error in the core path ⇒ fail-closed `block` by `AEGIS-CORE`.

`complete(ctx, interaction, verdict, outcome)` runs exactly once per request-direction
interaction: `on_complete` of every control that evaluated it, then upstream metrics.

ctx.state keys written here: `core.evaluated`, `core.completed`, `core.decision_id`,
`core.client` (set by `new_context`). Handlers set `core.outcome` before response hops.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from aegis.core.paths import glob_match
from aegis.core.policy_schema import ControlConfig, PolicySnapshot
from aegis.core.protocols import BaseControl
from aegis.core.sessions import resolve_session_id
from aegis.core.types import (
    ACTION_PRECEDENCE,
    ApprovalRequest,
    AuditEvent,
    ControlHit,
    Decision,
    DecisionDetail,
    DecisionSummary,
    Finding,
    Identity,
    Interaction,
    Outcome,
    Redaction,
    RequestContext,
    Source,
    TextSegment,
    Verdict,
    WireView,
    new_id,
)

log = logging.getLogger(__name__)

SECRET_HEADERS = frozenset(
    {"authorization", "x-api-key", "proxy-authorization", "cookie", "set-cookie",
     "x-aegis-agent-key", "x-aegis-key"}
)
DETERMINISTIC_KINDS = frozenset({"deterministic", "stateful"})
SEMANTIC_KINDS = frozenset({"semantic", "hybrid"})
ALLOWED_FINAL = frozenset({"allow", "log", "redact"})

WIRE_MAX = 500
WIRE_TTL_S = 3600.0
MAX_WAIT_S = 110.0  # Addendum A-19
MUTATION_ELIDE_LEN = 512  # Addendum A-10
CORE_CONTROL_ID = "AEGIS-CORE"
_WARN_EVERY_S = 30.0


def _is_claude_code(headers: Mapping[str, str]) -> bool:
    ua = headers.get("user-agent", "")
    return (ua.startswith("claude-cli") or headers.get("x-app", "") == "cli"
            or "x-claude-code-session-id" in headers)


def _when_ok(snap: PolicySnapshot, control_id: str, ctx: RequestContext, i: Interaction) -> bool:
    """Addendum A-14: optional `when` condition (policy-engine); missing module → True."""
    global _WHEN_FN
    if _WHEN_FN is None:
        try:
            from aegis.policy.conditions import control_when_ok  # type: ignore[import-not-found]

            _WHEN_FN = control_when_ok
        except Exception:
            _WHEN_FN = False
    if _WHEN_FN is False:
        return True
    try:
        return bool(_WHEN_FN(snap, control_id, ctx, i))
    except Exception:
        log.warning("when condition failed control=%s (treated as true)", control_id,
                    exc_info=True)
        return True


_WHEN_FN: Any = None


def elide_mutations(obj: Any) -> Any:
    """Addendum A-10: replace long `Mutation.value` strings in a dumped payload."""
    import hashlib

    def _el(value: Any) -> Any:
        if isinstance(value, str) and len(value) > MUTATION_ELIDE_LEN:
            return {"$elided": True,
                    "sha256": hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:16],
                    "len": len(value)}
        return value

    if isinstance(obj, dict):
        muts = obj.get("mutations")
        if isinstance(muts, list):
            for m in muts:
                if isinstance(m, dict) and "value" in m:
                    m["value"] = _el(m["value"])
        decs = obj.get("decisions")
        if isinstance(decs, list):
            for d in decs:
                if isinstance(d, dict):
                    elide_mutations(d)
    return obj


def _trace_id(headers: Mapping[str, str], fallback: str) -> str:
    tp = headers.get("traceparent", "")
    parts = tp.split("-")
    if len(parts) >= 3 and len(parts[1]) == 32:
        return parts[1]
    return headers.get("x-request-id") or fallback


def _overrides_enrich(control: Any) -> bool:
    if isinstance(control, BaseControl):
        return type(control).enrich is not BaseControl.enrich
    return callable(getattr(control, "enrich", None))


def _overrides_on_complete(control: Any) -> bool:
    if isinstance(control, BaseControl):
        return type(control).on_complete is not BaseControl.on_complete
    return callable(getattr(control, "on_complete", None))


def _scope_ok(cfg: ControlConfig, ident: Identity, i: Interaction) -> bool:
    sc = cfg.scope

    def _any(patterns: list[str], value: str | None) -> bool:
        if not patterns:
            return True
        return any(glob_match(p, value) for p in patterns)

    if not _any(sc.orgs, ident.org_id):
        return False
    if not _any(sc.teams, ident.team_id):
        return False
    if not _any(sc.members, ident.member_id):
        return False
    if not _any(sc.agents, ident.agent_id):
        return False
    if sc.kinds and i.kind not in sc.kinds:
        return False
    if sc.surfaces and i.surface not in sc.surfaces:
        return False
    return not (sc.destinations and i.destination.dest_class not in sc.destinations)


class _Run:
    """Per-evaluation bookkeeping."""

    __slots__ = ("cfg", "control", "priority")

    def __init__(self, control: Any, cfg: ControlConfig) -> None:
        self.control = control
        self.cfg = cfg
        try:
            self.priority = int(getattr(control, "priority", 100))
        except (TypeError, ValueError):
            self.priority = 100


class Pipeline:
    """Implements the `Pipeline` protocol (plus core-handler extras)."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt
        self._wire: OrderedDict[str, tuple[float, WireView]] = OrderedDict()
        self._audit_refs: OrderedDict[str, tuple[int, str]] = OrderedDict()
        self._last_warn: dict[str, float] = {}
        self.evaluations = 0

    # ================================================================ context
    def new_context(
        self,
        *,
        source: Source,
        identity: Identity,
        session_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        approval_token: str | None = None,
        wait_for_approval_s: float = 0.0,
        dry_run: bool = False,
        client_ip: str | None = None,
        body_session_hint: str | None = None,
    ) -> RequestContext:
        t0 = time.perf_counter()
        lower = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        safe = {k: v for k, v in lower.items() if k not in SECRET_HEADERS}
        request_id = new_id("req")
        sid = session_id or resolve_session_id(lower, body_session_hint, identity.principal)
        token = approval_token or lower.get("x-aegis-approval") or None
        wait = float(wait_for_approval_s or 0.0)
        if lower.get("x-aegis-wait"):  # explicit client value (incl. 0) wins (A-19)
            try:
                wait = float(lower["x-aegis-wait"])
            except ValueError:
                pass
        wait = max(0.0, min(MAX_WAIT_S, wait))
        ctx = RequestContext(
            request_id=request_id,
            trace_id=_trace_id(lower, request_id),
            session_id=sid,
            identity=identity,
            source=source,
            t0=t0,
            approval_token=token,
            wait_for_approval_s=wait,
            dry_run=dry_run,
            client_ip=client_ip,
            headers=safe,
        )
        if _is_claude_code(lower):
            ctx.state["core.client"] = "claude-code"
        try:
            snap = self.rt.policy.snapshot()
            ctx.policy = snap
            ctx.policy_version = int(snap.version)
        except Exception:
            log.exception("policy snapshot failed at ingress")
        ctx.feed_serial = self._feed_serial()
        try:
            touch = getattr(self.rt.sessions, "touch", None)
            if callable(touch):
                touch(sid, identity, source)
            else:
                self.rt.sessions.get(sid)
        except Exception:
            log.exception("session touch failed")
        return ctx

    def _feed_serial(self) -> int | None:
        try:
            return self.rt.feed.serial
        except Exception:
            return None

    # ================================================================ evaluate
    async def evaluate(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        *,
        policy: PolicySnapshot | None = None,
        dry_run: bool = False,
    ) -> Verdict:
        t_start = time.perf_counter()
        dry = bool(dry_run or ctx.dry_run)
        dec_id = new_id("dec")
        try:
            verdict = await self._evaluate(ctx, interaction, policy, dry, dec_id, t_start)
        except Exception:
            log.exception("pipeline internal error (fail-closed) surface=%s",
                          getattr(interaction, "surface", "?"))
            primary = Decision(
                action="block",
                control_id=CORE_CONTROL_ID,
                reason="internal error (fail-closed)",
                severity="high",
                degraded=True,
            )
            verdict = Verdict(
                id=dec_id,
                request_id=ctx.request_id,
                interaction_id=interaction.id or "",
                action="block",
                primary=primary,
                decisions=[primary],
                policy_version=ctx.policy_version,
                feed_serial=ctx.feed_serial,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                degraded=True,
                dry_run=dry,
            )
            if not dry:
                await self._record(ctx, interaction, verdict, [])
        return verdict

    async def _evaluate(
        self,
        ctx: RequestContext,
        i: Interaction,
        policy: PolicySnapshot | None,
        dry: bool,
        dec_id: str,
        t_start: float,
    ) -> Verdict:
        rt = self.rt
        self.evaluations += 1
        phases: dict[str, float] = {}

        # 1. snapshot ------------------------------------------------------------
        snap: PolicySnapshot = policy or ctx.policy or rt.policy.snapshot()
        ctx.policy = snap  # Addendum A-01: controls read policy only from ctx.policy
        ctx.policy_version = int(snap.version)
        if ctx.feed_serial is None:
            ctx.feed_serial = self._feed_serial()
        if not i.id:
            i.id = new_id("int")
        ctx.state["core.decision_id"] = dec_id

        # 2. select ----------------------------------------------------------------
        select_failed: list[tuple[_Run, str]] = []
        runs = self._select(snap, ctx, i, select_failed)
        if not dry:
            ctx.state.setdefault("core.evaluated", {})[i.id] = [(r.control, r.cfg) for r in runs]
        priority = {r.control.id: r.priority for r in runs}
        priority.update({r.control.id: r.priority for r, _ in select_failed})

        # 3. enrich ----------------------------------------------------------------
        t = time.perf_counter()
        enrich_failed: dict[str, str] = {}
        for r in runs:
            if not _overrides_enrich(r.control):
                continue
            try:
                timeout = max(r.cfg.timeout_ms, 1000) / 1000.0
                await asyncio.wait_for(r.control.enrich(ctx, i, r.cfg), timeout)
            except Exception as exc:
                # The control still evaluates (conservative); its decision is marked degraded.
                enrich_failed[r.control.id] = f"{type(exc).__name__}: {exc}"[:200]
                log.warning("enrich failed control=%s (evaluating degraded)", r.control.id,
                            exc_info=True)
        phases["enrich"] = time.perf_counter() - t

        # R2: a control whose applies_to raised is never silently skipped - it gets a
        # fail_mode decision (closed -> block, open/deterministic_only -> allow + degraded).
        decisions: list[Decision] = [self._select_fail_decision(r, err)
                                     for r, err in select_failed]

        # 4. deterministic ----------------------------------------------------------
        t = time.perf_counter()
        det_block = any(d.mode == "enforce" and d.action == "block" for d in decisions)
        for r in runs:
            if r.control.kind not in DETERMINISTIC_KINDS:
                continue
            d = await self._run_control(ctx, i, r, r.cfg.timeout_ms)
            if d is not None:
                decisions.append(d)
                if d.mode == "enforce" and d.action == "block":
                    det_block = True
        phases["deterministic"] = time.perf_counter() - t

        # 5. semantic ---------------------------------------------------------------
        t = time.perf_counter()
        sem_runs = [r for r in runs if r.control.kind in SEMANTIC_KINDS]
        skip_semantic = det_block and ctx.source != "selftest"  # A-09
        if sem_runs and not skip_semantic:
            default_ms = int(getattr(snap.doc.defaults, "semantic_timeout_ms", 400) or 400)
            coros = []
            for r in sem_runs:
                timeout_ms = (r.cfg.timeout_ms if "timeout_ms" in r.cfg.model_fields_set
                              else default_ms)
                coros.append(self._run_control(ctx, i, r, timeout_ms))
            for d in await asyncio.gather(*coros):
                if d is not None:
                    decisions.append(d)
        phases["semantic"] = time.perf_counter() - t
        if enrich_failed:
            for d in decisions:
                err = enrich_failed.get(d.control_id)
                if err is not None:
                    d.degraded = True
                    d.meta = {**(d.meta or {}), "enrich_error": err}

        # 8. combine ----------------------------------------------------------------
        final, primary = self._combine(decisions, priority)

        # 9. approvals --------------------------------------------------------------
        approval: ApprovalRequest | None = None
        t = time.perf_counter()
        if final == "require_approval" and not dry and primary is not None:
            approval, final, primary = await self._approvals(ctx, i, decisions, primary,
                                                             priority)
        phases["approvals"] = time.perf_counter() - t

        # 10. transform -------------------------------------------------------------
        t = time.perf_counter()
        segments: list[TextSegment] = []
        redactions: list[Redaction] = []
        mutations = []
        if final in ALLOWED_FINAL:
            enforce = [d for d in decisions if d.mode == "enforce"]
            spans: list[Finding] = [
                f
                for d in enforce
                if d.action == "redact"
                for f in d.findings
                if f.segment_index is not None and f.start is not None and f.end is not None
            ]
            if spans:
                try:
                    segments, redactions = rt.redactor.apply(ctx, list(i.segments), spans)
                except Exception:
                    log.exception("redactor.apply failed (fail-closed)")
                    primary = Decision(
                        action="block",
                        control_id=CORE_CONTROL_ID,
                        reason="redaction failed (fail-closed)",
                        severity="high",
                        degraded=True,
                    )
                    decisions.append(primary)
                    final = "block"
                    segments, redactions = [], []
            else:
                segments = list(i.segments)
            if final in ALLOWED_FINAL:
                for d in enforce:
                    if d.action in ("redact", "allow") and d.mutations:
                        mutations.extend(d.mutations)
        phases["transform"] = time.perf_counter() - t

        latency_ms = (time.perf_counter() - t_start) * 1000
        verdict = Verdict(
            id=dec_id,
            request_id=ctx.request_id,
            interaction_id=i.id,
            action=final,  # type: ignore[arg-type]
            primary=primary,
            decisions=decisions,
            segments=segments if final in ALLOWED_FINAL else [],
            redactions=redactions if final in ALLOWED_FINAL else [],
            mutations=mutations if final in ALLOWED_FINAL else [],
            approval=approval,
            policy_version=int(snap.version),
            feed_serial=ctx.feed_serial,
            latency_ms=latency_ms,
            degraded=any(d.degraded for d in decisions),
            dry_run=dry,
        )

        # timings ---------------------------------------------------------------------
        tm = ctx.timings
        tm["ctl"] = tm.get("ctl", 0.0) + latency_ms
        tm["pipeline"] = tm.get("pipeline", 0.0) + latency_ms

        # 11. record -----------------------------------------------------------------
        if not dry:
            t = time.perf_counter()
            await self._record(ctx, i, verdict, runs)
            phases["record"] = time.perf_counter() - t
            tm["record"] = tm.get("record", 0.0) + phases["record"] * 1000
        self._observe_phases(phases, latency_ms / 1000,
                             hop="response" if i.direction == "in" else "request")
        return verdict

    # ---------------------------------------------------------------- select
    def _select(self, snap: PolicySnapshot, ctx: RequestContext, i: Interaction,
                failed: list[tuple[_Run, str]] | None = None) -> list[_Run]:
        """Selected runs. Controls whose ``applies_to.matches`` raises (and that are otherwise
        in scope) go to ``failed`` with the error so the caller applies their fail_mode."""
        ident = ctx.identity
        runs: list[_Run] = []
        try:
            controls = list(self.rt.controls.all())
        except Exception:
            log.exception("control registry unavailable")
            controls = []
        for control in controls:
            cid = getattr(control, "id", None)
            if not cid:
                continue
            cfg = snap.controls.get(cid)
            if cfg is None or not cfg.enabled or cfg.mode == "off":
                continue
            try:
                if not control.applies_to.matches(i):
                    continue
            except Exception as exc:
                log.warning("applies_to failed control=%s (fail_mode=%s)", cid, cfg.fail_mode,
                            exc_info=True)
                if _scope_ok(cfg, ident, i) and _when_ok(snap, cid, ctx, i):
                    if failed is not None:
                        failed.append((_Run(control, cfg), f"{type(exc).__name__}: {exc}"))
                    ctx.state.setdefault("core.degraded_select", []).append(cid)
                continue
            if not _scope_ok(cfg, ident, i):
                continue
            if not _when_ok(snap, cid, ctx, i):
                continue
            runs.append(_Run(control, cfg))
        runs.sort(key=lambda r: (r.priority, r.control.id))
        return runs

    # ---------------------------------------------------------------- run one control
    async def _run_control(
        self, ctx: RequestContext, i: Interaction, r: _Run, timeout_ms: int | float
    ) -> Decision | None:
        control, cfg = r.control, r.cfg
        t = time.perf_counter()
        timeout = max(float(timeout_ms or 0), 1.0) / 1000.0
        task = asyncio.ensure_future(control.evaluate(ctx, i, cfg))
        error: str | None = None
        result: Any = None
        try:
            done, _ = await asyncio.wait({task}, timeout=timeout)
        except asyncio.CancelledError:
            task.cancel()
            raise
        elapsed_ms = (time.perf_counter() - t) * 1000
        key = f"ctl.{control.id}"
        ctx.timings[key] = ctx.timings.get(key, 0.0) + elapsed_ms
        ctx.state.setdefault("core.control_timings", []).append((control.id, elapsed_ms))
        if task in done:
            exc = (asyncio.CancelledError("control cancelled") if task.cancelled()
                   else task.exception())
            if exc is not None:
                error = f"{type(exc).__name__}: {exc}"
                log.warning("control raised id=%s error=%s", control.id, error,
                            exc_info=exc)
            else:
                result = task.result()
                if elapsed_ms > timeout * 1000:
                    self._warn_slow(control.id, elapsed_ms, timeout * 1000)
        else:
            task.cancel()
            error = f"timeout after {timeout * 1000:.0f} ms"
            log.warning("control timeout id=%s timeout_ms=%.0f", control.id, timeout * 1000)

        if error is not None:
            d = self._fail_decision(control, cfg, error)
        elif isinstance(result, Decision):
            d = result
        else:
            if result is not None:
                log.warning("control returned non-Decision id=%s type=%s", control.id,
                            type(result).__name__)
            # Addendum A-03: complete control trace (allow rows for silent controls)
            d = Decision(action="allow", control_id=control.id, meta={"no_finding": True})

        d.latency_ms = elapsed_ms
        if not d.control_id:
            d.control_id = control.id
        if not d.owasp:
            d.owasp = list(cfg.owasp or getattr(control, "owasp", []) or [])
        if cfg.mode == "monitor":
            d.mode = "monitor"
        return d

    def _fail_decision(self, control: Any, cfg: ControlConfig, error: str,
                       what: str = "unavailable") -> Decision:
        if cfg.fail_mode == "closed":
            return Decision(
                action="block",
                control_id=control.id,
                reason=f"{control.id} {what} (fail-closed)",
                severity=cfg.severity,
                degraded=True,
                meta={"error": error[:200]},
            )
        return Decision(
            action="allow",
            control_id=control.id,
            reason=f"{control.id} {what} (fail-open)",
            severity=cfg.severity,
            degraded=True,
            meta={"error": error[:200], "fail_mode": cfg.fail_mode},
        )

    def _select_fail_decision(self, r: _Run, error: str) -> Decision:
        """fail_mode decision for a control whose applies_to check raised (R2)."""
        control, cfg = r.control, r.cfg
        d = self._fail_decision(control, cfg, f"applies_to: {error}",
                                what="could not check whether it applies")
        d.meta["stage"] = "select"
        d.latency_ms = 0.0
        d.owasp = list(cfg.owasp or getattr(control, "owasp", []) or [])
        if cfg.mode == "monitor":
            d.mode = "monitor"
        return d

    def _warn_slow(self, cid: str, elapsed_ms: float, budget_ms: float) -> None:
        now = time.monotonic()
        if now - self._last_warn.get(cid, 0.0) >= _WARN_EVERY_S:
            self._last_warn[cid] = now
            log.warning("control over budget id=%s ms=%.1f budget_ms=%.0f (result used)",
                        cid, elapsed_ms, budget_ms)

    # ---------------------------------------------------------------- combine
    @staticmethod
    def _combine(
        decisions: list[Decision], priority: Mapping[str, int]
    ) -> tuple[str, Decision | None]:
        enforce = [d for d in decisions if d.mode == "enforce"]
        if not enforce:
            return "allow", None
        ranked = sorted(
            enforce,
            key=lambda d: (
                -ACTION_PRECEDENCE.get(d.action, 0),
                priority.get(d.control_id, 100),
                d.control_id,
            ),
        )
        primary = ranked[0]
        if primary.action == "allow":
            return "allow", None
        return primary.action, primary

    # ---------------------------------------------------------------- approvals
    async def _approvals(
        self,
        ctx: RequestContext,
        i: Interaction,
        decisions: list[Decision],
        primary: Decision,
        priority: Mapping[str, int],
    ) -> tuple[ApprovalRequest | None, str, Decision | None]:
        rt = self.rt

        def _grant(req: ApprovalRequest) -> tuple[str, Decision | None]:
            who = ", ".join(req.decided_by) or "auto-approval"
            for d in decisions:
                if d.mode == "enforce" and d.action == "require_approval":
                    d.action = "allow"
                    d.reason = f"approved by {who} ({req.id})"
                    d.approval_id = req.id
            final, new_primary = self._combine(decisions, priority)
            return final, new_primary

        try:
            pre = await rt.approvals.find_preapproved(ctx, i)
            if pre is not None:
                final, new_primary = _grant(pre)
                return pre, final, new_primary
            primary.meta["decision_id"] = ctx.state.get("core.decision_id")  # A-02
            req = await rt.approvals.request(ctx, i, primary)
            if req.status == "pending" and ctx.wait_for_approval_s > 0:
                try:
                    req = await rt.approvals.wait(req.id, ctx.wait_for_approval_s)
                except TimeoutError:
                    pass
            if req.status == "approved":
                final, new_primary = _grant(req)
                return req, final, new_primary
            if req.status in ("denied", "expired", "cancelled"):
                primary.action = "block"
                primary.reason = f"{primary.reason} — approval {req.status}".strip(" —")
                primary.approval_id = req.id
                final, new_primary = self._combine(decisions, priority)
                return req, final, new_primary
            primary.approval_id = req.id
            return req, "require_approval", primary
        except Exception:
            log.exception("approval service failed (fail-closed) control=%s", primary.control_id)
            primary.action = "block"
            primary.reason = f"{primary.reason} — approvals unavailable (fail-closed)".strip(" —")
            primary.degraded = True
            final, new_primary = self._combine(decisions, priority)
            return None, final, new_primary

    # ---------------------------------------------------------------- record
    def _observe_phases(self, phases: Mapping[str, float], total_s: float,
                        hop: str = "request") -> None:
        metrics = self.rt.metrics
        try:
            for phase, seconds in phases.items():
                metrics.observe_overhead(phase, seconds)
            metrics.observe_overhead(hop, total_s)  # A-03: "request" | "response"
        except Exception:
            log.debug("observe_overhead failed", exc_info=True)

    def _outcome_for(self, ctx: RequestContext, i: Interaction) -> Outcome | None:
        if i.direction != "in":
            return None
        outcome = ctx.state.get("core.outcome")
        return outcome if isinstance(outcome, Outcome) else None

    def _preview(self, i: Interaction, verdict: Verdict) -> str:
        """Masked preview: outbound text when allowed; masked original when blocked."""
        try:
            if verdict.action in ALLOWED_FINAL and verdict.segments:
                segs = verdict.segments
                text = next((s.text for s in reversed(segs) if s.role != "system"),
                            segs[-1].text)
            elif i.segments:
                idx = next((n for n in range(len(i.segments) - 1, -1, -1)
                            if i.segments[n].role != "system"), len(i.segments) - 1)
                text = i.segments[idx].text
                spans = sorted(
                    (f for d in verdict.decisions for f in d.findings
                     if f.segment_index == idx and f.start is not None and f.end is not None),
                    key=lambda f: f.start or 0, reverse=True)
                last_start = len(text) + 1
                for f in spans:
                    s, e = f.start or 0, f.end or 0
                    if e > last_start or s >= e:
                        continue
                    text = text[:s] + f"[{f.entity or f.category.upper()}]" + text[e:]
                    last_start = s
            else:
                return ""
            return self.rt.redactor.mask_for_log(text, 160)
        except Exception:
            log.debug("preview masking failed", exc_info=True)
            return ""

    def build_summary(
        self, ctx: RequestContext, i: Interaction, verdict: Verdict
    ) -> DecisionSummary:
        primary = verdict.primary
        outcome = self._outcome_for(ctx, i)
        entities = sorted(
            {r.entity for r in verdict.redactions if r.entity}
            | {f.entity for d in verdict.decisions for f in d.findings if f.entity}
        )
        hits = [
            ControlHit(
                control_id=d.control_id,
                action=d.action,
                mode=d.mode,
                score=d.score,
                latency_ms=round(d.latency_ms, 3),
                degraded=d.degraded,
            )
            for d in verdict.decisions
            if d.action != "allow" or d.degraded
        ]
        approval_id = (verdict.approval.id if verdict.approval else None) or (
            primary.approval_id if primary else None
        )
        tokens = None
        cost = None
        upstream_ms = None
        if outcome is not None:  # A-08: response hops carry upstream_ms only
            upstream_ms = outcome.upstream_ms
        return DecisionSummary(
            id=verdict.id,
            ts=verdict.ts,
            request_id=ctx.request_id,
            action=verdict.action,
            kind=i.kind,
            surface=i.surface,
            direction=i.direction,
            destination=i.destination,
            model=i.model,
            tool_name=i.tool_name,
            action_type=i.action_type,
            amount_usd=i.amount_usd,
            identity=ctx.identity,
            session_id=ctx.session_id,
            source=ctx.source,
            control_id=primary.control_id if primary else None,
            reason=primary.reason if primary else "",
            score=primary.score if primary else None,
            threshold=primary.threshold if primary else None,
            controls=hits,
            redaction_count=len(verdict.redactions),
            entities=entities,
            approval_id=approval_id,
            latency_ms=round(verdict.latency_ms, 3),
            upstream_ms=upstream_ms,
            policy_version=verdict.policy_version,
            feed_serial=verdict.feed_serial,
            degraded=verdict.degraded,
            cost_usd=cost,
            tokens=tokens,
            preview=self._preview(i, verdict),
            dry_run=verdict.dry_run,
        )

    async def _record(
        self, ctx: RequestContext, i: Interaction, verdict: Verdict, runs: list[_Run]
    ) -> DecisionSummary | None:
        rt = self.rt
        # WireView (in memory only)
        try:
            self._put_wire(WireView(decision_id=verdict.id, original=list(i.segments),
                                    outbound=list(verdict.segments)))
        except Exception:
            log.debug("wire view store failed", exc_info=True)
        try:
            summary = self.build_summary(ctx, i, verdict)
        except Exception:
            log.exception("decision summary build failed")
            return None
        # audit
        try:
            detail = DecisionDetail(
                **summary.model_dump(),
                decisions=verdict.decisions,
                redactions=verdict.redactions,
                mutations=verdict.mutations,
                usage=None,  # A-08: usage lives on the request hop (outcome record)
            )
            event = AuditEvent(
                event_type="decision",
                event_id=new_id("evt"),
                actor=ctx.identity,
                request_id=ctx.request_id,
                decision_id=verdict.id,
                session_id=ctx.session_id,
                trace_id=ctx.trace_id or None,
                kind=i.kind,
                surface=i.surface,
                direction=i.direction,
                destination=i.destination,
                model=i.model,
                tool_name=i.tool_name,
                action_type=i.action_type,
                amount_usd=i.amount_usd,
                resource=i.resource,
                action=verdict.action,
                control_id=summary.control_id,
                reason=summary.reason or None,
                score=summary.score,
                threshold=summary.threshold,
                controls=summary.controls,
                redactions=verdict.redactions,
                usage=None,
                latency_ms=round(verdict.latency_ms, 3),
                policy_version=verdict.policy_version,
                feed_serial=verdict.feed_serial,
                data={
                    "phase": "request" if i.direction == "out" else "response",
                    "summary": summary.model_dump(mode="json"),
                    "detail": elide_mutations(detail.model_dump(mode="json", exclude={"wire"})),
                },
            )
            recorded = await rt.audit.record(event)
            if recorded is not None and getattr(recorded, "seq", 0):
                self._audit_refs[verdict.id] = (recorded.seq, recorded.hash)
                while len(self._audit_refs) > WIRE_MAX:
                    self._audit_refs.popitem(last=False)
        except Exception:
            log.exception("audit record failed decision=%s", verdict.id)
        # metrics
        try:
            rt.metrics.observe_verdict(ctx, i, verdict)
        except Exception:
            log.exception("metrics observe_verdict failed")
        # live feed
        try:
            rt.bus.publish("decision", summary)
        except Exception:
            log.exception("bus publish failed")
        return summary

    # ================================================================ complete
    async def complete(
        self, ctx: RequestContext, interaction: Interaction, verdict: Verdict, outcome: Outcome
    ) -> None:
        """Exactly once per request-direction interaction: `on_complete` hooks, then the
        `outcome` audit record (Addendum A-08: usage + cost live on the request-hop decision)
        and upstream metrics."""
        done: set[str] = ctx.state.setdefault("core.completed", set())
        key = interaction.id or verdict.interaction_id
        if key in done:
            log.debug("complete called twice interaction=%s (ignored)", key)
            return
        done.add(key)
        rt = self.rt
        evaluated = ctx.state.get("core.evaluated", {}).get(key, [])
        for control, cfg in evaluated:
            if not _overrides_on_complete(control):
                continue
            try:
                await control.on_complete(ctx, interaction, verdict, outcome, cfg)
            except Exception:
                log.exception("on_complete failed control=%s", getattr(control, "id", "?"))
        usage = outcome.usage
        model = outcome.model_used or interaction.model
        if not usage.cost_usd and (usage.input_tokens or usage.output_tokens or usage.compute_s):
            try:
                usage.cost_usd = float(rt.ledger.price(model, usage))
            except Exception:
                log.debug("pricing failed model=%s", model, exc_info=True)
        if not (verdict.dry_run or ctx.dry_run):
            try:
                await rt.audit.record(AuditEvent(
                    event_type="decision",
                    event_id=new_id("evt"),
                    actor=ctx.identity,
                    request_id=ctx.request_id,
                    decision_id=verdict.id,
                    session_id=ctx.session_id,
                    trace_id=ctx.trace_id or None,
                    kind=interaction.kind,
                    surface=interaction.surface,
                    direction=interaction.direction,
                    destination=interaction.destination,
                    model=model,
                    tool_name=interaction.tool_name,
                    action=verdict.action,
                    usage=usage,
                    policy_version=verdict.policy_version,
                    feed_serial=verdict.feed_serial,
                    data={
                        "phase": "outcome",
                        "status_code": outcome.status_code,
                        "upstream_ms": outcome.upstream_ms,
                        "provider": outcome.provider,
                        "model_used": outcome.model_used,
                        "error": outcome.error,
                        "response_decision_id": outcome.response_verdict_id,
                    },
                ))
            except Exception:
                log.exception("outcome audit failed decision=%s", verdict.id)
        metrics = rt.metrics
        try:
            if outcome.upstream_ms is not None or outcome.provider:
                metrics.observe_upstream(
                    outcome.provider or "-",
                    model,
                    (outcome.upstream_ms or 0.0) / 1000.0,
                    usage,
                )
            metrics.observe_overhead("total", time.perf_counter() - ctx.t0)
        except Exception:
            log.debug("complete metrics failed", exc_info=True)

    def is_completed(self, ctx: RequestContext, interaction: Interaction) -> bool:
        return interaction.id in ctx.state.get("core.completed", set())

    async def record_only(
        self, ctx: RequestContext, interaction: Interaction, outcome: Outcome | None = None
    ) -> Verdict:
        """Allow verdict with no decisions (passthrough streams) so usage reaches audit + feed."""
        if not interaction.id:
            interaction.id = new_id("int")
        if outcome is not None:
            ctx.state["core.outcome"] = outcome
        verdict = Verdict(
            id=new_id("dec"),
            request_id=ctx.request_id,
            interaction_id=interaction.id,
            action="allow",
            segments=list(interaction.segments),
            policy_version=ctx.policy_version,
            feed_serial=ctx.feed_serial,
        )
        await self._record(ctx, interaction, verdict, [])
        return verdict

    # ================================================================ wire view LRU
    def _put_wire(self, view: WireView) -> None:
        now = time.monotonic()
        self._wire[view.decision_id] = (now, view)
        self._wire.move_to_end(view.decision_id)
        while len(self._wire) > WIRE_MAX:
            self._wire.popitem(last=False)
        # drop expired from the old end
        while self._wire:
            _k, (ts, _v) = next(iter(self._wire.items()))
            if now - ts <= WIRE_TTL_S:
                break
            self._wire.popitem(last=False)

    def wire(self, decision_id: str) -> WireView | None:
        item = self._wire.get(decision_id)
        if item is None:
            return None
        ts, view = item
        if time.monotonic() - ts > WIRE_TTL_S:
            self._wire.pop(decision_id, None)
            return None
        return view

    def attach_response(
        self, decision_id: str, *, response_raw: str | None, response_local: str | None
    ) -> None:
        view = self.wire(decision_id)
        if view is None:
            return
        view.response_raw = response_raw
        view.response_local = response_local

    def attach_request_preview(self, decision_id: str, preview: dict[str, Any]) -> None:
        view = self.wire(decision_id)
        if view is not None:
            view.upstream_request_preview = preview

    def audit_ref(self, decision_id: str) -> tuple[int, str] | None:
        """(audit seq, hash) of the decision's audit record, if still cached."""
        return self._audit_refs.get(decision_id)


def create(rt: Any) -> Pipeline:
    """Service factory (`rt.pipeline`)."""
    return Pipeline(rt)


__all__ = ["CORE_CONTROL_ID", "SECRET_HEADERS", "Pipeline", "create"]
