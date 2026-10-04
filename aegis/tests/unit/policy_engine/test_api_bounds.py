"""R8 / R13: oversized ints, unparseable filters, NaN amounts and huge strings on `/api/*`
answer a 4xx `invalid_request` / `not_found` envelope, never a 500 (SQLite OverflowError)."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest

OWNER = {"X-Aegis-View-As": "u_katarzyna"}
HUGE = 10**25


@pytest.fixture
async def client(policy_dir: Path):
    from asgi_lifespan import LifespanManager

    from aegis.app import create_app
    from aegis.settings import Settings

    app = create_app(Settings.from_env())
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=30):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as c:
            yield c


def _cur(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _invalid(r: httpx.Response, codes: tuple[int, ...] = (400, 422)) -> dict:
    assert r.status_code in codes, (r.status_code, r.text[:300])
    err = r.json()["error"]
    assert err["type"] in ("invalid_request", "not_found"), err
    return err


async def test_bounded_ints_never_500(client: httpx.AsyncClient) -> None:
    for path, params in (
        (f"/api/policy/versions/{HUGE}", None),
        ("/api/policy/versions/0", None),
        ("/api/policy/versions/-5", None),
        ("/api/audit", {"seq_from": str(HUGE)}),
        ("/api/audit", {"seq_from": "0"}),
        ("/api/audit", {"limit": str(HUGE)}),
        ("/api/decisions", {"limit": str(HUGE)}),
        ("/api/policy/history", {"limit": str(HUGE)}),
        ("/api/approvals", {"limit": str(HUGE)}),
    ):
        _invalid(await client.get(path, params=params, headers=OWNER))
    for body in ({"version": HUGE}, {"version": 1e25}, {"version": 0}, {"version": -1}):
        _invalid(await client.post("/api/policy/rollback", json=body, headers=OWNER))
    r = await client.post("/api/policy/apply", json={"yaml": "x: 1", "base_version": HUGE},
                          headers=OWNER)
    _invalid(r)
    # still fine for real values
    assert (await client.get("/api/policy/versions/1", headers=OWNER)).status_code == 200
    assert (await client.get("/api/policy/versions/999", headers=OWNER)).status_code == 404
    assert (await client.get("/api/audit", params={"seq_from": "1"})).status_code == 200


async def test_unparseable_filters_rejected(client: httpx.AsyncClient) -> None:
    for path in ("/api/audit", "/api/decisions"):
        for since in ("notadate", "inf", "nan", "1e300", "99999999999999w"):
            err = _invalid(await client.get(path, params={"since": since}))
            assert "since" in err["message"]
        for cursor in ("garbage!!", _cur("abc"), _cur(str(HUGE)), _cur(f"2026-01-01|{HUGE}")):
            err = _invalid(await client.get(path, params={"cursor": cursor}))
            assert "cursor" in err["message"]
        # valid relative / ISO filters still work
        assert (await client.get(path, params={"since": "24h"})).status_code == 200
        r = await client.get(path, params={"since": "2026-10-01T00:00:00Z"})
        assert r.status_code == 200
    assert (await client.get("/api/audit", params={"cursor": _cur("5")})).status_code == 200
    r = await client.get("/api/decisions", params={"cursor": _cur("2026-10-01T00:00:00.000Z|7")})
    assert r.status_code == 200


async def test_string_bounds(client: httpx.AsyncClient) -> None:
    big = "x" * 5000
    _invalid(await client.get("/api/decisions", params={"q": big}))
    _invalid(await client.get("/api/audit", params={"event_type": big}))
    _invalid(await client.get(f"/api/decisions/{big}"))
    _invalid(await client.get(f"/api/approvals/{big}"))
    r = await client.post("/api/policy/rollback", json={"version": 1, "reason": big},
                          headers=OWNER)
    _invalid(r)


async def test_manual_approval_bounds(client: httpx.AsyncClient) -> None:
    base = {"kind": "action", "action_type": "payments.charge", "title": "probe"}
    for extra, needle in (
        ({"title": "t" * 100_000}, "title too long"),
        ({"amount_usd": "NaN"}, "amount_usd"),
        ({"amount_usd": "Infinity"}, "amount_usd"),
        ({"amount_usd": -5}, "amount_usd"),
        ({"amount_usd": 1e300}, "amount_usd"),
        ({"payload": {"blob": "p" * 100_000}}, "payload too large"),
    ):
        err = _invalid(await client.post("/api/approvals", json={**base, **extra}, headers=OWNER),
                       (422,))
        assert needle in err["message"], err["message"]
    pending = (await client.get("/api/approvals", params={"status": "pending"})).json()
    assert not any(i.get("title") == "probe" for i in pending["items"])
    for body in ({"amount_usd": "NaN"}, {"amount_usd": 1e300}, {"increase_pct": "Infinity"},
                 {"action_type": "a" * 1000}):
        _invalid(await client.post("/api/approvals/simulate", json=body, headers=OWNER), (422,))
    r = await client.post("/api/approvals/simulate",
                          json={"kind": "action", "action_type": "payments.charge",
                                "amount_usd": 50, "requester_member_id": "u_piotr"},
                          headers=OWNER)
    assert r.status_code == 200, r.text


async def test_non_human_viewers_cannot_mutate_approvals(client: httpx.AsyncClient) -> None:
    """B-1 (R5/R6): the approvals routes must not swallow the central 403 for agents/anonymous."""
    draft = {"kind": "action", "action_type": "payments.charge", "title": "b1-probe"}
    for headers in ({}, {"X-Aegis-Agent": "trading-copilot@trading"},
                    {"X-Aegis-Agent": "trading-copilot@trading", **OWNER},
                    {"X-Aegis-View-As": "nobody"}):
        r = await client.post("/api/approvals", json=draft, headers=headers)
        assert r.status_code == 403, (headers, r.status_code, r.text[:200])
        assert r.json()["error"]["type"] == "forbidden"
    r = await client.post("/api/approvals", json=draft, headers=OWNER)
    assert r.status_code == 200, r.text
    apr_id = r.json()["id"]
    for verb in ("cancel", "approve", "deny"):
        r = await client.post(f"/api/approvals/{apr_id}/{verb}")
        assert r.status_code == 403, (verb, r.text[:200])
    assert (await client.get(f"/api/approvals/{apr_id}")).json()["status"] == "pending"
    r = await client.post(f"/api/approvals/{apr_id}/cancel", headers=OWNER)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
