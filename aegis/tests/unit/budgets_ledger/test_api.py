"""BUD-V09: /api/budgets* and /api/killswitch (in-process ASGI, fake runtime)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request

from aegis.api.routes import budgets as routes
from aegis.core.errors import AegisHTTPError
from aegis.core.policy_schema import PatchOp


@pytest.fixture
async def client(rt, led, clock):
    app = FastAPI()

    @app.exception_handler(AegisHTTPError)
    async def _err(request: Request, exc: AegisHTTPError):  # mirrors aegis.app
        return exc.response(None)

    app.include_router(routes.router)
    app.state.rt = rt
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


def as_(who: str) -> dict[str, str]:
    return {"x-aegis-view-as": who}


async def test_get_budgets_shape(client, led) -> None:
    await led.import_usage("team:trading", "usd", 38.4, "day")
    r = await client.get("/api/budgets")
    assert r.status_code == 200
    body = r.json()
    assert {"generated_at", "currency", "pricing_version", "scopes", "kill_switch"} <= set(body)
    assert set(body["kill_switch"]) >= {"global", "teams", "members", "agents", "sessions"}
    trading = [s for s in body["scopes"] if s["scope"] == "team:trading"]
    assert trading
    row = next(x for x in trading[0]["limits"] if x["dimension"] == "usd" and x["window"] == "day")
    assert row["used"] == pytest.approx(38.4) and row["limit"] == 60 and row["state"] == "ok"


async def test_raise_team_sets_entry(client, rt) -> None:
    r = await client.post(
        "/api/budgets/raise",
        json={"scope": "team:trading", "window": "day", "dimension": "usd", "new_limit": 75},
        headers=as_("u_piotr"),
    )
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    sent = rt.policy.proposed[-1]
    assert sent["patch"] == [
        PatchOp(op="set", path="budgets.limits[scope=team:trading,window=day].usd", value=75)
    ]
    assert sent["actor"].member_id == "u_piotr" and sent["source"] == "dashboard"


async def test_raise_member_appends(client, rt) -> None:
    r = await client.post(
        "/api/budgets/raise",
        json={"scope": "member:u_piotr", "dimension": "usd", "new_limit": 8},
        headers=as_("u_piotr"),
    )
    assert r.status_code == 200
    op = rt.policy.proposed[-1]["patch"][0]
    assert op.op == "append" and op.path == "budgets.limits"
    assert op.value["scope"] == "member:u_piotr" and op.value["usd"] == 8


async def test_raise_preview_route(client) -> None:
    r = await client.post(
        "/api/budgets/raise/preview",
        json={"scope": "team:trading", "window": "day", "dimension": "usd", "new_limit": 75},
        headers=as_("u_piotr"),
    )
    body = r.json()
    assert r.status_code == 200
    assert body["route"]["required_role"] == "admin" and body["viewer_can_apply"] is False
    assert body["change"]["before"] == 60 and body["change"]["after"] == 75


async def test_bad_requests_400(client) -> None:
    r = await client.post(
        "/api/budgets/raise", json={"scope": "team:trading", "dimension": "gold", "new_limit": 5}
    )
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request"
    r = await client.post("/api/budgets/raise", json={"scope": "planet:x", "new_limit": 5})
    assert r.status_code == 400
    r = await client.post("/api/budgets/raise", json={"scope": "team:trading", "new_limit": 0})
    assert r.status_code == 400
    r = await client.get("/api/budgets/history", params={"scope": "team:trading", "dimension": "x"})
    assert r.status_code == 400


async def test_reset_requires_admin(client, led) -> None:
    r = await client.post("/api/budgets/reset", json={}, headers=as_("u_piotr"))
    assert r.status_code == 403 and r.json()["error"]["type"] == "forbidden"
    await led.import_usage("team:trading", "usd", 10, "day")
    r = await client.post(
        "/api/budgets/reset", json={"scope": "team:trading"}, headers=as_("u_emily")
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert led.used("team:trading", "day", "usd") == 0.0


async def test_killswitch_patch_and_noop(client, rt) -> None:
    r = await client.post(
        "/api/killswitch",
        json={"scope": "agent:chaos-agent@platform", "active": True, "reason": "demo"},
        headers=as_("u_marek"),
    )
    assert r.status_code == 200
    op = rt.policy.proposed[-1]["patch"][0]
    assert op.op == "append" and op.path == "budgets.kill_switch.agents"
    n = len(rt.policy.proposed)
    r = await client.post(
        "/api/killswitch", json={"scope": "agent:chaos-agent@platform", "active": False}
    )
    assert r.json()["status"] == "noop" and len(rt.policy.proposed) == n
    r = await client.post("/api/killswitch", json={"scope": "bogus"})
    assert r.status_code == 400


async def test_history_enforcement_pricing_usage(client, led) -> None:
    r = await client.get("/api/budgets/history", params={"scope": "team:trading"})
    assert r.status_code == 200 and len(r.json()["points"]) >= 1 and "forecast" in r.json()
    r = await client.get("/api/budgets/enforcement")
    assert r.status_code == 200
    assert {"loop_detections", "hard_blocks", "kills", "cost_avoided_usd", "recent"} <= set(
        r.json()
    )
    r = await client.get("/api/budgets/pricing")
    assert r.status_code == 200 and r.json()["version"] == led.pricing.version
    r = await client.post(
        "/api/budgets/usage",
        json={"scope": "team:trading", "window": "day", "dimension": "usd", "amount": 5},
        headers=as_("u_piotr"),
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/budgets/usage",
        json={"scope": "team:trading", "window": "day", "dimension": "usd", "amount": 5},
        headers=as_("u_emily"),
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    assert led.used("team:trading", "day", "usd") == pytest.approx(5)
    r = await client.get("/api/budgets/sessions")
    assert r.status_code == 200 and "items" in r.json()
