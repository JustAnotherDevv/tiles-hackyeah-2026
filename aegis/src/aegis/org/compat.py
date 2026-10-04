"""Guarded access to core-gateway public surfaces with local fallbacks (CONTRACTS section 3.3).

Every lookup is lazy (at call time), so org-rbac works whether or not core-gateway's modules
have landed yet. Fallbacks implement the same semantics as the contract.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import logging
import os
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_local_key: bytes | None = None


def _local_hmac_key() -> bytes:  # TODO(integration): only used when aegis.core.crypto is missing
    global _local_key
    if _local_key is not None:
        return _local_key
    env = os.environ.get("AEGIS_HMAC_KEY")
    if env:
        _local_key = env.encode("utf-8")
        return _local_key
    data_dir = Path(os.environ.get("AEGIS_DATA_DIR", "data"))
    path = data_dir / "keys" / "hmac.key"
    try:
        data = path.read_bytes()
        if len(data) >= 16:
            _local_key = data
            return data
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    data = os.urandom(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    _local_key = data
    return data


def hmac_hex(value: str | bytes, *, purpose: str = "fp") -> str:
    """`aegis.core.crypto.hmac_hex`, or the identical local algorithm."""
    try:
        from aegis.core.crypto import hmac_hex as core_hmac
    except ImportError:  # pragma: no cover - core-gateway always ships crypto
        raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        msg = purpose.encode("utf-8") + b"\x00" + raw
        return _hmac.new(_local_hmac_key(), msg, hashlib.sha256).hexdigest()
    return core_hmac(value, purpose=purpose)


def glob_match(pattern: str | None, value: str | None) -> bool:
    """fnmatchcase glob; `*` matches anything (incl. empty / None values)."""
    if pattern is None:
        return False
    if pattern == "*":
        return True
    if value is None:
        return False
    return fnmatchcase(value, pattern)


def glob_any(patterns: list[str] | tuple[str, ...] | None, value: str | None) -> bool:
    return any(glob_match(p, value) for p in patterns or ())


def first_glob(patterns: list[str] | tuple[str, ...] | None, value: str | None) -> str | None:
    for p in patterns or ():
        if glob_match(p, value):
            return p
    return None


def api_error(status: int, type_: str, message: str, **fields: Any) -> Any:
    """CONTRACTS section 5.3 envelope as a JSONResponse (core-gateway's when available)."""
    try:
        from aegis.core.errors import api_error as core_api_error
    except ImportError:
        core_api_error = None
    if core_api_error is not None:
        try:
            return core_api_error(status, type_, message, **fields)
        except Exception:  # pragma: no cover - defensive
            log.warning("core api_error failed; using local envelope", exc_info=True)
    from fastapi.responses import JSONResponse

    inner: dict[str, Any] = {
        "type": type_,
        "message": message,
        "control_id": None,
        "decision_id": None,
        "approval_id": None,
        "required_role": None,
        "expires_at": None,
        "scope": None,
        "retry_after_s": None,
    }
    for key, val in fields.items():
        inner[key] = val.isoformat() if hasattr(val, "isoformat") else val
    return JSONResponse({"error": inner}, status_code=status)


async def get_rt(request: Any) -> Any:
    """`request.app.state.rt` (tests mount routers on a bare app), else `aegis.core.deps.get_rt`."""
    rt = getattr(getattr(request.app, "state", None), "rt", None)
    if rt is not None:
        return rt
    try:
        from aegis.core.deps import get_rt as core_get_rt
    except ImportError:
        core_get_rt = None
    if core_get_rt is not None:
        return await core_get_rt(request)
    try:
        from aegis.core.runtime import get_runtime

        return get_runtime()
    except Exception as exc:  # pragma: no cover - runtime not started
        raise RuntimeError("aegis runtime not available") from exc


def current_runtime() -> Any | None:
    """Process runtime for controls (they receive no `rt`), or None before startup."""
    try:
        from aegis.core.runtime import get_runtime
    except ImportError:
        return None
    try:
        return get_runtime()
    except Exception:
        return None


def setting(rt: Any, name: str, default: Any = None) -> Any:
    settings = getattr(rt, "settings", None)
    if settings is None:
        return default
    value = getattr(settings, name, default)
    return default if value is None else value


__all__ = [
    "api_error",
    "current_runtime",
    "first_glob",
    "get_rt",
    "glob_any",
    "glob_match",
    "hmac_hex",
    "setting",
]
