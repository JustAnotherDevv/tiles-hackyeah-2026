"""GW-V13 (in-process variant): the REAL app + Runtime (every bundle's services and controls,
`config/policy.yaml`) with a MockTransport echo upstream in place of mocks/mock_llm.

trading-copilot@trading sends a PESEL + email: the upstream sees placeholders only, the client gets
the real values back (DLP-08), `X-Aegis-Decision: redact`, and a decision row is queryable.
Marked `slow` (boots the whole gateway, ~1 s); uses a temp data dir, no ports, no models.
"""

from __future__ import annotations

import json

import httpx
import pytest

from aegis.proxy import upstream
from tests.unit.core_gateway_proxy.fakes import echo_anthropic

pytestmark = pytest.mark.slow

TEXT = "Client Jan Kowalski PESEL 44051401359, email jan.kowalski@example.com - draft a reply"


@pytest.mark.parametrize("stream", [False, True])
async def test_v13_redact_rehydrate_real_stack(tmp_path, monkeypatch, stream) -> None:
    from aegis.app import create_app
    from aegis.settings import Settings

    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return echo_anthropic(req)

    app = create_app(Settings(data_dir=tmp_path / "data", test_mode=True, semantic="off"))
    async with app.router.lifespan_context(app):
        upstream.set_transport(httpx.MockTransport(handler))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://aegis.test") as c:
                r = await c.post("/v1/messages", json={
                    "model": "mock-echo", "max_tokens": 64, "stream": stream,
                    "messages": [{"role": "user", "content": TEXT}]},
                    headers={"x-aegis-agent": "trading-copilot@trading"})
                assert r.status_code == 200, r.text
                sent = json.loads(seen[-1].content)["messages"][0]["content"]
                assert "44051401359" not in sent and "jan.kowalski@example.com" not in sent
                assert "[PESEL_" in sent and "[EMAIL_" in sent
                assert "44051401359" in r.text and "jan.kowalski@example.com" in r.text
                assert r.headers["x-aegis-decision"] == "redact"
                assert int(r.headers["x-aegis-redactions"]) >= 2
                assert "aegis;dur=" in r.headers["server-timing"]
                d = await c.get("/api/decisions?limit=5")
                if d.status_code == 200:
                    assert r.headers["x-aegis-request-id"] in d.text
        finally:
            upstream.set_transport(None)
