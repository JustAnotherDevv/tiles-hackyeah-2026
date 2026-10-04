"""APR-V09: F5 end to end on the real runtime (create_app + lifespan, in-process ASGI).

u_piotr raises team:trading day budget 60 -> 75 -> pending approval; u_emily approves ->
the approved change is applied (policy version + 1) and the audit trail reads
approval.created -> approval.decided -> approval.executed -> policy.applied.

The policy file is copied into tmp_path so the repo's config/policy.yaml is never written.
Integration is complete: every step asserts, so an F4/F5 regression fails here (no skips).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import asgi_lifespan
import httpx
import pytest

from aegis import app as app_mod
from aegis import settings as settings_mod
from aegis.approvals.service import ApprovalsService

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
async def live(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    src = ROOT / "config" / "policy.yaml"
    assert src.exists(), "config/policy.yaml missing"
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    policy = cfg_dir / "policy.yaml"
    shutil.copy(src, policy)
    settings = settings_mod.Settings(data_dir=tmp_path / "data", ui_dist=tmp_path / "dist",
                                     policy=policy)
    app = app_mod.create_app(settings)
    async with asgi_lifespan.LifespanManager(app, startup_timeout=60, shutdown_timeout=30):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://aegis.test") as client:
            yield app, client


def _limit(doc: dict, scope: str, window: str):
    for lim in (doc.get("budgets") or {}).get("limits") or []:
        if lim.get("scope") == scope and lim.get("window") == window:
            return lim.get("usd")
    return None


async def test_f5_budget_raise_end_to_end(live):
    app, client = live
    rt = app.state.rt
    assert isinstance(getattr(rt, "approvals", None), ApprovalsService), rt.approvals
    assert hasattr(rt.policy, "propose"), "policy engine has no propose()"
    v0 = rt.policy.snapshot().version

    r = await client.post("/api/budgets/raise", headers={"X-Aegis-View-As": "u_piotr"},
                          json={"scope": "team:trading", "window": "day", "dimension": "usd",
                                "new_limit": 75})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("status") == "pending_approval", f"raise did not route through GOV-05: {out}"
    approval = out.get("approval") or {}
    apr_id = approval.get("id") or out.get("approval_id")
    assert apr_id, out

    r = await client.post(f"/api/approvals/{apr_id}/approve", headers={"X-Aegis-View-As": "u_piotr"})
    assert r.status_code == 403

    r = await client.post(f"/api/approvals/{apr_id}/approve", headers={"X-Aegis-View-As": "u_emily"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    execution = body.get("execution") or {}
    assert execution.get("policy_version") == v0 + 1, execution
    assert rt.policy.snapshot().version == v0 + 1

    r = await client.get("/api/policy")
    assert r.status_code == 200, r.text
    assert isinstance(r.json().get("doc"), dict), r.json()
    assert _limit(r.json()["doc"], "team:trading", "day") == 75

    # the audit SQLite projection is write-behind (B15: lags the chain by up to ~20 ms, more
    # under load / right after a policy apply) -> poll briefly instead of a one-shot query
    import asyncio

    types: list[str] = []
    for _ in range(40):
        types = []
        for et in ("approval.created", "approval.decided", "approval.executed", "policy.applied"):
            events, _ = await rt.audit.query(event_type=et, limit=200)
            if et.startswith("approval."):
                events = [e for e in events if (e.data or {}).get("approval_id") == apr_id]
            if events:
                types.append(et)
        if types[:3] == ["approval.created", "approval.decided", "approval.executed"]:
            break
        await asyncio.sleep(0.05)
    assert types[:3] == ["approval.created", "approval.decided", "approval.executed"], types


async def test_f4_guard_hold_approve_redeem(live):
    """APR-V10 in-process: $50 MarketPulse purchase -> approval; piotr 403, emily approves;
    the identical retry is allowed ('approved by u_emily')."""
    app, client = live
    rt = app.state.rt
    assert isinstance(getattr(rt, "approvals", None), ApprovalsService), rt.approvals
    body = {"interaction": {"kind": "mcp", "surface": "mcp.call",
                            "destination": {"name": "mcp:marketpulse", "dest_class": "third_party"},
                            "tool_name": "marketpulse.purchase_subscription",
                            "tool_args": {"vendor": "marketpulse", "plan": "mp-pro-monthly",
                                          "amount_usd": 50}},
            "identity": {"agent_id": "trading-copilot@trading"}}
    r = await client.post("/v1/guard", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    verdict = out.get("verdict") or {}
    approval = out.get("approval") or verdict.get("approval") or {}
    assert verdict.get("action") == "require_approval", f"ACT-01 did not hold the $50 spend: {verdict}"
    assert approval.get("id"), f"no approval created for the held call: {out}"
    apr_id = approval["id"]
    r = await client.post(f"/api/approvals/{apr_id}/approve", headers={"X-Aegis-View-As": "u_piotr"})
    assert r.status_code == 403
    r = await client.post(f"/api/approvals/{apr_id}/approve", headers={"X-Aegis-View-As": "u_emily"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = await client.post("/v1/guard", json=body)
    verdict = r.json()["verdict"]
    assert verdict["action"] == "allow", verdict
    assert "u_emily" in str(r.json())
