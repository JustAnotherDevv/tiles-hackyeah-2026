"""OpenAI-compatible proxy: `POST /v1/chat/completions`, `POST /openai/v1/chat/completions`,
`GET /v1/models`.

Owner: core-gateway (bundle B02). Used by the scripted demo agents (mock-openai on :8791,
ollama-openai on :11434). Streaming requests get `stream_options.include_usage` injected; the
synthesized stream hides the usage chunk again if the client did not ask for it.

`GET /v1/models` = exact (non-glob) `models.allowed` entries that resolve to an enabled route +
`mock-echo`/`mock-sonnet` + Ollama `/api/tags` names (1 s timeout, cached 30 s). The shape
satisfies both the OpenAI and the Anthropic SDKs.
"""

from __future__ import annotations

import fnmatch
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from aegis.proxy import upstream
from aegis.proxy.flow import handle_model_request, runtime_of
from aegis.proxy.router import resolve_route

log = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])

_TAGS_CACHE: dict[str, tuple[float, list[str]]] = {}
_TAGS_TTL_S = 30.0
_MOCK_MODELS = ("mock-echo", "mock-sonnet")


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    """OpenAI chat completions (JSON + SSE)."""
    return await handle_model_request(request, wire="openai", op="chat")


@router.post("/openai/v1/chat/completions")
async def chat_completions_prefixed(request: Request) -> Response:
    """Same as `/v1/chat/completions` (for clients configured with an `/openai/v1` base URL)."""
    return await handle_model_request(request, wire="openai", op="chat")


_OLLAMA_UP: dict[str, bool] = {}


def _ollama_state(rt: Any, base: str, up: bool) -> None:
    """GW-13: bus `system` toast when Ollama reachability changes (first probe only logs)."""
    prev = _OLLAMA_UP.get(base)
    _OLLAMA_UP[base] = up
    if prev is None or prev == up:
        return
    bus = getattr(rt, "bus", None)
    if bus is None:
        return
    try:
        bus.publish("system", {
            "level": "info" if up else "warning", "component": "ollama",
            "message": f"Ollama {'reachable again' if up else 'unreachable'} at {base}",
        })
    except Exception:
        log.debug("system event publish failed", exc_info=True)


async def _ollama_tags(base: str, test_mode: bool, rt: Any = None) -> list[str]:
    if test_mode:
        return []
    now = time.monotonic()
    hit = _TAGS_CACHE.get(base)
    if hit and now - hit[0] < _TAGS_TTL_S:
        return hit[1]
    names: list[str] = []
    up = False
    try:
        resp = await upstream.get_client().get(f"{base.rstrip('/')}/api/tags",
                                               timeout=httpx.Timeout(1.0))
        up = resp.status_code < 500
        if resp.status_code == 200:
            for m in (resp.json() or {}).get("models") or []:
                name = m.get("name") or m.get("model")
                if isinstance(name, str):
                    names.append(name)
    except Exception:
        log.debug("ollama tags probe failed", exc_info=True)
    _ollama_state(rt, base, up)
    _TAGS_CACHE[base] = (now, names)
    return names


def _model_entry(mid: str, owner: str, created: int) -> dict[str, Any]:
    return {
        "id": mid,
        "object": "model",
        "type": "model",
        "display_name": mid,
        "created": created,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(created)),
        "owned_by": owner,
    }


@router.get("/v1/models")
async def list_models(request: Request) -> Response:
    """Merged list of routable, allowed models."""
    try:
        rt = runtime_of(request)
        snap = rt.policy.snapshot()
        settings = getattr(rt, "settings", None)
    except Exception:
        rt, snap, settings = None, None, None
    doc = getattr(snap, "doc", None)
    models_sec = getattr(doc, "models", None)
    allowed = list(getattr(models_sec, "allowed", None) or ["*"])
    denied = list(getattr(models_sec, "denied", None) or [])
    created = int(time.time())
    seen: dict[str, dict[str, Any]] = {}

    def add(mid: str, owner: str) -> None:
        if mid in seen:
            return
        if any(fnmatch.fnmatchcase(mid, d) for d in denied):
            return
        seen[mid] = _model_entry(mid, owner, created)

    for mid in _MOCK_MODELS:
        add(mid, "aegis-mock")
    for pattern in allowed:
        if any(ch in pattern for ch in "*?["):
            continue
        for wire in ("openai", "anthropic", "ollama"):
            route = resolve_route(pattern, wire, snap, settings)
            if route is not None:
                add(pattern, route.provider)
                break
    ollama = (getattr(settings, "ollama_url", None) or "http://127.0.0.1:11434")
    test_mode = bool(getattr(settings, "test_mode", False))
    for name in await _ollama_tags(ollama, test_mode, rt):
        if any(fnmatch.fnmatchcase(name, a) for a in allowed):
            add(name, "ollama")
    data = list(seen.values())
    return JSONResponse({
        "object": "list",
        "data": data,
        "has_more": False,
        "first_id": data[0]["id"] if data else None,
        "last_id": data[-1]["id"] if data else None,
    })
