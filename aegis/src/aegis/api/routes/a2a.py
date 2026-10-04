"""POST /a2a/{peer} - governed agent-to-agent (A2A) proxy (ASI07 / ASI01; controls A2A-01/02).

An agent sends a JSON-RPC A2A request (``message/send`` ...) to ``/a2a/<peer id>``; the gateway

1. resolves the caller (``rt.org.resolve_identity``) and the peer from the A2A-01 registry
   (``controls[A2A-01].params.peers``), fetches + checks the peer's agent card;
2. evaluates the ``a2a.message`` interaction (A2A-01 identity / allowlist / card / inbound
   signature, A2A-02 delegation depth + loop, DLP-02, EXE-04 ...);
3. signs the (possibly redacted) message with the peer's shared key (``x-a2a-*`` headers:
   sender = gateway id, recipient, timestamp, nonce) and forwards it with ``X-Aegis-Hop`` + 1
   and the delegation chain in ``X-Aegis-Chain``;
4. evaluates the reply as ``a2a.result`` (same context, A-02): A2A-01 verifies the peer's
   signature, freshness, single-use nonce and the binding to our request nonce; A2A-02 scans the
   untrusted reply for injection / smuggling / exfil links and quarantines or blocks;
5. returns the (possibly quarantined) JSON-RPC reply - the peer's ``x-a2a-*`` headers are
   stripped - or a JSON-RPC error ``-32001`` (blocked) / ``-32002`` (approval required) with
   ``error.data.aegis = {decision_id, action, control, reason, approval_id}``.

Inbound delegation: an agent relaying a message it received from a peer forwards the peer's
``x-a2a-*`` headers unchanged; A2A-01 then verifies that signature and A2A-02 treats the text as
untrusted. ``GET /a2a/peers`` lists the registry (no key material).

The outbound HTTP client lives in ``rt.extras["a2a.client"]`` (tests swap in an ASGI transport).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from aegis.a2a import card as a2a_card
from aegis.a2a import messages, peers, signing
from aegis.a2a.signing import ENVELOPE_KEY
from aegis.core.deps import client_ip, get_rt
from aegis.core.errors import block_status, decision_headers
from aegis.core.types import Destination, Interaction, Outcome, Usage, Verdict, new_id

log = logging.getLogger(__name__)

router = APIRouter(tags=["a2a"])

CLIENT_KEY = "a2a.client"
ALLOWED = ("allow", "log", "redact")
MAX_BODY = 1_000_000


# ------------------------------------------------------------------ helpers
def get_client(rt: Any) -> Any:
    extras = getattr(rt, "extras", None)
    if extras is None:
        extras = {}
        with contextlib.suppress(Exception):
            rt.extras = extras
    client = extras.get(CLIENT_KEY)
    if client is None:
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=False)
        extras[CLIENT_KEY] = client
    return client


def _rpc_error(rpc_id: Any, code: int, message: str, status: int,
               data: dict[str, Any] | None = None,
               headers: dict[str, str] | None = None) -> JSONResponse:
    err: dict[str, Any] = {"code": code, "message": message}
    if data:
        err["data"] = data
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "error": err}, status_code=status,
                        headers=headers)


def _headers(ctx: Any, verdict: Verdict, rverdict: Verdict | None = None) -> dict[str, str]:
    try:
        h = decision_headers(verdict, rverdict)
    except Exception:
        h = {}
    h.update({
        "x-aegis-request-id": ctx.request_id,
        "x-aegis-decision-id": verdict.id,
        "x-aegis-decision": verdict.action,
        "x-aegis-policy-version": str(verdict.policy_version),
        "x-aegis-redactions": str(len(verdict.redactions)
                                  + (len(rverdict.redactions) if rverdict else 0)),
    })
    if rverdict is not None:
        h["x-aegis-response-decision-id"] = rverdict.id
    approval_id = (verdict.approval.id if verdict.approval else None) or (
        verdict.primary.approval_id if verdict.primary else None)
    if approval_id:
        h["x-aegis-approval-id"] = approval_id
    return h


def _verdict_error(rpc_id: Any, verdict: Verdict, headers: dict[str, str]) -> JSONResponse:
    p = verdict.primary
    stop = block_status(p)
    status = stop[0] if stop else 403
    if stop:
        headers = {**headers, **stop[2]}
    control = p.control_id if p else "?"
    reason = p.reason if p else verdict.action
    approval_id = (verdict.approval.id if verdict.approval else None) or (
        p.approval_id if p else None)
    if verdict.action == "require_approval":
        code, msg = -32002, f"[Aegis] Approval required by {control}: {reason}"
    else:
        code, msg = -32001, f"[Aegis] Blocked by {control}: {reason}"
    data = {"aegis": {"decision_id": verdict.id, "action": verdict.action, "control": control,
                      "reason": reason, "approval_id": approval_id}}
    return _rpc_error(rpc_id, code, msg, status, data, headers)


async def _complete(rt: Any, ctx: Any, inter: Interaction, verdict: Verdict,
                    outcome: Outcome) -> None:
    try:
        await rt.pipeline.complete(ctx, inter, verdict, outcome)
    except Exception:
        log.exception("a2a completion failed decision=%s", verdict.id)


def _stash(ctx: Any, interaction_id: str, env: dict[str, str]) -> None:
    """Full envelope (incl. signature + nonce) for A2A-01, kept out of audited fields."""
    ctx.state.setdefault(ENVELOPE_KEY, {})[interaction_id] = dict(env)


def _public(env: dict[str, str]) -> dict[str, str]:
    """Envelope headers safe to record (signature + nonce stay in ``Interaction.raw``)."""
    return {k: v for k, v in env.items() if k not in (signing.H_SIG, signing.H_NONCE,
                                                       signing.H_REPLY_TO)}


def _hop(raw: str | None) -> int:
    try:
        return max(0, int((raw or "0").strip()))
    except ValueError:
        return 0


def _chain(raw: str | None) -> list[str]:
    return [c.strip() for c in (raw or "").split(",") if c.strip()][:32]


# ------------------------------------------------------------------ routes
@router.get("/a2a/peers")
async def list_peers(request: Request) -> dict[str, Any]:
    rt = await get_rt(request)
    snap = rt.policy.snapshot()
    params = peers.a2a01_params(snap)
    out = []
    for pid, p in peers.parse_peers(params).items():
        out.append({
            "id": pid, "url": p.url, "destination": p.destination, "enabled": p.enabled,
            "key_id": p.key_id,
            "key_source": "env" if any(
                os.environ.get(n) for n in [p.key_env, peers.env_name(pid)] if n) else "derived",
            "allowed_callers": p.allowed_callers,
            "card": {"name": p.card.name or pid, "pinned": bool(p.card.sha256),
                     "url": p.card_url},
        })
    return {"gateway_id": peers.gateway_id(params), "peers": out}


@router.post("/a2a/{peer}")
async def a2a_send(peer: str, request: Request) -> JSONResponse:
    rt = await get_rt(request)
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return _rpc_error(None, -32600, "A2A message too large", 413)
    try:
        body = json.loads(raw or b"null")
    except ValueError:
        return _rpc_error(None, -32700, "parse error: body is not JSON", 400)
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(
            body.get("method"), str):
        return _rpc_error(body.get("id") if isinstance(body, dict) else None, -32600,
                          "invalid request: expected a JSON-RPC 2.0 A2A message", 400)
    rpc_id = body.get("id")
    method = body["method"]

    identity = await rt.org.resolve_identity(request.headers)
    ctx = rt.pipeline.new_context(
        source="proxy", identity=identity,
        session_id=request.headers.get("x-aegis-session"),
        headers=request.headers, approval_token=request.headers.get("x-aegis-approval"),
        wait_for_approval_s=0.0, client_ip=client_ip(request))
    snap = ctx.policy or rt.policy.snapshot()
    params = peers.a2a01_params(snap)
    registry = peers.parse_peers(params)
    gw = peers.gateway_id(params)
    pcfg = registry.get(peer)
    hop = _hop(request.headers.get("x-aegis-hop"))
    chain = _chain(request.headers.get("x-aegis-chain"))
    inbound = {k.lower(): v for k, v in request.headers.items()
               if k.lower().startswith("x-a2a-")}
    client = get_client(rt)

    card_facts = None
    if pcfg is not None and pcfg.enabled and params.get("verify_card", True):
        card_facts = await a2a_card.fetch_and_check(client, pcfg)

    segments = messages.request_segments(body, trusted=not inbound)
    dest = Destination(name=f"a2a:{peer}",
                       dest_class=(pcfg.destination if pcfg and pcfg.destination in
                                   ("local", "remote", "third_party") else "third_party"),
                       host=pcfg.host if pcfg else None, url=pcfg.url if pcfg else None)
    a2a_meta: dict[str, Any] = {"peer": peer, "method": method, "hop": hop, "chain": chain,
                                "transport": "gateway", "card": card_facts,
                                "from_peer": bool(inbound)}
    interaction = Interaction(
        kind="a2a", surface="a2a.message", direction="out", destination=dest,
        tool_name=f"a2a.{peer}", tool_args={"method": method}, url=pcfg.url if pcfg else None,
        http_method="POST", headers=_public(inbound), segments=segments,
        resource=f"a2a:{peer}", meta={"a2a": a2a_meta, "source": "a2a"})
    interaction.id = new_id("int")
    interaction.raw = raw
    _stash(ctx, interaction.id, inbound)
    verdict: Verdict = await rt.pipeline.evaluate(ctx, interaction)

    if verdict.action not in ALLOWED:
        resp = _verdict_error(rpc_id, verdict, _headers(ctx, verdict))
        await _complete(rt, ctx, interaction, verdict,
                        Outcome(status_code=resp.status_code, usage=Usage(requests=0),
                                error=verdict.action))
        return resp
    if pcfg is None or not pcfg.url or not pcfg.enabled:
        # only reachable when A2A-01 is disabled / monitor-only: never forward to an
        # unregistered peer (there is no address for it anyway)
        await _complete(rt, ctx, interaction, verdict,
                        Outcome(status_code=404, usage=Usage(requests=0), error="unknown peer"))
        return _rpc_error(rpc_id, -32004, f"unknown A2A peer '{peer}'", 404,
                          headers=_headers(ctx, verdict))

    out_body = (messages.apply_segments(body, verdict.segments)
                if verdict.redactions and verdict.segments else body)
    out_bytes = json.dumps(out_body, ensure_ascii=False).encode("utf-8")
    sig = signing.sign_headers(peers.peer_key(pcfg), sender=gw, recipient=peer, body=out_bytes,
                               key_id=pcfg.key_id)
    caller = identity.agent_id or identity.member_id or "anonymous"
    fwd = {"content-type": "application/json", **sig, "x-aegis-hop": str(hop + 1),
           "x-aegis-chain": ",".join([*chain, caller] if not chain or chain[-1] != caller
                                     else chain)}
    t0 = time.perf_counter()
    try:
        up = await client.post(pcfg.url, content=out_bytes, headers=fwd)
    except (httpx.HTTPError, OSError) as exc:
        await _complete(rt, ctx, interaction, verdict,
                        Outcome(status_code=502, usage=Usage(requests=0),
                                error=f"upstream: {type(exc).__name__}", provider=f"a2a:{peer}"))
        return _rpc_error(rpc_id, -32003, f"peer '{peer}' unreachable ({type(exc).__name__})",
                          502, headers=_headers(ctx, verdict))
    upstream_ms = (time.perf_counter() - t0) * 1000
    reply_raw = up.content
    try:
        reply = json.loads(reply_raw or b"null")
    except ValueError:
        reply = None

    reply_env = {k.lower(): v for k, v in up.headers.items() if k.lower().startswith("x-a2a-")}
    rint = Interaction(
        kind="a2a", surface="a2a.result", direction="in", destination=dest,
        tool_name=f"a2a.{peer}", url=pcfg.url, http_method="POST",
        headers=_public(reply_env),
        segments=messages.result_segments(reply) if isinstance(reply, dict) else [],
        resource=f"a2a:{peer}", parent_id=interaction.id, labels={"peer_agent": peer},
        meta={"a2a": {"peer": peer, "method": method, "transport": "gateway",
                      "request_nonce": sig[signing.H_NONCE], "status_code": up.status_code},
              "source": "a2a"})
    rint.id = new_id("int")
    rint.raw = reply_raw
    _stash(ctx, rint.id, reply_env)
    rverdict: Verdict = await rt.pipeline.evaluate(ctx, rint)
    outcome = Outcome(status_code=up.status_code, upstream_ms=upstream_ms,
                      provider=f"a2a:{peer}", usage=Usage(requests=1, tool_calls=1),
                      response_verdict_id=rverdict.id)
    headers = _headers(ctx, verdict, rverdict)
    if rverdict.action not in ALLOWED:
        outcome.status_code = 403
        outcome.error = f"response {rverdict.action}"
        await _complete(rt, ctx, interaction, verdict, outcome)
        return _verdict_error(rpc_id, rverdict, headers)
    if not isinstance(reply, dict):
        await _complete(rt, ctx, interaction, verdict, outcome)
        return _rpc_error(rpc_id, -32003, f"peer '{peer}' returned a non-JSON reply", 502,
                          headers=headers)
    out_reply = (messages.apply_segments(reply, rverdict.segments)
                 if rverdict.redactions and rverdict.segments else reply)
    await _complete(rt, ctx, interaction, verdict, outcome)
    status = up.status_code if up.status_code < 500 else 502
    return JSONResponse(out_reply, status_code=status, headers=headers)


# ------------------------------------------------------------------ lifecycle
async def on_shutdown(rt: Any) -> None:
    client = getattr(rt, "extras", {}).pop(CLIENT_KEY, None)
    if client is not None:
        with contextlib.suppress(Exception):
            await client.aclose()
