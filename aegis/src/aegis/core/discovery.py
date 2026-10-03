"""Plug-in auto-discovery (CONTRACTS section 2.1).

Routers (`aegis.api.routes.*` → `router`, optional `ORDER`, `on_startup(rt)`, `on_shutdown(rt)`),
controls (`aegis.controls.**` → `CONTROLS`), redaction detectors (`DETECTORS`) and wire adapters
(`aegis.proxy.adapters.*` → `ADAPTERS`). Every module is imported inside try/except; failures are
logged at ERROR, collected in `plugin_errors` (→ `/healthz` components.plugins = degraded) and
never stop the gateway. Modules whose name segment starts with `_` are skipped.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import threading
from collections.abc import Iterator
from types import ModuleType
from typing import Any

log = logging.getLogger(__name__)

#: {"module": "aegis.api.routes.foo", "error": "ImportError: ..."} for every failed import.
plugin_errors: list[dict[str, str]] = []
_errors_lock = threading.Lock()


def _record_error(module: str, exc: BaseException | str, *, kind: str = "import") -> None:
    message = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    if isinstance(exc, BaseException):
        log.error("plugin %s failed module=%s error=%s", kind, module, message, exc_info=exc)
    else:
        log.error("plugin %s problem module=%s error=%s", kind, module, message)
    with _errors_lock:
        for err in plugin_errors:
            if err["module"] == module and err["error"] == message:
                return
        plugin_errors.append({"module": module, "error": message, "kind": kind})


def clear_plugin_errors() -> None:
    with _errors_lock:
        plugin_errors.clear()


def _iter_modules(package: str, *, recursive: bool) -> Iterator[ModuleType]:
    try:
        pkg = importlib.import_module(package)
    except Exception as exc:
        _record_error(package, exc)
        return
    path = getattr(pkg, "__path__", None)
    if path is None:
        return

    def _onerror(name: str) -> None:
        _record_error(name, "package import failed during walk")

    walker = (
        pkgutil.walk_packages(path, prefix=f"{package}.", onerror=_onerror)
        if recursive
        else pkgutil.iter_modules(path, prefix=f"{package}.")
    )
    for info in sorted(walker, key=lambda i: i.name):
        if any(part.startswith("_") for part in info.name[len(package) + 1 :].split(".")):
            continue
        try:
            yield importlib.import_module(info.name)
        except Exception as exc:
            _record_error(info.name, exc)


# ================================================================ routers
def discover_routers(package: str = "aegis.api.routes") -> list[ModuleType]:
    """Route modules exposing `router`, sorted by (ORDER, module name)."""
    found: list[tuple[int, str, ModuleType]] = []
    for mod in _iter_modules(package, recursive=False):
        if getattr(mod, "router", None) is None:
            log.warning("route module without `router` skipped module=%s", mod.__name__)
            continue
        try:
            order = int(getattr(mod, "ORDER", 100))
        except (TypeError, ValueError):
            order = 100
        found.append((order, mod.__name__, mod))
    return [m for _, _, m in sorted(found, key=lambda t: (t[0], t[1]))]


# ================================================================ controls
def _validate_control(control: Any) -> str | None:
    """Return a problem description or None when the object looks like a Control."""
    cid = getattr(control, "id", "")
    if not isinstance(cid, str) or not cid:
        return "missing id"
    if getattr(control, "kind", None) not in {"deterministic", "semantic", "hybrid", "stateful"}:
        return f"{cid}: invalid kind {getattr(control, 'kind', None)!r}"
    applies = getattr(control, "applies_to", None)
    if applies is None or not hasattr(applies, "matches"):
        return f"{cid}: missing applies_to"
    ev = getattr(control, "evaluate", None)
    if ev is None or not inspect.iscoroutinefunction(ev):
        return f"{cid}: evaluate must be async"
    return None


CONTROL_PACKAGES = ("aegis.controls", "aegis.integrations")  # Addendum A-15


def _iter_control_modules(packages: tuple[str, ...]) -> Iterator[ModuleType]:
    for package in packages:
        yield from _iter_modules(package, recursive=True)


def discover_controls(package: str | tuple[str, ...] = CONTROL_PACKAGES) -> list[Any]:
    """All valid `CONTROLS` instances under aegis.controls and aegis.integrations (recursive);
    duplicate ids: first wins."""
    controls: list[Any] = []
    seen: dict[str, str] = {}
    packages = (package,) if isinstance(package, str) else tuple(package)
    for mod in _iter_control_modules(packages):
        items = getattr(mod, "CONTROLS", None)
        if items is None:
            continue
        try:
            items = list(items)
        except TypeError:
            _record_error(mod.__name__, "CONTROLS is not a list", kind="controls")
            continue
        for control in items:
            problem = _validate_control(control)
            if problem:
                _record_error(mod.__name__, f"invalid control skipped: {problem}", kind="controls")
                continue
            cid = control.id
            if cid in seen:
                _record_error(
                    mod.__name__, f"duplicate control id={cid} (first in {seen[cid]})",
                    kind="controls",
                )
                continue
            seen[cid] = mod.__name__
            controls.append(control)
    return controls


class ControlRegistry:
    """`ControlRegistry` protocol: all() / get(id); plus `by_id`, `modules`, `errors`."""

    def __init__(self, controls: list[Any], errors: list[dict[str, str]] | None = None) -> None:
        self.by_id: dict[str, Any] = {}
        for c in controls:
            self.by_id.setdefault(c.id, c)
        self.errors = list(errors or [])

    def all(self) -> list[Any]:
        return list(self.by_id.values())

    def get(self, control_id: str) -> Any | None:
        return self.by_id.get(control_id)

    def ids(self) -> list[str]:
        return sorted(self.by_id)

    def __len__(self) -> int:
        return len(self.by_id)

    def health(self) -> str:
        return "degraded" if self.errors else "ok"


def create_registry(rt: Any = None) -> ControlRegistry:
    """Service factory for `rt.controls` (CONTRACTS section 3.3)."""
    before = len(plugin_errors)
    controls = discover_controls()
    errors = [e for e in plugin_errors[before:]
              if e["module"].startswith(CONTROL_PACKAGES)]
    log.info("controls discovered count=%d ids=%s", len(controls),
             ",".join(sorted(c.id for c in controls)) or "-")
    return ControlRegistry(controls, errors)


# ================================================================ detectors & adapters
def discover_detectors(package: str = "aegis.redaction.detectors") -> list[Any]:
    """All `DETECTORS` instances (used by redaction-engine's engine)."""
    out: list[Any] = []
    for mod in _iter_modules(package, recursive=False):
        out.extend(getattr(mod, "DETECTORS", None) or [])
    return out


_BUILTIN_ADAPTERS = (
    "aegis.proxy.adapters.anthropic",
    "aegis.proxy.adapters.openai",
    "aegis.proxy.adapters.ollama",
)


def discover_adapters(package: str = "aegis.proxy.adapters") -> dict[str, Any]:
    """`{wire: adapter}`. Built-in adapters are loaded first so a broken third-party adapter
    cannot remove the Anthropic path; first per wire wins."""
    out: dict[str, Any] = {}
    for name in _BUILTIN_ADAPTERS:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        except Exception as exc:
            _record_error(name, exc)
            continue
        for adapter in getattr(mod, "ADAPTERS", None) or []:
            out.setdefault(getattr(adapter, "wire", "?"), adapter)
    for mod in _iter_modules(package, recursive=False):
        if mod.__name__ in _BUILTIN_ADAPTERS:
            continue
        for adapter in getattr(mod, "ADAPTERS", None) or []:
            out.setdefault(getattr(adapter, "wire", "?"), adapter)
    return out


__all__ = [
    "CONTROL_PACKAGES",
    "ControlRegistry",
    "clear_plugin_errors",
    "create_registry",
    "discover_adapters",
    "discover_controls",
    "discover_detectors",
    "discover_routers",
    "plugin_errors",
]
