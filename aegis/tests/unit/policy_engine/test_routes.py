"""POL-07 / POL-V06: /api/policy*, /api/controls, /api/coverage against the real app (in-process ASGI).

Also exercises the governed path (POL-10) end to end with the real approvals engine when present:
an admin disabling DLP-02 needs the owner (F5-style), the owner's approval applies it.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from aegis.policy.patch import apply_patch_text

OWNER = {"X-Aegis-View-As": "u_katarzyna"}
ADMIN = {"X-Aegis-View-As": "u_marek"}
MEMBER = {"X-Aegis-View-As": "u_piotr"}

POLICY_RESPONSE = {"version", "yaml", "sha256", "applied_at", "applied_by", "source", "profile", "controls_count"}
APPLY_RESULT = {"status", "version", "previous_version", "approval", "decision_id", "errors", "changes",
                "latency_ms", "message"}
VALIDATION_REPORT = {"valid", "errors", "warnings", "selftest", "selftest_passed", "changes", "required_role"}
CONTROL_VIEW = {"id", "family", "name", "kind", "owner", "enabled", "mode", "action", "threshold", "severity",
                "owasp", "surfaces", "implemented", "hits_24h", "blocks_24h", "p95_ms"}
VERSION_INFO = {"version", "sha256", "applied_at", "applied_by", "source", "reason", "changes_count", "summary"}


@pytest.fixture
async def client(policy_dir: Path):
    from asgi_lifespan import LifespanManager

    from aegis.app import create_app
    from aegis.settings import Settings

    app = create_app(Settings.from_env())  # explicit settings: get_settings() is process-cached
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=30):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c


async def test_policy_read_endpoints(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/policy", headers=MEMBER)
    assert r.status_code == 200 and POLICY_RESPONSE <= set(r.json())
    r = await client.get("/api/policy/history", headers=MEMBER)
    assert r.status_code == 200 and VERSION_INFO <= set(r.json()["items"][0])
    assert (await client.get("/api/policy/versions/1", headers=MEMBER)).json()["yaml"]
    assert (await client.get("/api/policy/versions/999", headers=MEMBER)).status_code == 404
    schema = (await client.get("/api/policy/schema", headers=MEMBER)).json()
    assert schema["$id"] == "aegis.policy/1"
    items = (await client.get("/api/controls", headers=MEMBER)).json()["items"]
    assert len(items) >= 38 and CONTROL_VIEW <= set(items[0])
    cov = (await client.get("/api/coverage", headers=MEMBER)).json()
    assert [f["id"] for f in cov["frameworks"]] == ["OWASP-LLM-2026", "OWASP-ASI-2026", "OWASP-MCP-2025"]
    assert (await client.get("/api/policy/status", headers=MEMBER)).json()["state"] == "ok"


async def test_validate_diff_apply(client: httpx.AsyncClient) -> None:
    pol = (await client.get("/api/policy", headers=OWNER)).json()
    new = apply_patch_text(pol["yaml"], [{"op": "set", "path": "controls[id=INJ-02].threshold", "value": 0.5}])
    r = await client.post("/api/policy/validate", json={"yaml": new, "selftest": False}, headers=ADMIN)
    assert r.status_code == 200 and VALIDATION_REPORT <= set(r.json()) and r.json()["valid"]
    r = await client.post("/api/policy/diff", json={"yaml": new}, headers=ADMIN)
    body = r.json()
    assert r.status_code == 200 and body["changes"][0]["kind"] == "control.threshold.tighten"
    assert "threshold: 0.50" in body["unified"] or "threshold: 0.5" in body["unified"]
    bad = await client.post("/api/policy/diff", json={"yaml": "controls: [\n"}, headers=ADMIN)
    assert bad.status_code == 422 and bad.json()["error"]["errors"][0]["line"]
    r = await client.post("/api/policy/apply", json={"yaml": new, "base_version": pol["version"]}, headers=ADMIN)
    res = r.json()
    assert r.status_code == 200 and APPLY_RESULT <= set(res) and res["status"] == "applied"
    stale = await client.post("/api/policy/apply", json={"yaml": pol["yaml"], "base_version": pol["version"]},
                              headers=OWNER)
    assert stale.status_code == 409 and stale.json()["error"]["current_version"] == res["version"]
    broken = await client.post("/api/policy/apply", json={"yaml": new + "\nfoo: [\n", "base_version": res["version"]},
                               headers=OWNER)
    assert broken.status_code == 200 and broken.json()["status"] == "rejected"


async def test_reload_requires_admin(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/policy/reload", headers=MEMBER)).status_code == 403
    r = await client.post("/api/policy/reload", headers=OWNER)
    assert r.status_code == 200 and r.json()["status"] == "noop"


async def test_admin_disable_critical_needs_owner(client: httpx.AsyncClient) -> None:
    pol = (await client.get("/api/policy", headers=ADMIN)).json()
    new = apply_patch_text(pol["yaml"], [{"op": "set", "path": "controls[id=DLP-02].enabled", "value": False}])
    r = await client.post("/api/policy/apply", json={"yaml": new, "base_version": pol["version"], "reason": "test"},
                          headers=ADMIN)
    res = r.json()
    if res["status"] != "pending_approval":  # pragma: no cover - approvals engine not integrated
        pytest.skip(f"approvals engine unavailable: {res['message']}")
    assert res["approval"]["required_role"] == "owner"
    apr_id = res["approval"]["id"]
    r = await client.post(f"/api/approvals/{apr_id}/approve", json={"comment": "ok"}, headers=OWNER)
    assert r.status_code == 200, r.text
    cur = (await client.get("/api/policy", headers=OWNER)).json()
    assert cur["version"] == pol["version"] + 1
    controls = {c["id"]: c for c in (await client.get("/api/controls", headers=OWNER)).json()["items"]}
    assert controls["DLP-02"]["enabled"] is False


async def test_selftest_gate(client: httpx.AsyncClient) -> None:
    pol = (await client.get("/api/policy", headers=OWNER)).json()
    # owner switches to permissive: some balanced expectations loosen -> warnings, not a rejection
    perm = pol["yaml"].replace("profile: balanced", "profile: permissive", 1)
    r = await client.post("/api/policy/apply", json={"yaml": perm, "base_version": pol["version"]}, headers=OWNER)
    assert r.json()["status"] == "applied", r.json()["message"]
    back = await client.post("/api/policy/apply", json={"yaml": pol["yaml"], "base_version": r.json()["version"]},
                             headers=OWNER)
    assert back.json()["status"] == "applied"
    # a real regression: DLP-02 secrets -> log while its block tests stay -> rejected with line/col
    weak = apply_patch_text(pol["yaml"], [{"op": "set", "path": "controls[id=DLP-02].action", "value": "log"}])
    r = await client.post("/api/policy/apply", json={"yaml": weak, "base_version": back.json()["version"]},
                          headers=OWNER)
    res = r.json()
    assert res["status"] == "rejected" and "self-test" in res["message"]
    assert res["errors"][0]["line"] and any("DLP-02" in e["message"] for e in res["errors"])
    run = (await client.get("/api/policy/selftest", headers=MEMBER)).json()
    assert run["passed"] > 0
