"""ORG-V08: governed org-change flow (fake approvals)."""

from __future__ import annotations

from aegis.core.types import Identity
from aegis.org import changes as org_changes

MAREK = {"X-Aegis-View-As": "u_marek"}
KAT = {"X-Aegis-View-As": "u_katarzyna"}
PIOTR = {"X-Aegis-View-As": "u_piotr"}


def _ident(rt, member_id: str) -> Identity:
    m = rt.org.cache.members[member_id]
    return Identity(
        org_id=m.org_id, team_id=m.team_id, member_id=m.id, role=m.role, display_name=m.name
    )


async def _promote(client) -> dict:
    r = await client.patch("/api/members/u_piotr", json={"role": "admin"}, headers=MAREK)
    assert r.status_code == 403, r.text
    err = r.json()["error"]
    assert err["type"] == "approval_required"
    return err


async def test_member_cannot_manage(client, rt):
    r = await client.patch("/api/members/u_olivia", json={"team_id": "research"}, headers=PIOTR)
    assert r.status_code == 403 and r.json()["error"]["type"] == "forbidden"
    refused = [e for e in rt.audit.org_changes() if e.data.get("outcome") == "forbidden"]
    assert refused, "forbidden attempts are audited"


async def test_admin_direct_change(client, rt):
    r = await client.patch("/api/members/u_olivia", json={"team_id": "research"}, headers=MAREK)
    assert r.status_code == 200, r.text
    assert r.json()["team_id"] == "research"
    assert r.json()["meta"]["teams"] == ["research"]
    ev = [e for e in rt.audit.org_changes() if e.data.get("via") == "direct"]
    assert ev and ev[-1].actor.member_id == "u_marek"
    assert ev[-1].data["before"] == {"team_id": "trading"}
    assert ev[-1].data["after"]["email"].startswith("o***@")
    assert rt.bus.events("org.updated")[-1]["member"]["id"] == "u_olivia"


async def test_promotion_needs_owner_and_shows_pending(client, rt):
    err = await _promote(client)
    assert err["required_role"] == "owner"
    assert err["approval_id"].startswith("apr_")
    assert err["expires_at"]
    assert "Piotr" in err["message"] and "owner" in err["message"]
    r = await client.get("/api/members/u_piotr")
    pending = r.json()["meta"]["pending_changes"]
    assert pending[0]["to"] == "admin" and pending[0]["approval_id"] == err["approval_id"]
    assert r.json()["role"] == "member"
    req = rt.approvals.requests[err["approval_id"]]
    assert req.action_type == "org.role.promote_admin"
    assert req.resource == "member:u_piotr"
    assert req.title == "Promote Piotr Zieliński to admin"
    assert "@" not in str(req.payload) or "***@" in str(req.payload)
    pend = [e for e in rt.audit.org_changes() if e.data.get("outcome") == "pending_approval"]
    assert pend and pend[-1].data["approval_id"] == err["approval_id"]
    # (6) dedupe while pending
    err2 = await _promote(client)
    assert err2["approval_id"] == err["approval_id"]


async def test_target_cannot_approve_own_promotion(client, rt):
    rt.approvals.register_executor("action", org_changes.org_executor)
    err = await _promote(client)
    req = await rt.approvals.vote(err["approval_id"], _ident(rt, "u_piotr"), "approve")
    assert req.execution["applied"] is False
    assert "own promotion" in req.execution["reason"]
    assert rt.org.cache.members["u_piotr"].role == "member"


async def test_owner_approval_applies(client, rt):
    rt.approvals.register_executor("action", org_changes.org_executor)
    err = await _promote(client)
    req = await rt.approvals.vote(err["approval_id"], _ident(rt, "u_katarzyna"), "approve")
    assert req.execution["applied"] is True
    assert rt.org.cache.members["u_piotr"].role == "admin"
    applied = [
        e
        for e in rt.audit.org_changes()
        if e.data.get("via") == "approval" and e.data.get("outcome") == "applied"
    ]
    assert applied[-1].data["approval_id"] == err["approval_id"]
    assert applied[-1].actor.member_id == "u_katarzyna"
    assert applied[-1].data["requested_by"]["member_id"] == "u_marek"
    assert rt.bus.events("org.updated")[-1]["member"]["role"] == "admin"
    r = await client.get("/api/org/changes", params={"status": "applied"})
    assert any(c["approval_id"] == err["approval_id"] for c in r.json()["items"])
    # executor is idempotent
    again = await org_changes.org_executor(req)
    assert again["applied"] is False


async def test_executor_ignores_non_org_actions(rt):
    from aegis.core.types import ApprovalRequest

    req = ApprovalRequest(
        id="apr_x",
        action_type="spend.subscription",
        title="t",
        requester=_ident(rt, "u_piotr"),
        fingerprint="f",
        required_role="admin",
    )
    assert await org_changes.org_executor(req) is None


async def test_last_owner_conflict(client):
    r = await client.patch("/api/members/u_katarzyna", json={"role": "admin"}, headers=KAT)
    assert r.status_code == 409 and r.json()["error"]["type"] == "conflict"
    r = await client.patch("/api/members/u_katarzyna", json={"active": False}, headers=MAREK)
    assert r.status_code == 409


async def test_admin_cannot_change_own_role(client):
    r = await client.patch("/api/members/u_marek", json={"role": "member"}, headers=MAREK)
    assert r.status_code == 403 and r.json()["error"]["type"] == "forbidden"


async def test_approvals_unavailable(client, rt):
    rt.approvals.create_status = "denied"
    r = await client.patch("/api/members/u_piotr", json={"role": "admin"}, headers=MAREK)
    assert r.status_code == 403 and r.json()["error"]["type"] == "forbidden"
    from types import SimpleNamespace

    rt.approvals = SimpleNamespace(route=rt.approvals.route)  # no create_manual at all
    r = await client.patch("/api/members/u_james", json={"role": "admin"}, headers=MAREK)
    assert r.status_code == 403
    assert "approvals unavailable" in r.json()["error"]["message"]


async def test_reconcile_applies_without_executor(client, rt):
    err = await _promote(client)
    await rt.approvals.vote(
        err["approval_id"], _ident(rt, "u_katarzyna"), "approve", run_executor=False
    )
    assert rt.org.cache.members["u_piotr"].role == "member"
    r = await client.get("/api/members")
    piotr = next(m for m in r.json()["items"] if m["id"] == "u_piotr")
    assert piotr["role"] == "admin"
    assert piotr["meta"]["pending_changes"] == []


async def test_denied_approval_reconciles(client, rt):
    err = await _promote(client)
    await rt.approvals.vote(err["approval_id"], _ident(rt, "u_katarzyna"), "deny")
    r = await client.get("/api/org/changes")
    change = next(c for c in r.json()["items"] if c["approval_id"] == err["approval_id"])
    assert change["status"] == "denied"
    assert rt.org.cache.members["u_piotr"].role == "member"


async def test_owner_promotes_directly(client, rt):
    r = await client.patch("/api/members/u_piotr", json={"role": "admin"}, headers=KAT)
    assert r.status_code == 200 and r.json()["role"] == "admin"


async def test_create_member(client, rt):
    r = await client.post(
        "/api/members",
        headers=MAREK,
        json={
            "name": "Aleksandra Nowicka",
            "email": "a.nowicka@acme-capital.example",
            "role": "member",
            "team_id": "research",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "u_aleksandra"
    r = await client.post(
        "/api/members",
        headers=MAREK,
        json={"name": "Zofia Admin", "role": "admin", "team_id": "platform"},
    )
    assert r.status_code == 403 and r.json()["error"]["type"] == "approval_required"
    r = await client.post("/api/members", headers=PIOTR, json={"name": "X", "role": "member"})
    assert r.status_code == 403 and r.json()["error"]["type"] == "forbidden"
    r = await client.post("/api/members", headers=MAREK, json={"role": "member"})
    assert r.status_code == 400


async def test_agent_patch_flow(client, rt):
    r = await client.patch(
        "/api/agents/trading-copilot@trading",
        headers=MAREK,
        json={"allowed_models": ["claude-haiku-*", "mock-*"]},
    )
    assert r.status_code == 200 and r.json()["allowed_models"] == ["claude-haiku-*", "mock-*"]
    assert rt.org.peek_agent("trading-copilot@trading").allowed_models == [
        "claude-haiku-*",
        "mock-*",
    ]
    r = await client.patch(
        "/api/agents/research-agent@research", headers=MAREK, json={"max_destination": "remote"}
    )
    assert r.status_code == 403 and r.json()["error"]["type"] == "approval_required"
    r = await client.patch("/api/agents/legacy-bot@platform", headers=PIOTR, json={"active": True})
    assert r.status_code == 403


async def test_auto_route_cannot_bypass_owner_floor(client, rt, helpers):
    import copy

    doc = copy.deepcopy(helpers.POLICY)
    doc["approvals"]["rules"][0]["approver"] = "auto"  # org-owner-grants -> auto
    rt.policy.snap = helpers.make_snapshot(doc, version=2)
    rt.approvals.register_executor("action", org_changes.org_executor)
    r = await client.patch("/api/members/u_piotr", json={"role": "owner"}, headers=MAREK)
    assert r.status_code == 403, r.text
    assert "not applied" in r.json()["error"]["message"]
    assert rt.org.cache.members["u_piotr"].role == "member"


async def test_auto_approved_change_applies_once(client, rt, helpers):
    import copy

    doc = copy.deepcopy(helpers.POLICY)
    doc["approvals"]["rules"][1]["approver"] = "auto"  # org-privileged -> auto
    rt.policy.snap = helpers.make_snapshot(doc, version=2)
    rt.approvals.register_executor("action", org_changes.org_executor)
    # admin floor still applies to promote_admin: Marek (admin) satisfies it -> direct
    r = await client.patch("/api/members/u_piotr", json={"role": "admin"}, headers=MAREK)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    applied = [e for e in rt.audit.org_changes() if e.data.get("outcome") == "applied"]
    assert len(applied) == 1
