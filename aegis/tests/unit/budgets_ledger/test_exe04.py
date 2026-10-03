"""BUD-V08 (part 1): EXE-04 loop ladder, detectors, rate limits, step cap, dedupe."""

from __future__ import annotations

import asyncio

from aegis.budgets.ledger import Ledger
from aegis.controls.budget.exe04_loops import LoopBreakerControl
from aegis.core.types import Decision, Outcome, Verdict
from tests.unit.budgets_ledger.conftest import agent, cfg, ctx, model_hop, tool_hop

X = LoopBreakerControl()
CHAOS = agent("chaos-agent@platform", "platform")


async def run(snap, c, i, *, error: str | None = None) -> Decision | None:
    """evaluate + on_complete like the pipeline does (blocked hops complete as blocked)."""
    conf = cfg(snap, "EXE-04")
    d = await X.evaluate(c, i, conf)
    if d is None:
        v = Verdict(id="d", request_id=c.request_id, interaction_id=i.id, action="allow")
        await X.on_complete(c, i, v, Outcome(status_code=200, error=error), conf)
    else:
        v = Verdict(
            id="d",
            request_id=c.request_id,
            interaction_id=i.id,
            action="block",
            primary=d,
            decisions=[d],
        )
        await X.on_complete(c, i, v, Outcome(status_code=d.http_status or 200), conf)
    return d


def fetch(n: int = 0, **kw) -> object:
    return tool_hop("web.fetch_url", {"url": f"https://example.com/{n}"}, id=f"t{n}", **kw)


async def test_ladder_tool_error_block_kill(led: Ledger, snap, clock) -> None:
    c = ctx(CHAOS, session="ses_loop", snap=snap)
    assert await run(snap, c, fetch()) is None
    assert await run(snap, c, fetch()) is None
    d3 = await run(snap, c, fetch())
    assert d3 is not None and d3.action == "block" and d3.http_status is None
    assert "repeated 3x" in d3.reason and d3.meta["step"] == "tool_error"
    d4 = await run(snap, c, fetch())
    assert d4 is not None and d4.http_status == 429 and d4.retry_after_s == 30
    assert d4.meta["response_headers"]["x-should-retry"] == "false"
    # still cooling down
    d5 = await run(snap, c, fetch(99))
    assert d5 is not None and d5.http_status == 429 and d5.meta["stop"] == "cooldown"
    clock.advance(31)
    d6 = await run(snap, c, fetch())
    assert d6 is not None and d6.error_type == "killed"
    assert d6.http_status == 429 and d6.retry_after_s == 3600  # A-07: never 403
    assert d6.meta["response_headers"]["x-should-retry"] == "false"
    # the session stays killed (runtime) for model calls too
    d7 = await run(snap, c, model_hop("hello"))
    assert d7 is not None and d7.error_type == "killed"
    await asyncio.sleep(0)  # let the background persistence run
    assert led.rt.policy.applied and led.rt.policy.applied[0]["source"] == "budgets-ledger"
    ev = led.rt.bus.of("killswitch")
    assert ev and ev[0]["scope"] == "session:ses_loop" and ev[0]["active"] is True
    summ = led.enforcement.summary()
    assert summ["kills"] >= 1 and summ["loop_detections"] == 3


async def test_claude_code_also_gets_429(led: Ledger, snap, clock) -> None:
    cc = agent("claude-code@platform", "platform")
    c = ctx(cc, session="ses_cc", snap=snap)
    led.kills.add("ses_cc", "test")
    d = await run(snap, c, fetch())
    assert d is not None and d.http_status == 429 and d.error_type == "killed"


async def test_distinct_calls_allowed(led: Ledger, snap, clock) -> None:
    c = ctx(CHAOS, session="ses_distinct", snap=snap)
    for n in range(10):
        assert await run(snap, c, fetch(n)) is None


async def test_short_cycle(led: Ledger, snap, clock) -> None:
    # claude-code has repeat=6 (agent_overrides), so the A,B cycle trips before exact_repeat
    c = ctx(agent("claude-code@platform"), session="ses_cycle", snap=snap)
    seq = [1, 2, 1, 2, 1, 2]
    out = [await run(snap, c, fetch(n)) for n in seq]
    assert all(d is None for d in out[:5])
    assert out[5] is not None and out[5].meta["detector"] == "short_cycle"


async def test_error_streak(led: Ledger, snap, clock) -> None:
    c = ctx(CHAOS, session="ses_err", snap=snap)
    for n in range(5):
        assert await run(snap, c, fetch(n), error="tool_error") is None
    d = await run(snap, c, fetch(42))
    assert d is not None and d.meta["detector"] == "error_streak"


async def test_exe04_blocked_hops_not_counted(led: Ledger, snap, clock) -> None:
    c = ctx(CHAOS, session="ses_nc", snap=snap)
    for _ in range(3):
        await run(snap, c, fetch())  # third is our tool_error block
    assert led.loops.peek("ses_nc").error_streak == 0


async def test_hook_and_mcp_duplicate_counted_once(led: Ledger, snap, clock) -> None:
    hook = ctx(CHAOS, session="ses_dup", snap=snap, source="hook")
    mcp = ctx(CHAOS, session="ses_dup", snap=snap, source="mcp", request_id="req_2")
    # the same call seen by both sources, twice -> 2 logical calls, no trip at repeat=3
    for _ in range(2):
        assert await run(snap, hook, fetch()) is None
        assert await run(snap, mcp, fetch()) is None
        clock.advance(6)  # next logical call after the dedupe window
    assert len(led.loops.peek("ses_dup").tool_hist) == 2


async def test_rate_limit_429_retry_after(led: Ledger, snap, clock) -> None:
    c = ctx(agent("rate-bot@platform"), session="ses_rate", snap=snap)
    for n in range(60):
        assert await run(snap, c, fetch(n)) is None
    d = await run(snap, c, fetch(1000))
    assert d is not None and d.http_status == 429 and d.error_type == "rate_limited"
    assert d.retry_after_s and int(d.meta["response_headers"]["retry-after"]) == d.retry_after_s


async def test_step_cap_402(led: Ledger, snap, clock) -> None:
    c = ctx(CHAOS, session="ses_steps", snap=snap)
    await led.import_usage("session:ses_steps", "requests", 200, "session")
    d = await run(snap, c, model_hop("next step"))
    assert d is not None and d.http_status == 402 and d.error_type == "budget_exceeded"


async def test_model_repeat(led: Ledger, snap, clock) -> None:
    c = ctx(CHAOS, session="ses_mr", snap=snap)
    out = [await run(snap, c, model_hop("same prompt")) for _ in range(5)]
    assert all(d is None for d in out[:4])
    assert out[4] is not None and out[4].meta["detector"] == "model_repeat"


async def test_selftest_and_dry_run(led: Ledger, snap, clock) -> None:
    led.kills.add("ses_st", "test")
    st = ctx(CHAOS, session="ses_st", snap=snap, source="selftest")
    assert await X.evaluate(st, fetch(), cfg(snap, "EXE-04")) is None
    dry = ctx(CHAOS, session="ses_dry", snap=snap, dry_run=True)
    for _ in range(5):
        assert await X.evaluate(dry, fetch(), cfg(snap, "EXE-04")) is None
    assert led.loops.peek("ses_dry") is None
