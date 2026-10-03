"""exfil_sink FastAPI app (:8793): "Attacker received: N".

Any method / path outside `/_mock/*` is recorded (ts, method, host, path, query_len, body_len,
masked 120-char preview) and answered 200 `{ok: true}` - or a 1x1 PNG for image paths, so a
markdown beacon would "work" if it ever leaked. Reached via `AEGIS_HOST_MAP` (`exfil.test`) only
when a control fails, so the counter staying at 0 is the demo proof.

    GET    /_mock/hits     {count, items}   (CORS *, any dashboard page may read it)
    DELETE /_mock/hits     clear
    GET    /_mock/ui       big counter page (polls /_mock/hits every second)
    POST   /_mock/reset    clear
    GET    /_mock/health   {service: "exfil_sink", hits}
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from mocks import RequestLog, masked_preview, mock_data_dir

SERVICE = "exfil_sink"
UI_HTML = Path(__file__).with_name("ui.html")
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
IMAGE_EXT = (".png", ".gif", ".jpg", ".jpeg", ".webp", ".svg", ".ico")
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def create_app(*, data_dir: str | os.PathLike[str] | None = None, log_requests: bool = True) -> FastAPI:
    app = FastAPI(title="Aegis exfil sink", docs_url=None, redoc_url=None, openapi_url=None)
    path = (mock_data_dir(data_dir) / "exfil_sink.hits.jsonl") if log_requests else None
    hits = RequestLog(SERVICE, path=path)
    app.state.hits = hits

    @app.get("/_mock/hits")
    async def get_hits(limit: int = 100) -> JSONResponse:
        return JSONResponse({"count": hits.total, "items": hits.items(limit)}, headers=CORS)

    @app.delete("/_mock/hits")
    async def delete_hits() -> JSONResponse:
        return JSONResponse({"cleared": hits.clear()}, headers=CORS)

    @app.options("/_mock/hits")
    async def options_hits() -> Response:
        return Response(status_code=204, headers=CORS)

    @app.post("/_mock/reset")
    async def reset() -> dict[str, Any]:
        return {"ok": True, "cleared": hits.clear()}

    @app.get("/_mock/health")
    async def health(request: Request) -> JSONResponse:
        return JSONResponse(
            {"service": SERVICE, "port": request.url.port, "hits": hits.total, "ok": True},
            headers=CORS,
        )

    @app.get("/_mock/ui")
    async def ui() -> HTMLResponse:
        try:
            html = UI_HTML.read_text(encoding="utf-8")
        except OSError:
            html = "<h1>Attacker received: <span id=n>?</span></h1>"
        return HTMLResponse(html, headers={"cache-control": "no-store"})

    @app.api_route("/", methods=METHODS)
    @app.api_route("/{path:path}", methods=METHODS)
    async def catch_all(request: Request, path: str = "") -> Response:
        if path.startswith("_mock"):
            return JSONResponse({"error": "unknown mock endpoint"}, status_code=404)
        raw = await request.body()
        hits.add(
            {
                "method": request.method,
                "host": request.headers.get("host", ""),
                "path": "/" + path,
                "query_len": len(request.url.query or ""),
                "body_len": len(raw),
                "preview": masked_preview((request.url.query or "") + " " + raw.decode("utf-8", "replace")),
                "user_agent": masked_preview(request.headers.get("user-agent", ""), 60),
            }
        )
        if path.lower().endswith(IMAGE_EXT):
            return Response(PNG_1X1, media_type="image/png")
        return JSONResponse({"ok": True})

    return app


__all__ = ["PNG_1X1", "SERVICE", "create_app"]
