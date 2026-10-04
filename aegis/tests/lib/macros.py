"""Runtime macro expansion for case files — keeps secret-shaped literals out of git.

Generators (valid shapes, random per run, registered in the privacy registry):
  {{gen:aws_access_key_id}} {{gen:aws_secret}} {{gen:github_pat}} {{gen:slack_token}}
  {{gen:stripe_key}} {{gen:jwt}} {{gen:openssh_private_key}} {{gen:anthropic_key}}
Encoders (applied to the already-expanded inner text, innermost first):
  {{b64:T}} {{b64url:T}} {{hex:T}} {{tags:T}} (Unicode tag chars) {{zw:T}} (zero-width joiners)
  {{repeat:N:T}}
Samples (benign model artifacts generated at run time by `aegis.feed.samples`, base64-encoded):
  {{sample:<name>}}  e.g. {{sample:weights.bin}} (off-allowlist pickle) or
  {{sample:model.safetensors}}; send it as `meta: {artifact_b64: "{{sample:...}}", filename: ...}`
Values are cached per run, so the same macro yields the same value within one session (useful
for `assert.upstream_must_not_contain: ["{{gen:aws_access_key_id}}"]`).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
import string
import zlib
from typing import Any

from tests.lib import privacy

_B62 = string.digits + string.ascii_uppercase + string.ascii_lowercase
_ALNUM = string.ascii_letters + string.digits
_CACHE: dict[str, str] = {}


def _rand(alphabet: str, n: int) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _b62(n: int, width: int) -> str:
    out = ""
    while n:
        n, r = divmod(n, 62)
        out = _B62[r] + out
    return out.rjust(width, "0")


def _github_pat() -> str:
    body = _rand(_ALNUM, 30)
    return "gh" + "p_" + body + _b62(zlib.crc32(body.encode()) & 0xFFFFFFFF, 6)


def _jwt() -> str:
    def seg(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    sig = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    return f"{seg({'alg': 'HS256', 'typ': 'JWT'})}.{seg({'sub': 'svc-' + _rand(_ALNUM, 8), 'iat': 1759500000})}.{sig}"


def _ssh_key() -> str:
    body = base64.b64encode(secrets.token_bytes(180)).decode()
    lines = [body[i : i + 70] for i in range(0, len(body), 70)]
    kind = "OPENSSH " + "PRIVATE KEY"
    return "-----BEGIN " + kind + "-----\n" + "\n".join(lines) + "\n-----END " + kind + "-----"


GENERATORS = {
    "aws_access_key_id": lambda: "AK" + "IA" + _rand(string.ascii_uppercase + "234567", 16),
    "aws_secret": lambda: _rand(_ALNUM + "/+", 40),
    "aws_secret_access_key": lambda: _rand(_ALNUM + "/+", 40),
    "github_pat": _github_pat,
    "slack_token": lambda: (
        "xo"
        + "xb-"
        + _rand(string.digits, 12)
        + "-"
        + _rand(string.digits, 12)
        + "-"
        + _rand(_ALNUM, 24)
    ),
    "stripe_key": lambda: "sk" + "_live_" + _rand(_ALNUM, 24),
    "jwt": _jwt,
    "openssh_private_key": _ssh_key,
    "anthropic_key": lambda: "sk" + "-ant-api03-" + _rand(_ALNUM + "-_", 93) + "AA",
}


def gen(name: str) -> str:
    if name not in _CACHE:
        if name not in GENERATORS:
            raise KeyError(f"unknown generator {{{{gen:{name}}}}} (known: {', '.join(GENERATORS)})")
        _CACHE[name] = GENERATORS[name]()
        privacy.register(_CACHE[name], f"gen:{name}")
    return _CACHE[name]


def sample(name: str) -> str:
    """base64 of a generated SIG-02 sample (`aegis.feed.samples.SAMPLES[name]`); never committed."""
    from aegis.feed.samples import SAMPLES

    key = f"sample:{name}"
    if key not in _CACHE:
        if name not in SAMPLES:
            raise KeyError(f"unknown sample {{{{sample:{name}}}}} (known: {', '.join(SAMPLES)})")
        _CACHE[key] = base64.b64encode(SAMPLES[name][0]()).decode()
    return _CACHE[key]


def _tags(text: str) -> str:
    return "".join(chr(0xE0000 + ord(c)) if 0x20 <= ord(c) < 0x7F else c for c in text)


def _zw(text: str) -> str:
    return "‍".join(text)


ENCODERS = {
    "b64": lambda t: base64.b64encode(t.encode()).decode(),
    "b64url": lambda t: base64.urlsafe_b64encode(t.encode()).decode().rstrip("="),
    "hex": lambda t: binascii.hexlify(t.encode()).decode(),
    "tags": _tags,
    "zw": _zw,
}

# innermost macro first: no nested "{{" inside the argument
_KINDS = "gen|sample|b64|b64url|hex|tags|zw|repeat"
_INNER = re.compile(r"\{\{(" + _KINDS + r"):((?:(?!\{\{|\}\}).)*)\}\}", re.S)


def expand(text: str) -> str:
    """Expand all macros in `text` (repeatedly, innermost first)."""
    if not isinstance(text, str) or "{{" not in text:
        return text
    for _ in range(20):
        m = _INNER.search(text)
        if not m:
            break
        kind, arg = m.group(1), m.group(2)
        if kind == "gen":
            val = gen(arg.strip())
        elif kind == "sample":
            val = sample(arg.strip())
        elif kind == "repeat":
            n, _, body = arg.partition(":")
            val = body * max(0, min(int(n), 100_000))
        else:
            val = ENCODERS[kind](arg)
        text = text[: m.start()] + val + text[m.end() :]
    return text


def expand_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return expand(obj)
    if isinstance(obj, list):
        return [expand_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: expand_obj(v) for k, v in obj.items()}
    return obj


def has_macro(text: str) -> bool:
    return bool(isinstance(text, str) and _INNER.search(text))


__all__ = ["ENCODERS", "GENERATORS", "expand", "expand_obj", "gen", "has_macro", "sample"]
