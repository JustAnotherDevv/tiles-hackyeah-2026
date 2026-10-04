"""RED-V14: routes in-process (FastAPI app with only our router)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from aegis.api.routes.redaction import router
from aegis.core.errors import AegisHTTPError
from aegis.core.types import Identity
from aegis.redaction import entities as E


class _Org:
    async def resolve_viewer(self, headers, query):
        role = headers.get("x-aegis-view-as", "member")
        return Identity(member_id=f"u_{role}", role=role, authenticated=True)


@pytest.fixture
def app(rt):
    rt.org = _Org()
    a = FastAPI()
    a.state.rt = rt
    a.include_router(router)

    @a.exception_handler(AegisHTTPError)
    async def _h(request, exc: AegisHTTPError):
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    return a


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_entities(app) -> None:
    async with await _client(app) as c:
        r = await c.get("/api/redaction/entities")
    assert r.status_code == 200
    items = {i["entity"]: i for i in r.json()["items"]}
    for ent in ("PESEL", "IBAN", "PAN", "CVV", "EMAIL", "AWS_KEY", "PERSON", "CRYPTO_ADDRESS"):
        assert ent in items and items[ent]["detectors"], ent
    assert "ner.eu-pii-ner" in items["PERSON"]["detectors"]
    assert set(items) >= set(E.ENTITIES) - {"PROMPT_INJECTION"}


async def test_sessions_and_wipe(app, engine) -> None:
    engine.vaults.get("s-9").put("PESEL", "44051401359")
    async with await _client(app) as c:
        r = await c.get("/api/redaction/sessions/s-9")
        assert r.status_code == 200
        body = r.json()
        assert body["entities"] == {"PESEL": 1} and "44051401359" not in r.text
        r = await c.delete("/api/redaction/sessions/s-9")
        assert r.status_code == 403
        r = await c.delete("/api/redaction/sessions/s-9", headers={"X-Aegis-View-As": "admin"})
        assert r.status_code == 200 and r.json() == {"ok": True, "wiped": 1}
    assert engine.session_stats("s-9") is None


async def test_metrics_shape(app) -> None:
    async with await _client(app) as c:
        r = await c.get("/api/redaction/metrics")
    assert r.status_code == 200
    m = r.json()
    for k in ("generated_at", "cases", "gold", "ner_loaded", "overall", "latency_ms", "by_entity"):
        assert k in m
    assert m["overall"]["leak_rate"] == 0.0
