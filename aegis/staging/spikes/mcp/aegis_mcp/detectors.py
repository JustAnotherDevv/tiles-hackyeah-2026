"""Deterministic detectors for the MCP surfaces (pure functions, no I/O).

Three entry points, one per surface:

    scan_tool_definition(tool)   MCP-02 tool poisoning (names, descriptions, every string in the schemas)
    scan_text_dlp(text)          DLP-02/DLP-04 secrets, PII, encoded blobs (decoded and re-scanned)
    scan_text_injection(text)    INJ-01 indirect prompt-injection markers in results

Findings never carry raw sensitive values in their serialized form (`evidence` is masked for
DLP findings); the raw span is kept in-process only so callers can redact it.

These are spike-grade regexes. In the gateway they should come from the signed signature
feed / redaction engine (research 04 + 07) and run through google-re2.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

SEVERITY_SCORE = {"high": 3, "medium": 1, "low": 0}


@dataclass(frozen=True)
class Finding:
    rule: str  # e.g. "inj.hidden_tag", "secret.private_key", "pii.email"
    category: str  # poisoning | injection | secret | pii | encoded | invisible
    severity: str  # high | medium | low
    where: str = ""  # JSON-ish path inside the message, e.g. "arguments.summary"
    evidence: str = ""  # safe to log
    start: int = field(default=-1, compare=False)
    end: int = field(default=-1, compare=False)
    placeholder_type: str = field(default="", compare=False)  # e.g. EMAIL; empty = not redactable

    def at(self, where: str) -> Finding:
        return Finding(self.rule, self.category, self.severity, where, self.evidence, self.start, self.end,
                       self.placeholder_type)

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "category": self.category, "severity": self.severity, "where": self.where,
                "evidence": self.evidence}


def mask(value: str) -> str:
    value = value.replace("\n", " ")
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…({len(value)} chars)"


def snippet(value: str, limit: int = 80) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def iter_strings(obj: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Yield (path, string) for every string leaf of a JSON value."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_strings(v, f"{path}[{i}]")


# ---------------------------------------------------------------------------------------------
# Injection / poisoning signatures (shared by tool definitions and tool results)
# ---------------------------------------------------------------------------------------------

_I = re.IGNORECASE
INJECTION_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("inj.hidden_tag", re.compile(r"<\s*/?\s*(important|system|instructions?|secret|admin|hidden)\b[^>]{0,40}>", _I), "high"),
    ("inj.ignore_previous", re.compile(
        r"\b(ignore|disregard|forget|override)\b[\s\w,]{0,30}?\b(previous|prior|above|earlier|all|any|system)\b"
        r"[\s\w]{0,20}?\b(instructions?|prompts?|rules|guidelines|directions)\b", _I), "high"),
    ("inj.conceal_from_user", re.compile(
        r"\b(do\s*n[o']?t|never|without)\s+(tell|mention|inform|reveal|notify|alert|let)\w*\b[\s\w]{0,15}?\buser\b", _I),
     "high"),
    ("inj.role_override", re.compile(r"\byou are now\b|\bnew instructions?\s*:|\b(admin|developer|god|dan|jailbreak)\s+mode\b", _I),
     "high"),
    ("inj.chat_template", re.compile(r"<\|im_(start|end)\|>|\[/?INST\]|<\|(system|user|assistant)\|>|</?(tool_call|function_call)>", _I),
     "high"),
    ("inj.sensitive_path", re.compile(
        r"(?:~|\$HOME|^|[\s'\"`(])/?\.(?:ssh|aws|gnupg|kube|docker|cursor)\b(?!\.)|\bid_(?:rsa|ed25519|ecdsa|dsa)\b"
        r"|(?:^|[\s'\"`/])\.env\b|\bmcp\.json\b|\bcredentials\.json\b|/etc/(?:passwd|shadow)\b"
        r"|\.git-credentials\b|\.netrc\b", _I),
     "high"),
    ("inj.precondition_hijack", re.compile(r"\bbefore (using|calling|invoking|running) (this|the|any) tool\b", _I), "medium"),
    ("inj.tool_directive", re.compile(r"\b(call|invoke|run|use)\s+(the\s+)?(tool|function)\b|\bcall\s+[a-z][a-z0-9_]{2,}\s+with\b", _I),
     "medium"),
    ("inj.ansi_escape", re.compile(r"\x1b\["), "high"),
]
URL_RE = re.compile(r"https?://[^\s'\"<>)]+", _I)
# zero-width, bidi overrides/isolates, BOM, Unicode TAG block (ASCII smuggling)
INVISIBLE_RE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")


def _injection_findings(text: str, where: str) -> list[Finding]:
    out: list[Finding] = []
    normalized = unicodedata.normalize("NFKC", INVISIBLE_RE.sub("", text))
    for rule, rx, sev in INJECTION_RULES:
        matches = list(rx.finditer(text))
        for m in matches:
            out.append(Finding(rule, "injection", sev, where, snippet(m.group(0)), m.start(), m.end()))
        if not matches and rx.search(normalized):  # only visible after stripping invisibles / NFKC folding
            out.append(Finding(rule + ".obfuscated", "injection", "high", where, "(match after normalization)"))
    if m := INVISIBLE_RE.search(text):
        out.append(Finding("inj.invisible_chars", "invisible", "high", where, f"U+{ord(m.group(0)):04X}"))
    return out


def scan_text_injection(text: str, where: str = "") -> list[Finding]:
    """INJ-01 on untrusted content (tool results, resources, prompts)."""
    return _injection_findings(text, where)


def scan_tool_definition(tool: dict[str, Any], *, max_description_len: int = 2000,
                         url_allowlist: tuple[str, ...] = ()) -> list[Finding]:
    """MCP-02: scan name, title, description, annotations and EVERY string inside input/output schemas
    (property descriptions, defaults, enums, x-* fields) - poisoning is not limited to `description`."""
    findings: list[Finding] = []
    for path, text in iter_strings({k: v for k, v in tool.items() if k != "_meta"}):
        findings += [f.at(path) for f in _injection_findings(text, path)]
        for m in URL_RE.finditer(text):
            if not any(m.group(0).lower().startswith(a.lower()) for a in url_allowlist):
                findings.append(Finding("tooldef.url", "poisoning", "medium", path, snippet(m.group(0))))
    desc = tool.get("description") or ""
    if len(desc) > max_description_len:
        findings.append(Finding("tooldef.long_description", "poisoning", "medium", "description",
                                f"{len(desc)} chars > {max_description_len}"))
    if not re.fullmatch(r"[A-Za-z0-9_.\-/]{1,128}", str(tool.get("name", ""))):
        findings.append(Finding("tooldef.bad_name", "poisoning", "high", "name", snippet(str(tool.get("name")))))
    return findings


def poison_score(findings: list[Finding]) -> int:
    return sum(SEVERITY_SCORE.get(f.severity, 0) for f in findings)


# ---------------------------------------------------------------------------------------------
# DLP: secrets, PII, encoded blobs
# ---------------------------------------------------------------------------------------------

SECRET_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("secret.private_key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("secret.aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[0-9A-Z]{16}\b")),
    ("secret.aws_secret_key", re.compile(r"(?i)aws_?secret_?access_?key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}")),
    ("secret.github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b")),
    ("secret.slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("secret.llm_api_key", re.compile(r"\bsk-(?:ant-(?:api|admin)\d{2}-|proj-)?[A-Za-z0-9_-]{24,}\b")),
    ("secret.google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("secret.stripe_key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("secret.jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("secret.credential_assignment", re.compile(
        r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)\b"
        r"\s*[:=]\s*['\"]?[^\s'\"]{8,}")),
]

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PESEL_RE = re.compile(r"(?<!\d)\d{11}(?!\d)")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
PHONE_PL_RE = re.compile(r"(?<![\d+])(?:\+48[ -]?\d{3}[ -]?\d{3}[ -]?\d{3}|\d{3}[ -]\d{3}[ -]\d{3})(?![\d])")
B64_RE = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/=_-])")
HEX_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}){48,}\b")


def _pesel_ok(s: str) -> bool:
    w = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return (10 - sum(int(c) * k for c, k in zip(s, w)) % 10) % 10 == int(s[10])


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        d = int(c)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _iban_ok(s: str) -> bool:
    s = s.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def _try_decode(blob: str) -> str | None:
    """Decode base64 (std or url-safe) or hex; return text if it is mostly printable."""
    raw: bytes | None = None
    if HEX_RE.fullmatch(blob):
        try:
            raw = bytes.fromhex(blob)
        except ValueError:
            raw = None
    if raw is None:
        padded = blob + "=" * (-len(blob) % 4)
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                raw = decoder(padded)
                break
            except (binascii.Error, ValueError):
                continue
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
    return text if printable / max(len(text), 1) >= 0.85 else None


def _overlaps(start: int, end: int, taken: list[tuple[int, int]]) -> bool:
    return any(start < e and s < end for s, e in taken)


def scan_text_dlp(text: str, where: str = "", *, max_encoded_len: int = 512, decode_depth: int = 2) -> list[Finding]:
    """Secrets (block-class), PII (redact-class) and encoded blobs (decoded and re-scanned)."""
    findings: list[Finding] = []
    taken: list[tuple[int, int]] = []

    def add(rule: str, cat: str, sev: str, m: re.Match[str], ptype: str) -> None:
        taken.append((m.start(), m.end()))
        findings.append(Finding(rule, cat, sev, where, mask(m.group(0)), m.start(), m.end(), ptype))

    for rule, rx in SECRET_RULES:
        for m in rx.finditer(text):
            if not _overlaps(m.start(), m.end(), taken):
                add(rule, "secret", "high", m, "SECRET")

    for m in EMAIL_RE.finditer(text):
        if not _overlaps(m.start(), m.end(), taken):
            add("pii.email", "pii", "medium", m, "EMAIL")
    for m in IBAN_RE.finditer(text):
        if not _overlaps(m.start(), m.end(), taken) and _iban_ok(m.group(0)):
            add("pii.iban", "pii", "medium", m, "IBAN")
    for m in PESEL_RE.finditer(text):
        if not _overlaps(m.start(), m.end(), taken) and _pesel_ok(m.group(0)):
            add("pii.pesel", "pii", "medium", m, "PESEL")
    for m in CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if not _overlaps(m.start(), m.end(), taken) and 13 <= len(digits) <= 19 and _luhn_ok(digits):
            add("pii.card_pan", "pii", "high", m, "PAN")
    for m in PHONE_PL_RE.finditer(text):
        if not _overlaps(m.start(), m.end(), taken):
            add("pii.phone", "pii", "medium", m, "PHONE")

    for rx in (B64_RE, HEX_RE):
        for m in rx.finditer(text):
            if _overlaps(m.start(), m.end(), taken):
                continue
            decoded = _try_decode(m.group(0)) if decode_depth > 0 else None
            inner = scan_text_dlp(decoded, where, max_encoded_len=max_encoded_len,
                                  decode_depth=decode_depth - 1) if decoded else []
            inner += scan_text_injection(decoded, where) if decoded else []
            if any(f.category in ("secret", "injection") and f.severity == "high" for f in inner):
                kinds = sorted({f.rule for f in inner if f.severity == "high"})
                taken.append((m.start(), m.end()))
                findings.append(Finding("encoded.hidden_payload", "encoded", "high", where,
                                        f"{mask(m.group(0))} decodes to {','.join(kinds)}", m.start(), m.end(), "BLOB"))
            elif len(m.group(0)) >= max_encoded_len:
                taken.append((m.start(), m.end()))
                findings.append(Finding("encoded.large_blob", "encoded", "medium", where,
                                        f"{len(m.group(0))} chars", m.start(), m.end(), "BLOB"))
    return findings


def redact(text: str, findings: list[Finding], mapping: dict[str, str], counters: dict[str, int]) -> str:
    """Replace finding spans with typed placeholders ([EMAIL_1]); same value -> same placeholder per message.

    `mapping` (value -> placeholder) stays in-process; in the gateway it is the session vault
    (research 07) so placeholders can be rehydrated toward trusted local destinations only.
    """
    spans = sorted({(f.start, f.end, f.placeholder_type) for f in findings if f.start >= 0 and f.placeholder_type},
                   reverse=True)
    for start, end, ptype in spans:
        value = text[start:end]
        if value not in mapping:
            counters[ptype] = counters.get(ptype, 0) + 1
            mapping[value] = f"[{ptype}_{counters[ptype]}]"
        text = text[:start] + mapping[value] + text[end:]
    return text


def sanitize_injection(text: str, findings: list[Finding]) -> str:
    """Neutralize injection spans in untrusted content and drop invisible characters."""
    merged: list[list[int]] = []
    for start, end in sorted((f.start, f.end) for f in findings if f.start >= 0):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    for start, end in reversed(merged):
        text = text[:start] + "[aegis:removed]" + text[end:]
    return INVISIBLE_RE.sub("", text)
