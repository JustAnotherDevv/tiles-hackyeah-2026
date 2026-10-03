"""Stdlib-only media metadata walkers (JPEG, PNG, PDF, Office). Owner: metadata-egress."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SanitizeResult:
    data: bytes
    kind: str
    changed: bool = False
    removed: list[str] = field(default_factory=list)
    unsupported: bool = False
    reason: str = ""
    found: list[str] = field(default_factory=list)  # metadata kinds present (inspect)
    details: dict[str, object] = field(default_factory=dict)  # names only, never values
