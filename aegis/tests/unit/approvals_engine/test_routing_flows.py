"""APR-V03: contract headline flows (F4/F5/F6/F9) route correctly through route()."""

from __future__ import annotations

import pytest

from aegis.approvals.routing import compile_section, describe_when, route_one
from aegis.core.policy_schema import ApprovalsSection, PolicyChange


def _route(svc, h, requester, **kw):
    return svc.route(requester=requester, **kw)


@pytest.mark.parametrize(
    ("agent", "amount", "role", "rule", "two"),
    [
        ("research-agent@research", 12, "self", "spend-self", False),
        ("trading-copilot@trading", 50, "admin", "spend-admin", False),
        ("claude-code@platform", 480, "owner", "spend-owner", False),
        ("trading-copilot@trading", 1500, "owner", "spend-owner-2p", True),
        ("chaos-agent@platform", None, "owner", "spend-owner-2p", True),  # unknown amount: fail closed
    ],
)
async def test_f4_spend_tiers(svc, h, agent, amount, role, rule, two) -> None:
    r = svc.route(kind="action", action_type="spend.subscription", requester=h.agent(agent),
                  amount_usd=amount, resource="vendor:marketpulse")
    assert (r.required_role, r.rule_id, r.two_person) == (role, rule, two)


async def test_f4_data_access_derived_from_resources(svc, h) -> None:
    tc = h.agent("trading-copilot@trading")
    # no labels given: sensitivity/env derived from rt.org.resources()
    r = svc.route(kind="action", action_type="db.read", requester=tc, resource="db:customers")
    assert (r.required_role, r.rule_id) == ("admin", "db-pii-read")
    r = svc.route(kind="action", action_type="db.read", requester=tc, resource="db:payment_cards")
    assert (r.required_role, r.rule_id) == ("deny", "db-restricted")
    r = svc.route(kind="action", action_type="db.write", requester=tc, resource="db:trades",
                  labels={"bulk": "true"})
    assert (r.required_role, r.rule_id, r.two_person) == ("owner", "db-prod-write", False)
    r = svc.route(kind="action", action_type="db.read", requester=tc, resource="db:market_prices")
    assert (r.required_role, r.rule_id) == ("auto", "db-read")
    r = svc.route(kind="action", action_type="db.read", requester=tc, resource="db:mystery")
    assert (r.required_role, r.rule_id) == ("admin", None)


async def test_f4_strict_vendor_label_derived(svc, h, fake_rt) -> None:
    fake_rt.policy.set_profile("strict")
    r = svc.route(kind="action", action_type="spend.subscription",
                  requester=h.agent("trading-copilot@trading"), amount_usd=15,
                  resource="vendor:shady-signals")
    assert (r.required_role, r.rule_id) == ("admin", "spend-strict-vendor")


def _raise(before, after, scope="team:trading", window="day"):
    return PolicyChange(kind="budget.raise", path=f"budgets.limits[scope={scope},window={window}].usd",
                        scope=scope, dimension="usd", before=before, after=after,
                        increase_pct=(after - before) / before * 100, loosening=True)


async def test_f5_config_governance(svc, h) -> None:
    piotr = h.member("u_piotr")
    r = svc.route(kind="config_change", action_type="budget.raise", requester=piotr,
                  changes=[_raise(60, 75)])
    assert (r.required_role, r.rule_id) == ("admin", "raise-team-small")
    r = svc.route(kind="config_change", action_type="budget.raise", requester=piotr,
                  changes=[_raise(60, 150)])
    assert (r.required_role, r.rule_id) == ("owner", "raise-large")
    dlp02 = PolicyChange(kind="control.disable", path="controls[id=DLP-02].enabled",
                         control_id="DLP-02", before=True, after=False, loosening=True)
    r = svc.route(kind="config_change", action_type="control.disable", requester=h.member("u_marek"),
                  changes=[dlp02])
    assert (r.required_role, r.rule_id) == ("owner", "disable-control-critical")


async def test_increase_pct_derived_when_missing(svc, h) -> None:
    ch = PolicyChange(kind="budget.raise", path="budgets.limits[scope=team:trading,window=day].usd",
                      scope="team:trading", before=60, after=150, loosening=True)
    r = svc.route(kind="config_change", action_type="budget.raise", requester=h.member("u_piotr"),
                  changes=[ch])
    assert r.rule_id == "raise-large"


async def test_multi_change_takes_highest_level(svc, h) -> None:
    enable = PolicyChange(kind="control.enable", path="controls[id=INJ-03].enabled",
                          control_id="INJ-03", before=False, after=True)
    r = svc.route(kind="config_change", action_type="control.enable", requester=h.member("u_piotr"),
                  changes=[enable, _raise(60, 75), _raise(60, 150, scope="team:research")])
    assert (r.required_role, r.rule_id) == ("owner", "raise-large")


async def test_f6_f9_budget_override_and_repin(svc, h) -> None:
    r = svc.route(kind="budget_raise", action_type="budget.override",
                  requester=h.agent("chaos-agent@platform"),
                  labels={"scope": "agent:chaos-agent@platform", "scope_type": "agent"})
    assert (r.required_role, r.rule_id) == ("admin", "budget-override")
    r = svc.route(kind="mcp_pin", action_type="mcp.repin", requester=h.agent("claude-code@platform"),
                  resource="mcp:rugpull.get_exchange_rate", labels={"dest": "third_party"})
    assert (r.required_role, r.rule_id) == ("admin", "mcp-repin")
    r = svc.route(kind="mcp_pin", action_type="mcp.repin", requester=h.agent("claude-code@platform"),
                  labels={"destination": "local"})  # legacy label name still understood
    assert (r.required_role, r.rule_id) == ("self", "mcp-repin-internal")


async def test_route_ttls_and_grants(svc, h) -> None:
    info = svc.route_info(kind="action", action_type="spend.charge",
                          requester=h.agent("trading-copilot@trading"), amount_usd=1500)
    assert info.route.ttl_s == 7200 and info.route.max_uses == 1
    info = svc.route_info(kind="action", action_type="spend.charge",
                          requester=h.agent("research-agent@research"), amount_usd=5)
    assert info.grant_ttl_s == 600


def test_unknown_condition_key_never_matches() -> None:
    section = ApprovalsSection.model_validate({
        "rules": [
            {"id": "typo-auto", "when": {"action": ["spend.*"], "amout_usd_lte": 1000}, "approver": "auto"},
            {"id": "catch", "when": {"action": ["spend.*"]}, "approver": "owner"},
        ]
    })
    compiled = compile_section(section, 7)
    m = route_one(compiled, {"kind": "action", "action": "spend.charge", "amount_usd": 5, "labels": {}})
    assert m.rule is not None and m.rule.id == "catch"
    assert "unknown keys" in describe_when(compiled.rules[0])


def test_describe_when_is_human(snippet) -> None:
    section = ApprovalsSection.model_validate(snippet["approvals"])
    compiled = compile_section(section, 1)
    by_id = {r.id: describe_when(r) for r in compiled.rules}
    assert by_id["spend-owner"] == "action ∈ spend.* · amount > $200 (or unknown)"
    assert "sensitivity ∈ RESTRICTED, SECRET" in by_id["db-restricted"]


async def test_route_never_raises(svc, h, monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(svc, "route_info", boom)
    r = svc.route(kind="action", action_type="spend.charge", requester=h.agent("chaos-agent@platform"))
    assert r.required_role == "owner"
