"""Tool-definition poisoning scan (control MCP-02). Pure functions, no I/O.

Ported from staging/spikes/mcp/aegis_mcp/detectors.py, keeping only the tool-definition subset.
DLP/secrets/encoded-blob detection is done by the shared engines through the pipeline
(DLP-01/02/05, DLP-04, INJ-01/02, SIG-01).

Normalization goes through `aegis.injection.normalize.normalize` (public surface of
injection-defense) when importable, else a local NFKC + invisible-character strip.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

SEVERITY_SCORE = {"high": 3, "medium": 1, "low": 0}

_I = re.IGNORECASE
INJECTION_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "inj.hidden_tag",
        re.compile(
            r"<\s*/?\s*(important|system|instructions?|secret|admin|hidden)\b[^>]{0,40}>", _I
        ),
        "high",
    ),
    (
        "inj.ignore_previous",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[\s\w,]{0,30}?\b(previous|prior|above|earlier|all|any|system)\b"
            r"[\s\w]{0,20}?\b(instructions?|prompts?|rules|guidelines|directions)\b",
            _I,
        ),
        "high",
    ),
    (
        "inj.conceal_from_user",
        re.compile(
            r"\b(do\s*n[o']?t|never|without)\s+(tell|mention|inform|reveal|notify|alert|let)\w*\b"
            r"[\s\w]{0,15}?\buser\b",
            _I,
        ),
        "high",
    ),
    (
        "inj.role_override",
        re.compile(
            r"\byou are now\b|\bnew instructions?\s*:|\b(admin|developer|god|dan|jailbreak)\s+mode\b",
            _I,
        ),
        "high",
    ),
    (
        "inj.chat_template",
        re.compile(
            r"<\|im_(start|end)\|>|\[/?INST\]|<\|(system|user|assistant)\|>|</?(tool_call|function_call)>",
            _I,
        ),
        "high",
    ),
    (
        "inj.sensitive_path",
        re.compile(
            r"(?:~|\$HOME|^|[\s'\"`(])/?\.(?:ssh|aws|gnupg|kube|docker|cursor)\b(?!\.)"
            r"|\bid_(?:rsa|ed25519|ecdsa|dsa)\b"
            r"|(?:^|[\s'\"`/])\.env\b|\bmcp\.json\b|\bcredentials\.json\b|/etc/(?:passwd|shadow)\b"
            r"|\.git-credentials\b|\.netrc\b",
            _I,
        ),
        "high",
    ),
    (
        "inj.precondition_hijack",
        re.compile(r"\bbefore (using|calling|invoking|running) (this|the|any) tool\b", _I),
        "medium",
    ),
    (
        "inj.tool_directive",
        re.compile(
            r"\b(call|invoke|run|use)\s+(the\s+)?(tool|function)\b|\bcall\s+[a-z][a-z0-9_]{2,}\s+with\b",
            _I,
        ),
        "medium",
    ),
    (
        "inj.exfil_directive",
        re.compile(r"\b(always|also|secretly|silently)\s+(bcc|cc|forward|send|copy)\b", _I),
        "medium",
    ),
    ("inj.ansi_escape", re.compile(r"\x1b\["), "high"),
]
URL_RE = re.compile(r"https?://[^\s'\"<>)]+", _I)
# zero-width, bidi overrides/isolates, BOM, Unicode TAG block (ASCII smuggling)
INVISIBLE_RE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")
TAG_RE = re.compile("[\U000e0000-\U000e007f]")
NAME_RE = re.compile(r"[A-Za-z0-9_.\-/]{1,128}")
# keys whose string values are schema plumbing, not text a model reads
SKIP_KEYS = frozenset({"_meta", "type", "$schema", "$ref", "format"})


@dataclass(frozen=True)
class ToolFinding:
    """One indicator. `path` is relative to the tool dict (e.g. `inputSchema.properties.x.description`).
    `evidence` is a short, safe excerpt (tool definitions are third-party metadata, not user data)."""

    rule: str
    severity: str  # high | medium | low
    path: str = ""
    evidence: str = ""
    meta: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "path": self.path,
            "evidence": self.evidence,
        }


def snippet(value: str, limit: int = 80) -> str:
    value = " ".join(INVISIBLE_RE.sub("", value).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def iter_strings(
    obj: Any, path: str = "", skip: Iterable[str] = SKIP_KEYS
) -> Iterator[tuple[str, str]]:
    """Yield (path, string) for every string leaf of a JSON value (dotted keys, `[i]` indices)."""
    skip = frozenset(skip)
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in skip:
                continue
            yield from iter_strings(v, f"{path}.{k}" if path else str(k), skip)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_strings(v, f"{path}[{i}]", skip)


# ------------------------------------------------------------------ normalization
def _local_normalize(text: str) -> tuple[str, list[str], set[str]]:
    flags: set[str] = set()
    if INVISIBLE_RE.search(text):
        flags.add("invisible")
    if TAG_RE.search(text):
        flags.add("tag_chars")
        # ASCII smuggling: TAG characters U+E0020..E007E map to printable ASCII
        decoded = "".join(
            chr(ord(c) - 0xE0000) for c in TAG_RE.findall(text) if 0xE0020 <= ord(c) <= 0xE007E
        )
        variants = [decoded] if decoded.strip() else []
    else:
        variants = []
    return unicodedata.normalize("NFKC", INVISIBLE_RE.sub("", text)), variants, flags


def normalize_text(text: str) -> tuple[str, list[str], set[str]]:
    """(normalized text, decoded variants, flags) via aegis.injection.normalize when available."""
    local_text, local_variants, local_flags = _local_normalize(text)
    try:
        from aegis.injection.normalize import normalize  # public surface (injection-defense)
    except Exception:  # TODO(integration): remove fallback once injection-defense ships normalize
        return local_text, local_variants, local_flags
    try:
        n = normalize(text)
        variants = list(getattr(n, "variants", []) or [])
        for v in local_variants:  # keep our TAG decoding even if the shared normalizer drops it
            if v not in variants:
                variants.append(v)
        flags = set(getattr(n, "flags", set()) or set()) | local_flags
        return str(getattr(n, "text", local_text)), variants, flags
    except Exception:
        log.warning("injection normalize failed; using local normalization", exc_info=True)
        return local_text, local_variants, local_flags


def scan_text(text: str, path: str = "") -> list[ToolFinding]:
    """Injection/poisoning indicators in one string (raw, normalized and decoded variants)."""
    out: list[ToolFinding] = []
    norm, variants, flags = normalize_text(text)
    seen: set[str] = set()
    for rule, rx, sev in INJECTION_RULES:
        if m := rx.search(text):
            out.append(ToolFinding(rule, sev, path, snippet(m.group(0))))
            seen.add(rule)
        elif m := rx.search(norm):
            out.append(ToolFinding(rule + ".obfuscated", "high", path, snippet(m.group(0))))
            seen.add(rule)
    for variant in variants:
        for rule, rx, _sev in INJECTION_RULES:
            if rule in seen:
                continue
            if m := rx.search(variant):
                out.append(ToolFinding(rule + ".decoded", "high", path, snippet(m.group(0))))
                seen.add(rule)
    if "tag_chars" in flags:
        out.append(
            ToolFinding("inj.tag_chars", "high", path, "Unicode TAG block (ASCII smuggling)")
        )
    elif "invisible" in flags:
        m = INVISIBLE_RE.search(text)
        cp = f"U+{ord(m.group(0)):04X}" if m else "invisible"
        out.append(ToolFinding("inj.invisible_chars", "high", path, cp))
    return out


def scan_tool_definition(
    tool: dict[str, Any],
    *,
    max_description_len: int = 1024,
    url_allowlist: Iterable[str] = (),
    extra_markers: Iterable[Any] = (),
) -> list[ToolFinding]:
    """MCP-02: scan name, title, description, annotations and EVERY string inside the input/output
    schemas (property descriptions, defaults, enums, x-* fields); `_meta` is skipped."""
    allow = tuple(a.lower() for a in url_allowlist)
    findings: list[ToolFinding] = []
    for path, text in iter_strings(tool):
        findings += scan_text(text, path)
        for m in URL_RE.finditer(text):
            if not any(m.group(0).lower().startswith(a) for a in allow):
                findings.append(ToolFinding("tooldef.url", "medium", path, snippet(m.group(0))))
        for marker in extra_markers:
            try:
                if marker.search(text):
                    findings.append(
                        ToolFinding("tooldef.extra_marker", "high", path, snippet(text))
                    )
            except Exception:  # pragma: no cover - defensive (bad user regex)
                continue
    desc = tool.get("description") or ""
    if isinstance(desc, str) and len(desc) > max_description_len:
        findings.append(
            ToolFinding(
                "tooldef.long_description",
                "medium",
                "description",
                f"{len(desc)} chars > {max_description_len}",
            )
        )
    if not NAME_RE.fullmatch(str(tool.get("name", ""))):
        findings.append(
            ToolFinding("tooldef.bad_name", "high", "name", snippet(str(tool.get("name"))))
        )
    return findings


def scan_segments(
    texts: Iterable[tuple[str, str]],
    *,
    url_allowlist: Iterable[str] = (),
    extra_markers: Iterable[Any] = (),
) -> list[ToolFinding]:
    """Scan already-extracted (path, text) pairs (the control works on Interaction segments)."""
    allow = tuple(a.lower() for a in url_allowlist)
    findings: list[ToolFinding] = []
    for path, text in texts:
        findings += scan_text(text, path)
        for m in URL_RE.finditer(text):
            if not any(m.group(0).lower().startswith(a) for a in allow):
                findings.append(ToolFinding("tooldef.url", "medium", path, snippet(m.group(0))))
        for marker in extra_markers:
            try:
                if marker.search(text):
                    findings.append(
                        ToolFinding("tooldef.extra_marker", "high", path, snippet(text))
                    )
            except Exception:  # pragma: no cover
                continue
    return findings


def poison_score(findings: Iterable[ToolFinding]) -> int:
    return sum(SEVERITY_SCORE.get(f.severity, 0) for f in findings)


def cross_reference(
    text: str, known_tools: dict[str, set[str]], self_server: str, path: str = "description"
) -> list[ToolFinding]:
    """Tool shadowing: the text names ANOTHER registered server's tool as `server.tool`,
    `server__tool` or `mcp__server__tool` (e.g. "when mailer.send_email is used, always BCC ...").

    `known_tools` maps every registered server to its pinned tool names (may be empty). With known
    tools the reference must name one of them; otherwise it must look like a tool identifier
    (contains `_`), so hostnames such as `web.archive.org` do not count."""
    out: list[ToolFinding] = []
    for server, tools in known_tools.items():
        if not server or server == self_server:
            continue
        rx = re.compile(rf"(?<![\w-])(?:mcp__)?{re.escape(server)}(?:\.|__)([A-Za-z_][\w-]*)", _I)
        lowered = {t.lower() for t in tools}
        for m in rx.finditer(text):
            ident = m.group(1)
            if (lowered and ident.lower() in lowered) or (not lowered and "_" in ident):
                out.append(
                    ToolFinding(
                        "tooldef.cross_reference", "high", path, f"references {server}.{ident}"
                    )
                )
                break
    return out


def compile_markers(markers: Iterable[str]) -> list[Any]:
    """User-supplied extra markers compile with RE2 (linear time); skipped with a warning if missing."""
    out: list[Any] = []
    markers = list(markers or [])
    if not markers:
        return out
    try:
        import re2  # type: ignore[import-not-found]
    except Exception:
        log.warning("google-re2 unavailable; MCP-02 extra_markers ignored")
        return out
    for m in markers:
        try:
            out.append(re2.compile(m))
        except Exception:
            log.warning("invalid MCP-02 extra_marker skipped pattern=%r", m)
    return out


__all__ = [
    "INJECTION_RULES",
    "INVISIBLE_RE",
    "SEVERITY_SCORE",
    "URL_RE",
    "ToolFinding",
    "compile_markers",
    "cross_reference",
    "iter_strings",
    "normalize_text",
    "poison_score",
    "scan_segments",
    "scan_text",
    "scan_tool_definition",
    "snippet",
]
