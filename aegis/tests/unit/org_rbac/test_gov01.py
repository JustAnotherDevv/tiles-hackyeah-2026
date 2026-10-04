"""ORG-V09: GOV-01 caller identity & attribution."""

from __future__ import annotations

import copy

from aegis.controls.governance.gov01_identity import CONTROLS
from aegis.core.types import Identity, Interaction

GOV01 = CONTROLS[0]
INTERACTION = Interaction(kind="model_call", surface="model.request")


async def _eval(rt, helpers, headers=None, identity=None, source="proxy", snap=None):
    ident = identity or await rt.org.resolve_identity(headers or {})
    ctx = helpers.ctx_for(ident, source, snap)
    cfg = ctx.policy.controls["GOV-01"]
    return await GOV01.evaluate(ctx, INTERACTION, cfg)


async def test_revoked_key_blocks_401(rt, helpers):
    d = await _eval(rt, helpers, {"Authorization": f"Bearer {helpers.KEYS['revoked']}"})
    assert d.action == "block" and d.http_status == 401 and d.error_type == "unauthenticated"
    assert d.findings[0].detector == "gov.key_revoked"
    assert d.findings[0].category == "governance"
    assert "key_revoked_demo" in d.reason
    assert "aegis_" not in d.model_dump_json()


async def test_expired_and_unknown_keys_block(rt, helpers):
    d = await _eval(rt, helpers, {"x-api-key": helpers.KEYS["expired"]})
    assert d.action == "block" and d.findings[0].detector == "gov.key_expired"
    d = await _eval(rt, helpers, {"x-api-key": "aegis_totally_unknown"})
    assert d.action == "block" and d.findings[0].detector == "gov.key_unknown"
    assert "aegis_" not in d.model_dump_json()


async def test_spoofing_blocks_403(rt, helpers):
    d = await _eval(
        rt,
        helpers,
        {
            "Authorization": f"Bearer {helpers.KEYS['research']}",
            "X-Aegis-Agent": "trading-copilot@trading",
        },
    )
    assert d.action == "block" and d.http_status == 401 and d.error_type == "unauthenticated"
    assert "trading-copilot@trading" in d.reason and "research-agent@research" in d.reason


async def test_disabled_agent_blocks_even_as_plain_identity(rt, helpers):
    plain = Identity(org_id="acme-capital", agent_id="legacy-bot@platform", role="agent")
    d = await _eval(rt, helpers, identity=plain, source="selftest")
    assert d.action == "block" and "legacy-bot@platform is disabled" in d.reason
    assert d.http_status == 403 and d.error_type == "forbidden"
    d = await _eval(rt, helpers, {"X-Aegis-Agent": "legacy-bot@platform"})
    assert d.action == "block"


async def test_unknown_agent_logs_anonymous_allows(rt, helpers):
    d = await _eval(rt, helpers, {"X-Aegis-Agent": "ghost@nowhere"})
    assert d.action == "log" and d.findings[0].detector == "gov.unregistered_agent"
    assert await _eval(rt, helpers, {}) is None
    assert await _eval(rt, helpers, {"X-Aegis-Agent": "trading-copilot@trading"}) is None
    assert await _eval(rt, helpers, {"Authorization": f"Bearer {helpers.KEYS['cc']}"}) is None
    plain = Identity(org_id="acme-capital", agent_id="research-agent@research", role="agent")
    assert await _eval(rt, helpers, identity=plain, source="selftest") is None


async def test_require_auth(rt, helpers):
    doc = copy.deepcopy(helpers.POLICY)
    doc["defaults"]["require_auth"] = True
    snap = helpers.make_snapshot(doc)
    d = await _eval(rt, helpers, {"X-Aegis-Agent": "trading-copilot@trading"}, snap=snap)
    assert d.action == "block" and d.http_status == 401
    assert (
        await _eval(
            rt, helpers, {"X-Aegis-Agent": "trading-copilot@trading"}, source="selftest", snap=snap
        )
        is None
    )
    assert await _eval(rt, helpers, {"x-api-key": helpers.KEYS["copilot"]}, snap=snap) is None
    selftest = Identity(org_id="acme-capital", agent_id="selftest", role="agent")
    assert await _eval(rt, helpers, identity=selftest, snap=snap) is None


async def test_anonymous_block_param_and_boolean_spelling(rt, helpers):
    doc = copy.deepcopy(helpers.POLICY)
    doc["controls"][0]["params"] = {"anonymous_action": "block", "block_invalid_keys": False}
    snap = helpers.make_snapshot(doc)
    d = await _eval(rt, helpers, {}, snap=snap)
    assert d.action == "block"
    d = await _eval(rt, helpers, {"x-api-key": helpers.KEYS["revoked"]}, snap=snap)
    assert d.action == "log"


async def test_key_scopes_could(rt, helpers):
    doc = copy.deepcopy(helpers.POLICY)
    doc["controls"][0]["params"] = {"enforce_key_scopes": "block"}
    snap = helpers.make_snapshot(doc)
    # research key has ollama.chat but not hooks
    d = await _eval(rt, helpers, {"x-api-key": helpers.KEYS["research"]}, source="hook", snap=snap)
    assert d.action == "block" and d.findings[0].detector == "gov.key_scope"
    assert await _eval(rt, helpers, {"x-api-key": helpers.KEYS["research"]}, snap=snap) is None
