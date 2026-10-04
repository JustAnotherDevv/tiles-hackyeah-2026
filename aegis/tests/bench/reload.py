"""Policy reload latency: in-process `apply_yaml` (incl. self-test gate) and file-edit -> active (spawn)."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

from tests.eval.metrics import pct_summary
from tests.eval.overlay import build_policy_doc


def _with_inj02_threshold(doc: dict[str, Any], thr: float, profile: str) -> str:
    d = dict(doc)
    ctl = d.get("controls")
    if isinstance(ctl, list):
        for c in ctl:
            if isinstance(c, dict) and c.get("id") == "INJ-02":
                c["threshold"] = thr
    elif isinstance(ctl, dict) and isinstance(ctl.get("INJ-02"), dict):
        ctl["INJ-02"]["threshold"] = thr
    return f"# bench reload probe thr={thr} profile={profile}\n" + yaml.safe_dump(d, sort_keys=False, allow_unicode=True)


async def apply_latency(rt: Any, *, n: int = 10, profile: str = "balanced", **overlay: Any) -> dict[str, Any]:
    doc = build_policy_doc(profile=profile, **overlay)
    wall: list[float] = []
    reported: list[float] = []
    statuses: dict[str, int] = {}
    for k in range(n):
        text = _with_inj02_threshold(doc, 0.90 if k % 2 == 0 else 0.85, profile)
        t0 = time.perf_counter()
        res = await rt.policy.apply_yaml(text, actor=None, source="bench", reason=f"bench reload {k}")
        wall.append((time.perf_counter() - t0) * 1000)
        st = str(getattr(res, "status", "?"))
        statuses[st] = statuses.get(st, 0) + 1
        lm = getattr(res, "latency_ms", None)
        if isinstance(lm, (int, float)):
            reported.append(float(lm))
    w = pct_summary(wall, ndigits=1)
    out = {"p50": w["p50"], "p95": w["p95"], "max": w["max"], "n": w["n"], "statuses": statuses,
           "method": "rt.policy.apply_yaml (validate + profile merge + self-test gate + swap), wall time"}
    if reported:
        r = pct_summary(reported, ndigits=1)
        out["reported_latency_ms"] = {"p50": r["p50"], "p95": r["p95"]}
    return out


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".policy.", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def file_to_active(base_url: str, policy_path: Path, *, n: int = 5, profile: str = "balanced",
                   timeout_s: float = 8.0, **overlay: Any) -> dict[str, Any]:
    """Atomic policy file writes -> poll GET /healthz policy_version every 10 ms (needs the watcher on)."""
    import httpx

    doc = build_policy_doc(profile=profile, **overlay)
    lat: list[float] = []
    misses = 0
    with httpx.Client(base_url=base_url, timeout=2.0) as cl:
        for k in range(n):
            before = cl.get("/healthz").json().get("policy_version")
            text = _with_inj02_threshold(doc, 0.88 if k % 2 == 0 else 0.86, profile) + f"# probe {k} {time.time()}\n"
            t0 = time.perf_counter()
            _atomic_write(policy_path, text)
            ok = False
            while time.perf_counter() - t0 < timeout_s:
                try:
                    v = cl.get("/healthz").json().get("policy_version")
                except Exception:
                    v = None
                if v is not None and before is not None and v != before:
                    lat.append((time.perf_counter() - t0) * 1000)
                    ok = True
                    break
                time.sleep(0.01)
            if not ok:
                misses += 1
    s = pct_summary(lat, ndigits=1)
    return {"p50": s["p50"], "p95": s["p95"], "max": s["max"], "n": s["n"], "timeouts": misses,
            "method": "atomic file write -> watcher (debounce) -> validate + self-test gate -> /healthz policy_version"}


__all__ = ["apply_latency", "file_to_active"]
