"""ASI03 Identity & Privilege Abuse - GOV-01: claims are not credentials, anonymous least
privilege, per-session credential scope."""

from __future__ import annotations

import copy

import pytest

from aegis.controls.governance.gov01_identity import ANONYMOUS_TOOLS, CONTROLS, CallerIdentity
from aegis.core.types import Interaction

GOV01 = CONTROLS[0]
MODEL = Interaction(kind="model_call", surface="model.request")


def tool(name: str, surface: str = "mcp.call") -> Interaction:
    return Interaction(
        kind="mcp" if surface.startswith("mcp") else "tool_call", surface=surface, tool_name=name
    )


@pytest.fixture(autouse=True)
def _fresh_bindings():
    CallerIdentity._bindings.clear()
    yield
    CallerIdentity._bindings.clear()


async def _eval(
    rt, helpers, headers=None, *, inter=MODEL, source="proxy", params=None, hints=None, session=None
):
    ident = await rt.org.resolve_identity(headers or {}, hints=hints)
    snap = None
    if params is not None:
        doc = copy.deepcopy(helpers.POLICY)
        doc["controls"][0]["params"] = params
        snap = helpers.make_snapshot(doc)
    ctx = helpers.ctx_for(ident, source, snap)
    if session:
        ctx.session_id = session
    return await GOV01.evaluate(ctx, inter, ctx.policy.controls["GOV-01"])


# ------------------------------------------------------------------ claims are not credentials
async def test_header_only_claim_of_registered_agent_blocks(rt, helpers):
    for src in ("proxy", "mcp", "hook", "egress", "guard"):
        d = await _eval(rt, helpers, {"X-Aegis-Agent": "claude-code@platform"}, source=src)
        assert d is not None and d.action == "block", src
        assert d.http_status == 401 and d.error_type == "unauthenticated"
        assert "agent identity not proven" in d.reason and "claude-code@platform" in d.reason
        assert d.findings[0].detector == "gov.identity_unproven"
        assert "aegis_demo" not in d.model_dump_json()  # never echo key material


async def test_short_alias_claim_also_blocks(rt, helpers):
    d = await _eval(rt, helpers, {"X-Aegis-Agent": "trading-copilot"})
    assert d.action == "block" and "trading-copilot@trading" in d.reason


async def test_claim_with_the_agents_key_is_allowed(rt, helpers):
    h = {"X-Aegis-Agent": "claude-code@platform", "X-Aegis-Agent-Key": helpers.KEYS["cc"]}
    assert await _eval(rt, helpers, h) is None
    h = {"Authorization": f"Bearer {helpers.KEYS['copilot']}"}
    assert await _eval(rt, helpers, h, inter=tool("payments.create_charge")) is None


async def test_control_plane_sources_unaffected(rt, helpers):
    assert (
        await _eval(rt, helpers, {"X-Aegis-Agent": "trading-copilot@trading"}, source="selftest")
        is None
    )


async def test_hints_are_attribution_unless_configured(rt, helpers):
    hint = {"agent_id": "claude-code@platform"}
    # default: hints (demo guard body identity, Claude Code UA detection) are not claims
    for src in ("guard", "proxy", "hook"):
        assert await _eval(rt, helpers, hints=hint, source=src) is None, src
    d = await _eval(
        rt, helpers, hints=hint, source="guard", params={"unproven_hint_sources": ["guard"]}
    )
    assert d.action == "block" and "identity hint" in d.reason


async def test_no_claim_is_never_blocked_for_being_anonymous(rt, helpers):
    for src in ("proxy", "mcp", "hook", "egress", "guard"):
        assert await _eval(rt, helpers, {}, source=src) is None, src
        assert await _eval(rt, helpers, {}, source=src, inter=tool("weather.get_weather")) is None


async def test_non_blocking_action_downgrades_to_least_privilege(rt, helpers):
    params = {"unproven_agent_action": "log"}
    hdr = {"X-Aegis-Agent": "claude-code@platform"}  # claude-code may call payments.* WITH its key
    d = await _eval(rt, helpers, hdr, params=params)
    assert d.action == "log" and "downgraded" in d.reason
    d = await _eval(rt, helpers, hdr, inter=tool("payments.create_charge"), params=params)
    assert d.action == "block" and d.findings[0].detector == "gov.anonymous_tool"
    assert "unproven agent 'claude-code@platform'" in d.reason


async def test_disabled_agent_claim_still_reports_disabled(rt, helpers):
    d = await _eval(rt, helpers, {"X-Aegis-Agent": "legacy-bot@platform"})
    assert d.action == "block" and "disabled" in d.reason


# ------------------------------------------------------------------ anonymous least privilege
async def test_anonymous_model_call_allowed_but_tools_restricted(rt, helpers):
    assert await _eval(rt, helpers, {}) is None
    for name in (
        "payments.create_charge",
        "mailer.send_email",
        "trade.execute",
        "acme-db.query",
        "Bash",
    ):
        surface = "tool.input" if name == "Bash" else "mcp.call"
        d = await _eval(rt, helpers, {}, inter=tool(name, surface))
        assert d is not None and d.action == "block", name
        assert d.http_status == 403 and d.findings[0].detector == "gov.anonymous_tool"
        assert "anonymous caller may not call" in d.reason


async def test_anonymous_readonly_tools_allowed(rt, helpers):
    for name in ("marketpulse.list_plans", "weather.get_weather", "mcp__docs__search_pages"):
        assert await _eval(rt, helpers, {}, inter=tool(name)) is None, name
    assert await _eval(rt, helpers, {}, inter=tool("Read", "tool.input")) is None
    assert "*.list_*" in ANONYMOUS_TOOLS


async def test_unregistered_agent_gets_anonymous_allowlist(rt, helpers):
    d = await _eval(rt, helpers, {"X-Aegis-Agent": "ghost@nowhere"})
    assert d.action == "log" and d.findings[0].detector == "gov.unregistered_agent"
    d = await _eval(
        rt, helpers, {"X-Aegis-Agent": "ghost@nowhere"}, inter=tool("payments.create_charge")
    )
    assert d.action == "block" and "unregistered agent 'ghost@nowhere'" in d.reason


async def test_anonymous_allowlist_opt_out_is_legacy(rt, helpers):
    params = {"anonymous_allowed_tools": None}
    assert await _eval(rt, helpers, {}, inter=tool("payments.create_charge"), params=params) is None


# ------------------------------------------------------------------ per-session credential scope
async def test_session_bound_to_first_credential(rt, helpers):
    copilot = {"Authorization": f"Bearer {helpers.KEYS['copilot']}"}
    research = {"Authorization": f"Bearer {helpers.KEYS['research']}"}
    s = "ses_asi03_bind"
    assert await _eval(rt, helpers, copilot, session=s) is None
    assert await _eval(rt, helpers, copilot, session=s) is None
    d = await _eval(rt, helpers, research, session=s)
    assert d.action == "block" and d.findings[0].detector == "gov.session_binding"
    assert "trading-copilot@trading" in d.reason and "research-agent@research" in d.reason
    d = await _eval(rt, helpers, {}, session=s)  # credential-less relay into a keyed session
    assert d.action == "block" and "no credential" in d.reason
    # other sessions / the implicit default session are unaffected
    assert await _eval(rt, helpers, research, session="ses_asi03_other") is None
    assert await _eval(rt, helpers, research, session="default") is None
    assert (
        await _eval(rt, helpers, research, session=s, params={"session_binding_action": "allow"})
        is None
    )
