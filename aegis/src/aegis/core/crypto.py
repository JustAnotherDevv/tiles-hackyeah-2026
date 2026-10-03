"""HMAC fingerprints with a persistent key (public surface, CONTRACTS section 3.3).

`hmac_hex(value, purpose=...)` = HMAC-SHA256(key, purpose + b"\\x00" + value) hex. Key =
`AEGIS_HMAC_KEY` (utf-8) or 32 random bytes stored once in `<data_dir>/keys/hmac.key` (0600),
created lazily on first use (no import-time side effects). Use it for every fingerprint of a
sensitive value (approval fingerprints, audit value fingerprints, agent key hashes).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
from pathlib import Path

_lock = threading.Lock()
_key: bytes | None = None
_key_source: str | None = None
_data_dir: Path | None = None
_configured_key: str | None = None


def configure(*, data_dir: Path | str | None = None, key: str | None = None) -> None:
    """Called by the Runtime with its Settings (so tests with a temp data_dir stay hermetic).
    Resets the cached key when the location changes."""
    global _data_dir, _configured_key, _key, _key_source
    with _lock:
        new_dir = Path(data_dir) if data_dir is not None else None
        if new_dir != _data_dir or key != _configured_key:
            _data_dir, _configured_key = new_dir, key
            _key, _key_source = None, None


def _key_file() -> Path:
    if _data_dir is not None:
        return _data_dir / "keys" / "hmac.key"
    from aegis.settings import get_settings

    return Path(get_settings().data_dir) / "keys" / "hmac.key"


def _load_key() -> bytes:
    global _key, _key_source
    if _key is not None:
        return _key
    with _lock:
        if _key is not None:
            return _key
        env_key = _configured_key or os.environ.get("AEGIS_HMAC_KEY")
        if not env_key and _data_dir is None:
            try:
                from aegis.settings import get_settings

                env_key = get_settings().hmac_key
            except Exception:
                env_key = None
        if env_key:
            _key, _key_source = env_key.encode("utf-8"), "env"
            return _key
        path = _key_file()
        try:
            data = path.read_bytes()
            if len(data) >= 16:
                _key, _key_source = data, str(path)
                return _key
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        data = os.urandom(32)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        _key, _key_source = data, str(path)
        return _key


def hmac_hex(value: str | bytes, *, purpose: str = "fp") -> str:
    """Stable keyed fingerprint (64 hex chars). Differs per `purpose`."""
    raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    msg = purpose.encode("utf-8") + b"\x00" + raw
    return hmac.new(_load_key(), msg, hashlib.sha256).hexdigest()


def reset_key_cache() -> None:
    """Tests only: forget the cached key (next call re-reads env / key file)."""
    global _key, _key_source
    with _lock:
        _key, _key_source = None, None


def key_source() -> str | None:
    return _key_source


__all__ = ["configure", "hmac_hex", "key_source", "reset_key_cache"]
