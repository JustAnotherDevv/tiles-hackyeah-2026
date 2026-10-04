"""BUD-V04 / V05 / V12: ledger core (AND chain, reserve/settle/release, TTL, thresholds,
coalescing, concurrency, perf)."""

from __future__ import annotations

import asyncio
import logging
import statistics
import time

import pytest

from aegis.budgets.events import UpdateCoalescer
from aegis.budgets.ledger import Ledger
from aegis.core.types import BudgetDenial, Reservation, Usage
from tests.lib.perf import bound
from tests.unit.budgets_ledger.conftest import agent, ctx, make_snapshot, snippet_doc

RESEARCH = agent("research-agent@research", "research")
CHAOS = agent("chaos-agent@platform", "platform")
CC = agent("claude-code@platform", "platform")


async def test_and_semantics_names_team_scope(led: Ledger, clock) -> None:
    await led.import_usage("team:research", "usd", 14.99, "day")
    c = ctx(RESEARCH)
    res = await led.reserve(c, Usage(cost_usd=0.05))
    assert isinstance(res, BudgetDenial)
    assert res.scope == "team:research" and res.dimension == "usd" and res.window == "day"
    assert res.limit == 15 and res.used == pytest.approx(14.99)
    # the agent itself still has headroom
    assert led.used("agent:research-agent@research", "day", "usd") == 0.0


async def test_release_restores_headroom(led: Ledger, clock) -> None:
    c = ctx(CHAOS)
    r1 = await led.reserve(c, Usage(cost_usd=0.40))
    assert isinstance(r1, Reservation)
    denied = await led.reserve(c, Usage(cost_usd=0.20))
    assert isinstance(denied, BudgetDenial) and denied.scope == "agent:chaos-agent@platform"
    await led.release(r1)
    r2 = await led.reserve(c, Usage(cost_usd=0.20))
    assert isinstance(r2, Reservation)


async def test_settle_posts_actual_and_logs_overshoot(led: Ledger, clock, caplog) -> None:
    c = ctx(CC)
    r = await led.reserve(c, Usage(cost_usd=0.01, input_tokens=100))
    assert isinstance(r, Reservation)
    with caplog.at_level(logging.INFO, logger="aegis.budgets.ledger"):
        await led.settle(r, Usage(cost_usd=0.05, input_tokens=100, estimated=False))
    assert "overshoot" in caplog.text
    assert led.used("agent:claude-code@platform", "day", "usd") == pytest.approx(0.05)
    assert led.used("org:acme-capital", "month", "usd") == pytest.approx(0.05)
    assert led.session_usage("s1")["usd"] == pytest.approx(0.05)
    assert not led._reserved  # nothing left reserved


async def test_ttl_expiry_settles_at_estimate(led: Ledger, clock) -> None:
    c = ctx(CC)
    r = await led.reserve(c, Usage(cost_usd=0.03))
    assert isinstance(r, Reservation)
    assert await led.sweep() == 0
    clock.advance(601)
    assert await led.sweep() == 1
    assert led.used("agent:claude-code@platform", "day", "usd") == pytest.approx(0.03)
    assert not led._res


async def test_thresholds_emitted_once_each(led: Ledger, rt, clock) -> None:
    c = ctx(CHAOS)
    for amt in (0.26, 0.15, 0.10, 0.05):
        await led.commit(c, Usage(cost_usd=amt))
    ev = [e for e in rt.bus.of("budget.threshold") if e["scope"] == "agent:chaos-agent@platform"]
    usd = [e for e in ev if e["dimension"] == "usd"]
    assert [e["state"] for e in usd] == ["ok", "soft", "hard"]
    assert [round(e["pct"]) for e in usd] == [52, 82, 102]


async def test_budget_updated_published(led: Ledger, rt, clock) -> None:
    await led.commit(ctx(CC), Usage(cost_usd=0.02))
    upd = rt.bus.of("budget.updated")
    assert upd and any(s["scope"] == "agent:claude-code@platform" for s in upd[-1]["statuses"])
    assert "aegis_budget_utilization_ratio" in rt.metrics.gauges


async def test_coalescer_limits_rate(clock) -> None:
    calls: list[set | None] = []
    co = UpdateCoalescer(lambda s: calls.append(s), max_per_s=2.0)
    co.mark({"a"})  # first: immediate
    co.mark({"b"})
    co.mark({"c"})  # coalesced with b
    assert calls == [{"a"}]
    clock.advance(0.5)
    await asyncio.sleep(0.55)
    assert calls == [{"a"}, {"b", "c"}]
    co.cancel()


async def test_status_without_limit_has_usd_day_row(led: Ledger, clock) -> None:
    rows = await led.status("agent:nobody@x")
    assert any(r.dimension == "usd" and r.window == "day" and r.label == "no limit" for r in rows)


async def test_zero_usage_check_ignores_live_counters(led: Ledger, clock) -> None:
    await led.import_usage("agent:chaos-agent@platform", "usd", 0.5, "day")
    c = ctx(CHAOS)
    assert isinstance(await led.check(c, Usage(cost_usd=0.01)), BudgetDenial)
    ok = await led.check(c, Usage(cost_usd=0.01), zero_usage=True)
    assert isinstance(ok, Reservation) and not led._res  # check never reserves


async def test_concurrency_exactly_ten(rt, settings, clock) -> None:
    def add(d: dict) -> None:
        d["budgets"]["limits"].append({"scope": "session:conc", "window": "session", "usd": 0.10})

    rt.policy.snap = make_snapshot(snippet_doc(add))
    led = Ledger(rt, persist=False)
    c = ctx(CC, session="conc", snap=rt.policy.snap)
    results = await asyncio.gather(*(led.reserve(c, Usage(cost_usd=0.01)) for _ in range(200)))
    granted = [r for r in results if isinstance(r, Reservation)]
    assert len(granted) == 10
    denied = [r for r in results if isinstance(r, BudgetDenial)]
    assert denied and all(d.scope == "session:conc" for d in denied)
    await asyncio.gather(*(led.settle(r, Usage(cost_usd=0.011)) for r in granted))
    assert led.session_usage("conc")["usd"] <= 0.10 + 0.011 + 1e-9


async def test_reset_scope_and_all(led: Ledger, clock) -> None:
    await led.import_usage("team:trading", "usd", 10, "day")
    await led.reset("team:trading")
    assert led.used("team:trading", "day", "usd") == 0.0
    await led.import_usage("team:trading", "usd", 10, "day")
    await led.reset(None, reseed=False)
    assert led.used("team:trading", "day", "usd") == 0.0


@pytest.mark.slow
async def test_perf_reserve_settle(rt, clock) -> None:
    led = Ledger(rt, persist=False)
    led.coalescer.immediate = False
    led.coalescer.min_interval = 1e9  # publish once, then coalesce (as in production)
    c = ctx(CC, session="perf", snap=rt.policy.snap)
    scopes = [*led.scopes_for(c.identity, "perf"), "model:mock-echo"]
    est = Usage(cost_usd=0.000001, input_tokens=1, output_tokens=1, requests=0)
    lat: list[float] = []
    for _ in range(10_000):
        t0 = time.perf_counter()
        r = await led.reserve(c, est, scopes)
        await led.settle(r, est)  # type: ignore[arg-type]
        lat.append((time.perf_counter() - t0) * 1000)
    led.coalescer.cancel()
    p95 = statistics.quantiles(lat, n=20)[18]
    print(f"reserve+settle p95={p95:.3f} ms median={statistics.median(lat):.3f} ms")
    assert p95 < bound(1.0), f"p95={p95:.3f} ms"
