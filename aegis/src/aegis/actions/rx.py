"""Regex compilation for policy-supplied patterns.

Policy regexes (``actions[].args_match``, ``EXE-01 deny_patterns`` ...) are written by judges
live and run against attacker-controlled tool args / egress bodies, so they are compiled with
RE2 **only** (linear time, no ReDoS). There is no stdlib ``re`` fallback: a pattern RE2 cannot
express (look-arounds, backrefs) is rejected at policy validation time
(``aegis.policy.validate.compile_re2``) and, should one ever reach runtime, it becomes a
never-matching object recorded in ``INVALID_PATTERNS`` (never a backtracking ``re`` search).
Stdlib ``re`` is used only when the ``google-re2`` wheel itself is missing (a broken install,
logged as an error), never per pattern.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Protocol

log = logging.getLogger(__name__)

try:  # google-re2 (import name `re2`)
    import re2 as _re2  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - wheel missing
    _re2 = None


class Pattern(Protocol):
    def search(self, text: str) -> Any: ...


class _Never:
    """Never-matching stand-in for an invalid pattern."""

    def __init__(self, pattern: str, error: str) -> None:
        self.pattern = pattern
        self.error = error

    def search(self, text: str) -> None:
        return None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<never-match {self.pattern!r}: {self.error}>"


INVALID_PATTERNS: dict[str, str] = {}


@lru_cache(maxsize=1024)
def compile_rx(pattern: str) -> Pattern:
    """Compile ``pattern`` with RE2 only; RE2-rejected or invalid -> never-match (logged)."""
    if _re2 is None:  # pragma: no cover - wheel missing (pyproject pins google-re2)
        return _compile_stdlib(pattern)
    if _uses_lookaround(pattern):
        # RE2 rejects these anyway; skip the call to avoid absl stderr noise.
        return _never(pattern, "RE2 rejected pattern: look-around/backreference not supported")
    try:
        return _re2.compile(pattern)
    except Exception as exc:
        return _never(pattern, f"RE2 rejected pattern: {exc}")


def _never(pattern: str, error: str) -> _Never:
    INVALID_PATTERNS[pattern] = error
    log.error("policy regex not RE2-compatible - ignored (never matches) pattern=%r error=%s",
              pattern[:80], error)
    return _Never(pattern, error)


_WARNED_NO_RE2 = False


def _compile_stdlib(pattern: str) -> Pattern:  # pragma: no cover - wheel missing
    global _WARNED_NO_RE2
    if not _WARNED_NO_RE2:
        _WARNED_NO_RE2 = True
        log.error("google-re2 not importable - policy regexes use stdlib re (ReDoS-prone)")
    if _uses_lookaround(pattern):
        return _never(pattern, "RE2 rejected pattern: look-around/backreference not supported")
    try:
        return re.compile(pattern)
    except re.error as exc:
        return _never(pattern, str(exc))


def _uses_lookaround(pattern: str) -> bool:
    return any(tok in pattern for tok in ("(?=", "(?!", "(?<=", "(?<!", "(?P=", "\\1", "\\2"))


def rx_search(pattern: str, value: Any) -> bool:
    """True if ``pattern`` searches successfully in ``str(value)`` (None never matches)."""
    if value is None:
        return False
    text = value if isinstance(value, str) else _stringify(value)
    return compile_rx(pattern).search(text) is not None


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple):
        return ", ".join(_stringify(v) for v in value)
    return str(value)
