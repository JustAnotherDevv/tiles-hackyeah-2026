"""ORG-V07 (part 1): permission matrix, whoami permissions, org-op authorization."""

from __future__ import annotations

from aegis.core.types import Identity
from aegis.org import permissions as perms


def _viewer(rt, member_id):
    m = rt.org.cache.members[member_id]
    return Identity(org_id=m.org_id, team_id=m.team_id, member_id=m.id, role=m.role)


def test_whoami_permissions(rt):
    snap = rt.policy.snapshot()
    piotr = perms.whoami_permissions(rt, rt.org.cache, _viewer(rt, "u_piotr"), snap)
    assert piotr == {
        "can_apply_policy": "approval",
        "can_manage_members": False,
        "can_killswitch": False,
        "can_export_audit": False,
        "approver_levels": ["self"],
    }
    kat = perms.whoami_permissions(rt, rt.org.cache, _viewer(rt, "u_katarzyna"), snap)
    assert kat["can_apply_policy"] == "yes"
    assert kat["approver_levels"] == ["self", "admin", "owner"]
    marek = perms.whoami_permissions(rt, rt.org.cache, _viewer(rt, "u_marek"), snap)
    assert marek["can_apply_policy"] == "approval"
    assert marek["can_manage_members"] and marek["can_killswitch"] and marek["can_export_audit"]
    agent = Identity(org_id="acme-capital", agent_id="claude-code@platform", role="agent")
    assert perms.whoami_permissions(rt, rt.org.cache, agent, snap)["can_apply_policy"] == "no"


def test_capabilities_and_matrix(rt):
    caps = perms.capabilities_for(rt, rt.org.cache, _viewer(rt, "u_marek"))
    assert caps["members.manage"] == "partial"
    assert caps["policy.edit"] == "partial"
    assert caps["budgets.raise"] == "partial"
    assert caps["killswitch.engage"] == "yes"
    assert caps["approvals.owner"] == "no"
    piotr = perms.capabilities_for(rt, rt.org.cache, _viewer(rt, "u_piotr"))
    assert piotr["members.manage"] == "no" and piotr["policy.edit"] == "approval"
    m = perms.matrix(rt, rt.policy.snapshot())
    assert m["roles"] == ["owner", "admin", "member", "agent"]
    rows = {c["id"]: c for c in m["capabilities"]}
    assert rows["members.manage"]["cells"]["owner"]["value"] == "yes"
    assert rows["members.manage"]["cells"]["admin"]["value"] == "partial"
    assert rows["org.view"]["cells"]["agent"]["value"] == "no"
    lv = {r["rule_id"]: r for r in m["approval_levels"]}
    assert lv["org-privileged"]["roles"] == ["owner"]
    assert lv["org-routine"]["roles"] == ["owner", "admin"]


def test_matrix_follows_policy_edits(rt, helpers):
    import copy

    doc = copy.deepcopy(helpers.POLICY)
    doc["approvals"]["rules"][1]["approver"] = "admin"  # judges lower org-privileged
    rt.policy.snap = helpers.make_snapshot(doc, version=2)
    caps = perms.capabilities_for(rt, rt.org.cache, _viewer(rt, "u_marek"))
    # promote_owner / create_owner still need an owner (hard floor), so still partial
    assert caps["members.manage"] == "partial"
    authz, _ = perms.authorize_member_patch(
        rt, rt.org.cache, _viewer(rt, "u_marek"), rt.org.cache.members["u_piotr"], {"role": "admin"}
    )
    assert authz.decision == "direct"


def test_authorize_member_patch(rt):
    cache = rt.org.cache
    piotr, marek, kat = (_viewer(rt, m) for m in ("u_piotr", "u_marek", "u_katarzyna"))
    olivia = cache.members["u_olivia"]
    assert (
        perms.authorize_member_patch(rt, cache, piotr, olivia, {"team_id": "research"})[0].decision
        == "forbidden"
    )
    a, ch = perms.authorize_member_patch(rt, cache, marek, olivia, {"team_id": "research"})
    assert a.decision == "direct" and ch == {"team_id": "research"}
    a, _ = perms.authorize_member_patch(
        rt, cache, marek, cache.members["u_piotr"], {"role": "admin"}
    )
    assert (a.decision, a.required, a.action_type) == (
        "approval",
        "owner",
        "org.role.promote_admin",
    )
    a, _ = perms.authorize_member_patch(rt, cache, kat, cache.members["u_piotr"], {"role": "admin"})
    assert a.decision == "direct"
    a, _ = perms.authorize_member_patch(
        rt, cache, kat, cache.members["u_katarzyna"], {"role": "admin"}
    )
    assert a.decision == "conflict"  # last active owner (checked before "own role")
    a, _ = perms.authorize_member_patch(
        rt, cache, marek, cache.members["u_marek"], {"role": "member"}
    )
    assert a.decision == "forbidden"
    a, _ = perms.authorize_member_patch(rt, cache, marek, olivia, {"team_id": "nope"})
    assert a.decision == "invalid"
    a, _ = perms.authorize_member_patch(rt, cache, marek, olivia, {"team_id": "trading"})
    assert a.decision == "noop"
    # mixed patch is gated as a whole
    a, _ = perms.authorize_member_patch(
        rt, cache, marek, olivia, {"team_id": "research", "role": "admin"}
    )
    assert a.decision == "approval" and a.required == "owner"


def test_route_failure_falls_back_to_defaults(rt):
    rt.approvals.fail_route = True
    cache = rt.org.cache
    a, _ = perms.authorize_member_patch(
        rt, cache, _viewer(rt, "u_marek"), cache.members["u_piotr"], {"role": "admin"}
    )
    assert a.decision == "approval" and a.required == "owner"
    m = perms.matrix(rt, rt.policy.snapshot())
    assert m["capabilities"]


def test_agent_patch_levels(rt):
    cache = rt.org.cache
    marek = _viewer(rt, "u_marek")
    research = cache.agents["research-agent@research"]
    a, _ = perms.authorize_agent_patch(rt, cache, marek, research, {"max_destination": "remote"})
    assert (a.decision, a.action_type) == ("approval", "org.agent.widen_destination")
    a, _ = perms.authorize_agent_patch(rt, cache, marek, research, {"allowed_models": ["qwen*"]})
    assert a.decision == "direct"
    a, _ = perms.authorize_agent_patch(
        rt, cache, _viewer(rt, "u_piotr"), research, {"active": False}
    )
    assert a.decision == "forbidden"
