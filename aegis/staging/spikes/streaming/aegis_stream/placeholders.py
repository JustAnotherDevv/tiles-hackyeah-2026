"""Placeholder syntax, vault interface and batch (non-streaming) rehydration.

Placeholders look like ``[EMAIL_1]``, ``[PL_PESEL_2]`` or, with opaque ids,
``[PERSON_k7f3]``.  Models sometimes change case or spacing, so matching is
tolerant (``[email_1]``, ``[ PERSON 1 ]``, ``[EMAIL-1]``).  Anything the
vault did not issue (``[Step 1]``, ``arr[0]``, ``[EMAIL_9]`` invented by the
model) is left untouched.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from .jsonlex import json_escape

__all__ = [
    "PLACEHOLDER_RE",
    "PARTIAL_PLACEHOLDER_RE",
    "MAX_PLACEHOLDER_LEN",
    "Vault",
    "MappingVault",
    "canonical_key",
    "rehydrate_text",
    "rehydrate_json_value",
]

#: tolerant full placeholder: type, separator, id (digits or opaque alnum)
PLACEHOLDER_RE = re.compile(r"\[\s*([A-Za-z][A-Za-z0-9_]*?)[_\- ]([A-Za-z0-9]{1,12})\s*\]")
#: a possible *incomplete* placeholder at the end of the text (hold it back)
PARTIAL_PLACEHOLDER_RE = re.compile(r"\[\s*[A-Za-z0-9_\- ]{0,48}\Z")
MAX_PLACEHOLDER_LEN = 64


def canonical_key(ph_type: str, ph_id: str) -> str:
    """Canonical vault key: ``[TYPE_ID]`` upper-cased."""
    return f"[{ph_type.upper()}_{ph_id.upper()}]"


@runtime_checkable
class Vault(Protocol):
    """What the stream layer needs from the per-session vault.

    ``resolve`` receives the canonical, upper-cased key (``[PL_PESEL_1]``)
    and returns the original value, or ``None`` if this session never issued
    that placeholder (never rehydrate foreign placeholders).
    """

    def resolve(self, key: str) -> str | None: ...


class MappingVault:
    """Simple dict-backed vault (tests, demo, or an adapter for a real one)."""

    __slots__ = ("_m",)

    def __init__(self, mapping: Mapping[str, str] | Iterable[tuple[str, str]] = ()) -> None:
        items = mapping.items() if isinstance(mapping, Mapping) else mapping
        self._m: dict[str, str] = {}
        for k, v in items:
            m = PLACEHOLDER_RE.fullmatch(k)
            if not m:
                raise ValueError(f"not a placeholder: {k!r}")
            self._m[canonical_key(m.group(1), m.group(2))] = v

    def resolve(self, key: str) -> str | None:
        return self._m.get(key)

    def values(self) -> list[str]:
        return list(self._m.values())

    def __len__(self) -> int:
        return len(self._m)

    def __bool__(self) -> bool:  # an empty vault still disables nothing by itself
        return True


def rehydrate_text(text: str, vault: Vault, *, json_string: bool = False) -> tuple[str, int]:
    """Replace every vault-issued placeholder in ``text``.

    With ``json_string=True`` the values are JSON-escaped (``text`` is the
    *content* of a JSON string literal).  Returns ``(text, n_replaced)``.
    """
    if "[" not in text:
        return text, 0
    count = 0

    def rep(m: re.Match[str]) -> str:
        nonlocal count
        val = vault.resolve(canonical_key(m.group(1), m.group(2)))
        if val is None:
            return m.group(0)
        count += 1
        return json_escape(val) if json_string else val

    return PLACEHOLDER_RE.sub(rep, text), count


def rehydrate_json_value(obj: Any, vault: Vault) -> tuple[Any, int]:
    """Rehydrate every string leaf (and key) of an already-parsed JSON value."""
    if isinstance(obj, str):
        return rehydrate_text(obj, vault)
    if isinstance(obj, list):
        total = 0
        out_list = []
        for v in obj:
            nv, c = rehydrate_json_value(v, vault)
            total += c
            out_list.append(nv)
        return out_list, total
    if isinstance(obj, dict):
        total = 0
        out_dict = {}
        for k, v in obj.items():
            nk, c1 = rehydrate_text(k, vault) if isinstance(k, str) else (k, 0)
            nv, c2 = rehydrate_json_value(v, vault)
            total += c1 + c2
            out_dict[nk] = nv
        return out_dict, total
    return obj, 0
