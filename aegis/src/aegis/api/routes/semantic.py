"""Semantic model runtime routes (owner: semantic-models).

- ``GET /api/semantic/status`` (member+): ``rt.semantic.status()`` - a superset of
  ``PerfResponse["semantic"]`` (health, RAM plan, Ollama, per-model p50/p95, breakers, cache).
- ``POST /api/semantic/score`` (member+, diagnostic, CG-6): dry scoring of a short text; never
  audited or logged.
- ``POST /api/semantic/warmup`` (admin, CG-6): load the planned models now.

No import-time work; absolute paths; ``rt`` comes from ``aegis.core.deps``.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:  # public import surface of core-gateway (CONTRACTS section 3.3)
    from aegis.core.deps import get_rt, require_role, viewer
except Exception:  # pragma: no cover - TODO(integration): remove once aegis.core.deps exists

    async def get_rt(request: Request) -> Any:
        return getattr(request.app.state, "rt", None)

    async def viewer(request: Request) -> Any:
        return None

    def require_role(min_role: str) -> Any:
        async def _dep(request: Request) -> Any:
            return None

        return _dep


router = APIRouter(tags=["semantic"])

Rt = Annotated[Any, Depends(get_rt)]
Viewer = Annotated[Any, Depends(viewer)]
Admin = Annotated[Any, Depends(require_role("admin"))]

MAX_SCORE_CHARS = 8_000
TASKS = ("injection", "moderation", "adherence", "judge")


def _engine(rt: Any) -> Any:
    return getattr(rt, "semantic", None) if rt is not None else None


def _unavailable(request: Request) -> dict[str, Any]:
    settings = getattr(request.app.state, "settings", None)
    return {
        "mode": str(getattr(settings, "semantic", "auto")),
        "degraded": True,
        "health": "down",
        "ready": False,
        "models": [],
        "message": "semantic engine not running",
    }


@router.get("/api/semantic/status")
async def semantic_status(request: Request, rt: Rt, _viewer: Viewer) -> dict[str, Any]:
    eng = _engine(rt)
    if eng is None:
        return _unavailable(request)
    try:
        return eng.status()
    except Exception as exc:  # never 500 on a status page
        out = _unavailable(request)
        out["message"] = f"status failed: {type(exc).__name__}"
        return out


class ScoreRequest(BaseModel):
    text: str = Field(max_length=MAX_SCORE_CHARS)
    tasks: list[str] = Field(default_factory=lambda: ["injection", "moderation"])
    references: list[str] = Field(default_factory=list, max_length=32)
    rule: str | None = Field(default=None, max_length=2_000)
    mode: str = "prompt"


@router.post("/api/semantic/score")
async def semantic_score(body: ScoreRequest, rt: Rt, _viewer: Viewer) -> Any:
    eng = _engine(rt)
    if eng is None:
        return JSONResponse(
            status_code=503,
            content={"error": {"type": "unavailable", "message": "semantic engine not running"}},
        )
    unknown = [t for t in body.tasks if t not in TASKS]
    if unknown:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": f"unknown tasks: {unknown}"}},
        )
    jobs: dict[str, Any] = {}
    if "injection" in body.tasks:
        jobs["injection"] = eng.injection_score(body.text)
    if "moderation" in body.tasks:
        jobs["moderation"] = eng.moderate(body.text, mode=body.mode)
    if "adherence" in body.tasks and body.references:
        jobs["adherence"] = eng.similarity_detail(body.text, body.references)
    if "judge" in body.tasks and body.rule:
        jobs["judge"] = eng.judge(body.rule, body.text)
    results = await asyncio.gather(*jobs.values())
    return {
        "results": {
            k: (r.model_dump() if hasattr(r, "model_dump") else r)
            for k, r in zip(jobs, results, strict=True)
        }
    }


class WarmupRequest(BaseModel):
    models: list[str] | None = None


@router.post("/api/semantic/warmup")
async def semantic_warmup(rt: Rt, _admin: Admin, body: WarmupRequest | None = None) -> Any:
    eng = _engine(rt)
    if eng is None or not hasattr(eng, "warmup"):
        return JSONResponse(
            status_code=503,
            content={"error": {"type": "unavailable", "message": "semantic engine not running"}},
        )
    return await eng.warmup((body.models if body else None) or None)
