"""Threat-intel feed service (FastAPI, :8790). CONTRACTS section 5.6 + plan 13 section 2.5.

Distribution (what gateways pull):  GET /feed/latest.json(.sig) · /feed/bundle/{serial}.json(.sig)
                                    GET /feed/pubkey · GET /feed/events (SSE `published`)
Authoring (the editor UI at /):     /api/state · /api/signatures[/{id}] · /api/validate · /api/scan
                                    /api/publish · /api/tamper · /api/reset · /api/events

Binds 127.0.0.1 only; no auth (localhost demo - production = Git PR + CI signing). Signatures
are data (safe_load only) and never executed; the private key is never served.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from feed_service import signing
from feed_service.build import (
    MAX_YAML_BYTES,
    TAMPER_MODES,
    FeedService,
    FeedServiceError,
    PublishRefused,
    bundle_name,
    parse_yaml,
    validate_signature,
)

log = logging.getLogger("feed_service")
UI_DIR = Path(__file__).resolve().parent / "ui"
_BUNDLE_RE = re.compile(r"^(?:bundle-)?0*(\d{1,9})\.json(\.sig)?$")
_NO_STORE = {"Cache-Control": "no-store"}
_UI_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
             ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}


def _file_response(data: bytes | None, *, sig: bool) -> Response:
    if data is None:
        raise HTTPException(404, "not found")
    headers = dict(_NO_STORE)
    headers["ETag"] = '"' + hashlib.sha256(data).hexdigest() + '"'
    return Response(content=data, media_type="text/plain" if sig else "application/json",
                    headers=headers)


def create_app(
    state_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
    gateway_url: str | None = None,
    config_dir: str | Path | None = None,
) -> FastAPI:
    svc = FeedService(Path(state_dir) if state_dir else None,
                      Path(repo_root) if repo_root else None,
                      Path(config_dir) if config_dir else None)
    gw_url = (gateway_url or os.environ.get("AEGIS_GATEWAY_URL") or "http://127.0.0.1:8787").rstrip("/")
    gw_cache: dict[str, Any] = {"t": 0.0, "v": None}

    app = FastAPI(title="Aegis Threat Intel feed", version="1.0", docs_url="/api/docs",
                  redoc_url=None, openapi_url="/api/openapi.json")
    app.state.svc = svc
    app.state.gateway_url = gw_url
    svc.ensure_ready()

    @app.exception_handler(FeedServiceError)
    async def _svc_error(_: Request, exc: FeedServiceError) -> JSONResponse:
        return JSONResponse({"error": {"type": "feed_error", "message": str(exc)}},
                            status_code=exc.status)

    # ------------------------------------------------------------------ distribution
    @app.get("/feed/latest.json")
    async def latest_json() -> Response:
        return _file_response(svc.dist_file("latest.json"), sig=False)

    @app.get("/feed/latest.json.sig")
    async def latest_sig() -> Response:
        return _file_response(svc.dist_file("latest.json.sig"), sig=True)

    @app.get("/feed/bundle/{name}")
    async def bundle(name: str) -> Response:
        mt = _BUNDLE_RE.match(name)
        if not mt:
            raise HTTPException(404, "not found")
        fname = bundle_name(int(mt.group(1))) + (mt.group(2) or "")
        return _file_response(svc.dist_file(fname), sig=bool(mt.group(2)))

    @app.get("/feed/pubkey")
    async def pubkey() -> dict[str, Any]:
        seed = signing.load_signing_key(svc.state)
        if seed is None:
            raise HTTPException(404, "no key yet: run python -m feed_service keygen")
        pub = signing.public_key(seed)
        return {"alg": "ed25519", "key_id": signing.key_id(pub),
                "public_key": base64.b64encode(pub).decode("ascii")}

    @app.get("/feed/events")
    async def feed_events(request: Request) -> Response:
        from sse_starlette.sse import EventSourceResponse

        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        svc.listeners.add(q)

        async def gen() -> AsyncIterator[dict]:
            try:
                latest = svc.latest() or {}
                yield {"event": "hello", "data": json.dumps({"serial": latest.get("serial")})}
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(q.get(), timeout=1.0)
                    except TimeoutError:
                        continue
                    yield {"event": "published", "data": json.dumps(item)}
            finally:
                svc.listeners.discard(q)

        return EventSourceResponse(gen(), ping=15)

    # ------------------------------------------------------------------ authoring
    async def _gateway_status() -> dict | None:
        now = time.monotonic()
        if now - gw_cache["t"] < 0.5:
            return gw_cache["v"]
        try:
            async with httpx.AsyncClient(timeout=0.8) as client:
                r = await client.get(f"{gw_url}/api/feed/status")
                val = r.json() if r.status_code == 200 else None
        except Exception:
            val = None
        gw_cache.update(t=now, v=val)
        return val

    @app.get("/api/state")
    async def api_state() -> dict[str, Any]:
        doc = await asyncio.to_thread(svc.state_doc)
        doc["gateway"] = await _gateway_status()
        doc["gateway_url"] = gw_url
        return doc

    @app.get("/api/signatures")
    async def api_signatures() -> dict[str, Any]:
        return {"items": await asyncio.to_thread(svc.signature_rows)}

    @app.get("/api/signatures/{sid}")
    async def api_signature(sid: str) -> dict[str, Any]:
        text = svc.workspace.get_text(sid)
        try:
            doc = parse_yaml(text)
        except FeedServiceError as e:
            return {"id": sid, "yaml": text, "signature": None,
                    "report": {"valid": False, "problems": [str(e)], "checks": [], "tests": []}}
        rep = await asyncio.to_thread(validate_signature, doc, svc.workspace.lists())
        return {"id": sid, "yaml": text, "signature": doc, "report": rep}

    async def _body_text(request: Request) -> str:
        raw = await request.body()
        if len(raw) > MAX_YAML_BYTES:
            raise FeedServiceError("signature YAML larger than 64 KB", 413)
        ctype = request.headers.get("content-type", "")
        if "json" in ctype:
            try:
                d = json.loads(raw or b"{}")
            except ValueError:
                raise FeedServiceError("invalid JSON body", 400) from None
            return str(d.get("yaml", "")) if isinstance(d, dict) else ""
        return raw.decode("utf-8", "replace")

    @app.put("/api/signatures/{sid}")
    async def api_put(sid: str, request: Request) -> dict[str, Any]:
        text = await _body_text(request)
        doc = svc.workspace.put(sid, text)
        rep = await asyncio.to_thread(validate_signature, doc, svc.workspace.lists())
        svc.event("saved", id=sid, valid=rep["valid"])
        return {"saved": True, "valid": rep["valid"], "problems": rep["problems"],
                "tests": rep["tests"], "report": rep}

    @app.delete("/api/signatures/{sid}")
    async def api_withdraw(sid: str) -> dict[str, Any]:
        svc.workspace.withdraw(sid)
        svc.event("withdrawn", id=sid)
        return {"id": sid, "status": "withdrawn"}

    @app.post("/api/signatures/{sid}/enabled")
    async def api_enabled(sid: str, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        enabled = bool((body or {}).get("enabled", True))
        svc.workspace.set_enabled(sid, enabled)
        svc.event("enabled" if enabled else "disabled", id=sid)
        return {"id": sid, "enabled": enabled}

    @app.post("/api/validate")
    async def api_validate(request: Request) -> dict[str, Any]:
        text = await _body_text(request)
        try:
            doc = parse_yaml(text)
        except FeedServiceError as e:
            return {"valid": False, "problems": [str(e)], "warnings": [], "tests": [],
                    "checks": [{"name": "Schema", "ok": False, "detail": str(e)}],
                    "vectors": {"passed": 0, "total": 0}}
        return await asyncio.to_thread(validate_signature, doc, svc.workspace.lists())

    @app.post("/api/scan")
    async def api_scan(request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict):
            raise FeedServiceError("expected a JSON object", 400)
        return await asyncio.to_thread(svc.scan, body)

    @app.post("/api/publish")
    async def api_publish(request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        async with svc.lock:
            try:
                res = await asyncio.to_thread(svc.publish, force=bool(body.get("force")),
                                              note=body.get("note"))
            except PublishRefused as e:
                return JSONResponse({"error": {"type": "invalid_signatures",
                                               "message": "validation failed; fix or force-publish"},
                                     "problems": e.problems}, status_code=422)
        return JSONResponse(res)

    @app.post("/api/tamper")
    async def api_tamper(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        mode = (body or {}).get("mode", "unsigned") if isinstance(body, dict) else "unsigned"
        async with svc.lock:
            return await asyncio.to_thread(svc.tamper, str(mode))

    @app.get("/api/tamper/modes")
    async def api_tamper_modes() -> dict[str, str]:
        return TAMPER_MODES

    @app.post("/api/reset")
    async def api_reset(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        hard = bool((body or {}).get("hard")) if isinstance(body, dict) else False
        async with svc.lock:
            return await asyncio.to_thread(svc.reset, hard=hard)

    @app.get("/api/events")
    async def api_events(limit: int = 50) -> dict[str, Any]:
        return {"items": svc.events(min(max(limit, 1), 200))}

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        latest = svc.latest() or {}
        return {"status": "ok", "service": "aegis-threat-intel", "serial": latest.get("serial"),
                "key_id": svc.key_id()}

    # ------------------------------------------------------------------ UI
    @app.get("/")
    async def ui_index() -> Response:
        p = UI_DIR / "index.html"
        if not p.exists():
            return JSONResponse({"service": "aegis-threat-intel", "ui": "missing"})
        return FileResponse(p, media_type="text/html", headers=_NO_STORE)

    @app.get("/ui/{asset}")
    async def ui_asset(asset: str) -> Response:
        if "/" in asset or ".." in asset:
            raise HTTPException(404, "not found")
        p = UI_DIR / asset
        if not p.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(p, media_type=_UI_TYPES.get(p.suffix, "application/octet-stream"),
                            headers=_NO_STORE)

    return app
