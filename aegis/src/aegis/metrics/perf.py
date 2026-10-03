"""In-memory performance tracker behind GET /api/perf and the SSE `stats` tick.

Bounded ring-buffer reservoirs (exact percentiles over the buffer): gateway overhead per phase
(2048), per control (1024), per (provider, model) upstream (512) + a 120 s deque of
(monotonic, action) for rps / decisions_1m. Memory stays well under 2 MB.
Only REAL measurements go in here (live traffic + the dry-run primer), never synthetic history.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

from aegis.metrics.timing import iso_z

log = logging.getLogger(__name__)

ACTIONS = ("allow", "log", "redact", "require_approval", "block")


class Reservoir:
    __slots__ = ("buf", "count")

    def __init__(self, size: int) -> None:
        self.buf: deque[float] = deque(maxlen=size)
        self.count = 0

    def add(self, value_ms: float) -> None:
        self.buf.append(float(value_ms))
        self.count += 1

    def pct(self, *qs: float) -> list[float]:
        data = sorted(self.buf)
        if not data:
            return [0.0 for _ in qs]
        n = len(data)
        out = []
        for q in qs:
            k = min(n - 1, max(0, round(q * (n - 1))))
            out.append(round(data[k], 3))
        return out


def percentiles(values: list[float], *qs: float) -> list[float]:
    r = Reservoir(max(1, len(values)))
    for v in values:
        r.add(v)
    return r.pct(*qs)


class PerfTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.overhead: dict[str, Reservoir] = {}
        self.controls: dict[str, Reservoir] = {}
        self.control_kind: dict[str, str] = {}
        self.upstream: dict[tuple[str, str | None], Reservoir] = {}
        self.recent: deque[tuple[float, str]] = deque(maxlen=50_000)
        self.primer_samples = 0

    # ------------------------------------------------------------------ feed
    def add_overhead(self, phase: str, ms: float) -> None:
        with self._lock:
            self.overhead.setdefault(phase, Reservoir(2048)).add(ms)

    def add_control(self, control_id: str, ms: float, kind: str | None = None) -> None:
        with self._lock:
            self.controls.setdefault(control_id, Reservoir(1024)).add(ms)
            if kind:
                self.control_kind[control_id] = kind

    def add_upstream(self, provider: str, model: str | None, ms: float) -> None:
        with self._lock:
            self.upstream.setdefault((provider, model), Reservoir(512)).add(ms)

    def add_decision(self, action: str) -> None:
        self.recent.append((time.monotonic(), action))

    # ------------------------------------------------------------------ read
    def _recent(self, window_s: float) -> list[str]:
        cutoff = time.monotonic() - window_s
        while self.recent and self.recent[0][0] < cutoff - 60:
            self.recent.popleft()
        return [a for t, a in list(self.recent) if t >= cutoff]

    def rps(self, window_s: float = 60.0) -> float:
        return round(len(self._recent(window_s)) / window_s, 3)

    def decisions_1m(self) -> dict[str, int]:
        c = Counter(self._recent(60.0))
        return {a: int(c.get(a, 0)) for a in ACTIONS}

    def overhead_reservoir(self) -> Reservoir:
        """request+response phases when the gateway reports them, else the pipeline phase."""
        with self._lock:
            parts = [self.overhead[p] for p in ("request", "response") if p in self.overhead]
            if not parts:
                parts = [r for p, r in self.overhead.items() if p == "pipeline"]
            if not parts:
                parts = list(self.overhead.values())
            merged = Reservoir(sum(len(p.buf) for p in parts) or 1)
            for p in parts:
                for v in p.buf:
                    merged.buf.append(v)
                merged.count += p.count
            return merged

    def overhead_ms(self) -> dict[str, Any]:
        r = self.overhead_reservoir()
        p50, p95, p99 = r.pct(0.5, 0.95, 0.99)
        return {"p50": p50, "p95": p95, "p99": p99, "count": r.count}

    def by_control(self, kinds: dict[str, str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self.controls.items())
        out = []
        for cid, r in items:
            p50, p95 = r.pct(0.5, 0.95)
            kind = (kinds or {}).get(cid) or self.control_kind.get(cid) or "deterministic"
            out.append(
                {"control_id": cid, "kind": kind, "p50_ms": p50, "p95_ms": p95, "count": r.count}
            )
        out.sort(key=lambda x: (-x["p95_ms"], x["control_id"]))
        return out

    def upstream_ms(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self.upstream.items())
        out = []
        for (prov, model), r in items:
            p50, p95 = r.pct(0.5, 0.95)
            out.append({"provider": prov, "model": model, "p50": p50, "p95": p95, "count": r.count})
        out.sort(key=lambda x: -x["count"])
        return out

    def control_p95(self) -> dict[str, float]:
        with self._lock:
            return {cid: r.pct(0.95)[0] for cid, r in self.controls.items()}


# ------------------------------------------------------------------ bench.json
_bench_cache: dict[str, Any] = {"path": None, "mtime": None, "data": None}


def load_bench(path: Path) -> dict[str, Any] | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _bench_cache["path"] == str(path) and _bench_cache["mtime"] == mtime:
        return _bench_cache["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {"data": data}
    except (OSError, ValueError):
        data = None
    _bench_cache.update(path=str(path), mtime=mtime, data=data)
    return data


def semantic_status(rt: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"mode": "off", "degraded": True, "models": []}
    sem = getattr(rt, "semantic", None)
    if sem is None:
        return out
    try:
        st = sem.status() or {}
    except Exception:
        log.debug("semantic.status() failed", exc_info=True)
        return out
    out["mode"] = str(st.get("mode") or "off")
    out["degraded"] = bool(st.get("degraded", False))
    models = []
    for m in st.get("models") or []:
        if not isinstance(m, dict):
            continue
        p50 = m.get("p50_ms")
        models.append(
            {
                "name": str(m.get("name") or "?"),
                "backend": str(m.get("backend") or "?"),
                "loaded": bool(m.get("loaded", False)),
                "p50_ms": float(p50) if isinstance(p50, (int, float)) else None,
            }
        )
    out["models"] = models
    return out


def control_kinds(rt: Any) -> dict[str, str]:
    kinds: dict[str, str] = {}
    reg = getattr(rt, "controls", None)
    if reg is None:
        return kinds
    try:
        for c in reg.all():
            kinds[str(getattr(c, "id", ""))] = str(getattr(c, "kind", "deterministic"))
    except Exception:
        pass
    return kinds


def reports_dir(rt: Any) -> Path:
    """Settings.reports_dir / AEGIS_REPORTS_DIR (A-53), relative paths resolved against the repo root."""
    import os

    settings = getattr(rt, "settings", None)
    root = getattr(settings, "root", None)
    if root is None:
        root = Path(__file__).resolve().parents[3]
    rd = getattr(settings, "reports_dir", None) or os.environ.get("AEGIS_REPORTS_DIR") or "reports"
    rd = Path(rd)
    return rd if rd.is_absolute() else Path(root) / rd


def bench_path(rt: Any) -> Path:
    return reports_dir(rt) / "bench.json"


def build_perf_response(rt: Any, tracker: PerfTracker | None = None) -> dict[str, Any]:
    """PerfResponse (CONTRACTS section 5.5) with exactly the frozen keys."""
    if tracker is None:
        tracker = getattr(getattr(rt, "metrics", None), "perf", None) or PerfTracker()
    return {
        "generated_at": iso_z(),
        "overhead_ms": tracker.overhead_ms(),
        "by_control": tracker.by_control(control_kinds(rt)),
        "upstream_ms": tracker.upstream_ms(),
        "rps_1m": tracker.rps(60.0),
        "semantic": semantic_status(rt),
        "bench": load_bench(bench_path(rt)),
    }


__all__ = [
    "ACTIONS",
    "PerfTracker",
    "Reservoir",
    "build_perf_response",
    "load_bench",
    "percentiles",
    "reports_dir",
    "semantic_status",
]
