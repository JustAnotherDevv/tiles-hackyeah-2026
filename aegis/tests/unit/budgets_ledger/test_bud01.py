"""BUD-V07: BUD-01 control (clamp, downgrade, 402, budget_raise approval, dry-run, self-test,
on_complete pricing + settle, local compute fallback)."""

from __future__ import annotations

import pytest

from aegis.budgets.ledger import Ledger
from aegis.controls.budget.bud01_budgets import BudgetsControl
from aegis.core.types import Outcome, Usage, Verdict
from tests.unit.budgets_ledger.conftest import (
    agent,
    cfg,
    ctx,
    human,
    make_snapshot,
    model_hop,
    snippet_doc,
    tool_hop,
)

C = BudgetsControl()
CC = agent("claude-code@platform", "platform")
CHAOS = agent("chaos-agent@platform", "platform")


def verdict(action: str = "allow", mutations=None) -> Verdict:
    return Verdict(
        id="dec_1",
        request_id="req_1",
        interaction_id="i1",
        action=action,  # type: ignore[arg-type]
        mutations=mutations or [],
    )


@pytest.mark.parametrize(
    ("raw", "meta", "path"),
    [
        ({"max_tokens": 8000}, {"wire": "anthropic"}, "max_tokens"),
        ({"max_completion_tokens": 8000}, {"wire": "openai"}, "max_completion_tokens"),
        ({"options": {"num_predict": 8000}}, {"wire": "ollama"}, "options.num_predict"),
    ],
)
async def test_clamp_path_per_wire(led, snap, clock, raw, meta, path) -> None:
    i = model_hop(max_tokens=8000, raw=raw, meta=meta)
    d = await C.evaluate(ctx(CC, snap=snap), i, cfg(snap, "BUD-01"))
    assert d is not None and d.action == "allow"
    clamp = [m for m in d.mutations if m.target == "body"]
    assert clamp and clamp[0].path == path and clamp[0].value == 4096
    assert d.meta["pricing_version"] == led.pricing.version
    assert d.meta["response_headers"]["x-aegis-budget-remaining"].startswith("usd=")


async def test_clamp_skipped_with_thinking(led, snap, clock) -> None:
    raw = {"max_tokens": 32000, "thinking": {"type": "enabled", "budget_tokens": 16000}}
    i = model_hop(max_tokens=32000, raw=raw, meta={"wire": "anthropic"})
    d = await C.evaluate(ctx(CC, snap=snap), i, cfg(snap, "BUD-01"))
    assert d is not None and not [m for m in d.mutations if m.target == "body"]


async def test_soft_downgrade_to_local_judge(led: Ledger, snap, clock) -> None:
    await led.import_usage("agent:claude-code@platform", "usd", 25.5, "day")  # 85 % of $30
    d = await C.evaluate(ctx(CC, snap=snap), model_hop(), cfg(snap, "BUD-01"))
    assert d is not None and d.action == "redact"
    route = [m for m in d.mutations if m.target == "route"]
    assert route and route[0].path == "model" and route[0].value == "aegis-judge"
    assert d.meta["response_headers"]["x-aegis-downgraded-from"] == "mock-echo"
    assert led.enforcement.summary()["downgrades"] == 1


async def test_big_prompt_not_downgraded_to_local(led: Ledger, snap, clock) -> None:
    await led.import_usage("agent:claude-code@platform", "usd", 25.5, "day")
    i = model_hop(est_input_tokens=20_000)
    d = await C.evaluate(ctx(CC, snap=snap), i, cfg(snap, "BUD-01"))
    assert d is not None and d.action == "log"
    assert not [m for m in d.mutations if m.target == "route"]


async def test_no_downgrade_local_to_remote(led: Ledger, clock) -> None:
    def to_remote(d: dict) -> None:
        d["models"]["downgrade"] = [{"from": "*", "to": "claude-haiku-4-5"}]

    snap = make_snapshot(snippet_doc(to_remote))
    led.rt.policy.snap = snap
    await led.import_usage("agent:claude-code@platform", "usd", 25.5, "day")
    i = model_hop(model="qwen3:0.6b", dest="local")
    d = await C.evaluate(ctx(CC, snap=snap), i, cfg(snap, "BUD-01"))
    assert d is not None and d.action in ("allow", "log")
    assert not [m for m in d.mutations if m.target == "route"]


async def test_hard_limit_402(led: Ledger, snap, clock) -> None:
    await led.import_usage("member:u_piotr", "usd", 5.0, "day")
    d = await C.evaluate(ctx(human("u_piotr"), snap=snap), model_hop(), cfg(snap, "BUD-01"))
    assert d is not None and d.action == "block"
    assert d.http_status == 402 and d.error_type == "budget_exceeded"
    assert d.meta["response_headers"]["x-should-retry"] == "false"
    assert "member:u_piotr" in d.reason and "Stop and summarise" in d.reason
    assert not led._res
    assert led.enforcement.summary()["hard_blocks"] == 1


async def test_chaos_agent_budget_raise_approval(led: Ledger, snap, clock) -> None:
    await led.import_usage("agent:chaos-agent@platform", "usd", 0.5, "day")
    c = ctx(CHAOS, session="ses_runaway", snap=snap)
    d = await C.evaluate(c, model_hop("step 7"), cfg(snap, "BUD-01"))
    assert d is not None and d.action == "require_approval"
    a = d.approval
    assert a is not None and a.kind == "budget_raise" and a.action_type == "budget.override"
    assert a.labels["scope"] == "agent:chaos-agent@platform" and a.labels["scope_type"] == "agent"
    p = a.payload["patch"][0]
    assert p["path"] == "budgets.limits[scope=agent:chaos-agent@platform,window=day].usd"
    assert p["op"] == "set" and p["value"] == 1.0
    assert a.payload["before"] == 0.5 and a.payload["after"] == 1.0
    assert a.payload["tripped_by"]["session_id"] == "ses_runaway"
    assert a.resource == "budget:agent:chaos-agent@platform"


async def test_dry_run_reserves_nothing(led: Ledger, snap, clock) -> None:
    c = ctx(CC, snap=snap, dry_run=True)
    d = await C.evaluate(c, model_hop(), cfg(snap, "BUD-01"))
    assert d is not None and d.action == "allow"
    assert not led._res and not led._reserved


async def test_selftest_ignores_live_usage(led: Ledger, snap, clock) -> None:
    await led.import_usage("agent:chaos-agent@platform", "usd", 0.5, "day")
    c = ctx(CHAOS, snap=snap, source="selftest")
    d = await C.evaluate(c, model_hop(), cfg(snap, "BUD-01"))
    assert d is not None and d.action in ("allow", "log", "redact")
    assert not led._res
    # static limit logic still applies: usd 0 blocks even in a self-test
    z = await C.evaluate(
        ctx(agent("selftest-zero", "platform"), snap=snap, source="selftest"),
        model_hop(),
        cfg(snap, "BUD-01"),
    )
    assert z is not None and z.action == "block" and z.http_status == 402


async def test_on_complete_prices_and_settles(led: Ledger, snap, clock) -> None:
    c = ctx(CC, snap=snap)
    i = model_hop()
    d = await C.evaluate(c, i, cfg(snap, "BUD-01"))
    assert d is not None and d.action == "allow" and len(led._res) == 1
    out = Outcome(usage=Usage(input_tokens=1000, output_tokens=500, estimated=False))
    await C.on_complete(c, i, verdict(), out, cfg(snap, "BUD-01"))
    assert out.usage.cost_usd == pytest.approx(0.0105)  # mock-* priced like Sonnet
    assert not led._res and not led._reserved
    assert led.used("agent:claude-code@platform", "day", "usd") == pytest.approx(0.0105)
    assert led.session_usage("s1")["requests"] == 1


async def test_local_compute_fallback_from_wall_time(led: Ledger, snap, clock) -> None:
    c = ctx(CC, snap=snap)
    i = model_hop(model="aegis-judge", dest="local")
    d = await C.evaluate(c, i, cfg(snap, "BUD-01"))
    assert d is not None
    out = Outcome(usage=Usage(input_tokens=50, output_tokens=20), upstream_ms=2000)
    await C.on_complete(c, i, verdict(), out, cfg(snap, "BUD-01"))
    assert out.usage.compute_s == pytest.approx(2.0)
    assert out.usage.cost_usd == pytest.approx(0.0004)
    assert led.used("agent:claude-code@platform", "day", "compute_s") == pytest.approx(2.0)


async def test_blocked_upstream_releases(led: Ledger, snap, clock) -> None:
    c = ctx(CC, snap=snap)
    i = model_hop()
    await C.evaluate(c, i, cfg(snap, "BUD-01"))
    await C.on_complete(c, i, verdict(), Outcome(status_code=500), cfg(snap, "BUD-01"))
    assert not led._res and led.used("agent:claude-code@platform", "day", "usd") == 0.0


async def test_spend_action_reserves_spend_usd(led: Ledger, snap, clock) -> None:
    c = ctx(agent("trading-copilot@trading", "trading"), snap=snap)
    i = tool_hop("stripe.charge", action_type="spend.charge", amount_usd=2500.0)
    d = await C.evaluate(c, i, cfg(snap, "BUD-01"))
    assert d is not None and d.action == "block" and d.http_status == 402
    assert d.meta["dimension"] == "spend_usd" and d.meta["scope"] == "team:trading"


async def test_f6_runaway_reaches_budget_raise(led: Ledger, snap, clock) -> None:
    """F6: mock-echo, max_tokens 4096 -> the $0.50 wall (approval) arrives in < 10 calls; the
    chaos entry's `on_soft: warn` keeps the 80 % downgrade from deferring it forever."""
    conf = cfg(snap, "BUD-01")
    for n in range(1, 11):
        c = ctx(CHAOS, session="ses_runaway", snap=snap, request_id=f"r{n}")
        i = model_hop(f"step {n} [[LONG:20000]]", max_tokens=4096, id=f"i{n}")
        d = await C.evaluate(c, i, conf)
        assert d is not None
        assert not [m for m in d.mutations if m.target == "route"]
        if d.action == "require_approval":
            break
        out = Outcome(usage=Usage(input_tokens=10, output_tokens=4096), model_used="mock-echo")
        await C.on_complete(c, i, verdict(d.action), out, conf)
    assert d.action == "require_approval" and 6 <= n <= 10
