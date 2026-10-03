"""Mock MCP servers on ONE port (:8792), each at `/mcp/<name>` (both protocol eras via the SDK).

Sub-app lifespans don't run under `Mount`, so `create_app()` builds fresh `MCPServer`s, merges
each server's Streamable HTTP routes into one Starlette app and enters every
`session_manager.run()` in one combined lifespan.

Mock control routes:
    POST /_mock/rugpull/flip      serve the mutated rugpull definition (?on=false flips back)
    POST /_mock/reset             reseed acme_db, un-flip rugpull, clear the request log
    GET  /_mock/requests?limit=&server=   tool calls that actually reached the mock servers
    DELETE /_mock/requests        clear the log
    GET  /_mock/health
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mocks.mock_mcp import seed_db
from mocks.mock_mcp.servers import BUILDERS
from mocks.mock_mcp.state import STATE

SERVER_NAMES = list(BUILDERS)


def build_servers() -> dict[str, Any]:
    return {name: build() for name, build in BUILDERS.items()}


async def _flip(request: Request) -> JSONResponse:
    on = request.query_params.get("on", "true").lower() not in ("0", "false", "no", "off")
    STATE.rugpull_flipped = on
    return JSONResponse({"ok": True, "rugpull_flipped": STATE.rugpull_flipped})


async def _reset(_: Request) -> JSONResponse:
    STATE.reset()
    seed_db.seed(STATE.db_path)
    return JSONResponse({"ok": True, "rugpull_flipped": False, "db": str(STATE.db_path)})


async def _requests(request: Request) -> JSONResponse:
    if request.method == "DELETE":
        STATE.clear_requests()
        return JSONResponse({"ok": True})
    try:
        limit = int(request.query_params.get("limit", "100"))
    except ValueError:
        limit = 100
    items = STATE.recent(limit, request.query_params.get("server"))
    return JSONResponse({"items": items, "count": len(items)})


async def _health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": "mock_mcp",
            "ok": True,
            "servers": SERVER_NAMES,
            "rugpull_flipped": STATE.rugpull_flipped,
        }
    )


def create_app(*, data_dir: Path | str | None = None, log_to_file: bool = True) -> Starlette:
    """Fresh app with fresh servers (the SDK session manager can only run once per server)."""
    if data_dir is not None:
        STATE.configure(data_dir, log_to_file=log_to_file)
    servers = build_servers()
    routes: list[Any] = [
        Route("/_mock/rugpull/flip", _flip, methods=["POST"]),
        Route("/_mock/reset", _reset, methods=["POST"]),
        Route("/_mock/requests", _requests, methods=["GET", "DELETE"]),
        Route("/_mock/health", _health, methods=["GET"]),
    ]
    for name, srv in servers.items():
        sub = srv.streamable_http_app(streamable_http_path=f"/mcp/{name}")
        routes.extend(sub.routes)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        seed_db.ensure(STATE.db_path)
        async with contextlib.AsyncExitStack() as stack:
            for srv in servers.values():
                await stack.enter_async_context(srv.session_manager.run())
            yield

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.servers = servers
    return app


__all__ = ["SERVER_NAMES", "build_servers", "create_app"]
