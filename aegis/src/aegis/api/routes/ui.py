"""Dashboard static hosting (ORDER 900, included after every API router).

`GET /` → 302 `/ui/`; `GET /ui/{path}` → file under `settings.ui_dist` (path-traversal safe),
`assets/*` cached immutable, anything else → `index.html` (SPA fallback for deep links such as
`/ui/security/decisions/dec_…`). Dist missing → a friendly placeholder page.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

ORDER = 900
router = APIRouter(tags=["ui"], include_in_schema=False)

_NOT_BUILT = """<!doctype html><html lang="en" class="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Aegis</title>
<style>
:root{color-scheme:dark}
body{background:#07080A;color:#ECEEF1;font:15px/1.5 Inter,system-ui,sans-serif;display:grid;
place-items:center;min-height:100vh;margin:0;padding:16px;box-sizing:border-box}
.card{max-width:560px;border:1px solid #1F2329;border-radius:16px;padding:28px 32px;
background:linear-gradient(180deg,#0E1013,#0A0B0D);box-shadow:0 0 60px rgba(99,102,241,.08)}
h1{font-size:20px;margin:0 0 6px}p{color:#A8AFB8;margin:8px 0}
code{background:#13161A;border:1px solid #1F2329;padding:2px 6px;border-radius:6px;color:#ECEEF1}
a{color:#A5B4FC;text-decoration:none}a:hover{text-decoration:underline}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#10B981;
margin-right:8px;box-shadow:0 0 8px #10B981}
</style></head>
<body><div class="card"><h1><span class="dot"></span>Aegis gateway is running</h1>
<p>The dashboard bundle is not built yet &mdash; run <code>make web</code>.</p>
<p><a href="/healthz">/healthz</a> &middot; <a href="/api/events?replay=20">/api/events</a>
&middot; <a href="/api/docs">/api/docs</a></p></div></body></html>"""


def _dist(request: Request) -> Path:
    return Path(request.app.state.settings.ui_dist).resolve()


@router.api_route("/", methods=["GET", "HEAD"])
async def root() -> RedirectResponse:
    return RedirectResponse("/ui/", status_code=302)


@router.api_route("/ui", methods=["GET", "HEAD"])
async def ui_root() -> RedirectResponse:
    return RedirectResponse("/ui/", status_code=302)


@router.api_route("/ui/{path:path}", methods=["GET", "HEAD"])
async def ui(path: str, request: Request) -> Response:
    dist = _dist(request)
    index = dist / "index.html"
    if not index.is_file():
        return HTMLResponse(_NOT_BUILT)
    if path:
        try:
            candidate = (dist / path).resolve()
        except (OSError, ValueError):
            candidate = None
        if candidate is not None and candidate.is_relative_to(dist) and candidate.is_file():
            headers = {}
            if candidate.is_relative_to(dist / "assets"):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return FileResponse(candidate, headers=headers)
        if path.startswith("assets/"):
            return Response(status_code=404)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
