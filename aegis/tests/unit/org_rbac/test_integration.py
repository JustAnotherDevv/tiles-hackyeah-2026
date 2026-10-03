"""ORG-V13: org-rbac wired into the real app (create_app + lifespan, in-process ASGI).

Skips when the gateway app (or asgi_lifespan) is not importable yet. Steps that depend on
other bundles (guard pipeline, approvals engine) skip individually when those are still
running on Null fallbacks, so this test never fails because of another bundle's progress.
"""

from __future__ import annotations

import asyncio

import pytest

httpx = pytest.importorskip("httpx")
asgi_lifespan = pytest.importorskip("asgi_lifespan")
app_mod = pytest.importorskip("aegis.app")
settings_mod = pytest.importorskip("aegis.settings")

REVOKED_KEY = "aegis_demo_revoked_key_0000000000000099_NOT_A_SECRET"


@pytest.fixture
async def live(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    try:
        settings = settings_mod.Settings(data_dir=tmp_path / "data", ui_dist=tmp_path / "dist")
    except Exception as exc:  # pragma: no cover - settings shape changed
        pytest.skip(f"Settings not constructible: {exc}")
    app = app_mod.create_app(settings)
    async with asgi_lifespan.LifespanManager(app, startup_timeout=60, shutdown_timeout=30):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://aegis.test") as client:
            yield app, client


async def _guard(client, body: dict, headers: dict | None = None):
    r = await client.post("/v1/guard", json=body, headers=headers or {})
    if r.status_code == 404:
        pytest.skip("/v1/guard not mounted yet")
    assert r.status_code == 200, r.text
    return r.json()


async def test_org_rbac_end_to_end(live):
    app, client = live
    rt = app.state.rt
    if rt is None or getattr(rt, "org", None) is None or not hasattr(rt.org, "cache"):
        pytest.skip("rt.org is not the org-rbac service (Null fallback)")

    # (a) view-as role alias resolves to the first member with that role
    r = await client.get("/api/whoami", headers={"X-Aegis-View-As": "member"})
    assert r.status_code == 200, r.text
    assert r.json()["identity"]["member_id"] == "u_piotr"

    # (b) revoked key -> GOV-01 block (key material never echoed)
    body = {
        "interaction": {
            "kind": "model_call",
            "surface": "model.request",
            "destination": "remote",
            "model": "claude-sonnet-4-5",
            "text": "hello",
        }
    }
    out = await _guard(client, body, {"Authorization": f"Bearer {REVOKED_KEY}"})
    verdict = out["verdict"]
    if not verdict.get("decisions"):
        pytest.skip("guard pipeline has no controls loaded yet")
    assert verdict["action"] == "block", verdict
    assert verdict["primary"]["control_id"] == "GOV-01"
    assert REVOKED_KEY not in str(out)

    # (c) trading-copilot asking for a model outside its allowlist -> GOV-02
    body2 = {
        "interaction": {
            "kind": "model_call",
            "surface": "model.request",
            "destination": "remote",
            "model": "gpt-4.1-mini",
            "text": "hi",
        }
    }
    out = await _guard(client, body2, {"X-Aegis-Agent": "trading-copilot@trading"})
    assert out["verdict"]["action"] == "block", out["verdict"]
    assert out["verdict"]["primary"]["control_id"] == "GOV-02"

    # (d) promotion -> pending approval -> owner approves via the real approvals API
    r = await client.patch(
        "/api/members/u_piotr", json={"role": "admin"}, headers={"X-Aegis-View-As": "u_marek"}
    )
    assert r.status_code == 403, r.text
    err = r.json()["error"]
    assert err["type"] == "approval_required" and err["approval_id"].startswith("apr_")
    r = await client.post(
        f"/api/approvals/{err['approval_id']}/approve",
        json={"comment": "ok"},
        headers={"X-Aegis-View-As": "u_katarzyna"},
    )
    if r.status_code in (404, 503):
        pytest.skip("approvals engine not available")
    assert r.status_code == 200, r.text
    role = None
    for _ in range(50):  # executor may run asynchronously
        r = await client.get("/api/members/u_piotr")
        role = r.json()["role"]
        if role == "admin":
            break
        await asyncio.sleep(0.05)
    assert role == "admin"
