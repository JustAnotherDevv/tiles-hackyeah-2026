"""BUD-V08 (part 2): kill switch matching, toggle patches, policy-swap diff events."""

from __future__ import annotations

import asyncio

from aegis.budgets import killswitch as ks
from aegis.budgets.ledger import Ledger
from aegis.controls.budget.exe04_loops import LoopBreakerControl
from aegis.core.policy_schema import KillSwitch
from tests.unit.budgets_ledger.conftest import agent, cfg, ctx, make_snapshot, snippet_doc, tool_hop

X = LoopBreakerControl()
CHAOS = agent("chaos-agent@platform", "platform")


def killed_snap(version: int = 2, **ks_fields):
    def mut(d: dict) -> None:
        d["budgets"]["kill_switch"].update(ks_fields)

    return make_snapshot(snippet_doc(mut), version=version)


async def test_agent_glob_kill_blocks(led: Ledger, clock) -> None:
    snap = killed_snap(agents=["chaos-*"])
    d = await X.evaluate(ctx(CHAOS, snap=snap), tool_hop(), cfg(snap, "EXE-04"))
    assert d is not None and d.error_type == "killed" and d.http_status == 429
    assert d.retry_after_s == 3600 and "agent:chaos-agent@platform" in d.reason
    other = await X.evaluate(
        ctx(agent("claude-code@platform"), snap=snap), tool_hop(), cfg(snap, "EXE-04")
    )
    assert other is None


async def test_global_kill_and_selftest_bypass(led: Ledger, clock) -> None:
    snap = killed_snap(**{"global": True})
    d = await X.evaluate(ctx(CHAOS, snap=snap), tool_hop(), cfg(snap, "EXE-04"))
    assert d is not None and d.error_type == "killed"
    st = await X.evaluate(ctx(CHAOS, snap=snap, source="selftest"), tool_hop(), cfg(snap, "EXE-04"))
    assert st is None


def test_match_scopes() -> None:
    k = KillSwitch(teams=["trading"], members=["u_piotr"], sessions=["s9"])
    assert ks.match(k, agent("x@trading", "trading"), "s1") == "team:trading"
    assert ks.match(k, agent("x@platform"), "s9") == "session:s9"
    assert ks.match(k, agent("x@platform"), "s1") is None


def test_toggle_patch_and_noop(snap) -> None:
    on = ks.toggle_patch(snap, "agent:chaos-agent@platform", True)
    assert on and on[0].op == "append" and on[0].path == "budgets.kill_switch.agents"
    assert on[0].value == "chaos-agent@platform"
    assert ks.toggle_patch(snap, "agent:chaos-agent@platform", False) is None  # already off
    s2 = killed_snap(agents=["chaos-agent@platform"])
    off = ks.toggle_patch(s2, "agent:chaos-agent@platform", False)
    assert off and off[0].op == "remove" and off[0].path == "budgets.kill_switch.agents[0]"
    g = ks.toggle_patch(snap, "global", True)
    assert g and g[0].op == "set" and g[0].path == "budgets.kill_switch.global" and g[0].value
    assert ks.diff(KillSwitch(), KillSwitch(agents=["a"])) == [("agent:a", True)]


async def test_policy_swap_publishes_killswitch_and_audit(rt, clock) -> None:
    led = Ledger(rt, persist=False)
    await led.start()
    try:
        rt.policy.swap(killed_snap(agents=["chaos-agent@platform"]))
        await asyncio.sleep(0.01)
        ev = rt.bus.of("killswitch")
        assert ev and ev[-1] == {
            "scope": "agent:chaos-agent@platform",
            "active": True,
            "actor": None,
        }
        types = [e.event_type for e in rt.audit.events]
        assert "killswitch.toggled" in types
        assert rt.metrics.gauges.get("aegis_killswitch_active") == 1.0
        rt.policy.swap(killed_snap(version=3))
        await asyncio.sleep(0.01)
        assert rt.bus.of("killswitch")[-1]["active"] is False
    finally:
        await led.stop()
