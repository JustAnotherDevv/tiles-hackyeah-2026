"""Regex compilation for policy-supplied patterns.

Policy regexes (``actions[].args_match``, ``EXE-01 deny_patterns`` ...) are written by judges
live, so they are compiled with RE2 (linear time, no ReDoS) when the ``google-re2`` wheel is
available. Patterns RE2 cannot express (look-arounds, backrefs) fall back to Python ``re``
with a warning. An invalid pattern never crashes a request: it becomes a never-matching
object and is reported once.
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
    """Compile ``pattern`` with RE2, falling back to ``re``; invalid -> never-match."""
    if _re2 is not None and _re2_safe(pattern):
        try:
            return _re2.compile(pattern)
        except Exception:
            pass  # unsupported construct; try the stdlib engine below
    try:
        compiled = re.compile(pattern)
        if _re2 is not None and _uses_lookaround(pattern):
            log.warning("regex uses constructs RE2 cannot run; using re pattern=%r", pattern[:80])
        return compiled
    except re.error as exc:
        INVALID_PATTERNS[pattern] = str(exc)
        log.warning("invalid regex ignored (never matches) pattern=%r error=%s", pattern[:80], exc)
        return _Never(pattern, str(exc))


def _uses_lookaround(pattern: str) -> bool:
    return any(tok in pattern for tok in ("(?=", "(?!", "(?<=", "(?<!", "(?P=", "\\1", "\\2"))


def _re2_safe(pattern: str) -> bool:
    """Skip RE2 for patterns it rejects anyway (avoids noisy absl stderr logging)."""
    return not _uses_lookaround(pattern)


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
