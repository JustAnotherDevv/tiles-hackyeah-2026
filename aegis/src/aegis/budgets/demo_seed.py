"""Demo state: counters from `demo_state.budget_usage` of `config/org.seed.yaml` (read-only YAML,
CONTRACTS gap G12) plus deterministic synthetic history samples for the burn-down charts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

from . import windows

log = logging.getLogger(__name__)

# demo_state key -> (window, dimension)
KEY_MAP: dict[str, tuple[str, str]] = {
    "usd_today": ("day", "usd"),
    "usd_mtd": ("month", "usd"),
    "tokens_today": ("day", "tokens"),
    "tokens_mtd": ("month", "tokens"),
    "local_compute_s_today": ("day", "compute_s"),
    "local_compute_s_mtd": ("month", "compute_s"),
    "compute_s_today": ("day", "compute_s"),
    "spend_usd_mtd": ("month", "spend_usd"),
}
SAMPLE_DIMS = ("usd", "tokens", "compute_s")


def read_seed(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        log.warning("demo seed unreadable path=%s", p, exc_info=True)
        return {}


def map_scope(key: str, org_id: str) -> str:
    key = str(key).strip()
    if key == "org":
        return f"org:{org_id}"
    if "/" in key:
        kind, _, ident = key.partition("/")
        return f"{kind}:{ident}"
    if ":" in key:
        return key
    return f"org:{org_id}" if key == org_id else key


def seed_counters(seed: dict[str, Any]) -> list[tuple[str, str, str, float]]:
    """[(scope, window, dimension, used)] from demo_state.budget_usage. Month counters are at
    least the day value (MTD includes today)."""
    org_id = str(((seed.get("org") or {}).get("id")) or "default")
    usage = ((seed.get("demo_state") or {}).get("budget_usage")) or {}
    out: dict[tuple[str, str, str], float] = {}
    for key, vals in usage.items():
        if not isinstance(vals, dict):
            continue
        scope = map_scope(key, org_id)
        for k, v in vals.items():
            wd = KEY_MAP.get(str(k))
            if wd is None or v is None:
                continue
            out[(scope, wd[0], wd[1])] = float(v)
    for (scope, window, dim), val in list(out.items()):
        if window == "day":
            mk = (scope, "month", dim)
            out[mk] = max(out.get(mk, 0.0), val)
    for (scope, window, dim), val in list(out.items()):
        if window == "month":
            tk = (scope, "total", dim)
            out[tk] = max(out.get(tk, 0.0), val)
    return [(s, w, d, v) for (s, w, d), v in out.items()]


def seed_kill_switch(seed: dict[str, Any]) -> dict[str, Any] | None:
    ks = (seed.get("demo_state") or {}).get("kill_switch")
    return ks if isinstance(ks, dict) else None


def _weight(local: datetime) -> float:
    """Business-hours load profile (deterministic)."""
    h = local.hour + local.minute / 60.0
    if 8 <= h < 18:
        return 1.0 + 0.35 * ((int(h * 4) * 7) % 5) / 4.0
    if 7 <= h < 8 or 18 <= h < 20:
        return 0.4
    return 0.08


def synthetic_samples(
    counters: list[tuple[str, str, str, float]], at: datetime, tz: tzinfo, limit_for: Any = None
) -> list[tuple[str, str, str, str, float, float | None]]:
    """Ramp samples (ts, scope, dim, window, used, limit) ending at the current values:
    15-min steps for `day`, 3-hour steps for `month`."""
    rows: list[tuple[str, str, str, str, float, float | None]] = []
    for scope, window, dim, used in counters:
        if dim not in SAMPLE_DIMS or window not in ("day", "month") or used <= 0:
            continue
        start = windows.window_start_dt(window, at, tz)
        if start is None:
            continue
        step = timedelta(minutes=15) if window == "day" else timedelta(hours=3)
        points: list[datetime] = []
        t = start
        while t < at:
            points.append(t)
            t += step
        if not points:
            continue
        weights: list[float] = []
        for p in points:
            local = p.astimezone(tz)
            w = _weight(local) if window == "day" else (0.35 if local.weekday() >= 5 else 1.0)
            weights.append(w)
        total = sum(weights) or 1.0
        limit = None
        if limit_for is not None:
            try:
                limit = limit_for(scope, window, dim)
            except Exception:
                limit = None
        acc = 0.0
        for p, w in zip(points, weights, strict=True):
            rows.append((windows.iso(p), scope, dim, window, round(used * acc / total, 6), limit))
            acc += w
        rows.append((windows.iso(at), scope, dim, window, round(used, 6), limit))
    return rows


__all__ = ["map_scope", "read_seed", "seed_counters", "seed_kill_switch", "synthetic_samples"]
