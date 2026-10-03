"""Runtime service container (`rt`, CONTRACTS section 3.3).

Public surface: `get_runtime() -> RuntimeProto` (raises RuntimeError before startup).
Private: `Runtime`, `set_runtime`, `SERVICE_TABLE`.

`Runtime.build()` creates every service in SERVICE_TABLE order via `module:create(rt)`; any
import/create failure installs the Null fallback (`aegis.core.nulls`) and queues a `system`
warning. `start()` awaits `svc.start()` in order (failure → Null), `stop()` runs in reverse.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import logging
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from aegis.core import nulls
from aegis.core.types import FeedStatus
from aegis.settings import Settings, get_settings

log = logging.getLogger(__name__)

NullFactory = Callable[[Any], Any] | None

# (attr, "module:create", null factory) — order = build/start order (CONTRACTS section 3.3)
SERVICE_TABLE: list[tuple[str, str, NullFactory]] = [
    ("settings", "aegis.settings:get_settings", None),
    ("bus", "aegis.core.bus:create", None),
    ("metrics", "aegis.metrics.prom:create", nulls.NULL_FACTORIES["metrics"]),
    ("audit", "aegis.audit.log:create", nulls.NULL_FACTORIES["audit"]),
    ("policy", "aegis.policy.store:create", nulls.NULL_FACTORIES["policy"]),
    ("org", "aegis.org.service:create", nulls.NULL_FACTORIES["org"]),
    ("sessions", "aegis.core.sessions:create", None),
    ("ledger", "aegis.budgets.ledger:create", nulls.NULL_FACTORIES["ledger"]),
    ("redactor", "aegis.redaction.engine:create", nulls.NULL_FACTORIES["redactor"]),
    ("semantic", "aegis.semantic.engine:create", nulls.NULL_FACTORIES["semantic"]),
    ("feed", "aegis.feed.manager:create", nulls.NULL_FACTORIES["feed"]),
    ("approvals", "aegis.approvals.service:create", nulls.NULL_FACTORIES["approvals"]),
    ("controls", "aegis.core.discovery:create_registry", None),
    ("pipeline", "aegis.core.pipeline:create", None),
]

#: core-owned fallbacks when even a core factory fails (should never happen)
_CORE_FALLBACK: dict[str, str] = {
    "bus": "aegis.core.bus:create",
    "sessions": "aegis.core.sessions:create",
    "controls": "aegis.core.discovery:ControlRegistry",
}

#: components reported by /healthz
COMPONENTS = (
    "bus", "policy", "org", "ledger", "redactor", "semantic", "feed", "approvals",
    "audit", "metrics", "plugins", "ollama",
)

_FEED_MAP = {
    "ok": "ok", "stale": "stale", "seed": "degraded", "disabled": "off",
    "rejected": "degraded", "unreachable": "degraded",
}

OLLAMA_CACHE_S = 30.0
_VALID = {"ok", "degraded", "down", "off", "stale"}

_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    """The started runtime (module global). Raises RuntimeError before startup."""
    if _runtime is None:
        raise RuntimeError("aegis runtime not started")
    return _runtime


def set_runtime(rt: Runtime | None) -> None:
    global _runtime
    _runtime = rt


def _resolve(target: str) -> Any:
    module_name, _, attr = target.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr or "create")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class Runtime:
    """Implements `RuntimeProto`. One per app (create_app lifespan)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings: Settings = settings or get_settings()
        self.status: dict[str, str] = {}
        self.errors: dict[str, str] = {}
        self.started_at = time.time()
        self.started = False
        self._pending_system: list[dict[str, Any]] = []
        self._order: list[str] = []
        self._tasks: list[asyncio.Task[Any]] = []
        self._ollama: tuple[float, str] | None = None
        self._ollama_lock: asyncio.Lock | None = None
        # service attributes (filled by build)
        self.bus: Any = None
        self.metrics: Any = None
        self.audit: Any = None
        self.policy: Any = None
        self.org: Any = None
        self.sessions: Any = None
        self.ledger: Any = None
        self.redactor: Any = None
        self.semantic: Any = None
        self.feed: Any = None
        self.approvals: Any = None
        self.controls: Any = None
        self.pipeline: Any = None
        self.extras: dict[str, Any] = {}  # shared slots for core handlers (e.g. upstream client)

    # ------------------------------------------------------------------ build / start / stop
    def build(self) -> Runtime:
        from aegis.core import crypto

        try:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            (self.settings.data_dir / "keys").mkdir(parents=True, exist_ok=True)
        except OSError:
            log.exception("cannot create data dir path=%s", self.settings.data_dir)
        crypto.configure(data_dir=self.settings.data_dir, key=self.settings.hmac_key)
        for attr, target, null_factory in list(SERVICE_TABLE):
            if attr == "settings":
                continue
            self._order.append(attr)
            try:
                factory = _resolve(target)
                svc = factory(self)
                if svc is None:
                    raise RuntimeError(f"{target} returned None")
                setattr(self, attr, svc)
                self.status[attr] = "ok"
            except Exception as exc:
                self._fallback(attr, target, null_factory, exc, phase="create")
        return self

    def _fallback(
        self, attr: str, target: str, null_factory: NullFactory, exc: BaseException, *, phase: str
    ) -> None:
        missing = isinstance(exc, ModuleNotFoundError) and phase == "create"
        if missing:
            log.warning("service %s not available (%s) - using null fallback", attr, exc)
        else:
            log.error("service %s %s failed target=%s - using null fallback", attr, phase, target,
                      exc_info=exc)
        self.errors[attr] = f"{phase}: {type(exc).__name__}: {exc}"
        svc: Any = None
        if null_factory is not None:
            try:
                svc = null_factory(self)
            except Exception:
                log.exception("null factory failed attr=%s", attr)
        if svc is None and attr in _CORE_FALLBACK:
            try:
                fb = _resolve(_CORE_FALLBACK[attr])
                svc = fb([]) if attr == "controls" else fb(self)
            except Exception:
                log.exception("core fallback failed attr=%s", attr)
        if svc is None and attr == "pipeline":
            raise RuntimeError(f"pipeline unavailable: {exc}") from exc
        setattr(self, attr, svc)
        self.status[attr] = "down"
        self.system(
            "warning" if missing else "error",
            f"{attr} unavailable ({type(exc).__name__}) - running with null fallback",
            component=attr,
        )

    async def start(self) -> None:
        for attr in self._order:
            svc = getattr(self, attr, None)
            start = getattr(svc, "start", None)
            if start is None or not callable(start):
                continue
            try:
                await _maybe_await(start())
            except Exception as exc:
                null_factory = next((n for a, _t, n in SERVICE_TABLE if a == attr), None)
                self._fallback(attr, f"{attr}.start", null_factory, exc, phase="start")
                new = getattr(self, attr, None)
                new_start = getattr(new, "start", None)
                if new is not svc and callable(new_start):
                    with contextlib.suppress(Exception):
                        await _maybe_await(new_start())
        self.started = True
        self._flush_system()
        if not self.settings.test_mode:
            self._tasks.append(asyncio.create_task(self._ollama_watch(), name="aegis-ollama"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        for attr in reversed(self._order):
            svc = getattr(self, attr, None)
            stop = getattr(svc, "stop", None)
            if stop is None or not callable(stop):
                continue
            try:
                await _maybe_await(stop())
            except Exception:
                log.exception("service stop failed attr=%s", attr)
        self.started = False

    # ------------------------------------------------------------------ helpers
    def db(self) -> sqlite3.Connection:
        from aegis.core.db import connect

        return connect(self.settings.data_dir / "aegis.db")

    def system(self, level: str, message: str, component: str | None = None) -> None:
        """Publish a `system` event (queued until the bus exists)."""
        payload = {"level": level, "message": message, "component": component}
        bus = self.bus
        if bus is None or not hasattr(bus, "publish"):
            self._pending_system.append(payload)
            return
        try:
            bus.publish("system", payload)
        except Exception:
            log.exception("system event publish failed")

    def _flush_system(self) -> None:
        pending, self._pending_system = self._pending_system, []
        for payload in pending:
            self.system(payload["level"], payload["message"], payload.get("component"))

    @property
    def policy_version(self) -> int:
        try:
            return int(self.policy.snapshot().version)
        except Exception:
            return 0

    @property
    def feed_serial(self) -> int | None:
        try:
            return self.feed.serial
        except Exception:
            return None

    @property
    def uptime_s(self) -> float:
        return round(time.time() - self.started_at, 3)

    # ------------------------------------------------------------------ health
    def _component(self, name: str) -> str:
        if name == "plugins":
            from aegis.core.discovery import plugin_errors

            return "degraded" if plugin_errors else "ok"
        if name == "ollama":
            if self.settings.test_mode:
                return "off"
            return self._ollama[1] if self._ollama else "off"
        svc = getattr(self, name, None)
        if svc is None or nulls.is_null(svc):
            return "down"
        try:
            if name == "semantic":  # Addendum A-44: status()["health"]
                st = svc.status() or {}
                health = st.get("health")
                if health in _VALID:
                    return str(health)
                if str(st.get("mode", "")).lower() == "off":
                    return "off"
                return "degraded" if st.get("degraded") else "ok"
            if name == "feed":
                fs = svc.status()
                status = fs.status if isinstance(fs, FeedStatus) else (fs or {}).get("status")
                return _FEED_MAP.get(str(status), "degraded")
            if name == "policy":  # Addendum A-16: status()["state"] when present
                status_fn = getattr(svc, "status", None)
                if callable(status_fn):
                    st = status_fn() or {}
                    state = st.get("state") if isinstance(st, dict) else None
                    if state in _VALID:
                        return str(state)
                    if state in {"rejected", "error", "invalid"}:
                        return "degraded"
            if name == "audit":  # Addendum A-16: last_verify
                lv = getattr(svc, "last_verify", None)
                if lv is not None and getattr(lv, "ok", True) is False:
                    return "degraded"
            health = getattr(svc, "health", None)
            if callable(health):
                value = health()
                if value in _VALID:
                    return str(value)
            return "ok"
        except Exception:
            log.exception("health probe failed component=%s", name)
            return "degraded"

    def component_status(self) -> dict[str, str]:
        return {name: self._component(name) for name in COMPONENTS}

    async def probe_ollama(self, *, force: bool = False) -> str:
        """Cached (30 s) 1 s probe of `GET {ollama_url}/api/version`. Off in test mode."""
        if self.settings.test_mode:
            return "off"
        now = time.monotonic()
        if not force and self._ollama and now - self._ollama[0] < OLLAMA_CACHE_S:
            return self._ollama[1]
        if self._ollama_lock is None:
            self._ollama_lock = asyncio.Lock()
        async with self._ollama_lock:
            if not force and self._ollama and time.monotonic() - self._ollama[0] < OLLAMA_CACHE_S:
                return self._ollama[1]
            state = "down"
            try:
                import httpx

                async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
                    r = await client.get(self.settings.ollama_url.rstrip("/") + "/api/version")
                    state = "ok" if r.status_code == 200 else "degraded"
            except Exception:
                state = "down"
            previous = self._ollama[1] if self._ollama else None
            self._ollama = (time.monotonic(), state)
            if previous is not None and previous != state:
                level = "info" if state == "ok" else "warning"
                self.system(level, f"ollama {'reachable' if state == 'ok' else 'unreachable'}",
                            component="ollama")
            return state

    async def _ollama_watch(self) -> None:
        while True:
            try:
                await self.probe_ollama(force=True)
            except Exception:
                log.debug("ollama probe failed", exc_info=True)
            await asyncio.sleep(OLLAMA_CACHE_S)


__all__ = ["COMPONENTS", "SERVICE_TABLE", "Runtime", "get_runtime", "set_runtime"]
