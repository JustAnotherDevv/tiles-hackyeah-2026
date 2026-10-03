"""Hermetic in-process runtime for eval (plan 19 §2.5).

    async with hermetic_runtime("balanced", semantic="off") as h:
        rt = h.rt
        await switch_profile(h, "strict")

Temp dir with policy.yaml + data/, env AEGIS_POLICY / AEGIS_DATA_DIR / AEGIS_SEMANTIC /
AEGIS_FEED_URL=disabled / AEGIS_TEST_MODE=1 / AEGIS_DEMO_MODE=1, `create_app(Settings(...))`
under `app.router.lifespan_context`. Never touches config/policy.yaml or the real data dir.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.eval.overlay import ROOT, build_policy_text

MIN_SEM_AVAILABLE_GB = 2.0
SEM_MODEL_DIR = "pi-horizon-small"


@dataclass
class Hermetic:
    rt: Any
    app: Any
    tmp: Path
    policy_path: Path
    profile: str
    semantic: str
    boot_s: float
    log: list[str] = field(default_factory=list)


def hermetic_env(tmp: Path, policy_path: Path, semantic: str, *, test_mode: bool = True,
                 port: int | None = None) -> dict[str, str]:
    env = {
        "AEGIS_POLICY": str(policy_path),
        "AEGIS_DATA_DIR": str(tmp / "data"),
        "AEGIS_SEMANTIC": semantic,
        "AEGIS_FEED_URL": "disabled",
        "AEGIS_TEST_MODE": "1" if test_mode else "0",
        "AEGIS_DEMO_MODE": "1",
        "AEGIS_LOG_LEVEL": "WARNING",
        "AEGIS_WARMUP": "off" if semantic == "off" else "auto",
    }
    if port is not None:
        env["AEGIS_PORT"] = str(port)
    return env


def semantic_preflight(models_dir: Path | None = None) -> str | None:
    """None if a semantic run may start, else the skip reason."""
    try:
        import psutil

        avail = psutil.virtual_memory().available / 2**30
    except Exception:  # pragma: no cover
        return "psutil unavailable (cannot check memory)"
    if avail < MIN_SEM_AVAILABLE_GB:
        return f"available RAM {avail:.2f} GB < {MIN_SEM_AVAILABLE_GB} GB"
    md = models_dir or Path(os.environ.get("AEGIS_MODELS_DIR") or ROOT / "models")
    if not (md / SEM_MODEL_DIR).exists():
        return f"model {SEM_MODEL_DIR} not found in {md}"
    return None


def _clear_settings_cache() -> None:
    try:
        from aegis.settings import get_settings

        get_settings.cache_clear()
    except Exception:
        pass


@asynccontextmanager
async def hermetic_runtime(profile: str = "balanced", semantic: str = "off", *,
                           policy_text: str | None = None) -> AsyncIterator[Hermetic]:
    from aegis.app import create_app
    from aegis.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="aegis-eval-"))
    (tmp / "data").mkdir()
    policy_path = tmp / "policy.yaml"
    policy_path.write_text(policy_text or build_policy_text(profile=profile), encoding="utf-8")
    env = hermetic_env(tmp, policy_path, semantic)
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    _clear_settings_cache()
    try:
        settings = Settings.from_env()
        t0 = time.perf_counter()
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            rt = app.state.rt
            yield Hermetic(rt=rt, app=app, tmp=tmp, policy_path=policy_path, profile=profile,
                           semantic=semantic, boot_s=time.perf_counter() - t0)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _clear_settings_cache()
        shutil.rmtree(tmp, ignore_errors=True)


def active_profile(rt: Any) -> str | None:
    try:
        return str(rt.policy.snapshot().doc.profile)
    except Exception:
        return None


async def switch_profile(h: Hermetic, profile: str) -> dict[str, Any]:
    """Switch via `rt.policy.apply_yaml` (writes only the temp AEGIS_POLICY).

    Returns {status: applied|noop|rejected|unavailable, version, errors?, latency_ms}.
    """
    text = build_policy_text(profile=profile)
    t0 = time.perf_counter()
    try:
        res = await h.rt.policy.apply_yaml(text, actor=None, source="eval", reason=f"eval profile {profile}")
    except Exception as e:  # pragma: no cover - depends on policy-engine
        return {"status": "unavailable", "errors": [f"apply_yaml raised: {e!r}"]}
    wall = (time.perf_counter() - t0) * 1000
    status = str(getattr(res, "status", "unknown"))
    out: dict[str, Any] = {"status": status, "version": getattr(res, "version", None),
                           "latency_ms": round(wall, 2)}
    if status not in ("applied", "noop"):
        errs = getattr(res, "errors", None) or []
        out["errors"] = [getattr(e, "message", str(e)) for e in errs][:10]
        out["message"] = getattr(res, "message", None)
    elif active_profile(h.rt) != profile:
        out["status"] = "rejected"
        out["errors"] = [f"active profile is {active_profile(h.rt)!r} after apply"]
    if out["status"] in ("applied", "noop"):
        h.profile = profile
    return out


__all__ = ["Hermetic", "active_profile", "hermetic_env", "hermetic_runtime", "semantic_preflight",
           "switch_profile"]
