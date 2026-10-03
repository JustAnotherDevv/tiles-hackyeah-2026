"""Plug-in auto-discovery (CONTRACTS section 2.1).

SCAFFOLD STUB - owned by core-gateway, safe to extend/replace. Working discovery for routers,
controls, redaction detectors and wire adapters. Every module is imported inside
try/except; failures are logged and collected in `plugin_errors` and never stop the gateway.
Modules whose last name segment starts with `_` are skipped.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Iterator
from types import ModuleType
from typing import Any

log = logging.getLogger(__name__)

#: {"module": "aegis.api.routes.foo", "error": "ImportError: ..."} for every failed import.
plugin_errors: list[dict[str, str]] = []


def _record_error(module: str, exc: BaseException) -> None:
    log.error("plugin import failed module=%s error=%s", module, exc, exc_info=exc)
    plugin_errors.append({"module": module, "error": f"{type(exc).__name__}: {exc}"})


def _iter_modules(package: str, *, recursive: bool) -> Iterator[ModuleType]:
    try:
        pkg = importlib.import_module(package)
    except Exception as exc:  # pragma: no cover - only when the package itself is broken
        _record_error(package, exc)
        return
    path = getattr(pkg, "__path__", None)
    if path is None:
        return
    walker = (
        pkgutil.walk_packages(path, prefix=f"{package}.", onerror=lambda name: None)
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


def discover_routers(package: str = "aegis.api.routes") -> list[ModuleType]:
    """Route modules exposing `router`, sorted by (ORDER, module name)."""
    found: list[tuple[int, str, ModuleType]] = []
    for mod in _iter_modules(package, recursive=False):
        if getattr(mod, "router", None) is None:
            log.warning("route module without `router` skipped module=%s", mod.__name__)
            continue
        found.append((int(getattr(mod, "ORDER", 100)), mod.__name__, mod))
    return [m for _, _, m in sorted(found, key=lambda t: (t[0], t[1]))]


def discover_controls(package: str = "aegis.controls") -> list[Any]:
    """All `CONTROLS` instances under aegis.controls (recursive); duplicate ids: first wins."""
    controls: list[Any] = []
    seen: dict[str, str] = {}
    for mod in _iter_modules(package, recursive=True):
        for control in getattr(mod, "CONTROLS", None) or []:
            cid = getattr(control, "id", "")
            if not cid:
                log.error("control without id skipped module=%s", mod.__name__)
                continue
            if cid in seen:
                log.error(
                    "duplicate control id=%s module=%s first=%s", cid, mod.__name__, seen[cid]
                )
                continue
            seen[cid] = mod.__name__
            controls.append(control)
    return controls


class ControlRegistry:
    """Minimal `ControlRegistry` (protocols.ControlRegistry): all() / get(id)."""

    def __init__(self, controls: list[Any]) -> None:
        self.by_id: dict[str, Any] = {c.id: c for c in controls}

    def all(self) -> list[Any]:
        return list(self.by_id.values())

    def get(self, control_id: str) -> Any | None:
        return self.by_id.get(control_id)


def create_registry(rt: Any = None) -> ControlRegistry:
    """Service factory for `rt.controls` (CONTRACTS section 3.3)."""
    return ControlRegistry(discover_controls())


def discover_detectors(package: str = "aegis.redaction.detectors") -> list[Any]:
    """All `DETECTORS` instances (used by redaction-engine's engine)."""
    out: list[Any] = []
    for mod in _iter_modules(package, recursive=False):
        out.extend(getattr(mod, "DETECTORS", None) or [])
    return out


def discover_adapters(package: str = "aegis.proxy.adapters") -> dict[str, Any]:
    """`{wire: adapter}` from every module's `ADAPTERS` list; first per wire wins."""
    out: dict[str, Any] = {}
    for mod in _iter_modules(package, recursive=False):
        for adapter in getattr(mod, "ADAPTERS", None) or []:
            out.setdefault(getattr(adapter, "wire", "?"), adapter)
    return out
