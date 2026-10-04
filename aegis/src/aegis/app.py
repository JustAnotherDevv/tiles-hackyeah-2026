"""FastAPI app factory (public surface `aegis.app.create_app`, CONTRACTS section 3.3).

`create_app(settings=None)`:
- discovers and includes every router (`aegis.api.routes.*`, sorted by ORDER) at creation time;
- lifespan: `Runtime(settings).build()` → `await rt.start()` → `set_runtime(rt)` →
  `app.state.rt = rt` → routers' `on_startup(rt)` hooks → `system` "gateway started" event;
  teardown in reverse (on_shutdown hooks, shared upstream client, `rt.stop()`);
- pure-ASGI middleware (streaming untouched): request-size guard (413, Content-Length and
  streamed/chunked bodies), the optional admin token for mutating `/api/*` calls
  (`AEGIS_ADMIN_TOKEN`) and a last-resort 500 envelope that keeps the connection alive;
- exception handlers: `AegisHTTPError` → envelope; validation errors → 400/422 `invalid_request`;
  HTTP errors → envelope; unhandled → 500 `internal_error` — always in the wire format of the
  data-plane path (`/v1/messages` Anthropic, `/v1/chat…` OpenAI, `/ollama` Ollama).
"""

from __future__ import annotations

import inspect
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aegis import __version__
from aegis.core import discovery
from aegis.core.errors import AegisHTTPError, api_error, wire_error, wire_for_path
from aegis.core.runtime import Runtime, get_runtime, set_runtime
from aegis.log import setup_logging
from aegis.settings import Settings, get_settings

log = logging.getLogger(__name__)

DEFAULT_MAX_BODY = 8_000_000
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_STATUS_TYPE = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "invalid_request",
    422: "invalid_request",
    429: "rate_limited",
    501: "not_implemented",
    502: "upstream_error",
    503: "unavailable",
}


def _max_body(app: Any) -> int:
    rt = getattr(app.state, "rt", None)
    if rt is None:
        return DEFAULT_MAX_BODY
    try:
        return int(rt.policy.snapshot().doc.defaults.max_body_bytes) or DEFAULT_MAX_BODY
    except Exception:
        return DEFAULT_MAX_BODY


async def _send_json(send: Send, status: int, body: dict[str, Any],
                     headers: dict[str, str] | None = None) -> None:
    payload = json.dumps(body).encode()
    raw = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
    for k, v in (headers or {}).items():
        raw.append((k.lower().encode(), v.encode()))
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": payload})


def _envelope_for_path(path: str, type_: str, message: str) -> dict[str, Any]:
    """Standard error body in the wire format of `path` (JSON-RPC for `/mcp/*`)."""
    if path.startswith("/mcp"):
        from aegis.mcp.jsonrpc import INTERNAL_ERROR, INVALID_REQUEST, jsonrpc_error

        code = INTERNAL_ERROR if type_ == "internal_error" else INVALID_REQUEST
        return jsonrpc_error(None, code, f"[Aegis] {message}")
    from aegis.core.errors import error_inner, wire_body

    wire = wire_for_path(path)
    return wire_body(wire, type_, message) if wire else {"error": error_inner(type_, message)}


class GuardMiddleware:
    """Request-size guard + admin token + last-resort error envelope (pure ASGI so streaming
    responses are untouched).

    - Body size: the Content-Length fast path rejects early; chunked / streamed bodies are counted
      while the app reads them and answered with 413 as soon as the limit is crossed (the app then
      sees a client disconnect and its own output is discarded) — R1.
    - Unhandled exceptions are answered here with the standard 500 envelope instead of reaching
      Starlette's ServerErrorMiddleware, which re-raises and makes the server drop the keep-alive
      connection — R12. Internals (exception text / traceback) are only logged, never returned.
    """

    def __init__(self, app: ASGIApp, fastapi_app: Any = None) -> None:
        self.app = app
        self.fastapi_app = fastapi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        state_app = self.fastapi_app or scope.get("app")
        limit = _max_body(state_app)
        # 1. body size (declared)
        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > limit:
            msg = f"request body too large ({int(length)} > {limit} bytes)"
            await _send_json(send, 413, _envelope_for_path(path, "payload_too_large", msg))
            return
        # 2. admin token for mutating dashboard calls
        settings = getattr(getattr(state_app, "state", None), "settings", None)
        token = getattr(settings, "admin_token", None)
        if token and path.startswith("/api/") and method in _MUTATING:
            auth = headers.get("authorization", "")
            if auth != f"Bearer {token}":
                await _send_json(send, 401, {"error": {
                    "type": "unauthorized", "message": "admin token required (AEGIS_ADMIN_TOKEN)",
                    "control_id": None, "decision_id": None, "approval_id": None,
                    "required_role": None, "expires_at": None, "scope": None,
                    "retry_after_s": None}})
                return
        # 3. streamed body counting + last-resort error envelope
        received = 0
        started = False
        rejected = False

        async def guarded_receive() -> Message:
            nonlocal received, rejected, started
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body") or b"")
                if received > limit:
                    rejected = True
                    log.warning("request body over limit path=%s received=%d limit=%d",
                                path, received, limit)
                    if not started:
                        started = True
                        msg = f"request body too large (> {limit} bytes)"
                        await _send_json(send, 413,
                                         _envelope_for_path(path, "payload_too_large", msg))
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # 413 already answered; drop whatever the app produces after the cut
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except Exception as exc:
            if rejected:
                log.debug("app aborted after body limit path=%s (%s)", path, type(exc).__name__)
                return
            if started:
                raise  # response already on the wire; nothing sane left to send
            log.exception("unhandled error path=%s", path, exc_info=exc)
            started = True
            await _send_json(send, 500, _envelope_for_path(path, "internal_error",
                                                           "internal error"))


def _error_response(request: Request, status: int, type_: str, message: str,
                    headers: dict[str, str] | None = None, **fields: Any) -> JSONResponse:
    wire = wire_for_path(request.url.path)
    if wire:
        return wire_error(wire, status, type_, message, headers=headers, **fields)
    return api_error(status, type_, message, headers=headers, **fields)


def _install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AegisHTTPError)
    async def _aegis_error(request: Request, exc: AegisHTTPError) -> JSONResponse:
        return exc.response(wire_for_path(request.url.path))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = f"invalid request: {loc + ': ' if loc else ''}{first.get('msg', 'validation error')}"
        status = 400 if wire_for_path(request.url.path) or request.url.path.startswith("/v1/") \
            else 422
        details = [{"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg")}
                   for e in errors[:20]]
        return _error_response(request, status, "invalid_request", msg, details=details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        type_ = _STATUS_TYPE.get(exc.status_code, "error")
        return _error_response(request, exc.status_code, type_, detail,
                               headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error path=%s", request.url.path, exc_info=exc)
        return _error_response(request, 500, "internal_error", "internal error")


async def _run_hooks(routers: list[Any], name: str, rt: Any, *, reverse: bool = False) -> None:
    for mod in reversed(routers) if reverse else routers:
        hook = getattr(mod, name, None)
        if hook is None:
            continue
        try:
            result = hook(rt)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            log.exception("%s failed module=%s", name, mod.__name__)
            if name == "on_startup":
                discovery._record_error(mod.__name__, exc, kind="on_startup")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Aegis FastAPI app (routers included now; Runtime built in the lifespan)."""
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_json, settings.access_log)
    routers = discovery.discover_routers()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.time()
        rt = Runtime(settings).build()
        await rt.start()
        previous = None
        try:
            previous = get_runtime()
        except RuntimeError:
            previous = None
        set_runtime(rt)
        app.state.rt = rt
        await _run_hooks(routers, "on_startup", rt)
        degraded = [k for k, v in rt.status.items() if v != "ok"]
        rt.system(
            "info",
            f"gateway started v{__version__} · policy v{rt.policy_version} · "
            f"{len(rt.controls.all()) if rt.controls else 0} controls"
            + (f" · fallbacks: {', '.join(degraded)}" if degraded else ""),
            component="gateway",
        )
        log.info(
            "aegis gateway started version=%s policy_version=%s controls=%d routers=%d "
            "fallbacks=%s",
            __version__, rt.policy_version, len(rt.controls.all()) if rt.controls else 0,
            len(routers), ",".join(degraded) or "-",
        )
        try:
            yield
        finally:
            await _run_hooks(routers, "on_shutdown", rt, reverse=True)
            try:
                from aegis.proxy import upstream  # B02; optional

                close = getattr(upstream, "close", None)
                if close is not None:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
            except ModuleNotFoundError:
                pass
            except Exception:
                log.debug("upstream close failed", exc_info=True)
            try:
                bus = rt.bus
                if bus is not None and hasattr(bus, "close"):
                    bus.close()
            except Exception:
                log.debug("bus close failed", exc_info=True)
            await rt.stop()
            try:
                current = get_runtime()
            except RuntimeError:
                current = None
            if current is rt:
                set_runtime(previous)
            log.info("aegis gateway stopped")

    app = FastAPI(
        title="Aegis AI Control Layer",
        description="Local-first AI control layer: redaction, blocking, budgets, approvals.",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.rt = None
    app.state.started_at = time.time()
    _install_handlers(app)
    for mod in routers:
        try:
            app.include_router(mod.router)
        except Exception as exc:
            discovery._record_error(mod.__name__, exc, kind="include_router")
    app.state.router_modules = [m.__name__ for m in routers]
    app.state.plugin_errors = discovery.plugin_errors
    app.add_middleware(GuardMiddleware, fastapi_app=app)
    return app


def route_table(app: FastAPI) -> list[tuple[str, str, str]]:
    """Flattened `(methods, path, module)` rows. FastAPI >= 0.14x keeps included routers as
    `_IncludedRouter` entries in `app.routes`, so `r.path for r in app.routes` no longer works."""
    rows: list[tuple[str, str, str]] = []
    try:
        from fastapi.routing import iter_route_contexts

        items: list[Any] = list(iter_route_contexts(app.routes))
    except Exception:
        items = list(app.routes)
    for r in items:
        path = getattr(r, "path", None)
        if path is None:
            continue
        methods = ",".join(sorted(getattr(r, "methods", None) or [])) or "*"
        endpoint = getattr(r, "endpoint", None)
        module = getattr(endpoint, "__module__", "") if endpoint else ""
        rows.append((methods, path, module))
    return rows


__all__ = ["GuardMiddleware", "create_app", "route_table"]
