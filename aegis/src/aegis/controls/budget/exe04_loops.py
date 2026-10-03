"""EXE-04 - Loop / rate / circuit breaker / kill switch (priority 10). Owner: budgets-ledger.

Order (first hit returns): self-test -> None · kill switch (policy ∪ runtime) -> 429 `killed`
(Retry-After 3600, x-should-retry false; never 403, Addendum A-07) · session killed by the
ladder · tool cooldown -> 429 · rate (sliding 60 s per principal) -> 429 + Retry-After ·
burn-rate spike -> 429 · session step cap -> 402 · loop detectors -> ladder
(tool_error -> block -> kill) · record the pending fingerprint (not in dry-run).
"""

from __future__ import annotations

import logging
import math
from fnmatch import fnmatchcase
from typing import Any

from aegis.budgets import killswitch as ks_mod
from aegis.budgets import loops as loops_mod
from aegis.budgets.events import inc, publish, spawn
from aegis.budgets.ledger import Ledger
from aegis.budgets.schemas import Exe04Params, parse_params
from aegis.budgets.stop import hard_stop
from aegis.budgets.windows import monotonic
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import (
    AppliesTo,
    Decision,
    Finding,
    Interaction,
    Outcome,
    RequestContext,
    Verdict,
)

from . import _common

log = logging.getLogger(__name__)

TOOL_SURFACES = {"tool.input", "mcp.call", "egress.request", "mcp.init", "a2a.message"}
MODEL_SURFACES = {"model.request"}
PENDING_KEY = "exe04.pending"
DETECTOR_IDS = {
    "exact_repeat": "LOOP-001",
    "short_cycle": "LOOP-002",
    "error_streak": "LOOP-004",
    "model_repeat": "LOOP-005",
    "burn_rate": "LOOP-006",
}


class LoopBreakerControl(BaseControl):
    id = "EXE-04"
    family = "EXE"
    name = "Loop / rate / circuit breaker / kill switch"
    kind = "stateful"
    priority = 10
    applies_to = AppliesTo(
        surfaces={
            "prompt.user",
            "model.request",
            "model.admin",
            "tool.input",
            "mcp.init",
            "mcp.call",
            "egress.request",
            "a2a.message",
        },
        directions={"out"},
    )
    owasp = ["ASI08", "ASI10", "LLM06:2026"]

    # ------------------------------------------------------------ helpers
    def _stop(
        self,
        cfg: ControlConfig,
        kind: str,
        ctx: RequestContext,
        params: Exe04Params,
        reason: str,
        *,
        retry_after_s: int | None = None,
        detector: str | None = None,
        meta: dict[str, Any] | None = None,
        findings: list[Finding] | None = None,
    ) -> Decision:
        stop = hard_stop(kind, ctx, params, retry_after_s=retry_after_s)
        m = dict(meta or {})
        m["response_headers"] = dict(stop.headers)
        m["stop"] = kind
        f = findings or [
            Finding(
                control_id=self.id,
                category="loop",
                detector=detector or f"loop.{kind}",
                severity="high",
                meta={k: v for k, v in m.items() if k != "response_headers"},
            )
        ]
        return self.decide(cfg, action="block", reason=reason, findings=f, meta=m, **stop.kwargs())

    @staticmethod
    def _overrides(params: Exe04Params, agent_id: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if agent_id:
            for glob, ov in (params.agent_overrides or {}).items():
                if fnmatchcase(agent_id, glob) and isinstance(ov, dict):
                    out.update(ov)
        return out

    @staticmethod
    def _accounted_elsewhere(i: Interaction, snap: Any) -> bool:
        """A-36: a hook tool.input for an MCP server routed via the proxy is counted there."""
        try:
            return bool(
                i.surface == "tool.input" and i.mcp_server and i.mcp_server in snap.doc.mcp.servers
            )
        except Exception:
            return False

    # ------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        if ctx.source == "selftest":
            return None  # A-09: self-tests ignore kill switch, loop and rate state
        led = _common.ledger()
        if led is None:
            return None
        params = parse_params(Exe04Params, cfg.params)
        snap = _common.snapshot(ctx)
        budgets = snap.doc.budgets
        i = interaction
        ident = ctx.identity
        sid = ctx.session_id
        dry = ctx.dry_run
        is_tool = i.surface in TOOL_SURFACES
        is_model = i.surface in MODEL_SURFACES

        # 1. kill switch (policy) and 2. runtime kills (loop ladder)
        killed = ks_mod.match(budgets.kill_switch, ident, sid)
        if killed:
            return self._stop(
                cfg,
                "killed",
                ctx,
                params,
                f"Aegis: {killed} stopped by the kill switch. Do not retry.",
                detector="killswitch",
                meta={"scope": killed},
            )
        rk = led.kills.get(sid)
        if rk is not None:
            return self._stop(
                cfg,
                "killed",
                ctx,
                params,
                f"Aegis: session {sid} killed ({rk.reason}). Do not retry.",
                detector="killswitch.runtime",
                meta={"scope": rk.scope},
            )

        loops = budgets.loops
        ov = self._overrides(params, ident.agent_id)
        window = int(ov.get("window", loops.window))
        st = led.loops.peek(sid) if dry else led.loops.get(sid, window)
        now = monotonic()

        # 3. tool cooldown (ladder step 2)
        if is_tool and st is not None and st.blocked_until > now:
            left = max(1, math.ceil(st.blocked_until - now))
            return self._stop(
                cfg,
                "cooldown",
                ctx,
                params,
                f"Aegis: tool calls paused for {left}s after a repeated-call loop. "
                "Change approach or finish.",
                retry_after_s=left,
                detector="loop.cooldown",
                meta={"scope": f"session:{sid}", "cooldown_s": left},
            )

        # 4. rate limits (sliding 60 s per principal)
        limit = None
        kind = ""
        if is_model:
            limit, kind = budgets.rate.requests_per_min, "requests"
        elif is_tool and not self._accounted_elsewhere(i, snap):
            limit, kind = budgets.rate.tool_calls_per_min, "tool_calls"
        if limit:
            ok, retry = led.rates.hit((ident.principal, kind), int(limit), record=not dry)
            if not ok:
                retry = min(60, retry)
                if not dry:
                    led.enforcement.record(
                        "throttle", ident.principal, self.id, f"{kind} per minute > {limit}"
                    )
                return self._stop(
                    cfg,
                    "rate",
                    ctx,
                    params,
                    f"Aegis: rate limit {limit} {kind}/min for {ident.principal}. "
                    f"Retry in {retry}s.",
                    retry_after_s=retry,
                    detector=f"rate.{kind}",
                    meta={"scope": ident.principal, "limit": limit},
                )

        # 5. burn-rate spike (LOOP-006)
        if is_model:
            br = params.burn_rate
            spiking, fast, base = led.burn.spiking(ident.principal, br.factor, br.floor_usd_per_min)
            if spiking:
                if not dry:
                    led.enforcement.record(
                        "throttle",
                        ident.principal,
                        self.id,
                        f"burn rate {fast:.3f} $/min > {br.factor}x baseline",
                        detector="LOOP-006",
                    )
                    inc(led.rt, "aegis_loop_detections_total", {"detector": "burn_rate"})
                return self._stop(
                    cfg,
                    "rate",
                    ctx,
                    params,
                    f"Aegis: spend rate spike ({fast:.2f} $/min vs baseline "
                    f"{base:.2f}). Slow down.",
                    retry_after_s=br.throttle_s,
                    detector="loop.burn_rate",
                    meta={
                        "scope": ident.principal,
                        "fast_usd_per_min": fast,
                        "baseline_usd_per_min": base,
                    },
                )

        # 6. session step cap
        if is_model and loops.max_steps_per_session:
            steps = led.session_usage(sid).get("requests", 0.0)
            if steps >= loops.max_steps_per_session:
                if not dry:
                    led.enforcement.record(
                        "step_cap", f"session:{sid}", self.id, f"{int(steps)} model calls"
                    )
                return self._stop(
                    cfg,
                    "step_cap",
                    ctx,
                    params,
                    f"Aegis: session:{sid} step cap reached "
                    f"({int(steps)}/{loops.max_steps_per_session} model calls). "
                    "Stop and summarise progress.",
                    detector="loop.step_cap",
                    meta={"scope": f"session:{sid}", "steps": steps},
                )

        # 7. loop detectors
        if not (is_tool or is_model):
            return None
        if is_tool and i.tool_name in set(params.repeat_exempt_tools or ()):
            return None
        fp = loops_mod.fingerprint(i, params.volatile_keys)
        if st is not None:
            trip = self._detect(st, fp, is_model, loops, params, ov)
            if trip is not None:
                return await self._ladder(cfg, ctx, i, params, led, st, trip, dry, snap)
        if not dry:
            ctx.state.setdefault(PENDING_KEY, {})[_common.ikey(i)] = (fp, is_model)
        return None

    def _detect(
        self,
        st: loops_mod.LoopState,
        fp: str,
        is_model: bool,
        loops: Any,
        params: Exe04Params,
        ov: dict[str, Any],
    ) -> tuple[str, int, int] | None:
        """(detector, count, window) or None."""
        window = st.window
        if st.error_streak >= int(ov.get("error_streak", loops.error_streak) or 0) > 0:
            return "error_streak", st.error_streak, window
        if is_model:
            n = loops_mod.exact_repeat(
                st.model_hist, fp, int(ov.get("model_repeat", params.model_repeat))
            )
            return ("model_repeat", n, window) if n else None
        n = loops_mod.exact_repeat(st.tool_hist, fp, int(ov.get("repeat", loops.repeat)))
        if n:
            return "exact_repeat", n, window
        p = loops_mod.short_cycle(st.tool_hist, fp, int(ov.get("cycle_k", loops.cycle_k)))
        if p:
            return "short_cycle", p * int(ov.get("cycle_k", loops.cycle_k)), window
        return None

    async def _ladder(
        self,
        cfg: ControlConfig,
        ctx: RequestContext,
        i: Interaction,
        params: Exe04Params,
        led: Ledger,
        st: loops_mod.LoopState,
        trip: tuple[str, int, int],
        dry: bool,
        snap: Any,
    ) -> Decision:
        detector, count, window = trip
        ladder = list(snap.doc.budgets.loops.ladder or ["tool_error", "block", "kill"])
        step = ladder[min(st.trips, len(ladder) - 1)]
        sid = ctx.session_id
        what = i.tool_name or (f"model {i.model}" if i.model else i.surface)
        det_id = DETECTOR_IDS.get(detector, detector)
        label = f"{det_id} {detector}"
        meta = {
            "detector": detector,
            "count": count,
            "window": window,
            "trip": st.trips + 1,
            "step": step,
            "scope": f"session:{sid}",
            "tool": what,
        }
        finding = Finding(
            control_id=self.id,
            category="loop",
            detector=f"loop.{detector}",
            severity="high",
            meta={k: v for k, v in meta.items()},
        )
        if not dry:
            st.trips += 1
            if detector == "error_streak":
                st.error_streak = 0
            inc(led.rt, "aegis_loop_detections_total", {"detector": detector})
            led.enforcement.record(
                "loop_detection",
                f"session:{sid}",
                self.id,
                f"{label}: {what} x{count} -> {step}",
                detector=det_id,
            )
        if detector == "error_streak":
            reason = (
                f"Aegis loop detected ({label}): {count} failed or blocked calls in a row. "
                "Change approach or finish."
            )
        else:
            reason = params.tool_error_message.format_map(
                _Safe(detector=label, tool=what, count=count, window=window)
            )
        if step == "tool_error":
            return self.decide(cfg, action="block", reason=reason, findings=[finding], meta=meta)
        if step == "block":
            cooldown = max(1, int(params.cooldown_s))
            if not dry:
                st.blocked_until = monotonic() + cooldown
                led.enforcement.record(
                    "cooldown", f"session:{sid}", self.id, f"tool calls paused {cooldown}s"
                )
            return self._stop(
                cfg,
                "cooldown",
                ctx,
                params,
                f"{reason} Tool calls paused for {cooldown}s.",
                retry_after_s=cooldown,
                findings=[finding],
                meta={**meta, "cooldown_s": cooldown},
            )
        # kill
        kill_reason = f"loop ladder: {label} on {what}"
        if not dry:
            st.killed = True
            st.kill_reason = kill_reason
            led.kills.add(sid, kill_reason, params.kill_runtime_ttl_s)
            led.enforcement.record("kill", f"session:{sid}", self.id, kill_reason, detector=det_id)
            led.announce_kill(f"session:{sid}", True, reason=kill_reason)
            spawn(_persist_kill(led, sid, kill_reason))
        return self._stop(
            cfg,
            "killed",
            ctx,
            params,
            f"Aegis: session {sid} killed after repeated loops ({label}). Do not retry.",
            findings=[finding],
            meta=meta,
        )

    # ------------------------------------------------------------ on_complete
    async def on_complete(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        verdict: Verdict,
        outcome: Outcome,
        cfg: ControlConfig,
    ) -> None:
        if ctx.dry_run or ctx.source == "selftest":
            return
        led = _common.ledger()
        if led is None:
            return
        params = parse_params(Exe04Params, cfg.params)
        pend = ctx.state.get(PENDING_KEY, {}).pop(_common.ikey(interaction), None)
        st = led.loops.peek(ctx.session_id)
        if st is None:
            return
        if _common.executed(verdict, outcome):
            if pend is not None:
                fp, is_model = pend
                if not led.loops.is_duplicate(
                    ctx.identity.principal, fp, ctx.source, params.dedupe_s
                ):
                    (st.model_hist if is_model else st.tool_hist).append(fp)
            if outcome.error:
                st.error_streak += 1
            else:
                st.error_streak = 0
            return
        by_us = any(d.control_id == self.id and d.action == "block" for d in verdict.decisions)
        stop = verdict.primary is not None and (
            verdict.primary.http_status in (402, 429)
            or verdict.primary.error_type in ("budget_exceeded", "rate_limited", "killed")
        )
        if by_us or stop or verdict.action == "require_approval":
            return  # our own blocks, budget/rate stops and pending approvals never count
        st.error_streak += 1


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


async def _persist_kill(led: Ledger, session_id: str, reason: str) -> None:
    """A-36: persist a ladder kill via rt.policy.apply_patch (source="budgets-ledger")."""
    rt = led.rt
    pol = getattr(rt, "policy", None)
    if pol is None:
        return
    try:
        patch = ks_mod.toggle_patch(pol.snapshot(), f"session:{session_id}", True)
        if not patch:
            return
        res = await pol.apply_patch(patch, actor=None, source="budgets-ledger", reason=reason)
        status = getattr(res, "status", "?")
        if status not in ("applied", "noop"):
            raise RuntimeError(f"apply_patch status={status} {getattr(res, 'message', '')}")
    except Exception as exc:
        log.warning("kill persistence failed session=%s error=%s", session_id, exc)
        publish(
            rt,
            "system",
            {
                "level": "warning",
                "component": "budgets",
                "message": f"session {session_id} killed in memory only (persist failed: {exc})",
            },
        )


CONTROLS = [LoopBreakerControl()]
