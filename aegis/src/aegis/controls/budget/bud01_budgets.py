"""BUD-01 - Token & cost budgets (remote + local, spend). Owner: budgets-ledger.

evaluate: estimate usage -> clamp max_tokens (Mutation) -> atomic reserve across the scope chain
(org -> team -> member|agent -> session + model:/tool:) -> hard limit: 402 `budget_exceeded` |
`budget_raise` approval draft | usd downgrade; soft threshold: warn | downgrade (route
mutation) | approval. on_complete: price the actual usage (fills `outcome.usage.cost_usd`) and
settle / commit / release.
"""

from __future__ import annotations

import logging
from typing import Any

from aegis.budgets import ladder
from aegis.budgets.events import audit_event, inc, spawn
from aegis.budgets.ledger import Check, Ledger
from aegis.budgets.pricing import normalize_model
from aegis.budgets.schemas import Bud01Params, parse_params
from aegis.budgets.tokens import estimate_tokens
from aegis.budgets.windows import monotonic
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import (
    AppliesTo,
    BudgetDenial,
    Decision,
    Finding,
    Interaction,
    Mutation,
    Outcome,
    RequestContext,
    Reservation,
    Usage,
    Verdict,
)

from . import _common

log = logging.getLogger(__name__)

TOOL_SURFACES = {"tool.input", "mcp.call", "egress.request"}
STATE_KEY = "bud.reservations"


def wire_path(interaction: Interaction) -> str:
    """Body path of the max-output-tokens field for this wire (Addendum A-13 meta.wire)."""
    raw = interaction.raw if isinstance(interaction.raw, dict) else {}
    wire = str(interaction.meta.get("wire") or "")
    if wire == "ollama" or (not wire and isinstance(raw.get("options"), dict)):
        return "options.num_predict"
    if "max_completion_tokens" in raw:
        return "max_completion_tokens"
    return "max_tokens"


def thinking_budget(interaction: Interaction) -> int | None:
    raw = interaction.raw if isinstance(interaction.raw, dict) else {}
    th = raw.get("thinking")
    if isinstance(th, dict) and th.get("budget_tokens"):
        try:
            return int(th["budget_tokens"])
        except (TypeError, ValueError):
            return None
    return None


class BudgetsControl(BaseControl):
    id = "BUD-01"
    family = "BUD"
    name = "Token & cost budgets (remote + local, spend)"
    kind = "deterministic"
    priority = 90
    applies_to = AppliesTo(
        surfaces={"model.request", "tool.input", "mcp.call", "egress.request"},
        directions={"out"},
    )
    owasp = ["LLM06:2026", "ASI08", "ASI10"]

    # ------------------------------------------------------------ estimate
    def _estimate(
        self,
        ctx: RequestContext,
        i: Interaction,
        params: Bud01Params,
        snap: Any,
        led: Ledger,
        model: str | None = None,
    ) -> tuple[Usage, list[Mutation]]:
        model = model or i.model
        mutations: list[Mutation] = []
        in_tok = int(i.est_input_tokens or estimate_tokens(i.text(), model))
        asked = i.max_output_tokens
        out_tok = min(int(asked or params.default_output_tokens), params.reserve_max_output_tokens)
        clamp_to = None
        try:
            clamp_to = snap.doc.budgets.defaults.max_output_tokens
        except Exception:
            clamp_to = 4096
        th = thinking_budget(i)
        if clamp_to and asked and asked > clamp_to:
            if th is not None and params.clamp_skip_when_thinking:
                pass  # Anthropic requires max_tokens > thinking.budget_tokens (Claude Code)
            else:
                mutations.append(
                    Mutation(
                        target="body",
                        op="set",
                        path=wire_path(i),
                        value=int(clamp_to),
                        reason=f"max_tokens clamped {asked}→{clamp_to}",
                    )
                )
                out_tok = min(out_tok, int(clamp_to))
        local = led.pricing.is_local_priced(model) or i.destination.dest_class == "local"
        compute = 0.0
        if local:
            compute = in_tok / max(1.0, params.local_prompt_tokens_per_s) + out_tok / max(
                1.0, params.local_tokens_per_s
            )
        est = Usage(
            input_tokens=in_tok,
            output_tokens=out_tok,
            compute_s=round(compute, 3),
            requests=1,
            tool_calls=0,
            estimated=True,
        )
        est.cost_usd = led.pricing.price(model, est)
        return est, mutations

    def _tool_estimate(self, i: Interaction, snap: Any, led: Ledger) -> Usage | None:
        # A-36: a hook tool.input for a server routed through the MCP proxy is accounted there
        servers: dict[str, Any] = {}
        try:
            servers = dict(snap.doc.mcp.servers)
        except Exception:
            servers = {}
        if i.surface == "tool.input" and i.mcp_server and i.mcp_server in servers:
            return None
        spend = 0.0
        if (i.action_type or "").startswith("spend.") and i.amount_usd:
            spend = max(0.0, float(i.amount_usd))
        return Usage(
            requests=0,
            tool_calls=1,
            cost_usd=led.pricing.tool_price(i.tool_name),
            spend_usd=spend,
            estimated=True,
        )

    # ------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        if interaction.direction != "out":
            return None
        led = _common.ledger()
        if led is None:
            return None
        params = parse_params(Bud01Params, cfg.params)
        snap = _common.snapshot(ctx)
        i = interaction
        is_model = i.surface == "model.request"
        selftest = ctx.source == "selftest"
        commit = not (ctx.dry_run or selftest)
        if is_model:
            est, mutations = self._estimate(ctx, i, params, snap, led)
            extra = [f"model:{normalize_model(i.model)}"] if i.model else []
        else:
            est_t = self._tool_estimate(i, snap, led)
            if est_t is None:
                return None
            est, mutations = est_t, []
            extra = [f"tool:{i.tool_name}"] if i.tool_name else []
        scopes = led.scopes_for(ctx.identity, ctx.session_id) + extra
        result, chk = led.evaluate(ctx, est, scopes, commit=commit, zero_usage=selftest)
        meta: dict[str, Any] = {
            "pricing_version": led.pricing.version,
            "estimate_usd": round(est.cost_usd, 6),
        }
        headers: dict[str, str] = {}
        if chk.remaining:
            dim = "usd" if "usd" in chk.remaining else "tokens"
            headers["x-aegis-budget-remaining"] = (
                f"{dim}={ladder.fmt_amount(dim, chk.remaining[dim])};scope={chk.remaining['scope']}"
            )
        meta["response_headers"] = headers

        if isinstance(result, BudgetDenial):
            return await self._hard(
                ctx,
                i,
                cfg,
                params,
                snap,
                led,
                result,
                chk,
                est,
                mutations,
                meta,
                scopes,
                commit,
                is_model,
            )

        res: Reservation = result
        soft = chk.soft
        if soft:
            meta["soft"] = soft
            action = soft.get("action")
            if action == "downgrade" and is_model:
                dec = await self._downgrade(
                    ctx, i, cfg, params, snap, led, res, est, mutations, meta, scopes, commit, soft
                )
                if dec is not None:
                    return dec
                action = "warn"
            if action == "require_approval":
                if commit:
                    await led.release(res)
                denial = BudgetDenial(
                    scope=soft["scope"],
                    dimension=soft["dimension"],
                    window=soft["window"],
                    limit=soft["limit"],
                    used=soft["used"],
                    requested=self._requested(est, soft["dimension"]),
                    action="require_approval",
                )
                return self._approval(
                    ctx, i, cfg, params, led, denial, chk.soft_entry, meta, commit, soft=True
                )
            # warn
            self._remember(ctx, i, res, commit)
            return self.decide(
                cfg,
                action="log",
                reason=(
                    f"budget soft limit: {soft['scope']} at {soft['pct']:.0f}% of "
                    f"{soft['window']} {soft['dimension']}"
                ),
                findings=[
                    Finding(
                        control_id=self.id,
                        category="budget",
                        detector=f"budget.soft.{soft['dimension']}.{soft['window']}",
                        severity="low",
                        meta=dict(soft),
                    )
                ],
                mutations=mutations,
                meta=meta,
            )
        self._remember(ctx, i, res, commit)
        return self.decide(
            cfg, action="allow", reason="within budget", mutations=mutations, meta=meta
        )

    @staticmethod
    def _requested(est: Usage, dim: str) -> float:
        from aegis.budgets.ledger import usage_dims

        return usage_dims(est).get(dim, 0.0)

    @staticmethod
    def _remember(ctx: RequestContext, i: Interaction, res: Reservation, commit: bool) -> None:
        if not commit:
            return
        ctx.state.setdefault(STATE_KEY, {})[_common.ikey(i)] = res
        ctx.state["bud.reservation"] = res
        ctx.state["bud.t0"] = monotonic()

    # ------------------------------------------------------------ hard path
    async def _hard(
        self,
        ctx: RequestContext,
        i: Interaction,
        cfg: ControlConfig,
        params: Bud01Params,
        snap: Any,
        led: Ledger,
        denial: BudgetDenial,
        chk: Check,
        est: Usage,
        mutations: list[Mutation],
        meta: dict[str, Any],
        scopes: list[str],
        commit: bool,
        is_model: bool,
    ) -> Decision:
        on_hard = denial.action
        if on_hard == "downgrade" and denial.dimension == "usd" and is_model:
            target = self._target(i, snap, led, params)
            if target is not None:
                est2, _ = self._estimate(ctx, i, params, snap, led, model=target[0])
                scopes2 = [s for s in scopes if not s.startswith("model:")] + [f"model:{target[0]}"]
                res2, _chk2 = led.evaluate(
                    ctx, est2, scopes2, commit=commit, zero_usage=ctx.source == "selftest"
                )
                if isinstance(res2, Reservation):
                    self._remember(ctx, i, res2, commit)
                    return self._downgraded(
                        cfg,
                        i,
                        led,
                        target,
                        est,
                        est2,
                        mutations,
                        meta,
                        denial.scope,
                        f"{denial.window} {denial.dimension}",
                        100.0,
                        commit,
                        ctx,
                    )
            on_hard = "block"
        if on_hard == "require_approval":
            return self._approval(
                ctx, i, cfg, params, led, denial, chk.denial_entry, meta, commit, soft=False
            )
        msg = ladder.format_message(
            params.message,
            scope=denial.scope,
            window=denial.window,
            dimension=denial.dimension,
            used=denial.used,
            limit=denial.limit,
            requested=denial.requested,
        )
        meta.update(
            {
                "scope": denial.scope,
                "dimension": denial.dimension,
                "window": denial.window,
                "limit": denial.limit,
                "used": denial.used,
                "requested": denial.requested,
                "resets_at": denial.resets_at.isoformat() if denial.resets_at else None,
            }
        )
        meta["response_headers"] = {**meta.get("response_headers", {}), "x-should-retry": "false"}
        if commit:
            led.enforcement.record(
                "hard_block", denial.scope, self.id, msg, cost_avoided_usd=est.cost_usd
            )
            inc(
                led.rt,
                "aegis_cost_avoided_usd_total",
                {"reason": "budget_block"},
                round(est.cost_usd, 6),
            )
            spawn(
                audit_event(
                    led.rt,
                    "budget.exceeded",
                    actor=ctx.identity,
                    reason=msg,
                    control_id=self.id,
                    session_id=ctx.session_id,
                    request_id=ctx.request_id,
                    action="block",
                    data=denial.model_dump(mode="json"),
                    policy_version=ctx.policy_version,
                )
            )
        return self.decide(
            cfg,
            action="block",
            reason=msg,
            findings=[self._finding(denial)],
            http_status=402,
            error_type="budget_exceeded",
            meta=meta,
        )

    def _finding(self, denial: BudgetDenial) -> Finding:
        return Finding(
            control_id=self.id,
            category="budget",
            detector=f"budget.{denial.dimension}.{denial.window}",
            severity="high",
            meta={
                "scope": denial.scope,
                "used": denial.used,
                "limit": denial.limit,
                "requested": denial.requested,
            },
        )

    def _approval(
        self,
        ctx: RequestContext,
        i: Interaction,
        cfg: ControlConfig,
        params: Bud01Params,
        led: Ledger,
        denial: BudgetDenial,
        entry: Any,
        meta: dict[str, Any],
        commit: bool,
        *,
        soft: bool,
    ) -> Decision:
        index = led.index(_common.snapshot(ctx))
        new_limit = ladder.raise_value(
            denial.limit, denial.used, denial.requested, params.raise_factor
        )
        patch = ladder.build_raise_patch(
            index, entry, denial.scope, denial.window, denial.dimension, new_limit
        )
        principal = ctx.identity.principal
        draft = ladder.approval_draft(
            principal=principal,
            scope=denial.scope,
            window=denial.window,
            dimension=denial.dimension,
            limit=denial.limit,
            used=denial.used,
            requested=denial.requested,
            new_limit=new_limit,
            patch=patch,
            tripped_by={
                "agent_id": ctx.identity.agent_id,
                "member_id": ctx.identity.member_id,
                "session_id": ctx.session_id,
                "request_id": ctx.request_id,
                "requested": denial.requested,
                "used": denial.used,
                "limit": denial.limit,
                "soft": soft,
            },
        )
        msg = ladder.format_message(
            params.message,
            scope=denial.scope,
            window=denial.window,
            dimension=denial.dimension,
            used=denial.used,
            limit=denial.limit,
        )
        reason = (
            f"{msg} Raise to {ladder.fmt_amount(denial.dimension, new_limit)} needs approval."
            if not soft
            else f"{denial.scope} {denial.window} {denial.dimension} at soft limit - raise to "
            f"{ladder.fmt_amount(denial.dimension, new_limit)} needs approval."
        )
        meta.update(
            {
                "scope": denial.scope,
                "dimension": denial.dimension,
                "window": denial.window,
                "limit": denial.limit,
                "used": denial.used,
                "requested": denial.requested,
                "new_limit": new_limit,
            }
        )
        if commit:
            led.enforcement.record("approval_requested", denial.scope, self.id, reason)
            if not soft:
                spawn(
                    audit_event(
                        led.rt,
                        "budget.exceeded",
                        actor=ctx.identity,
                        reason=msg,
                        control_id=self.id,
                        session_id=ctx.session_id,
                        request_id=ctx.request_id,
                        action="require_approval",
                        data=denial.model_dump(mode="json"),
                        policy_version=ctx.policy_version,
                    )
                )
        return self.decide(
            cfg,
            action="require_approval",
            reason=reason,
            findings=[self._finding(denial)],
            approval=draft,
            meta=meta,
        )

    # ------------------------------------------------------------ downgrade
    def _target(
        self, i: Interaction, snap: Any, led: Ledger, params: Bud01Params
    ) -> tuple[str, str] | None:
        target = ladder.downgrade_target(
            snap,
            i.model,
            i.destination.dest_class,
            str(i.meta.get("wire") or "") or None,
            led.pricing,
        )
        if target is None:
            return None
        if target[1] == "local":
            tokens = int(i.est_input_tokens or estimate_tokens(i.text(), i.model))
            if tokens > params.local_downgrade_max_input_tokens:
                return None  # never push a huge prompt to a small local model
        return target

    async def _downgrade(
        self,
        ctx: RequestContext,
        i: Interaction,
        cfg: ControlConfig,
        params: Bud01Params,
        snap: Any,
        led: Ledger,
        res: Reservation,
        est: Usage,
        mutations: list[Mutation],
        meta: dict[str, Any],
        scopes: list[str],
        commit: bool,
        soft: dict[str, Any],
    ) -> Decision | None:
        target = self._target(i, snap, led, params)
        if target is None:
            return None
        est2, _ = self._estimate(ctx, i, params, snap, led, model=target[0])
        scopes2 = [s for s in scopes if not s.startswith("model:")] + [f"model:{target[0]}"]
        if commit:
            await led.release(res)
        res2, _chk2 = led.evaluate(
            ctx, est2, scopes2, commit=commit, zero_usage=ctx.source == "selftest"
        )
        if not isinstance(res2, Reservation):
            # target does not fit either: keep the original reservation, just warn
            if commit:
                res, _ = led.evaluate(ctx, est, scopes, commit=True)
                if isinstance(res, Reservation):
                    self._remember(ctx, i, res, commit)
            return None
        self._remember(ctx, i, res2, commit)
        return self._downgraded(
            cfg,
            i,
            led,
            target,
            est,
            est2,
            mutations,
            meta,
            soft["scope"],
            f"{soft['window']} {soft['dimension']}",
            soft["pct"],
            commit,
            ctx,
        )

    def _downgraded(
        self,
        cfg: ControlConfig,
        i: Interaction,
        led: Ledger,
        target: tuple[str, str],
        est: Usage,
        est2: Usage,
        mutations: list[Mutation],
        meta: dict[str, Any],
        scope: str,
        what: str,
        pct: float,
        commit: bool,
        ctx: RequestContext,
    ) -> Decision:
        src = i.model or "?"
        reason = f"downgraded {src} → {target[0]} ({scope} {pct:.0f}% of {what})"
        muts = [
            *mutations,
            Mutation(target="route", op="set", path="model", value=target[0], reason=reason),
        ]
        meta["downgraded_from"] = src
        meta["downgraded_to"] = target[0]
        meta["response_headers"] = {
            **meta.get("response_headers", {}),
            "x-aegis-downgraded-from": src,
        }
        avoided = max(0.0, est.cost_usd - est2.cost_usd)
        if commit:
            led.enforcement.record("downgrade", scope, self.id, reason, cost_avoided_usd=avoided)
            inc(led.rt, "aegis_cost_avoided_usd_total", {"reason": "downgrade"}, round(avoided, 6))
        return self.decide(
            cfg,
            action="redact",
            reason=reason,
            mutations=muts,
            meta=meta,
            findings=[
                Finding(
                    control_id=self.id,
                    category="budget",
                    detector="budget.downgrade",
                    severity="low",
                    meta={"from": src, "to": target[0], "scope": scope},
                )
            ],
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
        led = _common.ledger()
        if led is None or ctx.dry_run or ctx.source == "selftest":
            return
        key = _common.ikey(interaction)
        res: Reservation | None = ctx.state.get(STATE_KEY, {}).pop(key, None)
        is_model = interaction.surface == "model.request"
        usage = outcome.usage
        model = outcome.model_used or self._routed_model(verdict) or interaction.model
        ran = _common.executed(verdict, outcome)
        if is_model:
            if ran and led.pricing.is_local_priced(model) and not usage.compute_s:
                t0 = ctx.state.get("bud.t0")
                ms = (
                    outcome.upstream_ms
                    if outcome.upstream_ms is not None
                    else ((monotonic() - t0) * 1000.0 if t0 else 0.0)
                )
                usage.compute_s = round(max(0.0, ms) / 1000.0, 3)
            if not usage.cost_usd and (
                usage.input_tokens or usage.output_tokens or usage.compute_s
            ):
                usage.cost_usd = led.price(model, usage)  # A-08: fill in place
        if ran:
            if is_model:
                actual = usage
                if (
                    not (usage.input_tokens or usage.output_tokens or usage.compute_s)
                    and res is not None
                ):
                    actual = res.estimate  # upstream reported nothing: settle at estimate
                actual = actual.model_copy(update={"requests": 1, "tool_calls": 0})
            else:
                if res is not None:
                    actual = res.estimate
                else:
                    est = self._tool_estimate(interaction, _common.snapshot(ctx), led)
                    if est is None:
                        return
                    actual = est
            if res is not None:
                await led.settle(res, actual)
            else:
                extra = (
                    [f"model:{normalize_model(model)}"]
                    if is_model and model
                    else [f"tool:{interaction.tool_name}"]
                    if interaction.tool_name
                    else []
                )
                await led.commit(ctx, actual, led.scopes_for(ctx.identity, ctx.session_id) + extra)
            return
        if res is not None:
            await led.release(res)
        # upstream failed after being allowed: count the tokens it did report
        if (
            is_model
            and verdict.action in ("allow", "log", "redact")
            and (usage.input_tokens or usage.output_tokens)
        ):
            extra = [f"model:{normalize_model(model)}"] if model else []
            await led.commit(
                ctx,
                usage.model_copy(update={"requests": 1}),
                led.scopes_for(ctx.identity, ctx.session_id) + extra,
            )

    @staticmethod
    def _routed_model(verdict: Verdict) -> str | None:
        for m in verdict.mutations:
            if m.target == "route" and m.path == "model" and isinstance(m.value, str):
                return m.value
        return None


CONTROLS = [BudgetsControl()]
