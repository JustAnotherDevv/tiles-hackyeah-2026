"""APR-10/11/12: sweeper expiry, routing self-test warning after a policy apply, demo history seed."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from aegis.core.types import utcnow


async def test_sweep_expires_and_publishes(svc, h, fake_rt) -> None:
    i = h.spend(50.0)
    req = await svc.request(h.ctx(h.agent("trading-copilot@trading")), i, h.decision(i))
    assert fake_rt.metrics.gauges.get("aegis_approvals_pending") == 1
    req.expires_at = utcnow() - timedelta(seconds=1)
    svc.store.update(req)
    expired = await svc.sweep()
    assert [r.id for r in expired] == [req.id]
    assert (await svc.get(req.id)).status == "expired"
    assert any(m["status"] == "expired" for m in fake_rt.bus.events("approval.updated"))
    assert fake_rt.audit.of("approval.expired")
    assert fake_rt.metrics.gauges["aegis_approvals_pending"] == 0
    assert await svc.sweep() == []


async def test_sweeper_loop_runs_and_stops(svc, h, fake_rt) -> None:
    from aegis.approvals.expiry import sweeper_loop

    i = h.spend(50.0)
    req = await svc.request(h.ctx(h.agent("trading-copilot@trading")), i, h.decision(i))
    req.expires_at = utcnow() - timedelta(seconds=1)
    svc.store.update(req)
    task = asyncio.create_task(sweeper_loop(svc))
    for _ in range(40):
        await asyncio.sleep(0.1)
        if (await svc.get(req.id)).status == "expired":
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert (await svc.get(req.id)).status == "expired"


async def test_policy_change_runs_selftest_and_warns(svc, fake_rt, make_doc_fn, make_snapshot_fn) -> None:
    assert svc._on_policy_change in fake_rt.policy.callbacks
    await svc._on_policy_change(fake_rt.policy.snapshot())
    assert svc.selftest_results and all(r["passed"] for r in svc.selftest_results)
    assert not fake_rt.bus.events("system")
    # live edit: spend-admin now needs the owner -> self-test turns red with a system warning
    doc = fake_rt.policy.snapshot().doc
    approvals = doc.approvals.model_dump(mode="json", by_alias=True, exclude_none=True)
    for rule in approvals["rules"]:
        if rule["id"] == "spend-admin":
            rule["approver"] = "owner"
    bad = make_snapshot_fn(make_doc_fn(approvals=approvals), 2)
    await svc._on_policy_change(bad)
    warnings = fake_rt.bus.events("system")
    assert warnings, "no system warning published"
    msg = warnings[-1].get("message", "")
    assert msg.startswith("Approval routing self-test:") and "saas-subscription-50-needs-admin" in msg


async def test_demo_history_seed_only_when_empty(svc, fake_rt) -> None:
    from aegis.approvals.seed import seed_history

    n = await seed_history(svc)
    assert n >= 3
    statuses = {r.status for r in await svc.list_requests(limit=50)}
    assert {"approved", "denied", "expired"} <= statuses
    assert all(r.labels.get("seed") == "true" for r in await svc.list_requests(limit=50))
    assert await seed_history(svc) == 0
