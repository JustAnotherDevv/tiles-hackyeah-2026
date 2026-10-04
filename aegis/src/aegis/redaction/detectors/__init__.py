"""Auto-discovered detectors. Each module exposes ``DETECTORS: list[Detector]``.

Family modules are CoreViews over the shared Tier-D scan (``aegis.redaction.scan``); a new
non-core detector is just a module with ``DETECTORS = [obj]`` where ``obj`` has ``id``,
``entity``, ``data_class``, ``category``, ``languages`` and a pure ``detect(text) -> list[Span]``.
"""

from __future__ import annotations

from typing import Any

FAMILIES = (
    "pci",
    "pl_ids",
    "banking",
    "contact",
    "personal",
    "crypto",
    "secrets",
    "network",
    "metadata",
)


def builtin_detectors() -> list[Any]:
    """Fallback when core discovery is unavailable: import our own family modules."""
    import importlib

    out: list[Any] = []
    for name in FAMILIES:
        try:
            mod = importlib.import_module(f"{__name__}.{name}")
        except Exception:  # pragma: no cover - defensive
            continue
        out.extend(getattr(mod, "DETECTORS", None) or [])
    return out
