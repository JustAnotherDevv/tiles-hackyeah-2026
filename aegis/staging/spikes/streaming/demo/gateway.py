"""Minimal demo gateway: request redaction stand-in -> upstream -> aegis_stream -> client.

The request-side DLP engine and vault live elsewhere in Aegis; here a static
vault and a string replace stand in for them so the streaming path can be
shown end-to-end.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import Response, StreamingResponse  # noqa: E402

from aegis_stream import (  # noqa: E402
    AnthropicStreamTransformer,
    LeakScanner,
    MappingVault,
    StreamOptions,
    StreamReport,
    stream_transform,
)

UP_PORT = os.environ.get("AEGIS_DEMO_UPSTREAM_PORT", "8798")
UPSTREAM = os.environ.get("AEGIS_DEMO_UPSTREAM", f"http://127.0.0.1:{UP_PORT}")
PORT = int(os.environ.get("AEGIS_DEMO_GATEWAY_PORT", "8799"))

# stand-ins: per-session vault + compiled-once scanner (per policy version)
SESSION_VAULT = {"[PERSON_1]": "Jan Kowalski", "[EMAIL_1]": "jan.kowalski@bank.pl", "[PL_PESEL_1]": "44051401359"}
SCANNER = LeakScanner.default(allowed_image_hosts=["cdn.bank.example"], fingerprint_key=os.urandom(32))
FORWARD_HEADERS = ("anthropic-version", "anthropic-beta", "x-demo-scenario")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=300.0))
    yield
    await app.state.http.aclose()


app = FastAPI(lifespan=lifespan)


def redact_request(body: dict) -> dict:
    s = json.dumps(body, ensure_ascii=False)
    for ph, val in SESSION_VAULT.items():
        s = s.replace(val, ph)
    return json.loads(s)


def log_report(r: StreamReport) -> None:
    summary = {
        "rehydrated": r.rehydrated,
        "findings": [{"type": f.type, "action": f.action, "preview": f.preview, "fp": f.fingerprint}
                     for f in r.findings],
        "terminated": r.termination.to_dict() if r.termination else None,
        "usage": {"in": r.usage.input_tokens, "out": r.usage.estimated_output_tokens, "exact": r.usage.exact},
        "overhead_us_per_chunk": round(r.overhead_us_per_chunk, 1),
        "chunks": r.chunks_in,
    }
    print(f"\033[35m[aegis] {json.dumps(summary, ensure_ascii=False)}\033[0m", file=sys.stderr, flush=True)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/v1/messages")
async def messages(request: Request) -> Response:
    body = redact_request(await request.json())
    headers = {"content-type": "application/json", "accept-encoding": "identity"}
    headers.update({h: request.headers[h] for h in FORWARD_HEADERS if h in request.headers})
    http: httpx.AsyncClient = request.app.state.http
    upstream = await http.send(http.build_request("POST", f"{UPSTREAM}/v1/messages", json=body, headers=headers),
                               stream=True)
    if upstream.status_code != 200 or "text/event-stream" not in upstream.headers.get("content-type", ""):
        data = await upstream.aread()
        await upstream.aclose()
        return Response(data, status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))
    tr = AnthropicStreamTransformer(StreamOptions(vault=MappingVault(SESSION_VAULT), scanner=SCANNER))
    return StreamingResponse(
        stream_transform(upstream.aiter_bytes(), tr, aclose=upstream.aclose, on_complete=log_report),
        media_type=tr.media_type,
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
