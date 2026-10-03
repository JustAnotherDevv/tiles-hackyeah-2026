"""Ed25519 signing for the threat-intel feed service (PyNaCl only).

The private seed lives only in `<state>/keys/feed_signing.key` (base64, chmod 600) and is never
served or logged. Detached signatures are base64 over the exact file bytes.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from aegis.feed.verify import FeedRejected, key_id, parse_pubkey, verify_detached

__all__ = ["FeedRejected", "generate", "key_id", "load_signing_key", "public_key", "sign_detached",
           "verify_detached", "write_keypair"]

PRIVATE_NAME = "feed_signing.key"
PUBLIC_NAME = "feed_public.b64"


def generate() -> tuple[bytes, bytes]:
    """New keypair -> (32-byte seed, 32-byte raw public key)."""
    from nacl.signing import SigningKey

    sk = SigningKey.generate()
    return bytes(sk), bytes(sk.verify_key)


def public_key(seed: bytes) -> bytes:
    from nacl.signing import SigningKey

    return bytes(SigningKey(seed).verify_key)


def sign_detached(data: bytes, seed: bytes) -> str:
    """Base64 Ed25519 signature over `data`."""
    from nacl.signing import SigningKey

    return base64.b64encode(SigningKey(seed).sign(data).signature).decode("ascii")


def keys_dir(state: Path) -> Path:
    return Path(state) / "keys"


def write_keypair(state: Path, seed: bytes, pub: bytes) -> None:
    d = keys_dir(state)
    d.mkdir(parents=True, exist_ok=True)
    priv = d / PRIVATE_NAME
    tmp = priv.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(base64.b64encode(seed).decode("ascii") + "\n")
    os.replace(tmp, priv)
    os.chmod(priv, 0o600)
    (d / PUBLIC_NAME).write_text(base64.b64encode(pub).decode("ascii") + "\n", encoding="utf-8")


def load_signing_key(state: Path) -> bytes | None:
    """The 32-byte seed from `<state>/keys/feed_signing.key`, or None when missing."""
    p = keys_dir(state) / PRIVATE_NAME
    if not p.exists():
        return None
    seed = base64.b64decode(p.read_text(encoding="utf-8").strip(), validate=True)
    if len(seed) != 32:
        raise ValueError(f"{p}: expected a 32-byte seed")
    return seed


def load_public(state: Path) -> bytes | None:
    p = keys_dir(state) / PUBLIC_NAME
    return parse_pubkey(p.read_text(encoding="utf-8")) if p.exists() else None
