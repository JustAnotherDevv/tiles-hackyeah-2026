"""Fixtures: in-process mock_mcp (ASGI + lifespan) behind the real MCP proxy routes + FakeRuntime."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from aegis.sdk.cast import agent_headers  # ASI03: X-Aegis-Agent + its key

os.environ.setdefault("AEGIS_TEST_MODE", "1")
os.environ.setdefault("AEGIS_SEMANTIC", "off")

from aegis.api.routes import mcp as mcp_routes
from aegis.api.routes import mcp_admin
from aegis.mcp.client import McpHttpClient
from aegis.mcp.service import McpService, set_service
from mocks.mock_mcp.app import create_app
from mocks.mock_mcp.state import STATE
from tests.unit.mcp_proxy.fakes import MOCK_BASE, FakeRuntime

GW_BASE = "http://127.0.0.1:8787"


class Stack:
    """Gateway (FastAPI with the two MCP routers) + mock + fake runtime."""

    def __init__(
        self, rt: FakeRuntime, gw: httpx.AsyncClient, mock: httpx.AsyncClient, svc: McpService
    ) -> None:
        self.rt, self.gw, self.mock, self.svc = rt, gw, mock, svc

    def client(
        self,
        server: str,
        *,
        era: str = "auto",
        agent: str | None = "claude-code@platform",
        **headers: str,
    ) -> McpHttpClient:
        h = dict(headers)
        if agent:
            h.update(agent_headers(agent))  # ASI03: claim + key
        return McpHttpClient(GW_BASE, server, headers=h, client=self.gw, era=era)

    async def flip(self) -> None:
        r = await self.mock.post("/_mock/rugpull/flip")
        assert r.status_code == 200

    async def mock_requests(self, server: str | None = None) -> list[dict[str, Any]]:
        q = f"?server={server}" if server else ""
        return (await self.mock.get(f"/_mock/requests{q}")).json()["items"]


@pytest.fixture
async def mock_app(tmp_path: Any) -> AsyncIterator[Any]:
    STATE.reset()
    app = create_app(data_dir=tmp_path / "mocks", log_to_file=False)
    async with LifespanManager(app) as manager:
        yield manager.app
    STATE.reset()


@pytest.fixture
async def stack(tmp_path: Any, mock_app: Any) -> AsyncIterator[Stack]:
    rt = FakeRuntime(tmp_path)
    upstream = httpx.AsyncClient(transport=httpx.ASGITransport(mock_app), base_url=MOCK_BASE)
    svc = McpService(rt, client=upstream)
    set_service(svc)
    await svc.start()
    app = FastAPI()
    app.include_router(mcp_routes.router)
    app.include_router(mcp_admin.router)
    gw = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=GW_BASE, timeout=30)
    try:
        yield Stack(rt, gw, upstream, svc)
    finally:
        await gw.aclose()
        await svc.stop()
        await upstream.aclose()
        set_service(None)
