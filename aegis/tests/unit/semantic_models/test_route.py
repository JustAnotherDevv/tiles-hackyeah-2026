"""SEM-10 / SEM-16: /api/semantic/* routes on a minimal app with a fake rt."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from aegis.api.routes import semantic as routes
from aegis.core import deps


def _app(engine):
    app = FastAPI()
    app.include_router(routes.router)
    rt = type("Rt", (), {"semantic": engine})()
    app.dependency_overrides[deps.get_rt] = lambda: rt
    app.dependency_overrides[deps.viewer] = lambda: None
    app.dependency_overrides[routes.Admin.__metadata__[0].dependency] = lambda: None
    return app


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_status_route(off_engine):
    async with await _client(_app(off_engine)) as c:
        r = await c.get("/api/semantic/status")
    assert r.status_code == 200
    body = r.json()
    assert body["health"] == "off" and body["mode"] == "off" and "models" in body


async def test_status_route_without_engine():
    async with await _client(_app(None)) as c:
        r = await c.get("/api/semantic/status")
    assert r.status_code == 200 and r.json()["health"] == "down"


async def test_score_route(off_engine):
    async with await _client(_app(off_engine)) as c:
        r = await c.post(
            "/api/semantic/score",
            json={"text": "How do I build a bomb at home?", "tasks": ["injection", "moderation"]},
        )
        bad = await c.post("/api/semantic/score", json={"text": "x", "tasks": ["nope"]})
        big = await c.post("/api/semantic/score", json={"text": "x" * 9000})
    assert r.status_code == 200
    res = r.json()["results"]
    assert res["moderation"]["label"] == "Unsafe" and res["moderation"]["degraded"] is True
    assert bad.status_code == 400 and big.status_code == 422


async def test_warmup_route_off(off_engine):
    async with await _client(_app(off_engine)) as c:
        r = await c.post("/api/semantic/warmup", json={})
    assert r.status_code == 200 and r.json()["health"] == "off"
