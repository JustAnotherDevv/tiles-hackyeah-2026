"""Learned identifiers per session (usernames / git names seen in metadata).

Stored in `rt.sessions.get(session_id).data["metadata-egress"]["identifiers"]` (memory only,
never logged); a bounded in-process fallback keeps unit tests and runtime-less use working.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable

from aegis.egress import compat

_LOCAL: OrderedDict[str, list[str]] = OrderedDict()
_LOCAL_MAX = 512


def _store(session_id: str) -> list[str]:
    rt = compat.runtime_or_none()
    if rt is not None:
        try:
            data = rt.sessions.get(session_id).data
            ns = data.setdefault("metadata-egress", {})
            return ns.setdefault("identifiers", [])
        except Exception:
            pass
    lst = _LOCAL.get(session_id)
    if lst is None:
        lst = []
        _LOCAL[session_id] = lst
        while len(_LOCAL) > _LOCAL_MAX:
            _LOCAL.popitem(last=False)
    else:
        _LOCAL.move_to_end(session_id)
    return lst


def get(session_id: str) -> list[str]:
    return list(_store(session_id))


def learn(session_id: str, values: Iterable[str], *, max_identifiers: int = 32) -> int:
    """Add new identifiers (set only grows, bounded). Returns how many were added."""
    store = _store(session_id)
    added = 0
    low = {v.lower() for v in store}
    for v in values:
        if len(store) >= max_identifiers:
            break
        if v.lower() not in low:
            store.append(v)
            low.add(v.lower())
            added += 1
    return added


def reset_local() -> None:
    _LOCAL.clear()
