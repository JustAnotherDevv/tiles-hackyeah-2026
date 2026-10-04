"""A2A message signatures (A2A-01).

Canonical string (UTF-8, ``\\n``-joined)::

    a2a-v1
    <sender id>
    <recipient id>
    <unix timestamp, integer seconds>
    <nonce>
    <in-reply-to nonce, empty for requests>
    <sha256 hex of the exact body bytes>

``signature = "v1=" + hex(HMAC-SHA256(peer key, canonical))``. Headers (lower-case on the wire):
``x-a2a-sender``, ``x-a2a-recipient``, ``x-a2a-key-id``, ``x-a2a-timestamp``, ``x-a2a-nonce``,
``x-a2a-in-reply-to``, ``x-a2a-signature``. Any change to the body, the parties, the time, the
nonce or the reply binding invalidates the signature. Pure functions, no I/O.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass

VERSION = "a2a-v1"
H_SENDER = "x-a2a-sender"
H_RECIPIENT = "x-a2a-recipient"
H_KEY_ID = "x-a2a-key-id"
H_TS = "x-a2a-timestamp"
H_NONCE = "x-a2a-nonce"
H_REPLY_TO = "x-a2a-in-reply-to"
H_SIG = "x-a2a-signature"
#: ``ctx.state[ENVELOPE_KEY][interaction.id]`` = full x-a2a-* header set (route -> A2A-01); the
#: signature and nonce stay out of ``Interaction.headers`` (audited).
ENVELOPE_KEY = "a2a.envelopes"
SIGNED_HEADERS = (H_SENDER, H_RECIPIENT, H_KEY_ID, H_TS, H_NONCE, H_REPLY_TO, H_SIG)


def body_hash(body: bytes | str | None) -> str:
    if body is None:
        body = b""
    if isinstance(body, str):
        body = body.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def canonical(sender: str, recipient: str, ts: int | str, nonce: str, in_reply_to: str,
              digest: str) -> bytes:
    return "\n".join(
        [VERSION, sender, recipient, str(ts), nonce, in_reply_to or "", digest]
    ).encode("utf-8")


def _key_bytes(key: str | bytes) -> bytes:
    return key if isinstance(key, bytes) else key.encode("utf-8")


def compute(key: str | bytes, sender: str, recipient: str, ts: int | str, nonce: str,
            in_reply_to: str, body: bytes | str | None) -> str:
    mac = hmac.new(_key_bytes(key), canonical(sender, recipient, ts, nonce, in_reply_to,
                                              body_hash(body)), hashlib.sha256)
    return "v1=" + mac.hexdigest()


def new_nonce() -> str:
    return os.urandom(16).hex()


def sign_headers(key: str | bytes, *, sender: str, recipient: str, body: bytes | str | None,
                 key_id: str = "k1", in_reply_to: str = "", ts: int | None = None,
                 nonce: str | None = None) -> dict[str, str]:
    """The ``x-a2a-*`` header set for one message."""
    ts = int(time.time()) if ts is None else int(ts)
    nonce = nonce or new_nonce()
    h = {
        H_SENDER: sender,
        H_RECIPIENT: recipient,
        H_KEY_ID: key_id,
        H_TS: str(ts),
        H_NONCE: nonce,
        H_SIG: compute(key, sender, recipient, ts, nonce, in_reply_to, body),
    }
    if in_reply_to:
        h[H_REPLY_TO] = in_reply_to
    return h


@dataclass(slots=True)
class Envelope:
    """The signed-header facts of one message (lower-case header lookup)."""

    sender: str
    recipient: str
    key_id: str
    ts: str
    nonce: str
    in_reply_to: str
    signature: str

    @classmethod
    def from_headers(cls, headers: Mapping[str, str] | None) -> Envelope | None:
        """None when the message carries no signature at all."""
        if not headers:
            return None
        low = {str(k).lower(): str(v) for k, v in headers.items()}
        if H_SIG not in low:
            return None
        return cls(
            sender=low.get(H_SENDER, ""),
            recipient=low.get(H_RECIPIENT, ""),
            key_id=low.get(H_KEY_ID, ""),
            ts=low.get(H_TS, ""),
            nonce=low.get(H_NONCE, ""),
            in_reply_to=low.get(H_REPLY_TO, ""),
            signature=low.get(H_SIG, ""),
        )


@dataclass(slots=True)
class Check:
    ok: bool
    code: str  # ok | missing_field | bad_timestamp | stale | future | bad_signature
    detail: str = ""
    age_s: float | None = None


def verify(env: Envelope, key: str | bytes, body: bytes | str | None, *, ttl_s: float,
           now: float | None = None) -> Check:
    """Signature + freshness (|now - ts| <= ttl_s). Nonce reuse is checked by the caller."""
    for name in ("sender", "recipient", "ts", "nonce", "signature"):
        if not getattr(env, name):
            return Check(False, "missing_field", f"missing x-a2a-{name}")
    try:
        ts = int(env.ts)
    except ValueError:
        return Check(False, "bad_timestamp", "x-a2a-timestamp is not an integer")
    expected = compute(key, env.sender, env.recipient, ts, env.nonce, env.in_reply_to, body)
    if not hmac.compare_digest(expected, env.signature):
        return Check(False, "bad_signature", "HMAC signature does not match the message")
    now = time.time() if now is None else now
    age = now - ts
    if age > ttl_s:
        return Check(False, "stale", f"message is {int(age)} s old (ttl {int(ttl_s)} s)", age)
    if -age > ttl_s:
        return Check(False, "future", f"timestamp {int(-age)} s in the future", age)
    return Check(True, "ok", "", age)
