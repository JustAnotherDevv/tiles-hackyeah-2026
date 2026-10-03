"""Redaction engine API (owner: redaction-engine).

* ``GET /api/redaction/entities`` (contract) -> ``{items: [{entity, data_class, category,
  detectors}]}`` - every CONTRACTS section 3.4 entity (+ gap entities) with its detectors.
* ``GET /api/redaction/metrics`` -> precision / recall / leak-rate table (``?refresh=1``).
* ``GET /api/redaction/status`` -> NER backend, scan cache, vault sessions (counts only).
* ``GET /api/redaction/sessions/{session_id}`` -> vault counts (never values).
* ``DELETE /api/redaction/sessions/{session_id}`` (admin) -> wipe one session vault.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from aegis.redaction import entities as E

log = logging.getLogger(__name__)

router = APIRouter(tags=["redaction"])
ORDER = 100

try:  # TODO(integration): core deps are the contract surface; fall back to open access
    from aegis.core.deps import require_role, viewer
except Exception:  # pragma: no cover - only before core-gateway lands

    async def viewer(request: Request) -> Any:  # type: ignore[misc]
        return None

    def require_role(min_role: str) -> Any:  # type: ignore[misc]
        async def _dep(request: Request) -> Any:
            return None

        return _dep


Viewer = Annotated[Any, Depends(viewer)]
Admin = Annotated[Any, Depends(require_role("admin"))]


def _engine(request: Request) -> Any:
    rt = getattr(request.app.state, "rt", None)
    red = getattr(rt, "redactor", None)
    if red is None:
        try:
            from aegis.core.runtime import get_runtime

            red = getattr(get_runtime(), "redactor", None)
        except Exception:
            red = None
    return red


def entity_items(engine: Any = None) -> list[dict[str, Any]]:
    """Catalog rows with detector ids (Tier-D plug-ins, NER, heuristics, external owners)."""
    from aegis.redaction.scan import entity_catalog

    det: dict[str, set[str]] = {e: set() for e in E.ENTITIES}
    for row in entity_catalog():
        det.setdefault(row["entity"], set()).update(row["detectors"])
    plugins: list[Any] = []
    try:
        plugins = list(engine.detectors()) if engine is not None else []
    except Exception:
        plugins = []
    if not plugins:
        from aegis.redaction.detectors import builtin_detectors

        plugins = builtin_detectors()
    for d in plugins:
        ent = getattr(d, "entity", None)
        if ent:
            det.setdefault(ent, set()).add(str(getattr(d, "id", "?")))
    heur = {
        "PERSON": ["heuristic.person.lexicon", "heuristic.person.anchor"],
        "ADDRESS": ["heuristic.address.pl", "heuristic.address.en", "heuristic.address.postcode"],
        "HEALTH": ["heuristic.health.lexicon", "heuristic.health.anchor"],
        "SPECIAL_CATEGORY": [],
        "DOB": [],
    }
    for ent, ids in heur.items():
        if ent in E.NER_ENTITIES or ent == "DOB":
            det.setdefault(ent, set()).update(["ner.eu-pii-ner", *ids])
    for ent, info in E.ENTITIES.items():
        if info.source == "external":
            det.setdefault(ent, set()).add("egress.metadata (DLP-03)")
    items = []
    for ent, ids in det.items():
        info = E.info(ent)
        items.append(
            {
                "entity": ent,
                "data_class": info.data_class,
                "category": info.category,
                "detectors": sorted(ids),
                "reversible": E.is_reversible(ent),
                "description": info.description,
            }
        )
    order = {e: i for i, e in enumerate(E.ENTITIES)}
    items.sort(key=lambda r: order.get(r["entity"], 999))
    return items


@router.get("/api/redaction/entities")
async def list_entities(request: Request, who: Viewer) -> dict[str, Any]:
    return {"items": entity_items(_engine(request))}


@router.get("/api/redaction/metrics")
async def redaction_metrics(request: Request, who: Viewer, refresh: int = 0) -> dict[str, Any]:
    from aegis.redaction.evaluate import get_metrics

    m = await asyncio.to_thread(get_metrics, bool(refresh))
    eng = _engine(request)
    if eng is not None and hasattr(eng, "ner_status"):
        try:
            m = dict(m)
            m["ner_loaded"] = bool(eng.ner_status().get("loaded"))
        except Exception:
            pass
    return m


@router.get("/api/redaction/status")
async def redaction_status(request: Request, who: Viewer) -> dict[str, Any]:
    eng = _engine(request)
    if eng is None:
        return {"engine": "unavailable"}
    out: dict[str, Any] = {"engine": type(eng).__name__}
    for name in ("ner_status", "cache_stats"):
        fn = getattr(eng, name, None)
        if callable(fn):
            try:
                out[name.replace("_stats", "").replace("_status", "")] = fn()
            except Exception:
                pass
    vaults = getattr(eng, "vaults", None)
    if vaults is not None:
        out["vault"] = {
            "sessions": len(vaults),
            "ttl_s": vaults.ttl_s,
            "max_entries": vaults.max_entries,
            "token_format": vaults.token_format,
        }
    return out


@router.get("/api/redaction/sessions/{session_id}")
async def session_vault(session_id: str, request: Request, who: Viewer) -> dict[str, Any]:
    eng = _engine(request)
    fn = getattr(eng, "session_stats", None)
    stats = fn(session_id) if callable(fn) else None
    if stats is None:
        return {
            "session_id": session_id,
            "entries": 0,
            "entities": {},
            "created_at": None,
            "last_used": None,
            "ttl_s": getattr(getattr(eng, "vaults", None), "ttl_s", None),
        }
    return stats


@router.delete("/api/redaction/sessions/{session_id}")
async def wipe_session(session_id: str, request: Request, who: Admin) -> dict[str, Any]:
    eng = _engine(request)
    if eng is None:
        raise HTTPException(status_code=503, detail="redaction engine unavailable")
    fn = getattr(eng, "forget_session_count", None)
    if callable(fn):
        wiped = int(fn(session_id))
    else:
        f2 = getattr(eng, "forget_session", None)
        wiped = int(bool(f2(session_id))) if callable(f2) else 0
    log.info("vault wiped via api entries=%d", wiped)
    return {"ok": True, "wiped": wiped}
