"""Aegis spike: minimal Anthropic passthrough proxy for Claude Code.

Run:
  uv run --python 3.13 --with fastapi --with uvicorn --with httpx \
      python proxy.py --port 18787

What it does
  * catch-all forwarder -> https://api.anthropic.com (any method/path, incl. HEAD /api/hello)
  * streams SSE back byte-for-byte (aiter_raw) while parsing a copy for logging
  * logs every request's headers (auth headers redacted) to logs/proxy.jsonl
  * optional request rewrite: user text / tool_result text "4111 1111 1111 1111" -> "[CARD_1]"
  * optional budget short-circuit on POST /v1/messages (429/402/403/synthetic 200)
  * POST /hook  - PreToolUse decision endpoint used by hook.py
  * runtime config: GET/POST /_spike/config   (e.g. {"redact": true, "budget": "429_noretry"})
  * GET /_spike/install.sh - harmless script for the curl|sh test (only echoes)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

UPSTREAM = os.environ.get("SPIKE_UPSTREAM", "https://api.anthropic.com")
HERE = Path(__file__).resolve().parent
LOG_DIR = HERE / "logs"
LOG_DIR.mkdir(exist_ok=True)
PROXY_LOG = LOG_DIR / "proxy.jsonl"
HOOK_LOG = LOG_DIR / "hooks.jsonl"

CONFIG: dict = {"redact": False, "budget": None, "hook_delay_s": 0.0, "tag": ""}

SECRET_HEADERS = {"authorization", "x-api-key", "proxy-authorization", "cookie", "set-cookie"}
IDENTIFYING_HEADERS = {"anthropic-organization-id", "anthropic-workspace-id"}
HOP_BY_HOP = {
    "host", "content-length", "connection", "keep-alive", "transfer-encoding",
    "te", "trailer", "upgrade", "proxy-connection", "accept-encoding",
}
RESP_DROP = {"content-length", "transfer-encoding", "connection", "keep-alive", "date", "server"}

app = FastAPI()
client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=None, write=60, pool=10), http2=False)


def log(path: Path, rec: dict) -> None:
    rec = {"ts": round(time.time(), 3), "tag": CONFIG.get("tag", ""), **rec}
    with path.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def redact_headers(headers) -> dict:
    out = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in SECRET_HEADERS:
            scheme = v.split(" ", 1)[0] if " " in v else ""
            tok = v.split(" ", 1)[-1]
            kind = "oauth(sk-ant-oat*)" if tok.startswith("sk-ant-oat") else (
                "api-key(sk-ant-api*)" if tok.startswith("sk-ant-api") else "other")
            out[lk] = f"<redacted scheme={scheme or '-'} kind={kind} len={len(tok)}>"
        elif lk in IDENTIFYING_HEADERS:
            out[lk] = "<redacted-id>"
        else:
            out[lk] = v
    return out


# ---------------------------------------------------------------- redaction
CARD_RE = re.compile(r"\b4111[ -]?1111[ -]?1111[ -]?1111\b")


_REQ_COUNTER = {"n": 0}


def _redact_str(s: str) -> tuple[str, int]:
    # "redact_nondeterministic": placeholder changes per request ([CARD_1], [CARD_2], ...)
    # to demonstrate what happens when redaction is NOT stable across turns.
    ph = f"[CARD_{_REQ_COUNTER['n']}]" if CONFIG.get("redact_nondeterministic") else "[CARD_1]"
    return CARD_RE.subn(ph, s)


def redact_body(body: dict) -> int:
    """Rewrite only user-role text and tool_result text. Never system/tools/thinking."""
    n = 0
    for m in body.get("messages", []):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            m["content"], k = _redact_str(c)
            n += k
            continue
        for b in c or []:
            if b.get("type") == "text":
                b["text"], k = _redact_str(b["text"])
                n += k
            elif b.get("type") == "tool_result":
                tc = b.get("content")
                if isinstance(tc, str):
                    b["content"], k = _redact_str(tc)
                    n += k
                elif isinstance(tc, list):
                    for tb in tc:
                        if tb.get("type") == "text":
                            tb["text"], k = _redact_str(tb["text"])
                            n += k
    return n


def summarize_body(body: dict) -> dict:
    msgs = body.get("messages", [])
    last = msgs[-1] if msgs else {}
    lc = last.get("content")
    if isinstance(lc, list):
        parts = []
        for b in lc:
            t = b.get("type")
            if t == "text":
                parts.append({"text": b["text"][-600:]})
            elif t == "tool_result":
                parts.append({"tool_result": json.dumps(b.get("content"), ensure_ascii=False)[:600],
                              "is_error": b.get("is_error")})
            else:
                parts.append({"type": t})
        lc = parts
    elif isinstance(lc, str):
        lc = lc[-600:]
    md = body.get("metadata") or {}
    uid = md.get("user_id")
    if isinstance(uid, str):
        # 2.1.27x sends a JSON string {"device_id","account_uuid","session_id"}; keep only session_id
        try:
            u = json.loads(uid)
            uid = {k: (v if k == "session_id" else "<redacted>") for k, v in u.items()}
        except Exception:
            uid = re.sub(r"account_[0-9a-f-]+", "account_<redacted>", uid)
            uid = re.sub(r"user_[0-9a-f]{16,}", "user_<redacted>", uid)
    return {
        "keys": sorted(body.keys()),
        "model": body.get("model"),
        "max_tokens": body.get("max_tokens"),
        "stream": body.get("stream"),
        "thinking": body.get("thinking"),
        "n_messages": len(msgs),
        "n_tools": len(body.get("tools") or []),
        "tool_names": [t.get("name") for t in (body.get("tools") or [])][:30],
        "n_system_blocks": len(body.get("system") or []) if isinstance(body.get("system"), list) else "str",
        "metadata_user_id": uid,
        "msg_roles_types": [
            (m.get("role"), [b.get("type") for b in m["content"]] if isinstance(m.get("content"), list) else "str")
            for m in msgs
        ],
        "first_user_msg_sha256": hashlib.sha256(
            json.dumps(msgs[0], sort_keys=True).encode()).hexdigest()[:16] if msgs else None,
        "last_message": {"role": last.get("role"), "content": lc},
    }


# ---------------------------------------------------------------- SSE observer
class SSEObserver:
    def __init__(self) -> None:
        self.buf = b""
        self.events: dict[str, int] = {}
        self.text = ""
        self.usage: dict = {}
        self.stop_reason = None
        self.block_types: list[str] = []
        self.errors: list = []

    def feed(self, chunk: bytes) -> None:
        self.buf += chunk
        while b"\n\n" in self.buf:
            raw, self.buf = self.buf.split(b"\n\n", 1)
            ev, data = None, []
            for line in raw.decode("utf-8", "replace").splitlines():
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
            self.events[ev or "?"] = self.events.get(ev or "?", 0) + 1
            try:
                d = json.loads("\n".join(data)) if data else {}
            except Exception:
                continue
            t = d.get("type")
            if t == "message_start":
                self.usage.update(d["message"].get("usage", {}))
            elif t == "content_block_start":
                self.block_types.append(d["content_block"].get("type"))
            elif t == "content_block_delta" and d["delta"].get("type") == "text_delta":
                self.text += d["delta"]["text"]
            elif t == "message_delta":
                self.usage.update(d.get("usage", {}))
                self.stop_reason = d.get("delta", {}).get("stop_reason")
            elif t == "error":
                self.errors.append(d)

    def summary(self) -> dict:
        return {"events": self.events, "block_types": self.block_types, "text": self.text[:1500],
                "usage": self.usage, "stop_reason": self.stop_reason, "errors": self.errors}


# ---------------------------------------------------------------- budget modes
def anthropic_error(etype: str, msg: str) -> dict:
    return {"type": "error", "error": {"type": etype, "message": msg}}


BUDGET_MSG = "aegis: budget team:blue $5.00/day exhausted (control BUD-001)"
BUDGET_MODES = {
    "429_noretry": (429, {"retry-after": "3600", "x-should-retry": "false"}, "rate_limit_error"),
    "429_noretry_only": (429, {"x-should-retry": "false"}, "rate_limit_error"),
    "429_retryafter_only": (429, {"retry-after": "3600"}, "rate_limit_error"),
    "429_plain": (429, {}, "rate_limit_error"),
    "402": (402, {}, "billing_error"),
    "403": (403, {}, "permission_error"),
    "400": (400, {}, "invalid_request_error"),
}


def synthetic_sse(text: str, model: str) -> bytes:
    mid = "msg_aegis_" + uuid.uuid4().hex[:20]
    evs = [
        ("message_start", {"type": "message_start", "message": {
            "id": mid, "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 1}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return b"".join(f"event: {e}\ndata: {json.dumps(d)}\n\n".encode() for e, d in evs)


# ---------------------------------------------------------------- spike control endpoints
@app.get("/_spike/config")
async def get_config():
    return CONFIG


@app.post("/_spike/config")
async def set_config(req: Request):
    CONFIG.update(await req.json())
    log(PROXY_LOG, {"kind": "config", "config": dict(CONFIG)})
    return CONFIG


@app.get("/_spike/install.sh")
async def install_sh():
    return PlainTextResponse("echo AEGIS_SPIKE_HARMLESS_SCRIPT_RAN\n")


# ---------------------------------------------------------------- hook decision endpoint
PIPE_TO_SHELL = re.compile(r"curl .*\| *sh")
ENV_IN_CMD = re.compile(r"(^|[\s/'\"=<])\.env(\.[\w-]+)?($|[\s'\";|&>])")


def deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


@app.post("/hook")
async def hook(req: Request):
    t0 = time.perf_counter()
    data = await req.json()
    if CONFIG.get("hook_delay_s"):
        await asyncio.sleep(float(CONFIG["hook_delay_s"]))
    decision: dict = {}
    if data.get("hook_event_name") == "PreToolUse":
        tool = data.get("tool_name")
        ti = data.get("tool_input") or {}
        if tool == "Bash":
            cmd = ti.get("command", "")
            if PIPE_TO_SHELL.search(cmd):
                decision = deny("AEGIS-DENY CC-010 pipe-to-shell: downloading and executing a remote "
                                "script is blocked by Aegis policy v1. Do not retry or work around this.")
            elif ENV_IN_CMD.search(cmd):
                decision = deny("AEGIS-DENY SEC-004 secret-file access: .env files may not be read "
                                "(policy v1).")
        elif tool in ("Read", "Edit", "Write", "Grep"):
            p = ti.get("file_path") or ti.get("path") or ""
            if re.search(r"(^|/)\.env(\.[\w-]+)?$", p):
                decision = deny("AEGIS-DENY SEC-004 secret-file access: .env files may not be read "
                                "(policy v1).")
    log(HOOK_LOG, {"kind": "hook", "input": data, "decision": decision,
                   "latency_ms": round((time.perf_counter() - t0) * 1000, 2)})
    return JSONResponse(decision)


# ---------------------------------------------------------------- catch-all forwarder
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def forward(path: str, request: Request):
    rid = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()
    raw = await request.body()
    is_messages = request.method == "POST" and request.url.path.rstrip("/") == "/v1/messages"
    rec: dict = {"kind": "request", "rid": rid, "method": request.method, "path": request.url.path,
                 "query": request.url.query, "headers": redact_headers(request.headers),
                 "body_bytes": len(raw)}

    body_obj = None
    if request.url.path.startswith("/v1/messages") and raw:
        try:
            body_obj = json.loads(raw)
        except Exception:
            body_obj = None

    # --- budget short-circuit (no upstream call, no quota spent)
    mode = CONFIG.get("budget")
    if is_messages and mode:
        rec["summary"] = summarize_body(body_obj) if body_obj else None
        if mode == "200_synthetic":
            payload = synthetic_sse(f"[Aegis] {BUDGET_MSG}. Request was not sent to the model.",
                                    (body_obj or {}).get("model", "unknown"))
            rec.update({"short_circuit": mode, "status": 200})
            log(PROXY_LOG, rec)
            return Response(payload, status_code=200, media_type="text/event-stream",
                            headers={"cache-control": "no-cache"})
        status, hdrs, etype = BUDGET_MODES[mode]
        rec.update({"short_circuit": mode, "status": status, "resp_headers": hdrs})
        log(PROXY_LOG, rec)
        return JSONResponse(anthropic_error(etype, BUDGET_MSG), status_code=status, headers=hdrs)

    # --- optional request rewrite
    if is_messages and body_obj is not None:
        if CONFIG.get("redact"):
            _REQ_COUNTER["n"] += 1
            n = redact_body(body_obj)
            rec["redactions"] = n
            if n:
                raw = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":")).encode()
        rec["outgoing_contains_4111"] = b"4111 1111" in raw or b"4111111111111111" in raw
        rec["summary"] = summarize_body(body_obj)

    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    fwd_headers["accept-encoding"] = "identity"
    url = UPSTREAM + request.url.path + (("?" + request.url.query) if request.url.query else "")
    upstream_req = client.build_request(request.method, url, headers=fwd_headers, content=raw)
    try:
        upstream = await client.send(upstream_req, stream=True)
    except httpx.HTTPError as e:
        rec.update({"status": 502, "error": repr(e)})
        log(PROXY_LOG, rec)
        return JSONResponse(anthropic_error("api_error", f"spike proxy upstream error: {e!r}"), status_code=502)

    rec["status"] = upstream.status_code
    rec["resp_headers"] = redact_headers({k: v for k, v in upstream.headers.items()})
    rec["ttfb_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in RESP_DROP}
    ctype = upstream.headers.get("content-type", "")
    observer = SSEObserver() if "text/event-stream" in ctype else None

    async def body_iter():
        small = b""
        try:
            async for chunk in upstream.aiter_raw():
                if observer:
                    observer.feed(chunk)
                elif request.url.path.startswith("/v1/") and len(small) < 4000:
                    small += chunk
                yield chunk
        finally:
            await upstream.aclose()
            rec["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if observer:
                rec["sse"] = observer.summary()
            elif small:
                rec["resp_body_head"] = small[:2000].decode("utf-8", "replace")
            log(PROXY_LOG, rec)

    if request.method == "HEAD":
        await upstream.aclose()
        rec["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        log(PROXY_LOG, rec)
        return Response(status_code=upstream.status_code, headers=resp_headers)

    return StreamingResponse(body_iter(), status_code=upstream.status_code, headers=resp_headers)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18787)
    a = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
