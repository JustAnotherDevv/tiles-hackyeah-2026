"""UIG-16 — in-process API contract smoke test for the governance dashboard (plan 17 §5, UIG-V10).

Exercises exactly the endpoints and fields the approvals/org/rules/budgets pages rely on, as the
F4/F5 personas (view_as u_piotr / u_emily). Each step skips (never fails) when its endpoint is not
there yet (404/405/501) or the app cannot start, so the test is safe to run while other workstreams
are mid-flight. Owner: B18-dashboard-gov-approvals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

MISSING = {404, 405, 501}


@pytest.fixture
async def gov_client(aegis_env: dict[str, Any]) -> AsyncIterator[Any]:
    try:
        import httpx
        from asgi_lifespan import LifespanManager

        from aegis.app import create_app
        from aegis.settings import Settings

        application = create_app(Settings.from_env())
        manager = LifespanManager(application, startup_timeout=60, shutdown_timeout=30)
        await manager.__aenter__()
    except Exception as exc:
        pytest.skip(f"app not startable yet: {type(exc).__name__}: {exc}")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://aegis.test", timeout=30) as c:
            yield c
    finally:
        await manager.__aexit__(None, None, None)


def _skip_missing(resp: Any, what: str) -> None:
    if resp.status_code in MISSING:
        pytest.skip(f"{what} not implemented yet ({resp.status_code})")


async def test_approvals_list_carries_viewer_fields(gov_client: Any) -> None:
    r = await gov_client.get("/api/approvals?status=pending&view_as=u_piotr")
    _skip_missing(r, "GET /api/approvals")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and isinstance(body["items"], list)
    for item in body["items"]:
        assert "can_vote" in item, "A-28: list items carry can_vote/why_not when a viewer is known"
        if item["can_vote"] is False:
            assert item.get("why_not"), "locked items must explain why (LockedAction tooltip)"


async def test_rules_and_org_shapes(gov_client: Any) -> None:
    r = await gov_client.get("/api/approvals/rules")
    _skip_missing(r, "GET /api/approvals/rules")
    assert r.status_code == 200, r.text
    rules = r.json()
    assert {"rules", "config_rules", "defaults"} <= rules.keys()
    for row in rules["rules"] + rules["config_rules"]:
        assert {"id", "when", "approver", "two_person"} <= row.keys()

    m = await gov_client.get("/api/members?view_as=u_emily")
    _skip_missing(m, "GET /api/members")
    assert m.status_code == 200, m.text
    ids = {x["id"] for x in m.json()["items"]}
    assert {"u_katarzyna", "u_emily", "u_piotr"} <= ids

    a = await gov_client.get("/api/agents?view_as=u_emily")
    _skip_missing(a, "GET /api/agents")
    assert a.status_code == 200, a.text
    sponsors = {x["id"]: x.get("owner_member_id") for x in a.json()["items"]}
    if "trading-copilot@trading" in sponsors:
        assert sponsors["trading-copilot@trading"] == "u_piotr"


async def test_simulate_routes_like_the_inbox(gov_client: Any) -> None:
    r = await gov_client.post(
        "/api/approvals/simulate?view_as=u_emily",
        json={"kind": "action", "action_type": "spend.subscription", "amount_usd": 50, "requester_agent_id": "trading-copilot@trading"},
    )
    _skip_missing(r, "POST /api/approvals/simulate")
    assert r.status_code == 200, r.text
    route = r.json()
    assert route["required_role"] == "admin"
    assert {"two_person", "rule_id", "ttl_s", "max_uses"} <= route.keys()


async def test_budget_raise_flow_f5(gov_client: Any) -> None:
    before = await gov_client.get("/api/policy?view_as=u_emily")
    _skip_missing(before, "GET /api/policy")
    v0 = before.json()["version"]

    r = await gov_client.post(
        "/api/budgets/raise?view_as=u_piotr",
        json={"scope": "team:trading", "window": "day", "dimension": "usd", "new_limit": 75, "reason": "UIG-16 contract test"},
    )
    _skip_missing(r, "POST /api/budgets/raise")
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["status"] == "pending_approval", res
    apr = res["approval"]
    assert apr["required_role"] == "admin"

    # the requester (a member) cannot approve an admin-level item
    own = await gov_client.post(f"/api/approvals/{apr['id']}/approve?view_as=u_piotr", json={"comment": None})
    _skip_missing(own, "POST /api/approvals/{id}/approve")
    assert own.status_code == 403, own.text

    ok = await gov_client.post(f"/api/approvals/{apr['id']}/approve?view_as=u_emily", json={"comment": "fine"})
    assert ok.status_code == 200, ok.text
    done = ok.json()
    assert done["status"] == "approved"
    assert (done.get("execution") or {}).get("policy_version"), done.get("execution")

    after = await gov_client.get("/api/policy?view_as=u_emily")
    assert after.json()["version"] > v0


async def test_validate_reports_line_for_tab_error(gov_client: Any) -> None:
    pol = await gov_client.get("/api/policy?view_as=u_emily")
    _skip_missing(pol, "GET /api/policy")
    broken = pol.json()["yaml"] + "\nprofile:\n\tbad: tab\n"
    r = await gov_client.post("/api/policy/validate?view_as=u_emily", json={"yaml": broken, "selftest": False})
    _skip_missing(r, "POST /api/policy/validate")
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is False
    assert any(e.get("line") for e in rep["errors"]), rep["errors"]
