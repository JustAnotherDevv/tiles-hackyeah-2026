"""Approvals service: `aegis.approvals.service:create(rt)` -> `rt.approvals` (CONTRACTS section 3.2).

Implements the frozen `ApprovalService` protocol plus `start()/stop()` and a few extras used by the
`/api/approvals*` routes and GOV-05 (`route_info`, `proposer_authorized`, `counts`, `rules_view`,
`simulate`, `run_routing_selftest`, `sweep`).

Lifecycle: pending -> approved | denied | expired | cancelled. `auto` routes are stored as
approved (required_role "auto"), `deny` routes as denied (required_role "deny"). Approved action
grants are single-use (`max_uses`), bound to the exact parameters (fingerprint) and redeemable for
`grant_ttl_s`; redemptions of one grant within `redeem_window_s` count as one use (the Claude Code
hook and the MCP proxy both see the same call). Config / budget / MCP-pin approvals take effect
through executors and are never redeemable for another call.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Literal

from aegis.approvals import eligibility
from aegis.approvals.compat import test_mode
from aegis.approvals.executors import Executor, ExecutorRegistry
from aegis.approvals.facts import (
    OrgCache,
    facts_for_action,
    facts_for_change,
    self_members_for_changes,
)
from aegis.approvals.fingerprint import fp_draft, fp_interaction, strip_args
from aegis.approvals.notify import Notifier
from aegis.approvals.routing import (
    CompiledApprovals,
    RouteInfo,
    compiled_for,
    describe_when,
    route_many,
)
from aegis.approvals.store import STATUSES, ApprovalStore
from aegis.approvals.views import Masker, bound_params
from aegis.core.policy_schema import PolicyChange
from aegis.core.types import (
    ApprovalDraft,
    ApprovalRequest,
    ApprovalRoute,
    ApprovalVote,
    Decision,
    Identity,
    Interaction,
    RequestContext,
    new_id,
    utcnow,
)

log = logging.getLogger(__name__)

FINAL = frozenset({"approved", "denied", "expired", "cancelled"})
OK_EXECUTION = frozenset({"applied", "noop", "ok"})
ORG_REFRESH_S = 30.0


class ApprovalsService:
    """`rt.approvals` (see module docstring)."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt
        self.org = OrgCache()
        self.executors = ExecutorRegistry(rt)
        self.notify = Notifier(rt)
        self._store: ApprovalStore | None = None
        self._lock = asyncio.Lock()
        self._events: dict[str, asyncio.Event] = {}
        self._redeemed: dict[str, float] = {}
        self._tasks: list[asyncio.Task[Any]] = []
        self._org_loaded_at = 0.0
        self.selftest_results: list[dict[str, Any]] = []
        self.started = False

    # ================================================================ lifecycle
    async def start(self) -> None:
        self._ensure_store()
        await self.refresh_org()
        policy = getattr(self.rt, "policy", None)
        if policy is not None and hasattr(policy, "on_change"):
            try:
                policy.on_change(self._on_policy_change)
            except Exception:
                log.warning("policy.on_change registration failed", exc_info=True)
        if not test_mode(self.rt):
            from aegis.approvals.expiry import sweeper_loop
            from aegis.approvals.seed import seed_history

            try:
                await seed_history(self)
            except Exception:
                log.warning("approval history seed failed", exc_info=True)
            self._tasks.append(asyncio.create_task(sweeper_loop(self), name="approvals-sweeper"))
            self._tasks.append(asyncio.create_task(self._org_listener(), name="approvals-org"))
        self.notify.pending_gauge(self._ensure_store().counts()["pending"])
        self.started = True
        log.info("approvals started pending=%s", self._ensure_store().counts()["pending"])

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        for ev in self._events.values():
            ev.set()
        self.started = False

    def _ensure_store(self) -> ApprovalStore:
        if self._store is None:
            conn = None
            db = getattr(self.rt, "db", None)
            if callable(db):
                try:
                    conn = db()
                except Exception:
                    log.warning("rt.db() failed; approvals use an in-memory store", exc_info=True)
            self._store = ApprovalStore(conn) if conn is not None else ApprovalStore.in_memory()
        return self._store

    @property
    def store(self) -> ApprovalStore:
        return self._ensure_store()

    async def refresh_org(self) -> None:
        await self.org.load(getattr(self.rt, "org", None))
        self._org_loaded_at = time.monotonic()

    async def _org_listener(self) -> None:
        bus = getattr(self.rt, "bus", None)
        if bus is None or not hasattr(bus, "subscribe"):
            return
        try:
            async for _msg in bus.subscribe({"org.updated"}):
                await self.refresh_org()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("org.updated listener stopped", exc_info=True)

    async def _on_policy_change(self, snap: Any) -> None:
        try:
            from aegis.approvals.selftest import report_selftest

            await report_selftest(self, snap)
        except Exception:
            log.warning("approval routing self-test failed to run", exc_info=True)

    # ================================================================ policy access
    def _snap(self) -> Any | None:
        policy = getattr(self.rt, "policy", None)
        if policy is None:
            return None
        try:
            return policy.snapshot()
        except Exception:
            return None

    def compiled(self, snap: Any | None = None) -> CompiledApprovals:
        return compiled_for(snap if snap is not None else self._snap())

    def defaults(self, snap: Any | None = None) -> dict[str, Any]:
        return self.compiled(snap).defaults

    def _clock(self, seconds: float, snap: Any | None = None) -> float:
        mult = float(self.defaults(snap).get("clock_multiplier") or 1.0)
        return max(1.0, float(seconds) / mult) if mult > 0 else float(seconds)

    # ================================================================ routing
    def route_info(
        self,
        *,
        kind: str,
        action_type: str,
        requester: Identity,
        amount_usd: float | None = None,
        resource: str | None = None,
        labels: Mapping[str, Any] | None = None,
        changes: list[Any] | None = None,
        profile: str | None = None,
        snap: Any | None = None,
    ) -> RouteInfo:
        snap = snap if snap is not None else self._snap()
        compiled = compiled_for(snap)
        doc = getattr(snap, "doc", None)
        prof = profile or (str(doc.profile) if doc is not None else "balanced")
        if kind == "config_change":
            feed = getattr(self.rt, "feed", None)
            fact_list = [
                facts_for_change(
                    c, requester=requester, snap=snap, org=self.org, profile=prof, feed=feed,
                    action_type=action_type,
                )
                for c in (changes or [None])
            ]
        else:
            fact_list = [
                facts_for_action(
                    kind=kind, action_type=action_type, requester=requester,
                    amount_usd=amount_usd, resource=resource, labels=labels, profile=prof,
                    org=self.org,
                )
            ]
        return route_many(compiled, fact_list)

    def route(
        self,
        *,
        kind: str,
        action_type: str,
        requester: Identity,
        amount_usd: float | None = None,
        resource: str | None = None,
        labels: Mapping[str, str] | None = None,
        changes: list[PolicyChange] | None = None,
    ) -> ApprovalRoute:
        """First matching rule (config_rules for config_change, rules otherwise); no match ->
        defaults. Never raises: an internal error routes to `owner` (fail closed)."""
        try:
            return self.route_info(
                kind=kind, action_type=action_type, requester=requester, amount_usd=amount_usd,
                resource=resource, labels=labels, changes=list(changes) if changes else None,
            ).route
        except Exception:
            log.exception("approval routing failed; failing closed to owner")
            return ApprovalRoute(required_role="owner", rule_id=None)

    def self_set(
        self, kind: str, requester: Identity, info: RouteInfo, changes: list[Any] | None
    ) -> set[str]:
        if kind == "config_change" and changes:
            idx = min(info.deciding_index, len(changes) - 1)
            return set(self_members_for_changes([changes[idx]], requester, self.org))
        sponsor = self.org.sponsor_of(requester)
        return {sponsor} if sponsor else set()

    def proposer_authorized(
        self, identity: Identity, info: RouteInfo, changes: list[Any] | None = None,
        kind: str = "config_change",
    ) -> bool:
        """GOV-05: the human proposer already satisfies the required level (contract 3.5)."""
        return eligibility.proposer_satisfies(
            identity, info.route.required_role, self.self_set(kind, identity, info, changes),
            self.org,
        )

    def can_approve(self, voter: Identity, req: ApprovalRequest) -> tuple[bool, str]:
        return eligibility.can_vote(voter, req, self.org)

    def can_deny(self, voter: Identity, req: ApprovalRequest) -> tuple[bool, str]:
        return eligibility.can_vote(voter, req, self.org, "deny")

    def fingerprint(self, identity: Identity, interaction: Interaction) -> str:
        return fp_interaction(identity, interaction)

    def register_executor(self, kind: str, fn: Executor) -> None:
        self.executors.register(kind, fn)

    # ================================================================ creation
    def _requester(self, identity: Identity) -> Identity:
        data = identity.model_copy()
        if identity.agent_id and not identity.member_id:
            sponsor = self.org.sponsor_of(identity)
            if sponsor:
                data.member_id = sponsor
        if not data.team_id:
            data.team_id = self.org.team_of(identity)
        if not data.display_name:
            if identity.agent_id:
                a = self.org.agent(identity.agent_id)
                data.display_name = a.name if a else identity.agent_id
            elif identity.member_id:
                m = self.org.member(identity.member_id)
                data.display_name = m.name if m else None
        return data

    def _synth_draft(self, ctx: RequestContext, i: Interaction, decision: Decision) -> ApprovalDraft:
        action_type = i.action_type or (f"tool:{i.tool_name}" if i.tool_name else f"{i.kind}.{i.surface}")
        who = ctx.identity.agent_id or ctx.identity.member_id or "anonymous"
        what = i.tool_name or action_type
        title = f"{who} wants to run {what}"
        if decision.reason:
            title += f" — {decision.reason}"
        return ApprovalDraft(
            kind="action", action_type=action_type, title=title, summary=decision.reason or None,
            amount_usd=i.amount_usd, resource=i.resource,
            labels={k: str(v) for k, v in i.labels.items()},
        )

    async def request(
        self, ctx: RequestContext, interaction: Interaction, decision: Decision
    ) -> ApprovalRequest:
        """Create (or reuse the pending one with the same fingerprint) from decision.approval."""
        draft = decision.approval or self._synth_draft(ctx, interaction, decision)
        identity = ctx.identity
        labels = {str(k): str(v) for k, v in interaction.labels.items() if v is not None}
        labels.update({str(k): str(v) for k, v in draft.labels.items() if v is not None})
        changes = None
        if draft.kind == "config_change":
            changes = (draft.payload or {}).get("changes") or interaction.meta.get("changes")
        if draft.kind == "action":
            fp = fp_interaction(identity, interaction)
            masker = Masker(getattr(self.rt, "redactor", None))
            bound = bound_params(
                masker,
                interaction.tool_name,
                strip_args(interaction.tool_name, interaction.tool_args),
                {
                    "action_type": interaction.action_type or draft.action_type,
                    "resource": interaction.resource or draft.resource,
                    "amount_usd": interaction.amount_usd if interaction.amount_usd is not None
                    else draft.amount_usd,
                    "mcp_server": interaction.mcp_server,
                    "method": interaction.http_method,
                    "url": masker.text(interaction.url, 300) if interaction.url else None,
                    "surface": interaction.surface,
                },
            )
        else:
            fp = fp_draft(identity, draft)
            bound = None
        decision_id = decision.meta.get("decision_id") or ctx.state.get("aegis.decision_id")
        return await self._create(
            identity,
            draft,
            fp=fp,
            labels=labels,
            amount=draft.amount_usd if draft.amount_usd is not None else interaction.amount_usd,
            resource=draft.resource or interaction.resource,
            changes=changes,
            request_id=ctx.request_id,
            decision_id=str(decision_id) if decision_id else None,
            control_id=decision.control_id,
            bound=bound,
            replay_of=ctx.state.pop("apr.replay_of", None),
            execute_auto=draft.kind != "config_change",
            source=str(ctx.source),
        )

    async def create_manual(self, requester: Identity, draft: ApprovalDraft) -> ApprovalRequest:
        """Request created outside the pipeline (org-rbac org.* changes, mcp-proxy re-pins,
        policy-engine fallback, dashboard). Executors run on approval, including auto routes."""
        changes = (draft.payload or {}).get("changes") if draft.kind == "config_change" else None
        return await self._create(
            requester,
            draft,
            fp=fp_draft(requester, draft),
            labels={str(k): str(v) for k, v in draft.labels.items() if v is not None},
            amount=draft.amount_usd,
            resource=draft.resource,
            changes=changes,
            request_id=None,
            decision_id=None,
            control_id=None,
            bound=None,
            replay_of=None,
            execute_auto=True,
            source="manual",
        )

    async def _create(
        self,
        identity: Identity,
        draft: ApprovalDraft,
        *,
        fp: str,
        labels: dict[str, str],
        amount: float | None,
        resource: str | None,
        changes: list[Any] | None,
        request_id: str | None,
        decision_id: str | None,
        control_id: str | None,
        bound: dict[str, Any] | None,
        replay_of: Any,
        execute_auto: bool,
        source: str,
    ) -> ApprovalRequest:
        snap = self._snap()
        compiled = compiled_for(snap)
        defaults = compiled.defaults
        try:
            info = self.route_info(
                kind=draft.kind, action_type=draft.action_type, requester=identity,
                amount_usd=amount, resource=resource, labels=labels, changes=changes, snap=snap,
            )
        except Exception:
            log.exception("approval routing failed; failing closed to owner")
            info = route_many(compiled, [{"kind": draft.kind, "action": None}])
            info.route = ApprovalRoute(required_role="owner", rule_id=None)
        route = info.route
        level = route.required_role
        masker = Masker(getattr(self.rt, "redactor", None))
        requester = self._requester(identity)
        req_member = self.org.sponsor_of(identity)
        self_set = self.self_set(draft.kind, identity, info, changes)
        await self._expire_due()
        store = self._ensure_store()
        now = utcnow()
        sub: str | None = None
        async with self._lock:
            for existing in store.by_fingerprint(fp, "pending"):
                if existing.kind == draft.kind and (
                    existing.expires_at is None or existing.expires_at > now
                ):
                    log.debug("approval reused id=%s", existing.id)
                    return existing
            cooldown = float(defaults.get("deny_cooldown_s") or 0)
            for denied in store.by_fingerprint(fp, "denied"):
                if denied.decided_at and (now - denied.decided_at).total_seconds() < cooldown:
                    return denied
            flood_cap = None
            if level not in ("auto", "deny"):
                if store.pending_count() >= int(defaults.get("max_pending") or 50):
                    flood_cap = "max_pending"
                elif store.pending_count(
                    member_id=identity.member_id, agent_id=identity.agent_id
                ) >= int(defaults.get("max_pending_per_principal") or 10):
                    flood_cap = "max_pending_per_principal"
            grant_ttl = self._clock(info.grant_ttl_s, snap)
            payload: dict[str, Any] = dict(draft.payload or {})
            payload["routing"] = {
                **info.explain(),
                "requester_member": req_member,
                "self_members": sorted(self_set),
                "grant_ttl_s": int(grant_ttl),
                "source": source,
            }
            if bound is not None:
                payload["bound"] = bound
            if replay_of:
                payload["replay_of"] = replay_of
            req = ApprovalRequest(
                id=new_id("apr"),
                org_id=identity.org_id,
                team_id=requester.team_id,
                kind=draft.kind,
                action_type=draft.action_type,
                title=masker.text(draft.title, 300),
                summary=masker.text(draft.summary, 600) if draft.summary else None,
                requester=requester,
                amount_usd=amount,
                resource=resource,
                labels=labels,
                payload=payload,
                fingerprint=fp,
                required_role=level,
                two_person=route.two_person,
                rule_id=route.rule_id,
                status="pending",
                created_at=now,
                expires_at=now + timedelta(seconds=self._clock(route.ttl_s, snap)),
                request_id=request_id,
                decision_id=decision_id,
                control_id=control_id,
                max_uses=route.max_uses,
            )
            human = bool(identity.member_id) and not identity.agent_id
            role = self.org.role_of(identity)
            if flood_cap:
                # anti human-in-the-loop flooding (ASI09 / T10): no new card, denied outright
                req.status = "denied"
                req.rule_id = "defaults.max_pending"
                req.decided_at = now
                payload["routing"]["flood_cap"] = flood_cap
                sub = "denied"
            elif level == "auto":
                req.status = "approved"
                req.decided_at = now
                req.expires_at = now + timedelta(seconds=grant_ttl)
                sub = "auto"
                if source != "manual" and draft.kind == "action":
                    # the pipeline lets this very call through: that is the first use
                    req.uses = 1
                    self._redeemed[req.id] = time.monotonic()
            elif level == "deny":
                req.status = "denied"
                req.decided_at = now
                sub = "deny_rule"
            elif human and draft.kind == "config_change" and not route.two_person and (
                eligibility.proposer_satisfies(identity, level, self_set, self.org)
            ):
                req.votes = [ApprovalVote(member_id=identity.member_id or "", role=role,
                                          decision="approve",
                                          comment=f"authorized: {role} ≥ {level}")]
                req.status = "approved"
                req.decided_at = now
                req.decided_by = [identity.member_id or ""]
                req.expires_at = now + timedelta(seconds=grant_ttl)
                payload["routing"]["authorized"] = True
                sub = "approved"
            elif human and route.two_person and eligibility.proposer_satisfies(
                identity, level, self_set, self.org
            ):
                req.votes = [ApprovalVote(member_id=identity.member_id or "", role=role,
                                          decision="approve", comment="proposer co-sign")]
            if req.status == "approved" and draft.kind == "config_change" and source != "manual":
                req.uses = req.max_uses  # the pipeline applies it; never redeemable
            payload["routing"]["eligible"] = (
                eligibility.eligible_members(req, self.org) if req.status == "pending" else []
            )
            store.insert(req)
        await self.notify.created(req, sub=sub)
        self._gauge()
        log.info(
            "approval created id=%s kind=%s action=%s rule=%s level=%s two_person=%s status=%s",
            req.id, req.kind, req.action_type, req.rule_id, level, req.two_person, req.status,
        )
        if req.status == "approved" and execute_auto:
            req = await self._execute(req)
        return req

    # ================================================================ redemption
    async def find_preapproved(
        self, ctx: RequestContext, interaction: Interaction
    ) -> ApprovalRequest | None:
        """Approved, unexpired action grant for exactly these parameters (token and/or
        fingerprint). Consumes one use; repeats within `redeem_window_s` count as one use."""
        await self._expire_due()
        store = self._ensure_store()
        fp = fp_interaction(ctx.identity, interaction)
        window = float(self.defaults().get("redeem_window_s") or 30)
        now = utcnow()
        mono = time.monotonic()
        token = (ctx.approval_token or "").strip() or None
        hit: ApprovalRequest | None = None
        consumed = False
        mismatch: ApprovalRequest | None = None
        async with self._lock:
            candidates: list[ApprovalRequest] = []
            if token:
                t = store.get(token)
                if t is not None:
                    if t.fingerprint == fp and t.kind == "action":
                        candidates.append(t)
                    elif t.fingerprint != fp:
                        mismatch = t
            seen = {c.id for c in candidates}
            candidates += [
                r for r in store.by_fingerprint(fp, "approved")
                if r.kind == "action" and r.id not in seen
            ]
            for r in candidates:
                if r.status != "approved" or (r.expires_at is not None and r.expires_at <= now):
                    continue
                if r.uses < r.max_uses:
                    r.uses += 1
                    store.update(r)
                    self._redeemed[r.id] = mono
                    hit, consumed = r, True
                    break
                last = self._redeemed.get(r.id)
                if last is not None and mono - last <= window:
                    hit = r
                    break
        if mismatch is not None:
            ctx.state["apr.replay_of"] = f"{mismatch.id} (params mismatch)"
            await self.notify.audit(
                "system", mismatch, actor=ctx.identity, sub="approval.token_mismatch",
                reason="approval token presented for different parameters",
                extra={"presented_fp": fp[:16], "grant_fp": mismatch.fingerprint[:16]},
            )
        if hit is not None and consumed:
            await self.notify.updated(
                hit, "approval.executed", actor=ctx.identity, sub="redeemed",
                extra={"redeemed_by_request": ctx.request_id},
            )
        return hit

    # ================================================================ waiting
    async def wait(
        self, approval_id: str, timeout_s: float, *, consume: bool = True
    ) -> ApprovalRequest:
        """Block until the request is decided or `timeout_s` passes. When the pipeline holds a
        call and the approval arrives, that held call IS the use of the grant (`consume=True`);
        the long-poll API passes `consume=False`."""
        req = await self.get(approval_id)
        if req is None:
            raise KeyError(approval_id)
        if req.status == "pending" and timeout_s > 0:
            ev = self._events.setdefault(approval_id, asyncio.Event())
            remaining = float(timeout_s)
            if req.expires_at is not None:
                remaining = min(remaining, (req.expires_at - utcnow()).total_seconds() + 0.05)
            if remaining > 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(ev.wait(), timeout=remaining)
            req = await self.get(approval_id) or req
        if consume and req.status == "approved" and req.kind == "action":
            async with self._lock:
                fresh = self._ensure_store().get(approval_id) or req
                if fresh.uses < fresh.max_uses:
                    fresh.uses += 1
                    self._ensure_store().update(fresh)
                    self._redeemed[fresh.id] = time.monotonic()
                    req = fresh
                    consumed = True
                else:
                    consumed = False
            if consumed:
                await self.notify.updated(req, "approval.executed", sub="redeemed",
                                          extra={"redeemed_by": "held call"})
        return req

    def _wake(self, approval_id: str) -> None:
        ev = self._events.pop(approval_id, None)
        if ev is not None:
            ev.set()

    # ================================================================ voting
    async def vote(
        self,
        approval_id: str,
        voter: Identity,
        decision: Literal["approve", "deny"],
        comment: str | None = None,
    ) -> ApprovalRequest:
        """Raises KeyError (unknown), ValueError (already decided), PermissionError(why)."""
        if decision not in ("approve", "deny"):
            raise ValueError(f"invalid decision {decision!r}")
        await self._expire_due()
        store = self._ensure_store()
        masker = Masker(getattr(self.rt, "redactor", None))
        async with self._lock:
            req = store.get(approval_id)
            if req is None:
                raise KeyError(approval_id)
            if req.status != "pending":
                raise ValueError(f"approval {approval_id} is already {req.status}")
            ok, why = eligibility.can_vote(voter, req, self.org, decision)
            if not ok:
                raise PermissionError(why)
            role = self.org.role_of(voter)
            req.votes.append(
                ApprovalVote(
                    member_id=voter.member_id or "",
                    role=role,  # type: ignore[arg-type]
                    decision=decision,
                    comment=masker.text(comment, 300) if comment else None,
                )
            )
            outcome = eligibility.tally(req, self.org)
            now = utcnow()
            if outcome == "approved":
                req.status = "approved"
                req.decided_at = now
                req.decided_by = [v.member_id for v in req.votes if v.decision == "approve"]
                grant = (req.payload.get("routing") or {}).get("grant_ttl_s") or self.defaults().get(
                    "grant_ttl_s", 900
                )
                req.expires_at = now + timedelta(seconds=float(grant))
            elif outcome == "denied":
                req.status = "denied"
                req.decided_at = now
                req.decided_by = [v.member_id for v in req.votes if v.decision == "deny"]
            if req.status == "pending":
                req.payload.setdefault("routing", {})["eligible"] = eligibility.eligible_members(
                    req, self.org
                )
            store.update(req)
        final = req.status in FINAL
        await self.notify.updated(
            req,
            "approval.decided",
            actor=voter,
            sub=req.status if final else "vote",
            outcome=req.status if final else None,
            extra={"final": final, "vote": decision, "voter": voter.member_id},
        )
        self._gauge()
        if final:
            self._wake(req.id)
        log.info(
            "approval vote id=%s voter=%s decision=%s status=%s", req.id, voter.member_id,
            decision, req.status,
        )
        if req.status == "approved":
            req = await self._execute(req)
        return req

    async def _execute(self, req: ApprovalRequest) -> ApprovalRequest:
        execution = await self.executors.run(req)
        if execution is None:
            return req
        store = self._ensure_store()
        async with self._lock:
            fresh = store.get(req.id) or req
            fresh.execution = execution
            fresh.uses = fresh.max_uses
            store.update(fresh)
        ok = str(execution.get("status")) in OK_EXECUTION
        await self.notify.updated(
            fresh, "approval.executed", sub="execution",
            extra={"execution": {k: execution.get(k) for k in
                                 ("status", "policy_version", "previous_version", "message",
                                  "executor")},
                   "ok": ok},
        )
        if not ok:
            msg = execution.get("message") or ", ".join(map(str, execution.get("errors") or []))
            self.notify.system(
                "warning",
                f"Approved change {fresh.id} could not be applied: {msg or execution.get('status')}",
                approval_id=fresh.id,
            )
        return fresh

    async def cancel(self, approval_id: str, actor: Identity) -> ApprovalRequest:
        """Requester (same principal), the requester's member/sponsor or an admin+ may cancel."""
        await self._expire_due()
        store = self._ensure_store()
        async with self._lock:
            req = store.get(approval_id)
            if req is None:
                raise KeyError(approval_id)
            if req.status != "pending":
                raise ValueError(f"approval {approval_id} is already {req.status}")
            role = self.org.role_of(actor)
            same_principal = actor.principal == req.requester.principal
            sponsor = eligibility.requester_member(req, self.org)
            is_sponsor = bool(actor.member_id) and not actor.agent_id and actor.member_id in {
                sponsor, req.requester.member_id
            }
            if not (same_principal or is_sponsor or role in ("admin", "owner")):
                raise PermissionError(
                    "Only the requester, the sponsor or an admin can cancel this request."
                )
            req.status = "cancelled"
            req.decided_at = utcnow()
            req.decided_by = [actor.member_id or actor.agent_id or "unknown"]
            store.update(req)
        await self.notify.updated(req, "approval.decided", actor=actor, sub="cancelled",
                                  outcome="cancelled", extra={"final": True})
        self._gauge()
        self._wake(req.id)
        return req

    # ================================================================ reads
    async def get(self, approval_id: str) -> ApprovalRequest | None:
        await self._expire_due()
        return self._ensure_store().get(approval_id)

    async def list_requests(
        self, *, status: str | None = None, kind: str | None = None, limit: int = 200
    ) -> list[ApprovalRequest]:
        await self._expire_due()
        store = self._ensure_store()
        return await asyncio.to_thread(store.list, status=status, kind=kind, limit=limit)

    def counts(self) -> dict[str, int]:
        return self._ensure_store().counts()

    # ================================================================ expiry
    async def _expire_due(self) -> list[ApprovalRequest]:
        store = self._ensure_store()
        now = utcnow()
        expired: list[ApprovalRequest] = []
        async with self._lock:
            for req in store.due_for_expiry(now):
                req.status = "expired"
                req.decided_at = now
                store.update(req)
                expired.append(req)
        for req in expired:
            await self.notify.updated(req, "approval.expired", sub="expired", outcome="expired")
            self._wake(req.id)
            log.info("approval expired id=%s rule=%s", req.id, req.rule_id)
        if expired:
            self._gauge()
        return expired

    async def sweep(self) -> list[ApprovalRequest]:
        """Expire due requests now (sweeper loop / tests). Refreshes the org cache every 30 s."""
        expired = await self._expire_due()
        if time.monotonic() - self._org_loaded_at > ORG_REFRESH_S:
            await self.refresh_org()
        return expired

    def _gauge(self) -> None:
        try:
            self.notify.pending_gauge(self._ensure_store().counts()["pending"])
        except Exception:  # pragma: no cover - defensive
            log.debug("pending gauge failed", exc_info=True)

    # ================================================================ dashboard helpers
    def rules_view(self) -> dict[str, Any]:
        compiled = self.compiled()
        d = compiled.defaults

        def view(rules: list[Any]) -> list[dict[str, Any]]:
            return [
                {
                    "id": r.id,
                    "set": r.set,
                    "description": r.description,
                    "when": describe_when(r),
                    "approver": r.approver,
                    "two_person": r.two_person,
                    "ttl_s": r.ttl_s,
                    "aliases": list(r.aliases),
                    "grant_ttl_s": r.grant_ttl_s,
                    "order": r.index + 1,
                }
                for r in rules
            ]

        return {
            "rules": view(compiled.rules),
            "config_rules": view(compiled.config_rules),
            "defaults": {
                "ttl_s": int(d.get("ttl_s") or 900),
                "default_approver": d.get("default_approver", "admin"),
                "default_config_approver": d.get("default_config_approver", "owner"),
                "grant_ttl_s": d.get("grant_ttl_s"),
                "hold_s": d.get("hold_s"),
                "max_pending": d.get("max_pending"),
                "max_pending_per_principal": d.get("max_pending_per_principal"),
            },
            "policy_version": compiled.version,
            "selftest": {
                "total": len(self.selftest_results),
                "failed": sum(1 for r in self.selftest_results if not r.get("passed")),
            },
        }

    def simulate(
        self,
        *,
        kind: str,
        action_type: str,
        viewer: Identity | None = None,
        amount_usd: float | None = None,
        resource: str | None = None,
        requester_member_id: str | None = None,
        requester_agent_id: str | None = None,
        labels: Mapping[str, Any] | None = None,
        profile: str | None = None,
        changes: list[Any] | None = None,
        change: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """'Who would approve this?' — same routing as live, plus the explanation."""
        if requester_agent_id:
            requester = self.org.identity_for(requester_agent_id)
        elif requester_member_id:
            requester = self.org.identity_for(requester_member_id)
        else:
            requester = viewer or Identity(role="member", member_id="anonymous")
        if kind == "config_change" and not changes and change:
            changes = [dict(change)]
        info = self.route_info(
            kind=kind, action_type=action_type, requester=requester, amount_usd=amount_usd,
            resource=resource, labels=labels, changes=changes, profile=profile,
        )
        out = info.route.model_dump(mode="json")
        out["description"] = info.description
        self_set = self.self_set(kind, requester, info, changes)
        probe = ApprovalRequest(
            id="apr_simulated", kind=kind, action_type=action_type, title="simulated",  # type: ignore[arg-type]
            requester=self._requester(requester), fingerprint="-",
            required_role=info.route.required_role, two_person=info.route.two_person,
            rule_id=info.route.rule_id,
            payload={"routing": {"requester_member": self.org.sponsor_of(requester),
                                 "self_members": sorted(self_set)}},
        )
        eligible = eligibility.eligible_members(probe, self.org)
        authorized = False
        if kind == "config_change":
            authorized = self.proposer_authorized(requester, info, changes)
        out["explain"] = {
            **info.explain(),
            "eligible": eligible,
            "eligible_names": [self.org.name(m) for m in eligible],
            "requester": requester.model_dump(mode="json"),
            "proposer_authorized": authorized,
        }
        return out

    async def run_routing_selftest(self, snap: Any | None = None) -> list[dict[str, Any]]:
        from aegis.approvals.selftest import run_tests

        self.selftest_results = run_tests(self, snap if snap is not None else self._snap())
        return self.selftest_results


def create(rt: Any) -> ApprovalsService:
    """Factory used by the runtime (`aegis.approvals.service:create`). Cheap, no I/O."""
    return ApprovalsService(rt)


__all__ = ["FINAL", "STATUSES", "ApprovalsService", "create"]
