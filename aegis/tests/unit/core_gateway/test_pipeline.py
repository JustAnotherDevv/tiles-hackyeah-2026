"""GW-V05: pipeline semantics (CONTRACTS 3.5 + Addendum A-01..A-11) with fake controls/services."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from gw_fakes import EnrichingControl, FakeApprovals, FakeControl, FakeRT, cfg, interaction

from aegis.core import pipeline as pipeline_mod
from aegis.core.policy_schema import ControlScope
from aegis.core.types import Decision, Finding, Identity, Mutation, Outcome, Usage

AGENT = Identity(agent_id="bot@research", team_id="research", member_id="u_owner")


def make(tmp_path: Any, controls: list[Any], configs: list[Any] | None = None,
         **kw: Any) -> FakeRT:
    configs = configs if configs is not None else [cfg(c.id) for c in controls]
    return FakeRT(tmp_path, controls=controls, configs=configs, **kw)


def ctx_for(rt: FakeRT, **kw: Any):
    kw.setdefault("source", "guard")
    kw.setdefault("identity", AGENT)
    return rt.pipeline.new_context(**kw)


async def run(rt: FakeRT, text: str = "hello", **ikw: Any):
    ctx = ctx_for(rt)
    i = interaction(text, **ikw)
    v = await rt.pipeline.evaluate(ctx, i)
    return ctx, i, v


# ------------------------------------------------------------------ selection
async def test_selection_scope_applies_to_and_off(tmp_path) -> None:
    a = FakeControl("A-01", action="log")
    b = FakeControl("B-01", action="log", surfaces={"tool.input"})  # applies_to excludes
    c = FakeControl("C-01", action="log")  # mode off
    d = FakeControl("D-01", action="log")  # scoped to another team
    e = FakeControl("E-01", action="log")  # not in policy
    f = FakeControl("F-01", action="log")  # disabled
    g = FakeControl("G-01", action="log")  # scope.kinds narrows out
    configs = [cfg("A-01"), cfg("B-01"), cfg("C-01", mode="off"),
               cfg("D-01", scope=ControlScope(teams=["trading"])),
               cfg("F-01", enabled=False),
               cfg("G-01", scope=ControlScope(kinds=["mcp"]))]
    rt = make(tmp_path, [a, b, c, d, e, f, g], configs)
    _ctx, _i, v = await run(rt)
    assert [c.calls for c in (a, b, c, d, e, f, g)] == [1, 0, 0, 0, 0, 0, 0]
    assert v.action == "log" and v.primary and v.primary.control_id == "A-01"


async def test_scope_glob_matches_identity(tmp_path) -> None:
    a = FakeControl("A-01", action="log")
    rt = make(tmp_path, [a], [cfg("A-01", scope=ControlScope(agents=["*@research"]))])
    _ctx, _i, v = await run(rt)
    assert a.calls == 1 and v.action == "log"


async def test_ctx_policy_is_evaluated_snapshot(tmp_path) -> None:
    """A-01: controls read ctx.policy == the snapshot passed to evaluate()."""
    seen: list[Any] = []

    async def beh(ctx, i, c):
        seen.append(ctx.policy)
        return None

    a = FakeControl("A-01", behaviour=beh)
    rt = make(tmp_path, [a])
    candidate = rt.policy.snapshot().model_copy(update={"version": 42})
    ctx = ctx_for(rt)
    v = await rt.pipeline.evaluate(ctx, interaction(), policy=candidate)
    assert seen == [candidate] and ctx.policy is candidate and v.policy_version == 42


# ------------------------------------------------------------------ combine & monitor
async def test_precedence_and_primary_tie_break(tmp_path) -> None:
    ctrls = [FakeControl("Z-01", action="redact", priority=10),
             FakeControl("B-02", action="block", priority=50),
             FakeControl("A-02", action="block", priority=50),
             FakeControl("C-01", action="block", priority=20)]
    rt = make(tmp_path, ctrls)
    _ctx, _i, v = await run(rt)
    assert v.action == "block"
    assert v.primary.control_id == "C-01"  # lower priority wins the tie
    assert v.segments == [] and v.mutations == []


async def test_monitor_never_affects_action(tmp_path) -> None:
    a = FakeControl("A-01", action="block")
    b = FakeControl("B-01", behaviour=lambda *_: _ret(Decision(
        action="block", control_id="B-01", mode="monitor", reason="experimental")))
    rt = make(tmp_path, [a, b], [cfg("A-01", mode="monitor"), cfg("B-01")])
    _ctx, _i, v = await run(rt)
    assert v.action == "allow" and v.primary is None
    modes = {d.control_id: d.mode for d in v.decisions}
    assert modes == {"A-01": "monitor", "B-01": "monitor"}
    # monitor rows still reach the feed summary ("would have blocked")
    summary = rt.bus.recent(1, {"decision"})[0].data
    assert {c["control_id"] for c in summary["controls"]} == {"A-01", "B-01"}


async def _ret(value: Any) -> Any:
    return value


async def test_complete_trace_allow_rows(tmp_path) -> None:
    """A-03: silent controls produce allow rows with latency; timings recorded."""
    a = FakeControl("A-01")
    rt = make(tmp_path, [a])
    ctx, _i, v = await run(rt)
    assert v.action == "allow"
    assert len(v.decisions) == 1 and v.decisions[0].meta.get("no_finding") is True
    assert "ctl.A-01" in ctx.timings and "pipeline" in ctx.timings
    phases = {p for p, _ in rt.metrics.overhead}
    assert {"enrich", "deterministic", "semantic", "approvals", "transform", "record",
            "request"} <= phases


# ------------------------------------------------------------------ semantic & fail modes
async def test_semantic_skipped_after_deterministic_block(tmp_path) -> None:
    det = FakeControl("D-01", action="block")
    sem = FakeControl("S-01", kind="semantic", action="log")
    rt = make(tmp_path, [det, sem])
    _ctx, _i, v = await run(rt)
    assert v.action == "block" and sem.calls == 0


async def test_semantic_not_skipped_for_selftest(tmp_path) -> None:
    det = FakeControl("D-01", action="block")
    sem = FakeControl("S-01", kind="semantic", action="log")
    rt = make(tmp_path, [det, sem])
    ctx = ctx_for(rt, source="selftest", dry_run=True)
    await rt.pipeline.evaluate(ctx, interaction())
    assert sem.calls == 1


async def test_semantic_runs_concurrently(tmp_path) -> None:
    async def slow(ctx, i, c):
        await asyncio.sleep(0.15)
        return None

    ctrls = [FakeControl(f"S-0{n}", kind="semantic", behaviour=slow) for n in range(1, 4)]
    rt = make(tmp_path, ctrls, [cfg(c.id, timeout_ms=1000) for c in ctrls])
    loop = asyncio.get_running_loop()
    t = loop.time()
    _ctx, _i, v = await run(rt)
    assert loop.time() - t < 0.4 and v.action == "allow"


@pytest.mark.parametrize("fail_mode,action", [("closed", "block"), ("open", "allow"),
                                              ("deterministic_only", "allow")])
async def test_timeout_fail_modes(tmp_path, fail_mode: str, action: str) -> None:
    async def hang(ctx, i, c):
        await asyncio.sleep(5)

    s = FakeControl("S-01", kind="semantic", behaviour=hang)
    rt = make(tmp_path, [s], [cfg("S-01", timeout_ms=20, fail_mode=fail_mode)])
    _ctx, _i, v = await run(rt)
    assert v.action == action and v.degraded
    d = v.decisions[0]
    assert d.degraded and d.control_id == "S-01"
    assert ("fail-closed" in d.reason) == (fail_mode == "closed")


async def test_exception_fail_closed(tmp_path) -> None:
    async def boom(ctx, i, c):
        raise ValueError("nope")

    rt = make(tmp_path, [FakeControl("D-01", behaviour=boom)])
    _ctx, _i, v = await run(rt)
    assert v.action == "block" and v.primary.reason == "D-01 unavailable (fail-closed)"


async def test_completed_late_task_is_used(tmp_path) -> None:
    """A-05: a CPU-bound control that finished past its deadline is still used."""
    import time as _t

    async def busy(ctx, i, c):
        _t.sleep(0.05)  # blocks the loop: cannot be interrupted
        return Decision(action="log", control_id="D-01", reason="late but done")

    rt = make(tmp_path, [FakeControl("D-01", behaviour=busy)], [cfg("D-01", timeout_ms=5)])
    _ctx, _i, v = await run(rt)
    assert v.action == "log" and not v.decisions[0].degraded


async def test_enrich_errors_ignored_and_runs_first(tmp_path) -> None:
    order: list[str] = []

    def bad(ctx, i):
        order.append("enrich-bad")
        raise RuntimeError("x")

    def good(ctx, i):
        order.append("enrich-good")
        i.action_type = "db.write"

    async def beh(ctx, i, c):
        order.append(f"eval:{i.action_type}")
        return None

    rt = make(tmp_path, [EnrichingControl("A-01", enrich_fn=bad, priority=1),
                         EnrichingControl("B-01", enrich_fn=good, priority=2),
                         FakeControl("C-01", behaviour=beh, priority=3)])
    _ctx, _i, v = await run(rt)
    assert order == ["enrich-bad", "enrich-good", "eval:db.write"] and v.action == "allow"


# ------------------------------------------------------------------ approvals
def _appr(tmp_path, mode: str, **kw: Any) -> FakeRT:
    c = FakeControl("ACT-01", action="require_approval")
    return make(tmp_path, [c], approvals=FakeApprovals(mode), **kw)


async def test_preapproved_allows_with_reason(tmp_path) -> None:
    rt = _appr(tmp_path, "pre")
    _ctx, _i, v = await run(rt)
    assert v.action == "allow" and v.approval is not None
    d = v.decisions[0]
    assert d.action == "allow" and d.reason.startswith("approved by u_emily") and d.approval_id


async def test_auto_approved_on_request(tmp_path) -> None:
    rt = _appr(tmp_path, "approved")
    _ctx, _i, v = await run(rt)
    assert v.action == "allow"
    assert rt.approvals.decision_meta[0]["decision_id"] == v.id  # A-02


async def test_denied_becomes_block(tmp_path) -> None:
    rt = _appr(tmp_path, "denied")
    _ctx, _i, v = await run(rt)
    assert v.action == "block" and "approval denied" in v.primary.reason


async def test_pending_without_wait(tmp_path) -> None:
    rt = _appr(tmp_path, "pending")
    _ctx, _i, v = await run(rt)
    assert v.action == "require_approval" and v.approval.status == "pending"
    assert v.primary.approval_id == v.approval.id and v.segments == []
    assert rt.approvals.waits == []


async def test_pending_then_wait_approved(tmp_path) -> None:
    rt = _appr(tmp_path, "pending")
    rt.approvals.approve_on_wait = True
    ctx = ctx_for(rt, wait_for_approval_s=5)
    v = await rt.pipeline.evaluate(ctx, interaction())
    assert rt.approvals.waits and rt.approvals.waits[0][1] == 5
    assert v.action == "allow"


async def test_approvals_exception_fail_closed(tmp_path) -> None:
    rt = _appr(tmp_path, "raise")
    _ctx, _i, v = await run(rt)
    assert v.action == "block" and v.primary.degraded


async def test_null_approvals_fail_closed(tmp_path) -> None:
    from aegis.core.nulls import NullApprovals

    rt = make(tmp_path, [FakeControl("ACT-01", action="require_approval")],
              approvals=NullApprovals())
    _ctx, _i, v = await run(rt)
    assert v.action == "block"


async def test_dry_run_skips_approvals_and_record(tmp_path) -> None:
    rt = _appr(tmp_path, "approved")
    ctx = ctx_for(rt)
    v = await rt.pipeline.evaluate(ctx, interaction(), dry_run=True)
    assert v.action == "require_approval" and v.dry_run
    assert rt.approvals.requests == [] and rt.audit.events == []
    assert rt.bus.recent(10, {"decision"}) == [] and rt.metrics.verdicts == []
    assert rt.pipeline.wire(v.id) is None


# ------------------------------------------------------------------ transform
def _redacting(cid: str = "DLP-01", mutations: list[Mutation] | None = None) -> FakeControl:
    async def beh(ctx, i, c):
        text = i.segments[0].text
        s = text.index("jan@example.com")
        return Decision(action="redact", control_id=cid, reason="pii",
                        findings=[Finding(control_id=cid, detector="pii.email", category="pii",
                                          entity="EMAIL", segment_index=0, start=s,
                                          end=s + len("jan@example.com"))],
                        mutations=mutations or [])
    return FakeControl(cid, behaviour=beh)


async def test_redact_spans_via_redactor_and_mutations(tmp_path) -> None:
    mut = Mutation(path="max_tokens", value=128)
    allow_mut = Mutation(target="header", path="x-test", value="1")

    async def allow_with_mut(ctx, i, c):
        return Decision(action="allow", control_id="BUD-01", mutations=[allow_mut])

    rt = make(tmp_path, [_redacting(mutations=[mut]),
                         FakeControl("BUD-01", behaviour=allow_with_mut)])
    _ctx, i, v = await run(rt, "mail jan@example.com now")
    assert v.action == "redact"
    assert v.segments[0].text == "mail [EMAIL_1] now"
    assert i.segments[0].text == "mail jan@example.com now"  # original untouched
    assert v.redactions[0].placeholder == "[EMAIL_1]"
    assert v.mutations == [allow_mut, mut] or v.mutations == [mut, allow_mut]
    wire = rt.pipeline.wire(v.id)
    assert wire.original[0].text.startswith("mail jan@") and "[EMAIL_1]" in wire.outbound[0].text
    summary = rt.bus.recent(1, {"decision"})[0].data
    assert "jan@example.com" not in summary["preview"] and summary["entities"] == ["EMAIL"]


async def test_no_mutations_when_final_block(tmp_path) -> None:
    rt = make(tmp_path, [_redacting(mutations=[Mutation(path="x", value=1)]),
                         FakeControl("B-01", action="block")])
    _ctx, _i, v = await run(rt, "mail jan@example.com now")
    assert v.action == "block" and v.mutations == [] and v.redactions == []


async def test_redactor_failure_fail_closed(tmp_path) -> None:
    rt = make(tmp_path, [_redacting()])
    rt.redactor.fail = True
    _ctx, _i, v = await run(rt, "mail jan@example.com now")
    assert v.action == "block" and v.primary.control_id == pipeline_mod.CORE_CONTROL_ID


async def test_internal_error_fail_closed(tmp_path) -> None:
    rt = make(tmp_path, [])

    class BadPolicy:
        def snapshot(self):
            raise RuntimeError("policy exploded")

    rt.policy = BadPolicy()
    ctx = rt.pipeline.new_context(source="guard", identity=AGENT)
    v = await rt.pipeline.evaluate(ctx, interaction())
    assert v.action == "block" and v.primary.control_id == "AEGIS-CORE" and v.degraded


# ------------------------------------------------------------------ record & complete
async def test_record_once_audit_bus_metrics(tmp_path) -> None:
    rt = make(tmp_path, [FakeControl("A-01", action="log")])
    _ctx, _i, v = await run(rt)
    assert len(rt.audit.events) == 1 and rt.audit.events[0].decision_id == v.id
    assert rt.audit.events[0].data["phase"] == "request"
    assert "summary" in rt.audit.events[0].data and "detail" in rt.audit.events[0].data
    assert len(rt.bus.recent(10, {"decision"})) == 1
    assert rt.metrics.verdicts == [v]


async def test_complete_exactly_once_and_outcome_record(tmp_path) -> None:
    a = FakeControl("A-01")
    rt = make(tmp_path, [a])
    ctx, i, v = await run(rt)
    out = Outcome(status_code=200, usage=Usage(input_tokens=10, output_tokens=5),
                  upstream_ms=12.0, provider="mock-openai", model_used="mock-echo")
    await rt.pipeline.complete(ctx, i, v, out)
    await rt.pipeline.complete(ctx, i, v, out)
    assert len(a.completed) == 1
    outs = rt.audit.of_phase("outcome")
    assert len(outs) == 1 and outs[0].decision_id == v.id and outs[0].usage.input_tokens == 10
    assert len(rt.metrics.upstream) == 1
    assert rt.pipeline.is_completed(ctx, i)


async def test_complete_dry_run_no_outcome_record(tmp_path) -> None:
    rt = make(tmp_path, [FakeControl("A-01")])
    ctx = ctx_for(rt, dry_run=True)
    i = interaction()
    v = await rt.pipeline.evaluate(ctx, i)
    await rt.pipeline.complete(ctx, i, v, Outcome())
    assert rt.audit.events == []


async def test_wire_lru_eviction(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_mod, "WIRE_MAX", 3)
    rt = make(tmp_path, [])
    ids = []
    for _ in range(5):
        _ctx, _i, v = await run(rt)
        ids.append(v.id)
    assert [rt.pipeline.wire(x) is not None for x in ids] == [False, False, True, True, True]
    rt.pipeline.attach_response(ids[-1], response_raw="r", response_local="l")
    assert rt.pipeline.wire(ids[-1]).response_local == "l"


async def test_new_context_headers_session_wait(tmp_path) -> None:
    rt = make(tmp_path, [])
    ctx = rt.pipeline.new_context(
        source="proxy", identity=AGENT,
        headers={"Authorization": "Bearer sk-ant-oat-x", "X-Aegis-Agent-Key": "aegis_k",
                 "X-Claude-Code-Session-Id": "cc-123", "X-Aegis-Wait": "500",
                 "X-Aegis-Approval": "apr_1", "user-agent": "claude-cli/2.0"})
    assert "authorization" not in ctx.headers and "x-aegis-agent-key" not in ctx.headers
    assert ctx.session_id == "cc-123" and ctx.wait_for_approval_s == 110.0
    assert ctx.approval_token == "apr_1" and ctx.state["core.client"] == "claude-code"
    assert ctx.policy is not None and ctx.policy_version == 7
    # explicit 0 header wins over the handler default (A-19)
    ctx2 = rt.pipeline.new_context(source="hook", identity=AGENT,
                                   headers={"x-aegis-wait": "0"}, wait_for_approval_s=60)
    assert ctx2.wait_for_approval_s == 0.0
    # generated session id is deterministic per principal
    c3 = rt.pipeline.new_context(source="guard", identity=AGENT)
    c4 = rt.pipeline.new_context(source="guard", identity=AGENT)
    assert c3.session_id == c4.session_id and c3.session_id.startswith("ses_")


async def test_response_hop_shares_context(tmp_path) -> None:
    """A-02: request + response hop evaluated with one ctx; response hop records upstream_ms."""
    rt = make(tmp_path, [FakeControl("A-01")])
    ctx, i, v = await run(rt)
    ctx.state["core.outcome"] = Outcome(upstream_ms=33.0)
    r = interaction("reply", surface="model.response", direction="in", parent_id=i.id)
    v2 = await rt.pipeline.evaluate(ctx, r)
    assert v2.request_id == v.request_id
    rows = rt.bus.recent(2, {"decision"})
    assert rows[-1].data["upstream_ms"] == 33.0 and rows[-1].data["direction"] == "in"
    assert rt.audit.events[-1].data["phase"] == "response"
