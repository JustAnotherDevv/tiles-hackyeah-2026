"""Ed25519 detached-signature verification for the threat feed (CONTRACTS section 4.7).

Signatures are base64 Ed25519 over the **exact file bytes** (`latest.json.sig`,
`bundle-NNNNNN.json.sig`, `seed_bundle.json.sig`). The gateway trusts only the pinned
`config/feeds/feed_pubkey.b64`; `key_id` = first 8 hex chars of sha256(raw public key).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path


class FeedRejected(Exception):
    """A feed pointer or bundle failed verification; `reason` is shown to operators."""

    def __init__(self, reason: str, *, serial_attempted: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.serial_attempted = serial_attempted


def key_id(pub: bytes) -> str:
    """hex8: first 8 hex chars of sha256(raw 32-byte public key)."""
    return hashlib.sha256(pub).hexdigest()[:8]


def parse_pubkey(text: str) -> bytes:
    """Accept base64 (preferred) or hex of the raw 32-byte key; '#' comment lines ignored."""
    raw = "".join(ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#"))
    key: bytes | None = None
    if len(raw) == 64:
        try:
            key = binascii.unhexlify(raw)
        except binascii.Error:
            key = None
    if key is None:
        try:
            key = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("public key is neither base64 nor hex") from None
    if len(key) != 32:
        raise ValueError(f"public key must be 32 bytes, got {len(key)}")
    return key


def load_pubkey(path: str | Path) -> bytes:
    return parse_pubkey(Path(path).read_text(encoding="utf-8"))


def verify_detached(data: bytes, sig_b64: str | bytes, pub: bytes, *, what: str = "data") -> None:
    """Raise FeedRejected unless `sig_b64` is a valid Ed25519 signature over `data` by `pub`."""
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey

    if isinstance(sig_b64, bytes):
        sig_b64 = sig_b64.decode("ascii", "replace")
    try:
        sig = base64.b64decode(sig_b64.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise FeedRejected(f"bad_signature: {what}.sig is not base64") from None
    if len(sig) != 64:
        raise FeedRejected(f"bad_signature: {what}.sig has wrong length {len(sig)}")
    try:
        VerifyKey(pub).verify(data, sig)
    except BadSignatureError:
        raise FeedRejected(
            f"bad_signature: {what} does not verify with the pinned key {key_id(pub)}"
        ) from None
    except Exception as e:  # malformed key etc.
        raise FeedRejected(f"bad_signature: {what}: {type(e).__name__}") from None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
