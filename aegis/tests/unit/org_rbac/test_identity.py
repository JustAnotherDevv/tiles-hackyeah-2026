"""ORG-V05: data-plane identity resolution (table-driven)."""

from __future__ import annotations

import pytest

from aegis.core.types import RequestContext
from aegis.org.models import ResolvedIdentity

K = {
    "cc": "aegis_demo_cc_platform_0000000000000001_NOT_A_SECRET",
    "research": "aegis_demo_research_agent_0000000000000002_NOT_A_SECRET",
    "revoked": "aegis_demo_revoked_key_0000000000000099_NOT_A_SECRET",
    "expired": "aegis_demo_expired_key_0000000000000098_NOT_A_SECRET",
}


@pytest.mark.parametrize(
    ("headers", "hints", "expect"),
    [
        (
            {"Authorization": f"Bearer {K['research']}"},
            None,
            {
                "principal": "agent:research-agent@research",
                "authenticated": True,
                "member_id": "u_agnieszka",
                "team_id": "research",
                "auth_method": "api_key",
                "key_id": "key_research_01",
                "credential_error": None,
            },
        ),
        (
            {"x-api-key": K["research"]},
            None,
            {"principal": "agent:research-agent@research", "authenticated": True},
        ),
        (
            {"X-Aegis-Agent-Key": K["cc"], "Authorization": "Bearer sk-ant-oat01-xyz"},
            None,
            {
                "principal": "agent:claude-code@platform",
                "authenticated": True,
                "member_id": "u_tomasz",
            },
        ),
        (
            {"Authorization": f"Bearer {K['revoked']}"},
            None,
            {
                "principal": "agent:chaos-agent@platform",
                "credential_error": "revoked",
                "authenticated": False,
            },
        ),
        (
            {"Authorization": f"Bearer {K['expired']}"},
            None,
            {
                "principal": "agent:chaos-agent@platform",
                "credential_error": "expired",
                "authenticated": False,
            },
        ),
        (
            {"Authorization": "Bearer aegis_x"},
            None,
            {"principal": "agent:anonymous", "credential_error": "unknown_key"},
        ),
        (
            {
                "Authorization": "Bearer sk-ant-oat01-abc",
                "X-Aegis-Agent": "trading-copilot@trading",
            },
            None,
            {
                "principal": "agent:trading-copilot@trading",
                "auth_method": "header",
                "authenticated": False,
                "credential_error": None,
            },
        ),
        (
            {
                "Authorization": f"Bearer {K['research']}",
                "X-Aegis-Agent": "trading-copilot@trading",
            },
            None,
            {
                "principal": "agent:research-agent@research",
                "principal_mismatch": True,
                "asserted_agent_id": "trading-copilot@trading",
            },
        ),
        (
            {"X-Aegis-Agent": "claude-code"},
            None,
            {"principal": "agent:claude-code@platform", "known": True, "member_id": "u_tomasz"},
        ),
        (
            {"X-Aegis-Agent": "ghost@nowhere"},
            None,
            {"principal": "agent:ghost@nowhere", "known": False},
        ),
        (
            {"X-Aegis-Agent": "legacy-bot@platform"},
            None,
            {"principal": "agent:legacy-bot@platform", "known": True, "principal_active": False},
        ),
        (
            {"X-Aegis-Member": "u_piotr", "X-Aegis-Team": "research"},
            None,
            {"principal": "member:u_piotr", "team_id": "trading", "role": "member"},
        ),
        (
            {"X-Aegis-Member": "emily", "X-Aegis-Team": "research"},
            None,
            {"principal": "member:u_emily", "team_id": "research", "role": "admin"},
        ),
        (
            {},
            {"agent_id": "claude-code@platform"},
            {"principal": "agent:claude-code@platform", "auth_method": "hint"},
        ),
        ({}, {"member_id": "u_marek"}, {"principal": "member:u_marek", "auth_method": "hint"}),
        (
            {},
            None,
            {
                "principal": "agent:anonymous",
                "auth_method": "anonymous",
                "org_id": "acme-capital",
                "role": "agent",
            },
        ),
    ],
)
async def test_resolve_identity(rt, headers, hints, expect):
    ident = await rt.org.resolve_identity(headers, hints=hints)
    assert isinstance(ident, ResolvedIdentity)
    for key, value in expect.items():
        got = ident.principal if key == "principal" else getattr(ident, key)
        assert got == value, (key, got, value)


async def test_subclass_survives_context_but_not_json(rt):
    ident = await rt.org.resolve_identity({"Authorization": f"Bearer {K['revoked']}"})
    ctx = RequestContext(request_id="r", identity=ident)
    assert isinstance(ctx.identity, ResolvedIdentity)
    assert ctx.identity.credential_error == "revoked"
    dumped = ctx.model_dump(mode="json")["identity"]
    assert "credential_error" not in dumped and "key_id" not in dumped
    assert dumped["agent_id"] == "chaos-agent@platform"


async def test_last_seen_updated_in_memory(rt):
    await rt.org.resolve_identity({"X-Aegis-Agent": "trading-copilot@trading"})
    agent = await rt.org.get_agent("trading-copilot@trading")
    assert agent.last_seen is not None


async def test_revoked_key_takes_effect_immediately(rt):
    from aegis.core.types import Identity

    admin = Identity(org_id="acme-capital", member_id="u_marek", role="admin")
    rec, plaintext = await rt.org.issue_key("research-agent@research", actor=admin)
    ident = await rt.org.resolve_identity({"x-api-key": plaintext})
    assert ident.authenticated and ident.key_id == rec.key_id
    await rt.org.revoke_key(rec.key_id, actor=admin)
    ident = await rt.org.resolve_identity({"x-api-key": plaintext})
    assert ident.credential_error == "revoked"
    events = [e for e in rt.audit.org_changes() if e.data.get("op", "").startswith("key.")]
    assert len(events) == 2
    assert all(plaintext not in str(e.model_dump()) for e in rt.audit.events)
