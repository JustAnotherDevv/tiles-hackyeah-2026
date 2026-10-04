"""R5 / R6 regression: viewer/agent separation on the dashboard API (real app, in-process ASGI).

* R5 (P0): a request carrying agent credentials or an agent identity header can never vote on an
  approval or mutate dashboard state, whatever `X-Aegis-View-As` says.
* R6: an anonymous / unknown viewer is read-only (no proposals, no votes).
* The demo flows keep working: a human persona sent via `X-Aegis-View-As` still votes, and a
  same-origin browser request without view-as still gets the default viewer.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
asgi_lifespan = pytest.importorskip("asgi_lifespan")
app_mod = pytest.importorskip("aegis.app")
settings_mod = pytest.importorskip("aegis.settings")

from aegis.sdk.cast import agent_key  # noqa: E402

AGENT = "trading-copilot@trading"
PURCHASE = {
    "interaction": {
        "kind": "mcp",
        "surface": "mcp.call",
        "destination": "third_party",
        "mcp_server": "marketpulse",
        "tool_name": "marketpulse.purchase_subscription",
        "tool_args": {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50},
    },
    "wait_s": 0,
}


@pytest.fixture
async def live(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    monkeypatch.setenv("AEGIS_FEED_URL", "disabled")
    try:
        settings = settings_mod.Settings(data_dir=tmp_path / "data", ui_dist=tmp_path / "dist")
    except Exception as exc:  # pragma: no cover - settings shape changed
        pytest.skip(f"Settings not constructible: {exc}")
    app = app_mod.create_app(settings)
    async with asgi_lifespan.LifespanManager(app, startup_timeout=60, shutdown_timeout=30):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://aegis.test") as client:
            yield app, client


async def _pending_purchase(client) -> str:
    r = await client.post(  # ASI03: an agent claim needs the agent's key
        "/v1/guard",
        json=PURCHASE,
        headers={"X-Aegis-Agent": AGENT, "Authorization": f"Bearer {agent_key(AGENT)}"},
    )
    if r.status_code == 404:
        pytest.skip("/v1/guard not mounted")
    assert r.status_code == 200, r.text
    out = r.json()
    verdict = out.get("verdict") or {}
    apr = (
        (out.get("approval") or {}).get("id")
        or (verdict.get("primary") or {}).get("approval_id")
        or (verdict.get("approval") or {}).get("id")
    )
    assert verdict.get("action") == "require_approval" and apr, out
    return apr


async def _status(client, apr: str) -> str:
    r = await client.get(f"/api/approvals/{apr}", headers={"X-Aegis-View-As": "u_emily"})
    assert r.status_code == 200, r.text
    return r.json()["status"]


def _agent_header_sets() -> list[dict[str, str]]:
    key = agent_key(AGENT)
    sets = [{"X-Aegis-Agent": AGENT}]
    if key:
        sets += [
            {"Authorization": f"Bearer {key}"},
            {"x-api-key": key},
            {"X-Aegis-Agent-Key": key},
        ]
    return sets


async def test_agent_headers_cannot_vote_even_with_view_as(live):
    _, client = live
    apr = await _pending_purchase(client)
    for agent_headers in _agent_header_sets():
        for persona in ("u_emily", "u_katarzyna", "owner"):
            for decision in ("approve", "deny"):
                r = await client.post(
                    f"/api/approvals/{apr}/{decision}",
                    json={"comment": "self-approve"},
                    headers={**agent_headers, "X-Aegis-View-As": persona},
                )
                assert r.status_code == 403, (agent_headers.keys(), persona, r.text)
                assert r.json()["error"]["type"] == "forbidden"
            # ?view_as= and the cookie are no way around it either
            r = await client.post(
                f"/api/approvals/{apr}/approve?view_as={persona}", json={}, headers=agent_headers
            )
            assert r.status_code == 403, r.text
    assert await _status(client, apr) == "pending"

    # the agent's view of its own approval says it cannot vote
    r = await client.get(
        f"/api/approvals/{apr}", headers={"X-Aegis-Agent": AGENT, "X-Aegis-View-As": "u_emily"}
    )
    assert r.status_code == 200 and r.json()["can_vote"] is False

    # the same vote from the human admin persona (no agent headers) still works (demo flow)
    r = await client.post(
        f"/api/approvals/{apr}/approve", json={"comment": "ok"}, headers={"X-Aegis-View-As": "u_emily"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


async def test_anonymous_and_unknown_viewers_cannot_vote(live):
    _, client = live
    apr = await _pending_purchase(client)
    for headers in ({}, {"X-Aegis-View-As": "nobody"}, {"X-Aegis-View-As": AGENT}):
        r = await client.post(f"/api/approvals/{apr}/approve", json={}, headers=headers)
        assert r.status_code == 403, (headers, r.text)
    # the requester's side (the sponsor is a plain member) cannot approve an admin-level request
    r = await client.post(
        f"/api/approvals/{apr}/approve", json={}, headers={"X-Aegis-View-As": "u_piotr"}
    )
    assert r.status_code == 403, r.text
    assert await _status(client, apr) == "pending"


async def _approval_ids(client) -> set[str]:
    r = await client.get("/api/approvals?status=pending", headers={"X-Aegis-View-As": "u_emily"})
    assert r.status_code == 200, r.text
    return {a["id"] for a in r.json().get("items", [])}


async def test_non_human_viewers_cannot_mutate_dashboard_state(live):
    _, client = live
    before = await _approval_ids(client)
    ks = {"scope": "agent:chaos-agent@platform", "active": True, "reason": "probe"}
    raise_body = {"scope": f"agent:{AGENT}", "usd": 999, "reason": "probe"}
    for headers in (
        {},  # curl without view-as -> anonymous
        {"X-Aegis-View-As": "nobody"},
        {"X-Aegis-Agent": AGENT, "X-Aegis-View-As": "u_katarzyna"},
    ):
        r = await client.post("/api/killswitch", json=ks, headers=headers)
        assert r.status_code == 403, (headers, r.text)
        r = await client.post("/api/budgets/raise", json=raise_body, headers=headers)
        assert r.status_code == 403, (headers, r.text)
        r = await client.post(
            "/api/policy/apply", json={"yaml": "version: 1\n", "reason": "probe"}, headers=headers
        )
        assert r.status_code == 403, (headers, r.text)
        assert r.json()["error"]["type"] == "forbidden"
    assert await _approval_ids(client) == before

    # reads stay open to the anonymous viewer
    r = await client.get("/api/policy")
    assert r.status_code == 200, r.text


async def test_viewer_identity_resolution(live):
    _, client = live
    # agent headers override any persona
    r = await client.get(
        "/api/whoami", headers={"X-Aegis-Agent": AGENT, "X-Aegis-View-As": "u_katarzyna"}
    )
    assert r.status_code == 200, r.text
    ident = r.json()["identity"]
    assert ident["member_id"] is None and ident["agent_id"] == AGENT and ident["role"] == "agent"
    # curl without view-as -> anonymous viewer (least privilege)
    ident = (await client.get("/api/whoami")).json()["identity"]
    assert ident["member_id"] is None and ident["role"] == "viewer"
    # the dashboard's own same-origin fetch without view-as -> the default viewer (owner)
    r = await client.get("/api/whoami", headers={"Sec-Fetch-Site": "same-origin"})
    assert r.json()["identity"]["member_id"] == "u_katarzyna"
    # seeded personas resolve as before
    for persona, role in (("u_piotr", "member"), ("u_emily", "admin"), ("u_marek", "admin")):
        ident = (await client.get("/api/whoami", headers={"X-Aegis-View-As": persona})).json()
        assert ident["identity"]["member_id"] == persona and ident["identity"]["role"] == role
