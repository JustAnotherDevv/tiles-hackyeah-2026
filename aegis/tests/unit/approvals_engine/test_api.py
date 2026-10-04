"""APR-V07: /api/approvals* contract and RBAC over in-process ASGI (no ports)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from aegis.api.routes.approvals import router


@pytest.fixture
async def client(svc, fake_rt):
    app = FastAPI()
    app.include_router(router)
    app.state.rt = fake_rt
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://aegis.test") as c:
        yield c


def as_(member: str) -> dict[str, str]:
    return {"X-Aegis-View-As": member}


async def _pending(svc, h):
    i = h.spend(50.0)
    return await svc.request(h.ctx(h.agent("trading-copilot@trading")), i, h.decision(i))


async def test_list_has_can_vote_and_counts(client, svc, h) -> None:
    req = await _pending(svc, h)
    r = await client.get("/api/approvals", params={"status": "pending"}, headers=as_("u_piotr"))
    assert r.status_code == 200
    body = r.json()
    assert set(body["counts"]) == {"pending", "approved", "denied", "expired", "cancelled"}
    assert body["counts"]["pending"] == 1
    item = next(x for x in body["items"] if x["id"] == req.id)
    assert item["can_vote"] is False and "Separation of duties" in item["why_not"]
    r = await client.get("/api/approvals", params={"status": "pending"}, headers=as_("u_emily"))
    item = r.json()["items"][0]
    assert item["can_vote"] is True and item["why_not"] is None
    # mine: piotr sponsors the requesting agent; james does not
    r = await client.get("/api/approvals", params={"mine": "true"}, headers=as_("u_piotr"))
    assert [x["id"] for x in r.json()["items"]] == [req.id]
    r = await client.get("/api/approvals", params={"mine": "true"}, headers=as_("u_james"))
    assert r.json()["items"] == []


async def test_bad_filters_400(client) -> None:
    r = await client.get("/api/approvals", params={"status": "bogus"})
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request"


async def test_vote_rbac_conflict_and_not_found(client, svc, h) -> None:
    req = await _pending(svc, h)
    r = await client.post(f"/api/approvals/{req.id}/approve", headers=as_("u_piotr"))
    assert r.status_code == 403
    err = r.json()["error"]
    assert err["type"] == "forbidden" and "Separation of duties" in err["message"]
    r = await client.post(f"/api/approvals/{req.id}/approve", headers=as_("u_olivia"))
    assert r.status_code == 403 and "Needs admin" in r.json()["error"]["message"]
    r = await client.post(f"/api/approvals/{req.id}/approve", headers=as_("u_emily"),
                          json={"comment": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["decided_by"] == ["u_emily"]
    r = await client.post(f"/api/approvals/{req.id}/approve", headers=as_("u_marek"))
    assert r.status_code == 409 and r.json()["error"]["type"] == "conflict"
    r = await client.post("/api/approvals/apr_nope/approve", headers=as_("u_emily"))
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found"
    r = await client.get("/api/approvals/apr_nope")
    assert r.status_code == 404


async def test_deny_and_cancel(client, svc, h) -> None:
    req = await _pending(svc, h)
    r = await client.post(f"/api/approvals/{req.id}/cancel", headers=as_("u_james"))
    assert r.status_code == 403
    r = await client.post(f"/api/approvals/{req.id}/deny", headers=as_("u_emily"),
                          json={"comment": "not this quarter"})
    assert r.status_code == 200 and r.json()["status"] == "denied"
    req2 = await _pending(svc, h)
    assert req2.id != req.id or req2.status == "denied"  # deny cooldown may return the denied one
    i = h.spend(480.0, vendor="gpucloud", plan="a100-24h-reservation")
    req3 = await svc.request(h.ctx(h.agent("claude-code@platform")), i, h.decision(i))
    r = await client.post(f"/api/approvals/{req3.id}/cancel", headers=as_("u_tomasz"))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


async def test_get_one_has_full_payload(client, svc, h) -> None:
    req = await _pending(svc, h)
    r = await client.get(f"/api/approvals/{req.id}", headers=as_("u_emily"))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == req.id and body["can_vote"] is True
    assert body["required_role"] == "admin" and body["rule_id"] == "spend-admin"


async def test_rules_ordered_with_human_when(client) -> None:
    r = await client.get("/api/approvals/rules")
    assert r.status_code == 200
    body = r.json()
    ids = [x["id"] for x in body["rules"]]
    assert ids.index("spend-owner-2p") < ids.index("spend-owner") < ids.index("spend-admin")
    orders = [x["order"] for x in body["rules"]]
    assert orders == sorted(orders)
    spend_owner = next(x for x in body["rules"] if x["id"] == "spend-owner")
    assert isinstance(spend_owner["when"], str) and "$" in spend_owner["when"]
    assert body["defaults"]["ttl_s"] == 900
    assert any(x["id"] == "raise-team-small" for x in body["config_rules"])


async def test_simulate_contract_shape(client) -> None:
    r = await client.post("/api/approvals/simulate", json={
        "kind": "action", "action_type": "spend.subscription", "amount_usd": 50,
        "requester_agent_id": "trading-copilot@trading"})
    assert r.status_code == 200
    body = r.json()
    assert {k: body[k] for k in ("required_role", "rule_id", "two_person", "ttl_s", "max_uses")} == {
        "required_role": "admin", "rule_id": "spend-admin", "two_person": False, "ttl_s": 900,
        "max_uses": 1}
    assert "u_emily" in body["explain"]["eligible"] and "u_piotr" not in body["explain"]["eligible"]
    r = await client.post("/api/approvals/simulate", json={
        "kind": "config_change", "action_type": "budget.raise", "scope": "team:trading",
        "increase_pct": 150, "loosening": True, "requester_member_id": "u_piotr"})
    assert r.status_code == 200 and r.json()["rule_id"] == "raise-large"


async def test_wait_returns_early_after_vote(client, svc, h) -> None:
    req = await _pending(svc, h)

    async def later() -> None:
        await asyncio.sleep(0.15)
        await svc.vote(req.id, h.member("u_emily"), "approve")

    task = asyncio.create_task(later())
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    r = await client.get(f"/api/approvals/{req.id}/wait", params={"timeout_s": 10},
                         headers=as_("u_piotr"))
    elapsed = loop.time() - t0
    await task
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert elapsed < 3.0
    r = await client.get("/api/approvals/apr_nope/wait", params={"timeout_s": 0})
    assert r.status_code == 404


async def test_manual_budget_raise_request(client) -> None:
    draft = {"kind": "budget_raise", "action_type": "budget.raise", "title": "Raise trading day",
             "payload": {"patch": [{"op": "replace",
                                    "path": "budgets.limits[scope=team:trading,window=day].usd",
                                    "value": 75}]}}
    r = await client.post("/api/approvals", json=draft, headers=as_("u_piotr"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending" and r.json()["kind"] == "budget_raise"
    bad = dict(draft, payload={"patch": [{"op": "replace", "path": "controls[id=DLP-02].enabled",
                                          "value": False}]})
    r = await client.post("/api/approvals", json=bad, headers=as_("u_piotr"))
    assert r.status_code == 400


async def test_timeline(client, svc, h) -> None:
    req = await _pending(svc, h)
    await svc.vote(req.id, h.member("u_emily"), "approve")
    r = await client.get(f"/api/approvals/{req.id}/timeline")
    assert r.status_code == 200
    types = [e["event_type"] for e in r.json()["items"]]
    assert types[:2] == ["approval.created", "approval.decided"]
