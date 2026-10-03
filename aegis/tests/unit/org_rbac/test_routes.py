"""ORG-V07 (part 2): read endpoints validate against pydantic mirrors of the frozen TS types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from aegis.core.types import Agent, Identity, Member, Org, Team


class _Strict(BaseModel):
    model_config = ConfigDict(extra="allow")


class TeamRow(Team):
    member_count: int
    agent_count: int


class OrgResponseTS(_Strict):
    org: Org
    teams: list[TeamRow]
    counts: dict[str, int]


class MemberTS(Member):
    agents: list[str]


class AgentTS(Agent):
    status: Literal["active", "killed", "idle"]
    spend_today_usd: float


class PermissionsTS(BaseModel):
    model_config = ConfigDict(extra="forbid")
    can_apply_policy: Literal["yes", "approval", "no"]
    can_manage_members: bool
    can_killswitch: bool
    can_export_audit: bool
    approver_levels: list[Literal["auto", "self", "admin", "owner", "deny"]]


class WhoAmITS(_Strict):
    identity: Identity
    member: MemberTS | None
    permissions: PermissionsTS


async def test_whoami(client, helpers):
    r = await client.get("/api/whoami", headers=helpers.as_viewer("u_piotr"))
    assert r.status_code == 200
    body = WhoAmITS.model_validate(r.json())
    assert body.identity.member_id == "u_piotr"
    assert body.permissions.can_manage_members is False
    assert body.permissions.approver_levels == ["self"]
    assert body.permissions.can_apply_policy == "approval"
    assert body.member.agents == ["trading-copilot@trading"]
    data = r.json()
    assert data["capabilities"]["members.manage"] == "no"
    assert {o["member_id"] for o in data["view_as_options"]} >= {"u_katarzyna", "u_piotr"}
    r = await client.get("/api/whoami", headers={"X-Aegis-View-As": "member"})
    assert r.json()["identity"]["member_id"] == "u_piotr"
    r = await client.get("/api/whoami")
    body = WhoAmITS.model_validate(r.json())
    assert body.identity.member_id == "u_katarzyna"
    assert body.permissions.can_apply_policy == "yes"
    assert body.permissions.approver_levels == ["self", "admin", "owner"]


async def test_org(client):
    r = await client.get("/api/org")
    body = OrgResponseTS.model_validate(r.json())
    assert body.counts == {"members": 8, "agents": 5, "teams": 3}
    teams = {t.id: t for t in body.teams}
    assert teams["platform"].agent_count == 3
    assert teams["research"].member_count == 4  # katarzyna, emily, agnieszka, james
    assert r.json()["meta"]["seed_version"]


async def test_members(client):
    r = await client.get("/api/members")
    items = [MemberTS.model_validate(i) for i in r.json()["items"]]
    assert len(items) == 8
    tomasz = next(m for m in items if m.id == "u_tomasz")
    assert tomasz.agents == ["claude-code@platform", "chaos-agent@platform"]
    assert tomasz.meta["pending_changes"] == []
    r = await client.get("/api/members", params={"role": "admin"})
    assert [m["id"] for m in r.json()["items"]] == ["u_marek", "u_emily"]
    r = await client.get("/api/members", params={"team_id": "research"})
    assert len(r.json()["items"]) == 4
    r = await client.get("/api/members/u_piotr")
    assert r.json()["id"] == "u_piotr"
    r = await client.get("/api/members/u_nobody")
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found"


async def test_agents(client):
    r = await client.get("/api/agents")
    items = {i["id"]: AgentTS.model_validate(i) for i in r.json()["items"]}
    assert len(items) == 5
    assert items["legacy-bot@platform"].status == "killed"
    assert items["research-agent@research"].spend_today_usd == 0.0
    keys = {k["key_id"]: k for k in r.json()["items"][3]["keys"]}  # chaos-agent
    assert keys["key_revoked_demo"]["status"] == "revoked"
    assert keys["key_expired_demo"]["status"] == "expired"
    assert all("key_hmac" not in k and "key" not in k for k in keys.values())


async def test_agent_status_killswitch(client, rt, helpers):
    import copy

    doc = copy.deepcopy(helpers.POLICY)
    doc["budgets"]["kill_switch"]["agents"] = ["chaos-agent@*"]
    rt.policy.snap = helpers.make_snapshot(doc)
    r = await client.get("/api/agents")
    status = {i["id"]: i["status"] for i in r.json()["items"]}
    assert status["chaos-agent@platform"] == "killed"
    assert status["claude-code@platform"] == "idle"


async def test_permissions_endpoint(client):
    r = await client.get("/api/org/permissions", headers={"X-Aegis-View-As": "u_piotr"})
    body = r.json()
    assert body["policy_version"] == 1
    assert {c["id"] for c in body["capabilities"]} >= {"members.manage", "policy.edit"}


async def test_keys_endpoints(client, rt):
    r = await client.get(
        "/api/agents/claude-code@platform/keys", headers={"X-Aegis-View-As": "u_piotr"}
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/agents/claude-code@platform/keys", headers={"X-Aegis-View-As": "u_marek"}
    )
    assert r.status_code == 201
    created = r.json()
    assert created["key"].startswith("aegis_") and created["status"] == "active"
    ident = await rt.org.resolve_identity({"authorization": f"Bearer {created['key']}"})
    assert ident.authenticated and ident.agent_id == "claude-code@platform"
    r = await client.post(
        f"/api/agents/claude-code@platform/keys/{created['key_id']}/revoke",
        headers={"X-Aegis-View-As": "u_marek"},
    )
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    ident = await rt.org.resolve_identity({"authorization": f"Bearer {created['key']}"})
    assert ident.credential_error == "revoked"
    r = await client.get(
        "/api/agents/claude-code@platform/keys", headers={"X-Aegis-View-As": "u_marek"}
    )
    assert len(r.json()["items"]) == 2


async def test_set_view_as_cookie(client):
    r = await client.post("/api/whoami", json={"view_as": "emily"})
    assert r.status_code == 200 and "aegis_view_as=u_emily" in r.headers["set-cookie"]
