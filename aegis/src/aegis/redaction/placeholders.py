"""Placeholders, session vault and (streaming) rehydration - PUBLIC SURFACE (plan 03 gap 4.2).

Merged from ``staging/pii/placeholders.py`` (vault) and
``staging/spikes/streaming/aegis_stream/placeholders.py`` (tolerant regex, streaming), so the
core-gateway streaming path and the engine share ONE placeholder grammar.

Placeholders look like ``[EMAIL_1]``, ``[PESEL_2]``, ``[PL_ID_CARD_1]`` or, with opaque ids,
``[PERSON_K7F3]``. Models sometimes change case or spacing, so matching is tolerant
(``[email_1]``, ``[ PESEL 1 ]``, ``[EMAIL-1]``). Anything the vault did not issue
(``[Step 1]``, ``arr[0]``, ``[EMAIL_9]`` invented by the model, ``[REDACTED:CVV]``) is left
untouched.

Invariants enforced here (not left to policy):
  * SAD (CVV, TRACK_DATA) is NEVER vaulted: ``Vault.put`` raises ``ValueError``.
  * The vault is in-memory only, per session, numbered per entity by first appearance
    (``[PESEL_1]``), stable per canonical value, capped (``VaultFull``) and idle-TTL'd.
  * Values are never logged; ``stats()`` returns counts only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from .entities import IRREVERSIBLE

__all__ = [
    "MAX_PLACEHOLDER_LEN",
    "PARTIAL_PLACEHOLDER_RE",
    "PLACEHOLDER_RE",
    "MappingVault",
    "StreamRehydrator",
    "Vault",
    "VaultFull",
    "VaultLike",
    "VaultStore",
    "canonical_key",
    "canonicalize",
    "irreversible",
    "json_escape",
    "rehydrate_json_value",
    "rehydrate_text",
]

#: tolerant full placeholder: type, separator, id (digits or opaque alnum)
PLACEHOLDER_RE = re.compile(r"\[\s*([A-Za-z][A-Za-z0-9_]*?)[_\- ]([A-Za-z0-9]{1,12})\s*\]")
#: a possible *incomplete* placeholder at the end of the text (hold it back while streaming)
PARTIAL_PLACEHOLDER_RE = re.compile(r"\[\s*[A-Za-z0-9_\- ]{0,48}\Z")
#: longest text the stream rehydrator ever holds back
MAX_PLACEHOLDER_LEN = 64
#: strict form issued by this vault (used to detect placeholder-bearing text)
ISSUED_RE = re.compile(r"\[[A-Z][A-Z0-9_]*_[A-Z0-9]{1,12}\]")


def canonical_key(ph_type: str, ph_id: str) -> str:
    """Canonical vault key ``[TYPE_ID]`` upper-cased (type AND id, like aegis_stream)."""
    return f"[{ph_type.upper()}_{ph_id.upper()}]"


def irreversible(entity: str) -> str:
    """Irreversible marker, e.g. ``[REDACTED:CVV]`` (CONTRACTS section 3.4)."""
    return f"[REDACTED:{entity}]"


def json_escape(value: str) -> str:
    """Escape ``value`` for insertion *inside* a JSON string literal."""
    return json.dumps(value, ensure_ascii=False)[1:-1]


_DIGIT_ENTITIES = frozenset({"PAN", "PESEL", "NIP", "REGON", "CVV", "CARD_EXPIRY"})


def canonicalize(entity: str, raw: str) -> str:
    """Canonical (vault key / fingerprint input) form of a raw value.

    PAN/PESEL/NIP/REGON -> digits; IBAN/ID card/passport -> upper alnum; PHONE -> '+digits' for
    international numbers, else digits; EMAIL -> lower; others exact (stripped).
    """
    s = raw.strip()
    if entity in _DIGIT_ENTITIES:
        d = "".join(c for c in s if c.isdigit())
        if entity == "NIP" or not d:
            return d or s
        return d
    if entity in ("IBAN", "PL_ID_CARD", "PASSPORT"):
        return "".join(c for c in s if c.isalnum()).upper()
    if entity == "PHONE":
        d = "".join(c for c in s if c.isdigit())
        if s.startswith("+"):
            return "+" + d
        if s.startswith("00") and len(d) > 2:
            return "+" + d[2:]
        return d
    if entity == "EMAIL":
        return s.lower()
    return s


# ============================================================================ vault


class VaultFull(RuntimeError):
    """A session vault hit its cap; callers fall back to the irreversible marker (never leak)."""


@runtime_checkable
class VaultLike(Protocol):
    """What the stream layer needs (aegis_stream ``Vault`` protocol)."""

    def resolve(self, key: str) -> str | None: ...


_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


class Vault:
    """Per-session, in-memory, reversible placeholder store. Never persisted, never logged."""

    def __init__(
        self,
        session_id: str,
        *,
        max_entries: int = 10_000,
        token_format: str = "indexed",
        secret: bytes | None = None,
    ) -> None:
        self.session_id = session_id
        self.max_entries = max_entries
        self.token_format = token_format
        self._secret = secret
        self._fwd: dict[tuple[str, str], str] = {}  # (entity, canonical) -> placeholder
        self._rev: dict[str, str] = {}  # placeholder -> first surface form
        self._ent: dict[str, str] = {}  # placeholder -> entity
        self._counters: dict[str, int] = {}
        self._lock = threading.RLock()
        self.version = 0  # bumps on every new entry (known-value matcher cache key)
        self.created_at = time.time()
        self.last_used = time.monotonic()
        self.last_used_wall = time.time()

    # ------------------------------------------------------------------ write
    def put(self, entity: str, value: str, canonical: str | None = None) -> str:
        """Tokenize ``value`` -> ``[ENTITY_N]`` (same canonical value -> same placeholder)."""
        if entity in IRREVERSIBLE or entity in ("CARD_CVV", "CARD_TRACK"):
            raise ValueError(f"{entity} is sensitive authentication data and is never vaulted")
        canon = canonical if canonical else canonicalize(entity, value)
        key = (entity, canon)
        with self._lock:
            self._touch()
            ph = self._fwd.get(key)
            if ph is not None:
                return ph
            if len(self._rev) >= self.max_entries:
                raise VaultFull(self.session_id)
            n = self._counters.get(entity, 0) + 1
            self._counters[entity] = n
            ph = self._opaque(entity, canon) if self.token_format == "opaque" else None
            ph = ph or f"[{entity}_{n}]"
            self._fwd[key] = ph
            self._rev[ph] = value
            self._ent[ph] = entity
            self.version += 1
            return ph

    def _opaque(self, entity: str, canon: str) -> str | None:
        """Deterministic, unguessable id: base32(HMAC(secret, session|entity|canonical))[:4]."""
        if not self._secret:
            return None
        mac = hmac.new(
            self._secret, f"{self.session_id}\x1f{entity}\x1f{canon}".encode(), hashlib.sha256
        ).digest()
        b32 = base64.b32encode(mac).decode().rstrip("=")
        for width in (4, 6, 8):
            sfx = b32[:width]
            if sfx.isdigit():
                continue
            ph = f"[{entity}_{sfx}]"
            if ph not in self._rev:
                return ph
        return None

    # ------------------------------------------------------------------ read
    def resolve(self, key: str) -> str | None:
        """Original value for a placeholder (tolerant spelling accepted) or None."""
        m = PLACEHOLDER_RE.fullmatch(key.strip())
        k = canonical_key(m.group(1), m.group(2)) if m else key
        self._touch()
        return self._rev.get(k)

    def entity_of(self, placeholder: str) -> str | None:
        m = PLACEHOLDER_RE.fullmatch(placeholder.strip())
        k = canonical_key(m.group(1), m.group(2)) if m else placeholder
        return self._ent.get(k)

    def lookup(self, entity: str, canonical: str) -> str | None:
        return self._fwd.get((entity, canonical))

    def contains_value(self, entity: str, canonical: str) -> bool:
        return (entity, canonical) in self._fwd

    def values(self) -> list[str]:
        return list(self._rev.values())

    def items(self) -> list[tuple[str, str, str]]:
        """[(placeholder, entity, value)] - engine-internal (known-value rescan)."""
        with self._lock:
            return [(ph, self._ent[ph], v) for ph, v in self._rev.items()]

    def entity_counts(self) -> dict[str, int]:
        with self._lock:
            out: dict[str, int] = {}
            for e in self._ent.values():
                out[e] = out.get(e, 0) + 1
            return out

    def __len__(self) -> int:
        return len(self._rev)

    def __bool__(self) -> bool:  # an EMPTY vault is still a vault (avoid `vault or ...` bugs)
        return True

    def __repr__(self) -> str:  # never print values
        return f"<Vault session={self.session_id!r} entries={len(self._rev)}>"

    def _touch(self) -> None:
        self.last_used = time.monotonic()
        self.last_used_wall = time.time()

    def wipe(self) -> None:
        with self._lock:
            self._fwd.clear()
            self._rev.clear()
            self._ent.clear()
            self._counters.clear()
            self.version += 1


class VaultStore:
    """session_id -> Vault with idle TTL, a per-session cap and explicit wipe (SessionEnd)."""

    def __init__(
        self,
        *,
        ttl_s: float = 3600,
        max_entries: int = 10_000,
        token_format: str = "indexed",
        secret: bytes | None = None,
    ) -> None:
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self.token_format = token_format
        self.secret = secret
        self._vaults: dict[str, Vault] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        *,
        ttl_s: float | None = None,
        max_entries: int | None = None,
        token_format: str | None = None,
    ) -> None:
        with self._lock:
            if ttl_s is not None and ttl_s > 0:
                self.ttl_s = float(ttl_s)
            if max_entries is not None and max_entries > 0:
                self.max_entries = int(max_entries)
                for v in self._vaults.values():
                    v.max_entries = self.max_entries
            if token_format in ("indexed", "opaque"):
                self.token_format = token_format

    def get(self, session_id: str) -> Vault:
        with self._lock:
            self._evict()
            v = self._vaults.get(session_id)
            if v is None:
                v = Vault(
                    session_id,
                    max_entries=self.max_entries,
                    token_format=self.token_format,
                    secret=self.secret,
                )
                self._vaults[session_id] = v
            v._touch()
            return v

    def peek(self, session_id: str) -> Vault | None:
        """Existing vault or None (never creates one)."""
        with self._lock:
            self._evict()
            return self._vaults.get(session_id)

    def delete(self, session_id: str) -> int:
        """Wipe one session; returns the number of wiped entries (0 if unknown)."""
        with self._lock:
            v = self._vaults.pop(session_id, None)
        if v is None:
            return 0
        n = len(v)
        v.wipe()
        return n

    def wipe_all(self) -> None:
        with self._lock:
            vaults, self._vaults = list(self._vaults.values()), {}
        for v in vaults:
            v.wipe()

    def stats(self, session_id: str) -> dict[str, Any] | None:
        """Counts only - never values or placeholder->value pairs."""
        v = self.peek(session_id)
        if v is None:
            return None
        return {
            "session_id": session_id,
            "entries": len(v),
            "entities": v.entity_counts(),
            "created_at": v.created_at,
            "last_used": v.last_used_wall,
            "ttl_s": self.ttl_s,
        }

    def sessions(self) -> list[str]:
        with self._lock:
            return list(self._vaults)

    def _evict(self) -> None:
        now = time.monotonic()
        for sid in [s for s, v in self._vaults.items() if now - v.last_used > self.ttl_s]:
            self._vaults.pop(sid).wipe()

    def __len__(self) -> int:
        return len(self._vaults)


class MappingVault:
    """Dict-backed vault (tests, demos, adapters)."""

    __slots__ = ("_m",)

    def __init__(self, mapping: Mapping[str, str] | Iterable[tuple[str, str]] = ()) -> None:
        items = mapping.items() if isinstance(mapping, Mapping) else mapping
        self._m: dict[str, str] = {}
        for k, v in items:
            m = PLACEHOLDER_RE.fullmatch(k)
            if not m:
                raise ValueError(f"not a placeholder: {k!r}")
            self._m[canonical_key(m.group(1), m.group(2))] = v

    def resolve(self, key: str) -> str | None:
        return self._m.get(key)

    def values(self) -> list[str]:
        return list(self._m.values())

    def __len__(self) -> int:
        return len(self._m)

    def __bool__(self) -> bool:
        return True


# ============================================================================ rehydration

Resolver = Callable[[str], "str | None"]


def _resolver(resolve: Resolver | VaultLike | Mapping[str, str]) -> Resolver:
    if isinstance(resolve, Mapping):
        m = {}
        for k, v in resolve.items():
            mm = PLACEHOLDER_RE.fullmatch(k.strip())
            m[canonical_key(mm.group(1), mm.group(2)) if mm else k] = v
        return m.get
    fn = getattr(resolve, "resolve", None)
    if callable(fn):
        return fn
    if callable(resolve):
        return resolve
    raise TypeError("resolve must be a callable, a vault (.resolve) or a mapping")


def rehydrate_text(
    text: str,
    resolve: Resolver | VaultLike | Mapping[str, str],
    *,
    json_string: bool = False,
    allow: Callable[[str], bool] | None = None,
) -> tuple[str, int]:
    """Replace every vault-issued placeholder in ``text``. Returns ``(text, n_replaced)``.

    ``resolve(canonical_key) -> value | None``. ``json_string=True`` JSON-escapes values
    (``text`` is the content of a JSON string literal). ``allow(canonical_key)`` may veto a
    replacement (entity filters, e.g. respect_matrix for local tools).
    """
    if "[" not in text:
        return text, 0
    res = _resolver(resolve)
    count = 0

    def rep(m: re.Match[str]) -> str:
        nonlocal count
        key = canonical_key(m.group(1), m.group(2))
        if allow is not None and not allow(key):
            return m.group(0)
        val = res(key)
        if val is None:
            return m.group(0)
        count += 1
        return json_escape(val) if json_string else val

    return PLACEHOLDER_RE.sub(rep, text), count


def rehydrate_json_value(
    obj: Any,
    resolve: Resolver | VaultLike | Mapping[str, str],
    *,
    allow: Callable[[str], bool] | None = None,
) -> tuple[Any, int]:
    """Rehydrate every string leaf (and key) of an already-parsed JSON value."""
    if isinstance(obj, str):
        return rehydrate_text(obj, resolve, allow=allow)
    if isinstance(obj, list):
        total = 0
        out_list = []
        for v in obj:
            nv, c = rehydrate_json_value(v, resolve, allow=allow)
            total += c
            out_list.append(nv)
        return out_list, total
    if isinstance(obj, dict):
        total = 0
        out_dict = {}
        for k, v in obj.items():
            nk, c1 = rehydrate_text(k, resolve, allow=allow) if isinstance(k, str) else (k, 0)
            nv, c2 = rehydrate_json_value(v, resolve, allow=allow)
            total += c1 + c2
            out_dict[nk] = nv
        return out_dict, total
    return obj, 0


class StreamRehydrator:
    """Chunk-wise rehydration for one content block / tool call (SSE deltas, NDJSON).

    Holds back a possibly split placeholder (``[PE`` | ``SEL_1]``) of at most
    ``MAX_PLACEHOLDER_LEN`` chars; adds latency only while a ``[`` is pending.
    ``json_escape=True`` for ``partial_json`` tool input (values are JSON-escaped).
    """

    def __init__(
        self,
        resolve: Resolver | VaultLike | Mapping[str, str],
        *,
        json_escape: bool = False,
        allow: Callable[[str], bool] | None = None,
    ) -> None:
        self._resolve = _resolver(resolve)
        self.json_escape = json_escape
        self._allow = allow
        self.buf = ""
        self.count = 0

    def _emit(self, text: str) -> str:
        out, n = rehydrate_text(
            text, self._resolve, json_string=self.json_escape, allow=self._allow
        )
        self.count += n
        return out

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        m = PARTIAL_PLACEHOLDER_RE.search(self.buf)
        if m and len(self.buf) - m.start() <= MAX_PLACEHOLDER_LEN:
            emit, self.buf = self.buf[: m.start()], self.buf[m.start() :]
        else:
            emit, self.buf = self.buf, ""
        return self._emit(emit) if emit else ""

    def flush(self) -> str:
        out, self.buf = self.buf, ""
        return self._emit(out) if out else ""


def has_placeholders(text: str) -> bool:
    """True if ``text`` contains something shaped like an issued placeholder."""
    return "[" in text and ISSUED_RE.search(text) is not None
