"""Parse the `Server-Timing` header (`aegis`, `ctl`, `upstream`, `total`, `ctl-<ID>`)."""

from __future__ import annotations

import re

_ENTRY = re.compile(r"\s*([A-Za-z0-9_.\-]+)\s*((?:;[^,]*)?)")
_DUR = re.compile(r";\s*dur\s*=\s*\"?([0-9.eE+\-]+)\"?")


def parse(header: str | None) -> dict[str, float]:
    """`aegis;dur=1.2;desc="x", ctl;dur=0.4, ctl-DLP-01;dur=0.2` -> {"aegis": 1.2, "ctl": 0.4, "ctl-DLP-01": 0.2}."""
    out: dict[str, float] = {}
    if not header:
        return out
    for part in _split(header):
        m = _ENTRY.match(part)
        if not m:
            continue
        name, params = m.group(1), m.group(2) or ""
        d = _DUR.search(params)
        if d:
            try:
                out[name] = float(d.group(1))
            except ValueError:
                continue
    return out


def _split(header: str) -> list[str]:
    """Split on commas that are not inside quoted desc values."""
    parts, buf, q = [], [], False
    for ch in header:
        if ch == '"':
            q = not q
        if ch == "," and not q:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def controls(timings: dict[str, float]) -> dict[str, float]:
    """Only the per-control entries, keyed by control id."""
    return {k[4:]: v for k, v in timings.items() if k.startswith("ctl-")}


__all__ = ["controls", "parse"]
