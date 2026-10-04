"""Exfil sink fake (same surface as `mocks.exfil_sink`): records every request it receives.

`GET /_mock/hits` → {count, hits}; `DELETE /_mock/hits` resets. A non-zero count after an
exfiltration case means the attacker received something.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import FastAPI, Request


class SinkState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.hits: list[dict[str, Any]] = []


def create_app(state: SinkState | None = None) -> FastAPI:
    st = state or SinkState()
    app = FastAPI(title="aegis-test-exfil-sink")
    app.state.fake = st

    @app.get("/_mock/health")
    async def health() -> dict[str, str]:
        return {"service": "exfil_sink"}

    @app.get("/_mock/hits")
    async def hits() -> dict[str, Any]:
        with st.lock:
            return {"count": len(st.hits), "hits": list(st.hits)}

    @app.delete("/_mock/hits")
    async def clear() -> dict[str, bool]:
        with st.lock:
            st.hits.clear()
        return {"ok": True}

    @app.post("/_mock/reset")
    async def reset() -> dict[str, bool]:
        with st.lock:
            st.hits.clear()
        return {"ok": True}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def catch_all(path: str, request: Request) -> dict[str, Any]:
        body = await request.body()
        with st.lock:
            st.hits.append(
                {
                    "ts": time.time(),
                    "method": request.method,
                    "path": "/" + path,
                    "query": str(request.url.query),
                    "body_len": len(body),
                    "headers": {
                        k.lower(): v
                        for k, v in request.headers.items()
                        if k.lower() not in ("authorization", "cookie")
                    },
                }
            )
        return {"ok": True, "received": len(body)}

    return app


__all__ = ["SinkState", "create_app"]
