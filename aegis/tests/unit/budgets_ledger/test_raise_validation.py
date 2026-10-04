"""R7: budget raise / preview / usage import reject non-finite, negative and absurd amounts.

`Infinity` used to be written to policy.yaml as `usd: .inf` (budget silently disabled).
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request

from aegis.api.routes import budgets as routes
from aegis.core.errors import AegisHTTPError

BAD_LIMITS = ["Infinity", "-Infinity", "NaN", "inf", 1e308, -1, 0, 1e7, True]


@pytest.fixture
async def client(rt, led, clock):
    app = FastAPI()

    @app.exception_handler(AegisHTTPError)
    async def _err(request: Request, exc: AegisHTTPError):  # mirrors aegis.app
        return exc.response(None)

    app.include_router(routes.router)
    app.state.rt = rt
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _raise(new_limit, **kw):
    return {"scope": "team:trading", "window": "day", "dimension": "usd", "new_limit": new_limit,
            "reason": "probe", **kw}


def _assert_invalid(r: httpx.Response, needle: str) -> None:
    assert r.status_code in (400, 422), (r.status_code, r.text)
    err = r.json()["error"]
    assert err["type"] == "invalid_request"
    assert needle in err["message"], err["message"]


@pytest.mark.parametrize("value", BAD_LIMITS)
@pytest.mark.parametrize("path", ["/api/budgets/raise", "/api/budgets/raise/preview"])
async def test_raise_rejects_bad_amounts(client, rt, path, value) -> None:
    n = len(rt.policy.proposed)
    r = await client.post(path, json=_raise(value))
    _assert_invalid(r, "new_limit")
    assert len(rt.policy.proposed) == n  # nothing proposed -> policy version unchanged


async def test_raise_raw_json_infinity_literal(client, rt) -> None:
    # Python's json accepts the bare `Infinity` literal; it must not slip through either
    body = b'{"scope":"team:trading","window":"day","dimension":"usd","new_limit":Infinity}'
    r = await client.post("/api/budgets/raise", content=body,
                          headers={"content-type": "application/json"})
    _assert_invalid(r, "finite")
    assert rt.policy.proposed == []


async def test_raise_per_dimension_caps(client) -> None:
    ok = await client.post("/api/budgets/raise/preview",
                           json=_raise(5_000_000, dimension="tokens"))
    assert ok.status_code == 200, ok.text
    r = await client.post("/api/budgets/raise/preview", json=_raise(1e13, dimension="tokens"))
    _assert_invalid(r, "exceeds the maximum")


async def test_raise_string_bounds(client, rt) -> None:
    r = await client.post("/api/budgets/raise", json=_raise(75, reason="x" * 10_000))
    _assert_invalid(r, "reason too long")
    r = await client.post("/api/budgets/raise", json={**_raise(75), "scope": "team:" + "a" * 500})
    _assert_invalid(r, "scope too long")
    r = await client.post("/api/killswitch", json={"scope": "agent:x@y", "reason": "y" * 10_000})
    _assert_invalid(r, "reason too long")
    r = await client.get("/api/budgets/history", params={"scope": "team:" + "a" * 500})
    assert r.status_code in (400, 422)
    assert rt.policy.proposed == []


async def test_demo_raises_still_work(client, rt) -> None:
    """Demo: 60 -> 75 by u_piotr (pending, admin approves), 60 -> 150 previewed by the owner."""
    r = await client.post("/api/budgets/raise", json=_raise(75), headers={"x-aegis-view-as": "u_piotr"})
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    assert rt.policy.proposed[-1]["patch"][0].value == 75
    r = await client.post("/api/budgets/raise/preview", json=_raise(150),
                          headers={"x-aegis-view-as": "u_katarzyna"})
    assert r.status_code == 200 and r.json()["change"]["after"] == 150


@pytest.mark.parametrize("amount", ["Infinity", "NaN", 1e308, 0, True])
async def test_usage_import_rejects_bad_amounts(client, led, amount) -> None:
    r = await client.post(
        "/api/budgets/usage",
        json={"scope": "team:trading", "dimension": "usd", "amount": amount, "window": "day"},
        headers={"x-aegis-view-as": "u_marek"},
    )
    _assert_invalid(r, "amount")
    assert led.used("team:trading", "day", "usd") == 0.0


async def test_usage_import_negative_correction_allowed(client, led) -> None:
    await led.import_usage("team:trading", "usd", 10, "day")
    r = await client.post(
        "/api/budgets/usage",
        json={"scope": "team:trading", "dimension": "usd", "amount": -4, "window": "day"},
        headers={"x-aegis-view-as": "u_marek"},
    )
    assert r.status_code == 200, r.text
