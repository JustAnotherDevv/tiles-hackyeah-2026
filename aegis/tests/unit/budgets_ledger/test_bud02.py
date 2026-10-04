"""BUD-12: BUD-02 local compute & concurrency control."""

from __future__ import annotations

from aegis.controls.budget.bud02_local import LocalComputeControl
from aegis.core.types import Interaction, Outcome, Verdict
from tests.unit.budgets_ledger.conftest import agent, cfg, ctx, model_hop

B = LocalComputeControl()
RA = agent("research-agent@research", "research")


def fast_cfg(snap):
    c = cfg(snap, "BUD-02")
    return c.model_copy(update={"timeout_ms": 300})  # queue wait capped at 50 ms


async def test_slot_saturation_429_then_release(led, snap, clock) -> None:
    conf = fast_cfg(snap)
    c1, c2 = ctx(RA, session="a", snap=snap), ctx(RA, session="b", snap=snap)
    i1 = model_hop(model="aegis-judge", dest="local", id="l1", meta={"wire": "ollama"})
    i2 = model_hop(model="aegis-judge", dest="local", id="l2", meta={"wire": "ollama"})
    d1 = await B.evaluate(c1, i1, conf)
    assert d1 is None or d1.action == "allow"
    d2 = await B.evaluate(c2, i2, conf)
    assert d2 is not None and d2.http_status == 429 and d2.retry_after_s == 2
    v = Verdict(id="d", request_id="r", interaction_id="l1", action="allow")
    await B.on_complete(c1, i1, v, Outcome(), conf)
    d3 = await B.evaluate(c2, i2, conf)
    assert d3 is None or d3.action == "allow"


async def test_num_predict_clamp(led, snap, clock) -> None:
    raw = {
        "model": "aegis-judge",
        "prompt": "hi",
        "options": {"num_predict": 5000, "num_ctx": 32768},
    }
    i = model_hop(model="aegis-judge", dest="local", raw=raw, meta={"wire": "ollama"})
    d = await B.evaluate(ctx(RA, snap=snap, dry_run=True), i, fast_cfg(snap))
    assert d is not None
    paths = {m.path: m.value for m in d.mutations}
    assert paths == {"options.num_predict": 1024, "options.num_ctx": 8192}


async def test_model_too_big_blocked(led, snap, clock) -> None:
    i = Interaction(
        kind="model_call",
        surface="model.admin",
        model="llama3.1:70b",
        meta={"op": "pull"},
    )
    d = await B.evaluate(ctx(RA, snap=snap), i, fast_cfg(snap))
    assert d is not None and d.action == "block" and "too big" in d.reason
