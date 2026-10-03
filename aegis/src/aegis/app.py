"""FastAPI app factory (public surface `aegis.app.create_app`, CONTRACTS section 3.3).

SCAFFOLD STUB - owned by core-gateway, safe to extend/replace. Builds the app, includes every
auto-discovered router (sorted by ORDER) and exposes `app.state.settings`, `app.state.rt`
(None until core-gateway's Runtime exists) and `app.state.plugin_errors`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aegis import __version__
from aegis.core import discovery
from aegis.settings import Settings, get_settings

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    routers = discovery.discover_routers()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.time()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        rt = app.state.rt
        # TODO(core-gateway): build + start aegis.core.runtime.Runtime here and set app.state.rt.
        if rt is not None:
            for mod in routers:
                hook = getattr(mod, "on_startup", None)
                if hook is not None:
                    try:
                        await hook(rt)
                    except Exception:
                        log.exception("on_startup failed module=%s", mod.__name__)
        log.info("aegis gateway started version=%s routers=%d", __version__, len(routers))
        try:
            yield
        finally:
            if rt is not None:
                for mod in reversed(routers):
                    hook = getattr(mod, "on_shutdown", None)
                    if hook is not None:
                        try:
                            await hook(rt)
                        except Exception:
                            log.exception("on_shutdown failed module=%s", mod.__name__)

    app = FastAPI(
        title="Aegis AI Control Layer",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.rt = None
    app.state.started_at = time.time()
    for mod in routers:
        app.include_router(mod.router)
    app.state.router_modules = [m.__name__ for m in routers]
    app.state.plugin_errors = discovery.plugin_errors
    return app
