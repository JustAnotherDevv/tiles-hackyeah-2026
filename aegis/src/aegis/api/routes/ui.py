"""Dashboard static hosting: GET / -> 302 /ui/, GET /ui/{path} (web/dist, SPA fallback).

SCAFFOLD STUB - owned by core-gateway, safe to extend/replace. ORDER 900 so it is included
after every API router.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

ORDER = 900
router = APIRouter(tags=["ui"], include_in_schema=False)

_NOT_BUILT = """<!doctype html><html class="dark"><head><meta charset="utf-8"><title>Aegis</title>
<style>body{background:#07080A;color:#ECEEF1;font:14px system-ui;display:grid;place-items:center;height:100vh;margin:0}
code{background:#13161A;padding:2px 6px;border-radius:6px}a{color:#A5B4FC}</style></head>
<body><div><h1>Aegis gateway is running</h1><p>Dashboard not built &mdash; run <code>make web</code>.</p>
<p><a href="/healthz">/healthz</a> &middot; <a href="/api/docs">/api/docs</a></p></div></body></html>"""


def _dist(request: Request) -> Path:
    return Path(request.app.state.settings.ui_dist).resolve()


@router.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/ui/", status_code=302)


@router.get("/ui")
async def ui_root() -> RedirectResponse:
    return RedirectResponse("/ui/", status_code=302)


@router.get("/ui/{path:path}")
async def ui(path: str, request: Request) -> Response:
    dist = _dist(request)
    index = dist / "index.html"
    if not index.is_file():
        return HTMLResponse(_NOT_BUILT)
    candidate = (dist / path).resolve()
    if path and candidate.is_file() and candidate.is_relative_to(dist):
        headers = {}
        if candidate.is_relative_to(dist / "assets"):
            headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return FileResponse(candidate, headers=headers)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
