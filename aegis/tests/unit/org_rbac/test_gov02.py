"""ORG-V10: GOV-02 model allowlist & destination tiering."""

from __future__ import annotations

import copy

from aegis.controls.governance.gov02_models import CONTROLS
from aegis.core.types import Destination, Identity, Interaction, Mutation, TextSegment

GOV02 = CONTROLS[0]


def _agent(agent_id: str) -> Identity:
    return Identity(org_id="acme-capital", agent_id=agent_id, role="agent")


async def _eval(
    helpers, identity, model=None, dest="remote", surface="model.request", params=None, text="hi"
):
    doc = copy.deepcopy(helpers.POLICY)
    if params is not None:
        doc["controls"][1]["params"] = params
    snap = helpers.make_snapshot(doc)
    ctx = helpers.ctx_for(identity, "proxy", snap)
    i = Interaction(
        kind="model_call",
        surface=surface,
        model=model,
        destination=Destination(name="x", dest_class=dest),
        segments=[TextSegment(path="messages[0].content", text=text)],
    )
    return await GOV02.evaluate(ctx, i, snap.controls["GOV-02"])


async def test_agent_allowlist_blocks(rt, helpers):
    d = await _eval(helpers, _agent("trading-copilot@trading"), "gpt-4.1-mini")
    assert d.action == "block"
    assert d.reason == "model gpt-4.1-mini not in agent trading-copilot@trading allowlist"
    assert d.findings[0].meta["allowed"]
    d = await _eval(helpers, _agent("trading-copilot@trading"), "claude-opus-4-1")
    assert d.action == "block"


async def test_allowed_models_pass(rt, helpers):
    assert await _eval(helpers, _agent("claude-code@platform"), "claude-sonnet-4-5") is None
    assert (
        await _eval(helpers, _agent("research-agent@research"), "aegis-judge", dest="local") is None
    )
    assert (
        await _eval(helpers, _agent("research-agent@research"), "aegis-judge:latest", dest="local")
        is None
    )
    member = Identity(org_id="acme-capital", member_id="u_piotr", role="member")
    assert await _eval(helpers, member, "claude-haiku-4-5") is None
    assert await _eval(helpers, _agent("claude-code@platform"), None) is None


async def test_local_only_agent(rt, helpers):
    d = await _eval(helpers, _agent("research-agent@research"), "mock-echo", dest="remote")
    assert d.action == "block" and "local-only" in d.reason
    d = await _eval(helpers, _agent("research-agent@research"), None, dest="remote")
    assert d.action == "block"
    d = await _eval(
        helpers,
        _agent("research-agent@research"),
        "mock-echo",
        dest="remote",
        params={"on_tier_violation": "reroute"},
    )
    assert d.action == "redact"
    assert d.mutations == [
        Mutation(
            target="route",
            op="set",
            path="model",
            value="aegis-judge",
            reason=d.mutations[0].reason,
        )
    ]


async def test_policy_denied_and_not_allowed(rt, helpers):
    d = await _eval(helpers, _agent("chaos-agent@platform"), "qwen3:cloud")
    assert d.action == "block" and "*:cloud" in d.reason
    d = await _eval(
        helpers, _agent("chaos-agent@platform"), "evil/model", surface="model.admin", dest="local"
    )
    assert d.action == "block" and "not in policy allowlist" in d.reason
    d = await _eval(
        helpers, Identity(org_id="acme-capital", agent_id="ghost@x", role="agent"), "gpt-5-turbo"
    )
    assert d.action == "block"


async def test_reroute_on_restricted_data(rt, helpers):
    params = {"reroute_on_class": {"RESTRICTED": "local"}}
    d = await _eval(
        helpers,
        _agent("claude-code@platform"),
        "claude-sonnet-4-5",
        params=params,
        text="card 4111111111111111 please",
    )
    assert d.action == "redact" and d.mutations[0].value == "aegis-judge"
    assert "RESTRICTED" in d.reason
    assert (
        await _eval(
            helpers,
            _agent("claude-code@platform"),
            "claude-sonnet-4-5",
            params=params,
            text="no card here",
        )
        is None
    )
