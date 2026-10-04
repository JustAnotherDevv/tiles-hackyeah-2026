"""APR-V06: GOV-05 config-change governance decisions (decide_change with the fake runtime)."""

from __future__ import annotations

from typing import Any

import pytest

from aegis.controls.config.gov05_config import CONTROLS, ConfigChangeGovernance, change_summary
from aegis.core.policy_schema import ControlConfig, PolicyChange

RAISE_75 = {"kind": "budget.raise", "path": "budgets.limits[scope=team:trading,window=day].usd",
            "scope": "team:trading", "dimension": "usd", "before": 60, "after": 75,
            "increase_pct": 25, "loosening": True}
ORG_RAISE = {"kind": "budget.raise", "path": "budgets.limits[scope=org,window=month].usd",
             "scope": "org", "dimension": "usd", "before": 1000, "after": 1500,
             "increase_pct": 50, "loosening": True}
DLP02_OFF = {"kind": "control.disable", "path": "controls[id=DLP-02].enabled",
             "control_id": "DLP-02", "before": True, "after": False, "loosening": True}


def _cfg(fake_rt) -> ControlConfig:
    cfg = fake_rt.policy.control_config("GOV-05")
    assert cfg is not None, "GOV-05 entry missing from the snippet"
    return cfg


def _decide(fake_rt, h, identity, changes: list[dict[str, Any]] | None, **meta: Any):
    ctl: ConfigChangeGovernance = CONTROLS[0]
    i = h.config_interaction(changes or [])
    if changes is None:
        i.meta.pop("changes", None)
    i.meta.update(meta)
    ctx = h.ctx(identity, source="dashboard")
    ctx.policy = fake_rt.policy.snapshot()
    if changes is None:
        return None, ctx, i
    return ctl.decide_change(fake_rt, ctx, i, _cfg(fake_rt), changes), ctx, i


def test_control_surface() -> None:
    ctl = CONTROLS[0]
    assert ctl.id == "GOV-05" and ctl.kind == "deterministic"
    assert "config.change" in ctl.applies_to.surfaces and "config_change" in ctl.applies_to.kinds


def test_change_summary_budget_raise() -> None:
    s = change_summary(PolicyChange.model_validate(RAISE_75))
    assert s == "raise team:trading day usd 60 → 75 (+25%)"


async def test_member_raise_requires_admin_approval(svc, h, fake_rt) -> None:
    d, _, _ = _decide(fake_rt, h, h.member("u_piotr"), [RAISE_75])
    assert d.action == "require_approval"
    assert d.approval is not None and d.approval.kind == "config_change"
    assert "+25%" in d.approval.title and "Piotr" in d.approval.title
    assert d.approval.payload["changes"][0]["after"] == 75
    assert d.findings[0].meta["rule_id"] == "raise-team-small"
    assert d.findings[0].meta["required_role"] == "admin"
    assert d.findings[0].category == "governance"


async def test_admin_raise_is_authorized(svc, h, fake_rt) -> None:
    d, _, _ = _decide(fake_rt, h, h.member("u_emily"), [RAISE_75])
    assert d.action == "allow"
    assert d.reason.startswith("authorized: admin ≥ admin")
    assert "raise-team-small" in d.reason


async def test_owner_org_raise_is_authorized(svc, h, fake_rt) -> None:
    d, _, _ = _decide(fake_rt, h, h.member("u_katarzyna"), [ORG_RAISE])
    assert d.action == "allow" and d.reason.startswith("authorized: owner ≥ owner")


async def test_admin_disabling_critical_control_needs_owner(svc, h, fake_rt) -> None:
    d, _, _ = _decide(fake_rt, h, h.member("u_marek"), [DLP02_OFF])
    assert d.action == "require_approval"
    assert d.findings[0].meta["rule_id"] == "disable-control-critical"
    assert d.findings[0].meta["required_role"] == "owner"
    assert d.severity == "high"


async def test_agent_proposer_requires_approval(svc, h, fake_rt) -> None:
    d, _, _ = _decide(fake_rt, h, h.agent("claude-code@platform"), [RAISE_75])
    assert d.action == "require_approval" and d.approval is not None


async def test_agent_proposals_block_param(svc, h, fake_rt) -> None:
    cfg = _cfg(fake_rt).model_copy(update={"params": {"agent_proposals": "block"}})
    i = h.config_interaction([RAISE_75])
    ctx = h.ctx(h.agent("claude-code@platform"), source="dashboard")
    d = CONTROLS[0].decide_change(fake_rt, ctx, i, cfg, [RAISE_75])
    assert d.action == "block" and "agents may not change policy" in d.reason


async def test_strict_owner_two_person_cosigns(svc, h, fake_rt) -> None:
    fake_rt.policy.set_profile("strict")
    owner = h.member("u_katarzyna")
    d, ctx, i = _decide(fake_rt, h, owner, [DLP02_OFF])
    assert d.action == "require_approval"
    assert d.findings[0].meta["rule_id"] == "disable-control-strict"
    assert d.findings[0].meta["two_person"] is True
    assert "second admin" in d.reason
    req = await svc.request(ctx, i, d)
    assert req.status == "pending" and req.two_person
    assert [(v.member_id, v.decision) for v in req.votes] == [("u_katarzyna", "approve")]
    done = await svc.vote(req.id, h.member("u_emily"), "approve")
    assert done.status == "approved"


async def test_protect_more_is_auto(svc, h, fake_rt) -> None:
    on = {"kind": "control.enable", "path": "controls[id=INJ-02].enabled", "control_id": "INJ-02",
          "before": False, "after": True, "loosening": False}
    d, _, _ = _decide(fake_rt, h, h.member("u_piotr"), [on])
    assert d.action == "allow" and d.reason == "auto: rule protect-more"


async def test_deny_rule_blocks(h, make_doc_fn, svc, fake_rt) -> None:
    from aegis.core.policy_schema import PolicyDoc  # noqa: F401

    doc = fake_rt.policy.snapshot().doc
    approvals = doc.approvals.model_dump(mode="json", by_alias=True, exclude_none=True)
    approvals["config_rules"].insert(0, {"id": "no-raises", "when": {"action": ["budget.raise"]},
                                         "approver": "deny"})
    new_doc = make_doc_fn(approvals=approvals)
    from aegis.core.policy_schema import PolicySnapshot

    fake_rt.policy.snap = PolicySnapshot(version=9, sha256="x", doc=new_doc,
                                         controls={c.id: c for c in new_doc.controls})
    d, _, _ = _decide(fake_rt, h, h.member("u_katarzyna"), [RAISE_75])
    assert d.action == "block" and "no-raises" in d.reason


async def test_no_changes_returns_none(svc, h, fake_rt, monkeypatch) -> None:
    ctl = CONTROLS[0]
    monkeypatch.setattr(ctl, "_rt", lambda: fake_rt)
    i = h.config_interaction([])
    i.meta.pop("changes")
    ctx = h.ctx(h.member("u_piotr"), source="hook")
    assert await ctl.evaluate(ctx, i, _cfg(fake_rt)) is None


@pytest.mark.parametrize("member", ["u_piotr", "u_emily"])
async def test_evaluate_uses_runtime(svc, h, fake_rt, monkeypatch, member) -> None:
    ctl = CONTROLS[0]
    monkeypatch.setattr(ctl, "_rt", lambda: fake_rt)
    i = h.config_interaction([RAISE_75])
    d = await ctl.evaluate(h.ctx(h.member(member), source="dashboard"), i, _cfg(fake_rt))
    assert d.action == ("require_approval" if member == "u_piotr" else "allow")
