"""Guarded access to core-gateway public surfaces (CONTRACTS section 3.3).

approvals-engine must import and work before core-gateway lands, so every cross-workstream import
is wrapped: `aegis.core.crypto.hmac_hex` falls back to a process-local HMAC key (WARNING once),
`aegis.core.paths.glob_match` falls back to `fnmatch.fnmatchcase`.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_LOCAL_KEY: bytes | None = None
_warned = False


def _local_hmac(value: str | bytes, *, purpose: str = "fp") -> str:
    global _LOCAL_KEY, _warned
    if _LOCAL_KEY is None:
        env_key = os.environ.get("AEGIS_HMAC_KEY")
        _LOCAL_KEY = env_key.encode() if env_key else os.urandom(32)
    if not _warned:
        _warned = True
        log.warning("aegis.core.crypto unavailable; approvals use a process-local hmac key")
    data = value.encode() if isinstance(value, str) else value
    return hmac.new(_LOCAL_KEY, purpose.encode() + b"\x00" + data, hashlib.sha256).hexdigest()


def hmac_hex(value: str | bytes, *, purpose: str = "fp") -> str:
    """HMAC-SHA256 with the persistent gateway key (core-gateway), else a local fallback."""
    try:
        from aegis.core.crypto import hmac_hex as core_hmac_hex  # type: ignore[import-not-found]
    except Exception:  # TODO(integration): core-gateway crypto not landed yet
        return _local_hmac(value, purpose=purpose)
    try:
        return core_hmac_hex(value, purpose=purpose)
    except Exception:  # pragma: no cover - defensive
        log.exception("core hmac_hex failed; using local fallback")
        return _local_hmac(value, purpose=purpose)


def glob_match(pattern: str, value: str) -> bool:
    """`fnmatchcase` glob (`*` matches anything), via aegis.core.paths when available."""
    try:
        from aegis.core.paths import glob_match as core_glob  # type: ignore[import-not-found]
    except Exception:  # TODO(integration): core-gateway paths not landed yet
        return fnmatch.fnmatchcase(value, pattern)
    try:
        return bool(core_glob(pattern, value))
    except Exception:  # pragma: no cover - defensive
        return fnmatch.fnmatchcase(value, pattern)


def iglob_match(pattern: str, value: str) -> bool:
    """Case-insensitive glob (labels such as sensitivity=confidential vs CONFIDENTIAL)."""
    return fnmatch.fnmatchcase(value.lower(), pattern.lower())


def get_runtime_or_none() -> Any | None:
    try:
        from aegis.core.runtime import get_runtime  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return get_runtime()
    except Exception:
        return None


def settings_of(rt: Any) -> Any | None:
    settings = getattr(rt, "settings", None)
    if settings is not None:
        return settings
    try:
        from aegis.settings import get_settings

        return get_settings()
    except Exception:  # pragma: no cover - defensive
        return None


def test_mode(rt: Any) -> bool:
    settings = settings_of(rt)
    if settings is not None and getattr(settings, "test_mode", False):
        return True
    return os.environ.get("AEGIS_TEST_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
