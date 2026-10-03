"""Guarded access to other workstreams' public surfaces (CONTRACTS section 3.3).

Everything here degrades to a local fallback so metadata-egress works in unit tests and
before the other bundles land. Fallbacks are marked `TODO(integration)` only where the
integrator might want to verify behaviour; the public modules are preferred when present.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from collections.abc import Mapping
from fnmatch import fnmatchcase
from typing import Any

log = logging.getLogger(__name__)

_PROCESS_KEY = os.urandom(32)


# ---------------------------------------------------------------- runtime
def runtime_or_none() -> Any | None:
    """The started Runtime, or None (unit tests / before startup)."""
    try:
        from aegis.core.runtime import get_runtime  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return get_runtime()
    except Exception:
        return None


# ---------------------------------------------------------------- crypto
def hmac_hex(value: str | bytes, *, purpose: str = "fp") -> str:
    """aegis.core.crypto.hmac_hex when available, else a per-process keyed HMAC."""
    try:
        from aegis.core.crypto import hmac_hex as core_hmac  # type: ignore[import-not-found]
    except Exception:
        core_hmac = None
    if core_hmac is not None:
        try:
            return str(core_hmac(value, purpose=purpose))
        except Exception:  # pragma: no cover - defensive
            log.warning("core hmac_hex failed; using local fallback")
    env_key = os.environ.get("AEGIS_HMAC_KEY")
    key = env_key.encode() if env_key else _PROCESS_KEY
    data = value.encode() if isinstance(value, str) else value
    return hmac.new(key + b"|" + purpose.encode(), data, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- glob
def glob_match(pattern: str, value: str) -> bool:
    """Case-insensitive fnmatch (aegis.core.paths.glob_match semantics, lower-cased)."""
    return fnmatchcase(value.lower(), pattern.lower())


def any_glob(patterns: list[str] | tuple[str, ...] | None, value: str | None) -> bool:
    if not value or not patterns:
        return False
    return any(glob_match(p, value) for p in patterns)


def host_matches(patterns: list[str] | tuple[str, ...] | None, host: str | None) -> bool:
    """Domain allow-list semantics: glob match, or exact domain / subdomain of a plain entry."""
    if not host or not patterns:
        return False
    h = host.lower().rstrip(".")
    for p in patterns:
        p = p.lower().strip()
        if not p:
            continue
        if p == "*":
            return True
        if any(ch in p for ch in "*?["):
            if fnmatchcase(h, p):
                return True
            if p.startswith("*.") and h == p[2:]:
                return True
        elif h == p or h.endswith("." + p):
            return True
    return False


# ---------------------------------------------------------------- dotted paths
_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _parse_path(path: str) -> list[str | int]:
    out: list[str | int] = []
    for m in _TOKEN.finditer(path):
        if m.group(1) is not None:
            out.append(m.group(1))
        else:
            out.append(int(m.group(2)))
    return out


def get_path(obj: Any, path: str, default: Any = None) -> Any:
    try:
        from aegis.core.paths import get_path as core_get  # type: ignore[import-not-found]

        return core_get(obj, path, default)
    except ImportError:
        pass
    except Exception:
        return default
    cur = obj
    for tok in _parse_path(path):
        try:
            cur = cur[tok]
        except (KeyError, IndexError, TypeError):
            return default
    return cur


def set_path(obj: Any, path: str, value: Any) -> bool:
    """Set an existing (or new leaf dict key) path; returns False when the parent is missing."""
    try:
        from aegis.core.paths import set_path as core_set  # type: ignore[import-not-found]

        core_set(obj, path, value)
        return True
    except ImportError:
        pass
    except Exception:
        return False
    toks = _parse_path(path)
    if not toks:
        return False
    cur = obj
    for tok in toks[:-1]:
        try:
            cur = cur[tok]
        except (KeyError, IndexError, TypeError):
            return False
    last = toks[-1]
    try:
        cur[last] = value
        return True
    except (IndexError, TypeError):
        return False


def remove_path(obj: Any, path: str) -> bool:
    try:
        from aegis.core.paths import remove_path as core_remove  # type: ignore[import-not-found]

        core_remove(obj, path)
        return True
    except ImportError:
        pass
    except Exception:
        return False
    toks = _parse_path(path)
    if not toks:
        return False
    cur = obj
    for tok in toks[:-1]:
        try:
            cur = cur[tok]
        except (KeyError, IndexError, TypeError):
            return False
    try:
        del cur[toks[-1]]
        return True
    except (KeyError, IndexError, TypeError):
        return False


# ---------------------------------------------------------------- validators
def luhn_ok(digits: str) -> bool:
    try:
        from aegis.redaction.validators import luhn_ok as v  # type: ignore[import-not-found]

        return bool(v("".join(c for c in digits if c.isdigit())))
    except Exception:
        pass
    d = [int(c) for c in digits if c.isdigit()]
    if len(d) < 12:
        return False
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def card_ok(digits: str) -> bool:
    d = "".join(c for c in digits if c.isdigit())
    try:
        from aegis.redaction.validators import card_ok as v  # type: ignore[import-not-found]

        return bool(v(d))
    except Exception:
        pass
    return 13 <= len(d) <= 19 and d[0] in "3456" and luhn_ok(d)


def pesel_ok(digits: str) -> bool:
    d = "".join(c for c in digits if c.isdigit())
    try:
        from aegis.redaction.validators import pesel_ok as v  # type: ignore[import-not-found]

        return bool(v(d))
    except Exception:
        pass
    if len(d) != 11:
        return False
    w = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    s = sum(int(d[i]) * w[i] for i in range(10))
    if (10 - s % 10) % 10 != int(d[10]):
        return False
    month = int(d[2:4]) % 20
    day = int(d[4:6])
    return 1 <= month <= 12 and 1 <= day <= 31


def iban_ok(s: str) -> bool:
    try:
        from aegis.redaction.validators import iban_ok as v  # type: ignore[import-not-found]

        return bool(v(s))
    except Exception:
        pass
    t = re.sub(r"\s+", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", t):
        return False
    r = t[4:] + t[:4]
    num = "".join(str(int(c, 36)) for c in r)
    return int(num) % 97 == 1


# ---------------------------------------------------------------- side channels
def inc_metric(name: str, labels: Mapping[str, str] | None = None, value: float = 1.0) -> None:
    rt = runtime_or_none()
    if rt is None:
        return
    try:
        rt.metrics.inc(name, labels, value)
    except Exception:
        log.debug("metric inc failed name=%s", name)


def publish(event: str, data: dict[str, Any], rt: Any | None = None) -> None:
    rt = rt or runtime_or_none()
    if rt is None:
        return
    try:
        rt.bus.publish(event, data)
    except Exception:
        log.debug("bus publish failed event=%s", event)
