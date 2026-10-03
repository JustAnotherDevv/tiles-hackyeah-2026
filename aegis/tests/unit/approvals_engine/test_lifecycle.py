"""APR-V04: lifecycle and safety properties (request, vote, two-person, cancel, expiry, wait,
redemption, replay protection, flood caps, deny cooldown)."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

import pytest

from aegis.core.types import utcnow


async def _spend(svc, h, agent="trading-copilot@trading", amount=50.0, **kw):
    i = h.spend(amount, **kw)
    ctx = h.ctx(h.agent(agent))
    return await svc.request(ctx, i, h.decision(i)), i, ctx


async def test_f4_admin_flow_with_separation_of_duties(svc, h, fake_rt) -> None:
    req, i, _ = await _spend(svc, h)
    assert (req.status, req.required_role, req.rule_id) == ("pending", "admin", "spend-admin")
    assert req.requester.member_id == "u_piotr" and req.team_id == "trading"
    assert req.payload["routing"]["eligible"] == ["u_katarzyna", "u_emily", "u_marek"]
    ok, why = svc.can_approve(h.member("u_piotr"), req)
    assert not ok and why == "Separation of duties: you sponsor trading-copilot@trading."
    ok, why = svc.can_approve(h.member("u_olivia"), req)
    assert not ok and "Needs admin approval" in why
    with pytest.raises(PermissionError, match="Separation of duties"):
        await svc.vote(req.id, h.member("u_piotr"), "approve")
    done = await svc.vote(req.id, h.member("u_emily"), "approve", "ok for the desk")
    assert done.status == "approved" and done.decided_by == ["u_emily"]
    assert done.expires_at is not None and done.expires_at > utcnow() + timedelta(seconds=800)
    with pytest.raises(ValueError, match="already approved"):
        await svc.vote(req.id, h.member("u_marek"), "approve")
    # audit trail + SSE
    kinds = [e.event_type for e in fake_rt.audit.events]
    assert kinds[:2] == ["approval.created", "approval.decided"]
    assert fake_rt.bus.events("approval.created") and fake_rt.bus.events("approval.updated")
    # the agent retries the exact same call -> redeemed once
    hit = await svc.find_preapproved(h.ctx(h.agent("trading-copilot@trading")), i)
    assert hit is not None and hit.id == req.id and hit.uses == 1


async def test_pending_reused_by_fingerprint(svc, h) -> None:
    a, _, _ = await _spend(svc, h)
    b, _, _ = await _spend(svc, h, extra_args={"request_id": "r-2", "nonce": "x"})
    assert a.id == b.id
    assert svc.counts()["pending"] == 1
    c, _, _ = await _spend(svc, h, plan="mp-pro-monthly", amount=50.01)
    assert c.id != a.id


async def test_auto_and_deny_routes(svc, h, fake_rt) -> None:
    i = h.db("SELECT * FROM market_prices", "market_prices")
    ctx = h.ctx(h.agent("trading-copilot@trading"))
    req = await svc.request(ctx, i, h.decision(i, control="ACT-02"))
    assert (req.status, req.required_role, req.uses, req.votes) == ("approved", "auto", 1, [])
    assert req.decided_at == req.created_at
    i2 = h.db("SELECT * FROM payment_cards", "payment_cards")
    denied = await svc.request(ctx, i2, h.decision(i2, control="ACT-02"))
    assert (denied.status, denied.required_role, denied.rule_id) == ("denied", "deny", "db-restricted")
    ok, why = svc.can_approve(h.member("u_katarzyna"), denied)
    assert not ok and "Request is already denied" in why
    subs = [e.data.get("sub") for e in fake_rt.audit.of("approval.decided")]
    assert "auto" in subs and "deny_rule" in subs


async def test_self_approval_by_sponsor(svc, h) -> None:
    req, _, _ = await _spend(svc, h, agent="research-agent@research", amount=12.0,
                             tool="opendata.buy_dataset", vendor="opendata-shop",
                             plan="eu-equities-2025-csv")
    assert (req.required_role, req.rule_id) == ("self", "spend-self")
    ok, why = svc.can_approve(h.member("u_james"), req)
    assert not ok and "Agnieszka Lewandowska or an admin" in why
    ok, why = svc.can_approve(h.agent("research-agent@research"), req)
    assert not ok and "Agents can never approve" in why
    with pytest.raises(PermissionError):
        await svc.vote(req.id, h.agent("research-agent@research"), "approve")
    done = await svc.vote(req.id, h.member("u_agnieszka"), "approve")
    assert done.status == "approved"


async def test_owner_only_480(svc, h) -> None:
    req, _, _ = await _spend(svc, h, agent="claude-code@platform", amount=480.0,
                             tool="payments.create_charge", vendor="gpucloud",
                             plan="a100-24h-reservation")
    assert (req.required_role, req.rule_id) == ("owner", "spend-owner")
    for mid in ("u_marek", "u_emily", "u_tomasz"):
        assert not svc.can_approve(h.member(mid), req)[0]
    assert svc.can_approve(h.member("u_katarzyna"), req)[0]


async def test_two_person_1500(svc, h) -> None:
    req, _, _ = await _spend(svc, h, amount=1500.0, tool="payments.create_charge",
                             vendor="gpucloud", plan="a100-cluster-week")
    assert (req.required_role, req.two_person, req.rule_id) == ("owner", True, "spend-owner-2p")
    step1 = await svc.vote(req.id, h.member("u_emily"), "approve")
    assert step1.status == "pending" and len(step1.votes) == 1
    ok, why = svc.can_approve(h.member("u_marek"), step1)
    assert not ok and "Two-person rule" in why
    ok, why = svc.can_approve(h.member("u_emily"), step1)
    assert not ok and "already voted" in why
    step2 = await svc.vote(req.id, h.member("u_katarzyna"), "approve")
    assert step2.status == "approved" and step2.decided_by == ["u_emily", "u_katarzyna"]


async def test_two_person_owner_first(svc, h) -> None:
    req, _, _ = await _spend(svc, h, amount=1500.0, tool="payments.create_charge",
                             vendor="gpucloud", plan="a100-cluster-week")
    s1 = await svc.vote(req.id, h.member("u_katarzyna"), "approve")
    assert s1.status == "pending"
    assert not svc.can_approve(h.member("u_piotr"), s1)[0]  # sponsor never counts
    s2 = await svc.vote(req.id, h.member("u_marek"), "approve")
    assert s2.status == "approved"


async def test_proposer_cosign_two_person(svc, h, fake_rt) -> None:
    fake_rt.policy.set_profile("strict")
    change = {"kind": "control.disable", "path": "controls[id=INJ-02].enabled",
              "control_id": "INJ-02", "before": True, "after": False, "loosening": True}
    proposal = {"patch": [{"op": "set", "path": "controls[id=INJ-02].enabled", "value": False}],
                "base_version": 1}
    i = h.config_interaction([change], proposal)
    ctx = h.ctx(h.member("u_katarzyna"), source="dashboard")
    req = await svc.request(ctx, i, h.decision(i, control="GOV-05", kind="config_change",
                                               action_type="control.disable",
                                               payload={"changes": [change], "proposal": proposal}))
    assert (req.required_role, req.two_person, req.rule_id) == ("owner", True, "disable-control-strict")
    assert req.status == "pending" and req.votes[0].comment == "proposer co-sign"
    assert not svc.can_approve(h.member("u_katarzyna"), req)[0]  # co-signed already
    done = await svc.vote(req.id, h.member("u_emily"), "approve")
    assert done.status == "approved" and done.decided_by == ["u_katarzyna", "u_emily"]
    assert done.execution["status"] == "applied" and done.execution["executor"] == "fallback"
    assert len(fake_rt.policy.calls) == 1
    call = fake_rt.policy.calls[0]
    assert call["source"] == "approval" and call["actor"].member_id == "u_emily"


async def test_any_eligible_deny_denies(svc, h) -> None:
    req, i, _ = await _spend(svc, h, amount=1500.0, tool="payments.create_charge",
                             vendor="gpucloud", plan="a100-cluster-week")
    await svc.vote(req.id, h.member("u_katarzyna"), "approve")
    with pytest.raises(PermissionError):
        await svc.vote(req.id, h.member("u_olivia"), "deny")
    done = await svc.vote(req.id, h.member("u_marek"), "deny", "too expensive")
    assert done.status == "denied" and done.decided_by == ["u_marek"]
    # deny cooldown: the identical call right away returns the same denied request
    again = await svc.request(h.ctx(h.agent("trading-copilot@trading")), i, h.decision(i))
    assert again.id == req.id and again.status == "denied"


async def test_cancel_rules(svc, h) -> None:
    req, _, _ = await _spend(svc, h)
    with pytest.raises(PermissionError):
        await svc.cancel(req.id, h.member("u_olivia"))
    done = await svc.cancel(req.id, h.member("u_piotr"))  # sponsor may withdraw
    assert done.status == "cancelled"
    with pytest.raises(ValueError):
        await svc.cancel(req.id, h.member("u_emily"))
    req2, _, _ = await _spend(svc, h, amount=60.0)
    assert (await svc.cancel(req2.id, h.member("u_marek"))).status == "cancelled"


async def test_lazy_expiry(svc, h, fake_rt) -> None:
    req, _, _ = await _spend(svc, h)
    row = svc.store.get(req.id)
    row.expires_at = utcnow() - timedelta(seconds=1)
    svc.store.update(row)
    got = await svc.get(req.id)
    assert got.status == "expired"
    assert fake_rt.audit.of("approval.expired")
    assert any(m["status"] == "expired" for m in fake_rt.bus.events("approval.updated"))
    with pytest.raises(ValueError):
        await svc.vote(req.id, h.member("u_emily"), "approve")


async def test_wait_wakes_fast_and_consumes_for_held_call(svc, h) -> None:
    req, i, _ = await _spend(svc, h)

    async def approve_soon() -> None:
        await asyncio.sleep(0.05)
        await svc.vote(req.id, h.member("u_emily"), "approve")

    task = asyncio.create_task(approve_soon())
    t0 = time.perf_counter()
    got = await svc.wait(req.id, 5)
    elapsed = time.perf_counter() - t0
    await task
    assert got.status == "approved" and elapsed < 0.5
    assert got.uses == 1  # the held call is the use
    # the MCP proxy seeing the same call within 30 s passes (one use)
    hit = await svc.find_preapproved(h.ctx(h.agent("trading-copilot@trading")), i)
    assert hit is not None and hit.uses == 1


async def test_wait_timeout_returns_pending(svc, h) -> None:
    req, _, _ = await _spend(svc, h)
    got = await svc.wait(req.id, 0.05)
    assert got.status == "pending"


async def test_redemption_single_use_and_window(svc, h) -> None:
    req, i, _ = await _spend(svc, h)
    await svc.vote(req.id, h.member("u_emily"), "approve")
    ctx = h.ctx(h.agent("trading-copilot@trading"))
    first = await svc.find_preapproved(ctx, i)
    assert first and first.uses == 1
    second = await svc.find_preapproved(h.ctx(h.agent("trading-copilot@trading")), i)
    assert second and second.id == req.id  # within the 30 s window: same use
    svc._redeemed[req.id] -= 3600  # window passed
    assert await svc.find_preapproved(h.ctx(h.agent("trading-copilot@trading")), i) is None


async def test_expired_grant_not_redeemable(svc, h) -> None:
    req, i, _ = await _spend(svc, h)
    done = await svc.vote(req.id, h.member("u_emily"), "approve")
    done.expires_at = utcnow() - timedelta(seconds=1)
    svc.store.update(done)
    assert await svc.find_preapproved(h.ctx(h.agent("trading-copilot@trading")), i) is None


async def test_token_for_other_params_rejected(svc, h, fake_rt) -> None:
    req, _, _ = await _spend(svc, h)
    await svc.vote(req.id, h.member("u_emily"), "approve")
    other = h.spend(4800.0, plan="mp-enterprise-annual")
    ctx = h.ctx(h.agent("trading-copilot@trading"), token=req.id)
    assert await svc.find_preapproved(ctx, other) is None
    assert ctx.state["apr.replay_of"] == f"{req.id} (params mismatch)"
    assert any(e.data.get("sub") == "approval.token_mismatch" for e in fake_rt.audit.of("system"))
    new = await svc.request(ctx, other, h.decision(other))
    assert new.id != req.id and new.payload["replay_of"] == f"{req.id} (params mismatch)"
    assert new.rule_id == "spend-owner-2p"


async def test_token_and_fingerprint_match(svc, h) -> None:
    req, i, _ = await _spend(svc, h)
    await svc.vote(req.id, h.member("u_emily"), "approve")
    hit = await svc.find_preapproved(h.ctx(h.agent("trading-copilot@trading"), token=req.id), i)
    assert hit and hit.id == req.id


async def test_other_principal_cannot_redeem(svc, h) -> None:
    req, i, _ = await _spend(svc, h)
    await svc.vote(req.id, h.member("u_emily"), "approve")
    assert await svc.find_preapproved(h.ctx(h.agent("chaos-agent@platform"), token=req.id), i) is None


async def test_config_and_budget_approvals_never_redeemable(svc, h) -> None:
    patch = [{"op": "set", "path": "budgets.limits[scope=agent:chaos-agent@platform,window=day].usd",
              "value": 1.0}]
    i = h.spend(1.0)
    d = h.decision(i, control="BUD-01", kind="budget_raise", action_type="budget.override",
                   payload={"patch": patch, "scope": "agent:chaos-agent@platform"},
                   labels={"scope": "agent:chaos-agent@platform", "scope_type": "agent"})
    req = await svc.request(h.ctx(h.agent("chaos-agent@platform")), i, d)
    assert (req.kind, req.rule_id) == ("budget_raise", "budget-override")
    done = await svc.vote(req.id, h.member("u_marek"), "approve")
    assert done.execution["status"] == "applied" and done.uses == done.max_uses
    assert await svc.find_preapproved(h.ctx(h.agent("chaos-agent@platform")), i) is None


async def test_flood_caps(svc, h, fake_rt) -> None:
    fake_rt.policy.snap.doc.approvals.defaults.max_pending_per_principal = 2  # type: ignore[attr-defined]
    fake_rt.policy.snap.compiled.clear()
    a, _, _ = await _spend(svc, h, amount=30.0)
    b, _, _ = await _spend(svc, h, amount=31.0)
    c, _, _ = await _spend(svc, h, amount=32.0)
    assert a.status == b.status == "pending"
    assert c.status == "denied" and c.rule_id == "defaults.max_pending"
    assert c.payload["routing"]["flood_cap"] == "max_pending_per_principal"
    # other principals are unaffected
    d, _, _ = await _spend(svc, h, agent="claude-code@platform", amount=33.0)
    assert d.status == "pending"


async def test_list_and_counts(svc, h) -> None:
    await _spend(svc, h)
    await _spend(svc, h, amount=480.0, agent="claude-code@platform")
    items = await svc.list_requests(status="pending")
    assert len(items) == 2 and items[0].created_at >= items[1].created_at
    counts = svc.counts()
    assert set(counts) == {"pending", "approved", "denied", "expired", "cancelled"}
    assert counts["pending"] == 2


async def test_create_manual_org_change_runs_action_executor(svc, h) -> None:
    from aegis.core.types import ApprovalDraft

    seen = []

    async def org_exec(req):
        if not req.action_type.startswith("org."):
            return None
        seen.append(req.id)
        return {"status": "applied", "org_change_id": "och_1"}

    svc.register_executor("action", org_exec)
    draft = ApprovalDraft(kind="action", action_type="org.role.promote_admin",
                          title="Promote Piotr to admin", resource="member:u_piotr",
                          labels={"category": "org", "to_role": "admin"})
    req = await svc.create_manual(h.member("u_marek"), draft)
    assert (req.required_role, req.rule_id) == ("owner", "org-privileged")
    assert not svc.can_approve(h.member("u_marek"), req)[0]
    done = await svc.vote(req.id, h.member("u_katarzyna"), "approve")
    assert done.execution == {"status": "applied", "org_change_id": "och_1", "executor": "registered"}
    assert seen == [req.id]
    # a plain data-plane action approval is untouched by the org executor
    r2, _i2, _ = await _spend(svc, h)
    d2 = await svc.vote(r2.id, h.member("u_emily"), "approve")
    assert d2.execution is None and d2.uses == 0


async def test_restart_safety(fake_rt, h) -> None:
    """Pending rows survive a service restart on the same connection."""
    import sqlite3

    from aegis.approvals.service import create

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    fake_rt.db = lambda: conn
    s1 = create(fake_rt)
    await s1.start()
    i = h.spend(50.0)
    req = await s1.request(h.ctx(h.agent("trading-copilot@trading")), i, h.decision(i))
    await s1.stop()
    s2 = create(fake_rt)
    await s2.start()
    assert (await s2.get(req.id)).status == "pending"
    assert (await s2.vote(req.id, h.member("u_emily"), "approve")).status == "approved"
    await s2.stop()
