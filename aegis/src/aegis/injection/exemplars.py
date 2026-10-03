"""Exemplar matching over ``rt.semantic.embed`` (docs/plan/05 INJ-09).

The index (``data/exemplars.yaml``) is embedded lazily in a background task on first need and is
never awaited inline: until it is ready the stage is skipped. ``embed()`` returning ``[]`` or
raising (MiniLM unavailable, Addendum A-44) disables the stage. A hit requires the best attack
similarity >= ``threshold`` and > best benign similarity + ``margin``; it never acts alone.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from functools import cache
from pathlib import Path
from typing import Any

log = logging.getLogger("aegis.injection.exemplars")
DATA = Path(__file__).with_name("data")

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_indexes: dict[int, dict[str, Any]] = {}  # id(semantic) -> {state, labels, vecs, task}
_warned = False
_BG: set[Any] = set()  # strong refs to fire-and-forget tasks


@cache
def _load() -> tuple[list[str], list[str], frozenset[str]]:
    import yaml

    try:
        data = yaml.safe_load((DATA / "exemplars.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        log.exception("exemplars.yaml unreadable")
        return [], [], frozenset()
    texts: list[str] = []
    labels: list[str] = []
    for label, items in (data.get("exemplars") or {}).items():
        for t in items or []:
            texts.append(str(t))
            labels.append(str(label))
    return texts, labels, frozenset(data.get("benign_labels") or ())


def _emit_warning(rt: Any) -> None:
    global _warned
    if _warned:
        return
    _warned = True
    log.warning("exemplar index unavailable (embeddings degraded)")
    bus = getattr(rt, "bus", None)
    if bus is None:
        return
    try:
        res = bus.publish(
            "system",
            {
                "level": "warning",
                "component": "injection",
                "message": "exemplar index unavailable (embeddings degraded)",
            },
        )
        if asyncio.iscoroutine(res):
            _BG.add(task := asyncio.ensure_future(res))
            task.add_done_callback(_BG.discard)
    except Exception:
        log.debug("system event publish failed", exc_info=True)


def _entry(sem: Any) -> dict[str, Any]:
    entry = _indexes.get(id(sem))
    if entry is None or entry.get("sem") is not sem:  # id() reuse after GC -> fresh entry
        entry = _indexes[id(sem)] = {"state": "idle", "sem": sem}
    return entry


async def build_index(rt: Any) -> dict[str, Any] | None:
    """Embed the exemplar set now (tests / warm-up). Returns the ready index or None."""
    sem = getattr(rt, "semantic", None)
    if sem is None:
        return None
    entry = _entry(sem)
    texts, labels, benign = _load()
    if not texts:
        entry["state"] = "failed"
        return None
    try:
        vecs = await sem.embed(texts)
    except Exception:
        vecs = []
    if not vecs or len(vecs) != len(texts):
        entry["state"] = "failed"
        _emit_warning(rt)
        return None
    import numpy as np

    m = np.asarray(vecs, dtype="float32")
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    entry.update(state="ready", vecs=m / norms, labels=labels, benign=benign)
    return entry


def _index(rt: Any) -> dict[str, Any] | None:
    sem = getattr(rt, "semantic", None)
    if sem is None:
        return None
    entry = _entry(sem)
    if entry["state"] == "ready":
        return entry
    if entry["state"] == "idle":
        entry["state"] = "building"
        try:
            entry["task"] = asyncio.get_running_loop().create_task(build_index(rt))
        except RuntimeError:
            entry["state"] = "idle"
    return None


async def best_by_label(rt: Any, text: str, max_sentences: int = 16) -> dict[str, float] | None:
    idx = _index(rt)
    if idx is None:
        return None
    sents = [s.strip() for s in _SENT.split(text or "") if len(s.strip()) >= 8][:max_sentences] or [
        text[:500]
    ]
    try:
        vecs = await rt.semantic.embed(sents)
    except Exception:
        return None
    if not vecs:
        return None
    import numpy as np

    q = np.asarray(vecs, dtype="float32")
    qn = np.linalg.norm(q, axis=1, keepdims=True)
    qn[qn == 0] = 1.0
    sims = (q / qn) @ idx["vecs"].T  # (n_sent, n_ex)
    best = sims.max(axis=0)
    out: dict[str, float] = {}
    for lbl, s in zip(idx["labels"], best.tolist(), strict=False):
        out[lbl] = max(out.get(lbl, -1.0), float(s))
    return out


def vote_from_sims(
    sims: dict[str, float],
    benign: frozenset[str],
    threshold: float,
    margin: float,
    only: str | None = None,
) -> dict[str, Any]:
    attack = {k: v for k, v in sims.items() if k not in benign and (only is None or k == only)}
    ben = {k: v for k, v in sims.items() if k in benign}
    a_lbl, a_sim = max(attack.items(), key=lambda kv: kv[1]) if attack else ("", 0.0)
    b_lbl, b_sim = max(ben.items(), key=lambda kv: kv[1]) if ben else ("", 0.0)
    hit = a_sim >= threshold and a_sim > b_sim + margin
    return {
        "stage": "exemplar",
        "label": a_lbl,
        "sim": round(a_sim, 4),
        "benign_label": b_lbl,
        "benign_sim": round(b_sim, 4),
        "threshold": threshold,
        "hit": bool(hit),
    }


def exemplar_vote_fn(
    rt: Any, params: Any, only: str | None = None
) -> Callable[[str], Awaitable[dict[str, Any] | None]] | None:
    """An async ``vote(text)`` for the cascade, or None when no semantic engine exists."""
    if rt is None or getattr(rt, "semantic", None) is None:
        return None

    async def vote(text: str) -> dict[str, Any] | None:
        sims = await best_by_label(rt, text)
        if not sims:
            return None
        idx = _indexes.get(id(rt.semantic)) or {}
        return vote_from_sims(
            sims,
            idx.get("benign", frozenset()),
            float(params.threshold),
            float(params.margin),
            only,
        )

    return vote
