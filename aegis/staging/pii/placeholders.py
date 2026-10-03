"""Session vault, redaction operators, audit spans and (streaming) rehydration - research 07 s7-9,
aligned with CONTRACTS.md s3.4 (entity names, placeholders, data-class x destination matrix).

Invariants enforced here (not left to policy):
  * SAD (CVV, TRACK_DATA) is NEVER vaulted, never fingerprinted, never previewed: always dropped
    irreversibly as "[REDACTED:CVV]" / "[REDACTED:TRACK_DATA]"; a policy asking to tokenize SAD is
    coerced (PCI DSS 3.3.1).
  * PAN display (audit/dashboard) is at most first 6 + last 4: "411111******1111" (PCI DSS
    3.4.1). The model only ever sees "[PAN_n]".
  * Audit fingerprints are keyed HMAC-SHA256 (``detectors.fingerprint``); never a plain hash.
  * Vault is in-memory only, per session, numbered per canonical entity by first appearance
    ("[PESEL_1]"), stable per value, capped, idle-TTL'd. ``redact(rehydrate(y)) == y``.
  * Rehydration only toward trusted hops (``rehydrate_to: [local_user, local_tools]``);
    placeholders not in the vault (``[EMAIL_9]``, ``[Step 1]``, ``arr[0]``) are left untouched.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .detectors import DATA_CLASS, Finding, contract_entity, fingerprint

SAD_ENTITIES = frozenset({"CVV", "TRACK_DATA"})
SAD_TYPES = frozenset({"CARD_CVV", "CARD_TRACK"}) | SAD_ENTITIES   # accepts both vocabularies

# research 07 zone names -> CONTRACTS DestClass
ZONE_ALIASES = {"T0": "local", "T1": "remote", "T2": "third_party"}

DEFAULT_POLICY: dict = {
    "token_format": "indexed",          # indexed -> [EMAIL_1] | opaque -> [EMAIL_k7f3]
    "mask_style": "placeholder",        # placeholder | pci (PAN -> 411111******1111 to the model)
    "max_entities_per_request": 50,
    "redaction_ratio_block": None,      # DLP-01 param (policy.yaml uses 0.6); needs min_chars
    "redaction_ratio_min_chars": 200,
    "rehydrate_to": ["local_user", "local_tools"],
    # CONTRACTS policy.yaml `destinations.matrix`: data class x destination -> action
    "matrix": {
        "PUBLIC":       {"local": "allow",  "remote": "allow",  "third_party": "allow"},
        "CONFIDENTIAL": {"local": "allow",  "remote": "redact", "third_party": "block"},
        "RESTRICTED":   {"local": "redact", "remote": "redact", "third_party": "block"},
        "SECRET":       {"local": "log",    "remote": "block",  "third_party": "block"},
        "INTERNAL":     {"local": "allow",  "remote": "redact", "third_party": "redact"},
    },
    # per-entity (canonical name) or per-detector-type overrides of the redact operator
    "entities": {
        "CVV": {"operator": "drop"},
        "TRACK_DATA": {"operator": "drop"},
        "URL_SECRET": {"operator": "redact_param_value"},           # detector type
        "USERNAME": {"operator": "replace", "value": "user"},       # keeps paths usable
    },
}


def _irreversible(entity: str) -> str:
    return f"[REDACTED:{entity}]"


class VaultFull(RuntimeError):
    """Raised when a session vault hits its cap -> caller must fail closed (block)."""


# ============================================================================ vault

_OPAQUE_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


def _placeholder_key(etype: str, suffix: str) -> str:
    return f"[{etype.upper()}_{suffix if suffix.isdigit() else suffix.lower()}]"


class Vault:
    """Per-session, in-memory, reversible placeholder store. Never persisted, never logged."""

    def __init__(self, session_id: str, *, token_format: str = "indexed",
                 max_entries: int = 10_000):
        self.session_id = session_id
        self.token_format = token_format
        self.max_entries = max_entries
        self._fwd: dict[tuple[str, str], str] = {}
        self._rev: dict[str, str] = {}
        self._types: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._lock = threading.Lock()
        self.last_used = time.monotonic()

    def put(self, etype: str, value: str, canonical: str | None = None) -> str:
        """etype = canonical entity (CONTRACTS s3.4) -> '[PESEL_1]'."""
        if etype in SAD_TYPES:
            raise ValueError(f"{etype} is sensitive authentication data and must never be vaulted")
        key = (etype, canonical or value)
        with self._lock:
            self.last_used = time.monotonic()
            ph = self._fwd.get(key)
            if ph is not None:
                return ph
            if len(self._rev) >= self.max_entries:
                raise VaultFull(self.session_id)
            n = self._counters.get(etype, 0) + 1
            self._counters[etype] = n
            if self.token_format == "opaque":
                while True:
                    sfx = "".join(secrets.choice(_OPAQUE_ALPHABET) for _ in range(4))
                    if not sfx.isdigit() and f"[{etype}_{sfx}]" not in self._rev:
                        break
                ph = f"[{etype}_{sfx}]"
            else:
                ph = f"[{etype}_{n}]"
            self._fwd[key] = ph
            self._rev[ph] = value
            self._types[ph] = etype
            return ph

    def resolve(self, placeholder: str) -> str | None:
        m = PH_RE.fullmatch(placeholder.strip())
        key = _placeholder_key(m.group(1), m.group(2)) if m else placeholder
        return self._rev.get(key)

    def lookup(self, etype: str, canonical: str) -> str | None:
        return self._fwd.get((etype, canonical))

    def contains_value(self, etype: str, canonical: str) -> bool:
        return (etype, canonical) in self._fwd

    def reverse_map(self) -> dict[str, str]:
        return dict(self._rev)

    def __len__(self) -> int:
        return len(self._rev)

    def __bool__(self) -> bool:  # an EMPTY vault is still a vault (avoid `vault or Vault()` bugs)
        return True

    def wipe(self) -> None:
        with self._lock:
            self._fwd.clear()
            self._rev.clear()
            self._types.clear()
            self._counters.clear()


class VaultStore:
    """Session -> Vault with idle TTL (default 2 h) and explicit wipe (SessionEnd hook)."""

    def __init__(self, *, ttl_s: float = 7200, token_format: str = "indexed",
                 max_entries: int = 10_000):
        self.ttl_s = ttl_s
        self.token_format = token_format
        self.max_entries = max_entries
        self._vaults: dict[str, Vault] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Vault:
        with self._lock:
            self._evict()
            v = self._vaults.get(session_id)
            if v is None:
                v = self._vaults[session_id] = Vault(session_id, token_format=self.token_format,
                                                     max_entries=self.max_entries)
            v.last_used = time.monotonic()
            return v

    def delete(self, session_id: str) -> bool:
        with self._lock:
            v = self._vaults.pop(session_id, None)
        if v:
            v.wipe()
        return v is not None

    def _evict(self) -> None:
        now = time.monotonic()
        for sid in [s for s, v in self._vaults.items() if now - v.last_used > self.ttl_s]:
            self._vaults.pop(sid).wipe()

    def __len__(self) -> int:
        return len(self._vaults)


# ============================================================================ previews (audit)

def _ent(f_or_type: str) -> str:
    """Accept a canonical entity or a granular detector type."""
    return contract_entity(f_or_type) if f_or_type not in DATA_CLASS else f_or_type


def pci_preview(canonical_digits: str) -> str:
    """First 6 / last 4: '411111******1111' (PCI DSS 3.4.1 maximum; CONTRACTS mask_style pci)."""
    d = canonical_digits
    return d[:6] + "*" * max(0, len(d) - 10) + d[-4:] if len(d) > 10 else "*" * len(d)


def mask_preview(entity: str, value: str, canonical: str = "", meta: Mapping | None = None) -> str | None:
    """Type-aware, non-reversible preview for the audit log / dashboard. None for SAD."""
    e = _ent(entity)
    if e in SAD_ENTITIES:
        return None
    c = canonical or value
    if e == "PAN":
        return pci_preview(c)
    if e == "EMAIL":
        local, _, dom = c.partition("@")
        tld = dom.rsplit(".", 1)[-1] if "." in dom else ""
        return f"{local[:1]}***@{dom[:1]}***.{tld}"
    if DATA_CLASS.get(e) == "SECRET":
        rule = (meta or {}).get("rule") or e.lower()
        return f"<{rule}:{len(value)} chars>"
    if e == "IP_ADDRESS":
        return c.split(".")[0] + ".*.*.*" if "." in c else c.split(":")[0] + ":*"
    if e == "USERNAME":
        return c[:1] + "***"
    if e == "DOB":
        return "****"
    if e == "IBAN" and c[:2].isalpha():
        return c[:2] + "*" * max(0, len(c) - 4) + c[-2:]
    # IDs, phone, NRB, crypto, ...: last 2 only (never the PESEL birth-date prefix)
    return "*" * max(0, len(c) - 2) + c[-2:]


def mask_for_log(text: str, detector, max_len: int = 160) -> str:
    """Reference `rt.redactor.mask_for_log`: findings -> type-aware masks / [ENTITY], every other
    digit and '@' masked too, truncated. Safe for excerpts, SSE payloads and audit previews."""
    out, pos = [], 0
    for f in detector.detect(text):
        out.append(re.sub(r"[0-9]", "*", text[pos:f.start]).replace("@", "(at)"))
        pv = mask_preview(f.entity, f.value, f.canonical, f.meta)
        out.append(pv if pv and f.entity in ("PAN", "EMAIL") else f"[{f.entity}]")
        pos = f.end
    out.append(re.sub(r"[0-9]", "*", text[pos:]).replace("@", "(at)"))
    s = "".join(out)
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


# ============================================================================ redaction

@dataclass
class RedactionResult:
    text: str                       # payload as it may leave (redacted)
    action: str                     # allow | log | redact | block   (CONTRACTS Action subset)
    spans: list[dict] = field(default_factory=list)   # audit spans, offsets in `text`
    reasons: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action == "block"


def _decide(f: Finding, dest: str, policy: Mapping) -> tuple[str, dict]:
    """-> (op, entity_cfg). op in allow | log | block | tokenize | drop | fragment | replace |
    redact_param_value | generalize_year | mask | pci."""
    ents = policy.get("entities", {})
    ent = {**ents.get(f.entity, {}), **ents.get(f.type, {})}
    cls = ent.get("class") or DATA_CLASS.get(f.entity, "CONFIDENTIAL")
    action = policy.get("matrix", {}).get(cls, {}).get(dest, "redact")
    if action in ("allow", "log"):
        return action, ent
    if action != "redact":          # block, require_approval -> nothing leaves
        return "block", ent
    if f.entity in SAD_ENTITIES:
        return "drop", ent          # PCI DSS 3.3.1: never stored, not even reversibly
    if f.meta.get("fragment"):
        return "fragment", ent
    op = ent.get("operator", "tokenize")
    if op == "tokenize" and f.entity == "PAN" and policy.get("mask_style") == "pci":
        op = "pci"
    return op, ent


def redact(text: str, findings: Iterable[Finding], *, vault: Vault | None, zone: str = "remote",
           policy: Mapping | None = None, hmac_key: bytes | None = None) -> RedactionResult:
    """Apply the data-class x destination matrix to one segment. `zone` is a CONTRACTS DestClass
    (local | remote | third_party) or a research-07 alias (T0 | T1 | T2)."""
    policy = policy or DEFAULT_POLICY
    dest = ZONE_ALIASES.get(zone, zone)
    fs = sorted(findings, key=lambda f: f.start)
    out: list[str] = []
    spans: list[dict] = []
    reasons: list[str] = []
    pos = olen = redacted_chars = 0
    any_redact = any_log = blocked = False
    for f in fs:
        if f.start < pos:  # overlapping (caller did not merge) - skip, first wins
            continue
        op, ent = _decide(f, dest, policy)
        chunk = text[pos:f.start]
        out.append(chunk)
        olen += len(chunk)
        if op in ("allow", "log"):
            rep = f.value
            any_log |= op == "log"
        elif op == "block":
            blocked = True
            reasons.append(f"{f.entity}:{f.detector}")
            rep = _irreversible(f.entity)
        elif op in ("drop", "fragment", "redact_param_value"):
            rep = _irreversible(f.entity)
        elif op == "replace":
            rep = str(ent.get("value", _irreversible(f.entity)))
        elif op == "generalize_year":
            yrs = re.findall(r"(?:19|20)[0-9]{2}", f.canonical or f.value)
            rep = yrs[0] if yrs else _irreversible(f.entity)
        elif op in ("mask", "pci"):
            rep = mask_preview(f.entity, f.value, f.canonical, f.meta) or _irreversible(f.entity)
        else:  # tokenize
            if vault is None:
                raise ValueError("tokenize requires a vault")
            rep = vault.put(f.entity, f.value, f.canonical)
        if op not in ("allow", "log"):
            any_redact = True
            redacted_chars += f.end - f.start
        sad = f.entity in SAD_ENTITIES
        spans.append({
            "type": f.type, "entity": f.entity, "data_class": f.data_class,
            "detector": f.detector, "score": round(f.score, 3), "op": op,
            "ph": rep if op not in ("allow", "log") else None, "reversible": op == "tokenize",
            "start": olen, "end": olen + len(rep), "orig_len": f.end - f.start,
            "preview": None if sad else mask_preview(f.entity, f.value, f.canonical, f.meta),
            "fp": None if (sad or hmac_key is None) else fingerprint(f.entity, f.canonical, hmac_key),
        })
        out.append(rep)
        olen += len(rep)
        pos = f.end
    out.append(text[pos:])
    red = "".join(out)
    n_ent = sum(1 for s in spans if s["op"] not in ("allow", "log"))
    cap = policy.get("max_entities_per_request")
    if cap and n_ent > cap:
        blocked = True
        reasons.append(f"max_entities_per_request>{cap}")
    ratio = policy.get("redaction_ratio_block")
    if ratio and len(text) >= policy.get("redaction_ratio_min_chars", 200) and \
            redacted_chars / max(1, len(text)) > ratio:
        blocked = True
        reasons.append(f"redaction_ratio>{ratio}")
    action = "block" if blocked else "redact" if any_redact else "log" if any_log else "allow"
    return RedactionResult(red, action, spans, reasons)


# ============================================================================ rehydration

# tolerant: models change case / spacing: [email_1], [ PERSON_1 ], [PL PESEL 1], [PERSON_k7f3]
PH_RE = re.compile(r"\[\s*([A-Za-z][A-Za-z0-9_]*?)[_\- ]([0-9]{1,4}|[A-Za-z0-9]{4})\s*\]")
PARTIAL_RE = re.compile(r"\[\s*[A-Za-z0-9_\- ]{0,40}$")   # possible placeholder split by a chunk
MAX_PH = 48


def may_rehydrate(destination: str, policy: Mapping | None = None) -> bool:
    """Rehydrate only toward trusted hops (A15: injected '[PESEL_1]' bound for a third-party tool
    stays a placeholder). Accepts rehydrate_to names plus 'local'/'T0' as local aliases."""
    allowed = set((policy or DEFAULT_POLICY).get("rehydrate_to", ()))
    if destination in ("local", "T0"):
        return bool(allowed & {"local_user", "local_tools"})
    return destination in allowed


def _sub(text: str, rev: Mapping[str, str], json_escape: bool) -> str:
    def rep(m: re.Match) -> str:
        val = rev.get(_placeholder_key(m.group(1), m.group(2)))
        if val is None:
            return m.group(0)
        return json.dumps(val, ensure_ascii=False)[1:-1] if json_escape else val
    return PH_RE.sub(rep, text)


def rehydrate(text: str, vault: Vault, *, destination: str = "local_user",
              json_escape: bool = False, policy: Mapping | None = None) -> str:
    if not may_rehydrate(destination, policy):
        return text
    return _sub(text, vault._rev, json_escape)


class StreamRehydrator:
    """One per content block / tool call (SSE text_delta, input_json_delta, NDJSON content).

    Holds back a possible split placeholder (``[PL_PE`` | ``SEL_1]``) up to 48 chars; adds
    latency only while a '[' is pending. ``json_escape=True`` for partial_json tool input."""

    def __init__(self, vault_or_map: Vault | Mapping[str, str], *, json_escape: bool = False):
        self.rev = vault_or_map._rev if isinstance(vault_or_map, Vault) else vault_or_map
        self.json_escape = json_escape
        self.buf = ""

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        m = PARTIAL_RE.search(self.buf)
        if m and len(self.buf) - m.start() <= MAX_PH:
            emit, self.buf = self.buf[:m.start()], self.buf[m.start():]
        else:
            emit, self.buf = self.buf, ""
        return _sub(emit, self.rev, self.json_escape)

    def flush(self) -> str:
        out, self.buf = _sub(self.buf, self.rev, self.json_escape), ""
        return out


class InverseCache:
    """sha256(rehydrated assistant text) -> exact placeholder text (research 07 s8.4).

    On the next turn the client resends the rehydrated history; replacing it byte-exactly keeps
    the prompt prefix (cache, thinking signatures) stable and avoids detector drift."""

    def __init__(self, max_items: int = 4096):
        self._d: OrderedDict[str, str] = OrderedDict()
        self.max_items = max_items

    @staticmethod
    def _k(s: str) -> str:
        return hashlib.sha256(s.encode()).hexdigest()

    def remember(self, rehydrated: str, placeholder_text: str) -> None:
        k = self._k(rehydrated)
        self._d[k] = placeholder_text
        self._d.move_to_end(k)
        while len(self._d) > self.max_items:
            self._d.popitem(last=False)

    def restore(self, text: str) -> str | None:
        return self._d.get(self._k(text))


def leak_scan(text: str, detector, vault: Vault | None = None) -> list[Finding]:
    """Tier-D scan of a model output BEFORE rehydration. Values the vault already holds are
    marked meta.from_vault (the user supplied them; not a new leak)."""
    out = []
    for f in detector.detect(text):
        if PH_RE.fullmatch(f.value.strip()):
            continue
        if vault is not None and vault.contains_value(f.entity, f.canonical or f.value):
            f.meta = {**f.meta, "from_vault": True}
        out.append(f)
    return out
