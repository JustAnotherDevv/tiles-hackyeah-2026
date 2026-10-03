"""Body-field pseudonymization for DLP-03 (e.g. Claude Code `metadata.user_id`).

Pseudonyms are deterministic HMACs (`hmac_hex(v, purpose="pseudonym")`), so the provider
still sees a stable per-user id and the prompt cache survives; the JSON-string shape of
Claude Code's `metadata.user_id` ({device_id, account_uuid, session_id}) is preserved.
"""

from __future__ import annotations

import json
import re
from typing import Any

from aegis.core.types import Mutation
from aegis.egress.compat import get_path, hmac_hex

ANON_PREFIX = "anon-"
GENERIC_PREFIX = "aegis-anon-"
_CC_ID_KEYS = ("device_id", "account_uuid", "user_id", "email", "account_id", "organization_uuid")
_LEGACY_CC = re.compile(
    r"^user_(?P<user>[0-9a-fA-F]{8,128})_account_(?P<account>[0-9a-fA-F\-]{0,64})"
    r"_session_(?P<session>[0-9a-fA-F\-]{8,64})$")


def pseudonym(value: str, *, prefix: str = ANON_PREFIX) -> str:
    if value.startswith((ANON_PREFIX, GENERIC_PREFIX)):
        return value
    return prefix + hmac_hex(value, purpose="pseudonym")[:12]


def _pseudo_obj(obj: dict[str, Any], *, pseudonymize_session: bool) -> tuple[dict[str, Any], bool]:
    out = dict(obj)
    changed = False
    for k, v in obj.items():
        if not isinstance(v, str) or not v:
            continue
        if k in _CC_ID_KEYS or (k == "session_id" and pseudonymize_session):
            nv = pseudonym(v)
            if nv != v:
                out[k] = nv
                changed = True
    return out, changed


def pseudonymize_value(value: Any, *, pseudonymize_session: bool = False) -> tuple[Any, bool]:
    """Return (new value, changed)."""
    if isinstance(value, dict):
        return _pseudo_obj(value, pseudonymize_session=pseudonymize_session)
    if not isinstance(value, str) or not value:
        return value, False
    s = value.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            new, changed = _pseudo_obj(obj, pseudonymize_session=pseudonymize_session)
            if not changed:
                return value, False
            compact = ", " not in s and ": " not in s
            sep = (",", ":") if compact else (", ", ": ")
            return json.dumps(new, separators=sep, ensure_ascii=False), True
    m = _LEGACY_CC.match(s)
    if m:
        user = pseudonym(m["user"])
        account = pseudonym(m["account"]) if m["account"] else ""
        session = pseudonym(m["session"]) if pseudonymize_session else m["session"]
        new = f"user_{user}_account_{account}_session_{session}"
        return new, new != value
    if value.startswith((ANON_PREFIX, GENERIC_PREFIX)):
        return value, False
    return pseudonym(value, prefix=GENERIC_PREFIX), True


def plan_body_fields(raw: Any, rules: list[Any], *, pseudonymize_session: bool = False
                     ) -> list[Mutation]:
    """Mutations for the configured body-field rules (paths relative to `Interaction.raw`)."""
    if not isinstance(raw, dict) or not rules:
        return []
    out: list[Mutation] = []
    for rule in rules:
        path = getattr(rule, "path", None) or (rule.get("path") if isinstance(rule, dict) else None)
        op = getattr(rule, "op", None) or (rule.get("op") if isinstance(rule, dict) else None)
        op = op or "pseudonymize"
        if not path or op == "keep":
            continue
        cur = get_path(raw, path, None)
        if cur is None:
            continue
        if op == "remove":
            out.append(Mutation(target="body", op="remove", path=path,
                                reason="DLP-03 body field removed"))
            continue
        new, changed = pseudonymize_value(cur, pseudonymize_session=pseudonymize_session)
        if changed:
            out.append(Mutation(target="body", op="set", path=path, value=new,
                                reason="DLP-03 pseudonymized"))
    return out
