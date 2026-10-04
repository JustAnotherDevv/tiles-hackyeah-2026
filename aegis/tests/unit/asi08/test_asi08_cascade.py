"""ASI08: RES-01 cascading-failure breaker - quarantine, downstream circuit, cascade taint.

Positive: healthy agents / healthy peers / healthy servers are untouched. Negative: an agent
whose actions keep getting blocked is quarantined (require_approval), a failing MCP server is
circuit-broken for every agent (block 503), and outputs of a quarantined agent are dropped and
taint their consumers transitively.
"""

from __future__ import annotations

import pytest

from aegis.controls.resilience._state import CascadeState
from aegis.controls.resilience.res01_cascade import CascadeBreaker
from aegis.core.types import (
    Decision,
    Identity,
    Interaction,
    Outcome,
    RequestContext,
    TextSegment,
    Verdict,
)
from tests.unit.injection_defense._helpers import make_cfg

A, B, C = "research-agent@research", "trading-copilot@trading", "claude-code@platform"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def ctl(clock: Clock) -> CascadeBreaker:
    return CascadeBreaker(state=CascadeState(), clock=clock)


def cfg(**params):
    return make_cfg("RES-01", action="require_approval", severity="high", params=params)


def ctx(agent: str = A, session: str = "s1", **kw) -> RequestContext:
    kw.setdefault("source", "guard")
    return RequestContext(
        request_id="r", session_id=session, identity=Identity(agent_id=agent), **kw
    )


def tool(name: str = "Bash", **kw) -> Interaction:
    kw.setdefault("surface", "mcp.call" if "." in name else "tool.input")
    kw.setdefault("kind", "mcp" if "." in name else "tool_call")
    return Interaction(tool_name=name, tool_args={"q": "x"}, **kw)


def a2a_result(
    peer: str, text: str = "peer answer", peer_session: str | None = None
) -> Interaction:
    labels = {"peer_agent": peer, **({"peer_session": peer_session} if peer_session else {})}
    return Interaction(
        kind="a2a",
        surface="a2a.result",
        direction="in",
        labels=labels,
        segments=[TextSegment(path="result", text=text, role="tool_result", trusted=False)],
    )


def blocked(control: str = "EXE-01") -> Verdict:
    d = Decision(action="block", control_id=control, reason=f"{control} blocked it")
    return Verdict(id="dec", request_id="r", interaction_id="i", action="block", primary=d)


def allowed() -> Verdict:
    return Verdict(id="dec", request_id="r", interaction_id="i", action="allow")


async def block_n(ctl, n: int, *, agent: str = A, session: str = "s1", control: str = "EXE-01"):
    for _ in range(n):
        await ctl.on_complete(
            ctx(agent, session), tool(), blocked(control), Outcome(status_code=403), cfg()
        )


# ---------------------------------------------------------------- quarantine
async def test_healthy_agent_untouched(ctl) -> None:
    assert await ctl.evaluate(ctx(), tool(), cfg()) is None
    await block_n(ctl, 2)  # below threshold
    assert await ctl.evaluate(ctx(), tool(), cfg()) is None


async def test_repeated_blocks_quarantine_agent(ctl) -> None:
    await block_n(ctl, 2, control="EXE-01")
    await block_n(ctl, 1, control="INJ-01")
    d = await ctl.evaluate(ctx(), tool("Write"), cfg())
    assert d is not None and d.action == "require_approval" and d.control_id == "RES-01"
    assert "quarantined" in d.reason and "EXE-01" in d.reason and "INJ-01" in d.reason
    assert d.approval is not None and d.approval.labels["signals"] == "cascade_quarantine"
    assert d.findings[0].detector == "res.cascade.quarantine"


async def test_quarantine_is_session_scoped_and_expires(ctl, clock) -> None:
    await block_n(ctl, 3)
    assert await ctl.evaluate(ctx(session="other"), tool(), cfg()) is None
    assert await ctl.evaluate(ctx(B), tool(), cfg()) is None
    clock.t += 901
    assert await ctl.evaluate(ctx(), tool(), cfg()) is None


async def test_agent_scope_quarantines_all_sessions(ctl) -> None:
    c = cfg(scope="agent")
    for s in ("s1", "s2", "s3"):
        await ctl.on_complete(ctx(session=s), tool(), blocked(), Outcome(status_code=403), c)
    d = await ctl.evaluate(ctx(session="s9"), tool(), c)
    assert d is not None and d.action == "require_approval"


async def test_blocks_outside_window_do_not_count(ctl, clock) -> None:
    await block_n(ctl, 2)
    clock.t += 301
    await block_n(ctl, 1)
    assert await ctl.evaluate(ctx(), tool(), cfg()) is None


async def test_breaker_controls_are_ignored(ctl) -> None:
    await block_n(ctl, 5, control="EXE-04")  # the loop breaker already handles runaways
    await block_n(ctl, 5, control="BUD-01")
    assert await ctl.evaluate(ctx(), tool(), cfg()) is None


async def test_selftest_and_dry_run_never_mutate(ctl) -> None:
    for c in (ctx(source="selftest"), ctx(dry_run=True)):
        for _ in range(4):
            await ctl.on_complete(c, tool(), blocked(), Outcome(status_code=403), cfg())
    assert await ctl.evaluate(ctx(), tool(), cfg()) is None


async def test_model_turns_are_not_gated(ctl) -> None:
    await block_n(ctl, 3)
    i = Interaction(kind="model_call", surface="model.request")
    assert await ctl.evaluate(ctx(), i, cfg()) is None  # out of applies_to / quarantine_surfaces


# ---------------------------------------------------------------- downstream circuit
async def fail_n(ctl, n: int, *, server: str = "crm", status: int = 502, agent: str = A):
    for k in range(n):
        await ctl.on_complete(
            ctx(agent, f"s{k}"),
            tool(f"{server}.lookup", mcp_server=server),
            allowed(),
            Outcome(status_code=status, error="upstream 502"),
            cfg(),
        )


async def test_failing_mcp_server_opens_circuit_for_every_agent(ctl) -> None:
    await fail_n(ctl, 5)
    for agent in (A, B):
        d = await ctl.evaluate(ctx(agent, "fresh"), tool("crm.lookup", mcp_server="crm"), cfg())
        assert d is not None and d.action == "block" and d.http_status == 503
        assert d.error_type == "circuit_open" and d.retry_after_s and "mcp:crm" in d.reason
    # a healthy server is unaffected
    assert await ctl.evaluate(ctx(), tool("news.get", mcp_server="news"), cfg()) is None


async def test_circuit_half_open_probe_then_close(ctl, clock) -> None:
    await fail_n(ctl, 5)
    clock.t += 61
    i = tool("crm.lookup", mcp_server="crm")
    assert await ctl.evaluate(ctx(), i, cfg()) is None  # the single probe
    d = await ctl.evaluate(ctx(B), i, cfg())
    assert d is not None and d.action == "block"  # second caller waits for the probe
    await ctl.on_complete(ctx(), i, allowed(), Outcome(status_code=200), cfg())
    assert await ctl.evaluate(ctx(B), i, cfg()) is None


async def test_few_failures_or_4xx_or_builtin_tools_do_not_trip(ctl) -> None:
    await fail_n(ctl, 4)
    await fail_n(ctl, 10, server="crm2", status=404)
    for k in range(10):  # Claude Code tool_error on Bash: normal work, never a circuit target
        await ctl.on_complete(
            ctx(C, f"b{k}"),
            tool("Bash"),
            allowed(),
            Outcome(status_code=200, error="tool_error"),
            cfg(),
        )
    assert await ctl.evaluate(ctx(), tool("crm.lookup", mcp_server="crm"), cfg()) is None
    assert await ctl.evaluate(ctx(), tool("crm2.lookup", mcp_server="crm2"), cfg()) is None
    assert await ctl.evaluate(ctx(C), tool("Bash"), cfg()) is None


# ---------------------------------------------------------------- cascade taint (A -> B -> C)
async def test_healthy_peer_result_passes(ctl) -> None:
    assert await ctl.evaluate(ctx(B), a2a_result(A, peer_session="s1"), cfg()) is None
    assert await ctl.evaluate(ctx(B), tool(), cfg()) is None


async def test_quarantined_output_dropped_and_taint_propagates(ctl) -> None:
    await block_n(ctl, 3, agent=A)  # A is compromised
    d = await ctl.evaluate(ctx(B, "sb"), a2a_result(A, peer_session="s1"), cfg())
    assert d is not None and d.action == "block" and A in d.reason
    assert d.findings[0].detector == "res.cascade.quarantined_output"
    # B consumed it -> B's side effects need a human, with the chain explained
    d = await ctl.evaluate(ctx(B, "sb"), tool("Write"), cfg())
    assert d is not None and d.action == "require_approval"
    assert f"{A} -> {B}" in d.reason and d.approval.labels["signals"] == "cascade_tainted"
    # C reads B's (tainted) output -> logged + C tainted transitively
    d = await ctl.evaluate(ctx(C, "sc"), a2a_result(B), cfg())
    assert d is not None and d.action == "log" and f"{A} -> {B} -> {C}" in d.reason
    d = await ctl.evaluate(ctx(C, "sc"), tool("acme-crm.export_all", mcp_server="acme-crm"), cfg())
    assert d is not None and d.action == "require_approval" and d.meta["taint"]["root"] == A


async def test_taint_gates_consumer_session_or_every_session(ctl) -> None:
    await block_n(ctl, 3, agent=A)
    await ctl.evaluate(ctx(B, "sb"), a2a_result(A, peer_session="s1"), cfg())
    assert await ctl.evaluate(ctx(B, "other"), tool(), cfg()) is None  # default: session scope
    c = cfg(taint_scope="agent")
    await ctl.evaluate(ctx(B, "sb"), a2a_result(A, peer_session="s1"), c)
    d = await ctl.evaluate(ctx(B, "other"), tool(), c)
    assert d is not None and d.action == "require_approval"


async def test_dry_run_inbound_does_not_taint(ctl) -> None:
    await block_n(ctl, 3, agent=A)
    d = await ctl.evaluate(ctx(B, dry_run=True), a2a_result(A, peer_session="s1"), cfg())
    assert d is not None and d.action == "block"
    assert await ctl.evaluate(ctx(B), tool(), cfg()) is None


async def test_a2a_peer_naming_matches_agent_id(ctl) -> None:
    """A2A-01 names peers ``a2a.<peer>`` without the team suffix."""
    await block_n(ctl, 3, agent=A)  # research-agent@research
    i = Interaction(
        kind="a2a",
        surface="a2a.result",
        direction="in",
        tool_name="a2a.research-agent",
        meta={"peer_session": "s1"},
    )
    d = await ctl.evaluate(ctx(B, "sb"), i, cfg())
    assert d is not None and d.action == "block" and d.meta["peer"] == "research-agent"


async def test_session_quarantine_does_not_leak_to_unrelated_sessions(ctl) -> None:
    """A session-scoped quarantine drops the agent's output only where it applies."""
    await block_n(ctl, 3, agent=A, session="s1")
    assert await ctl.evaluate(ctx(B, "sb"), a2a_result(A), cfg()) is None  # unrelated session
    d = await ctl.evaluate(ctx(B, "s1"), a2a_result(A), cfg())  # same (shared) session
    assert d is not None and d.action == "block"


async def test_quarantined_in_many_sessions_goes_agent_wide(ctl) -> None:
    for sid in ("s1", "s2", "s3"):
        await block_n(ctl, 3, agent=A, session=sid)
    d = await ctl.evaluate(ctx(B, "sb"), a2a_result(A), cfg())
    assert d is not None and d.action == "block" and "quarantined" in d.reason


async def test_release_lifts_quarantine(ctl) -> None:
    await block_n(ctl, 3)
    assert ctl.state.release(agent=A) >= 1
    assert await ctl.evaluate(ctx(), tool(), cfg()) is None
