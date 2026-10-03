"""Matcher engine core: Event, RE2 helpers, matcher composition, CompiledSignature.

Ported from `staging/feed-seed/feedlib.py` (the executable reference). Changes vs. staging:
contract leaf names (old names stay as aliases), contract `Surface` values, contract action
precedence (`aegis.core.types.ACTION_PRECEDENCE`) and span-aware evidence (`start`/`end`).

A signature is *data*: nothing in a feed is ever executed, imported, unpickled or eval'd.
Feed regexes are compiled with RE2 only (linear time, no backreferences / lookaround).
"""

from __future__ import annotations

import json
import re  # only for fixed, internal patterns (never for feed-supplied regexes)
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import re2

from aegis.core.types import ACTION_PRECEDENCE

FEED_NAME = "aegis-threat-intel"
SCHEMA_VERSION = 1

STATUSES = ("experimental", "test", "stable", "deprecated", "withdrawn")
ENFORCED_STATUSES = frozenset({"test", "stable", "deprecated"})
MONITOR_STATUSES = frozenset({"experimental"})  # evaluated, logged, never enforced
FIELDS = ("all", "text", "url", "body", "filename", "bytes")

MAX_REGEX_LEN = 2048
MAX_SCAN_CHARS = 256 * 1024
MAX_JSONPATH_NODES = 10_000
MAX_MATCHER_DEPTH = 6
MAX_PICKLE_OPS = 2_000_000
MAX_ZIP_MEMBERS = 4096
MAX_ZIP_MEMBER_BYTES = 64 * 1024 * 1024
MAX_SPANS = 512

#: staging leaf names -> canonical contract names
LEAF_ALIASES: dict[str, str] = {
    "literal": "literal_set",
    "pickle_opcode": "pickle_globals",
    "jsonpath": "json_path",
    "semantic_exemplar": "semantic",
}


class FeedError(Exception):
    """A signature or bundle is invalid (schema, RE2, structure, crypto)."""


def canonical_json(obj: Any) -> bytes:
    """Bytes that are signed / hashed: sorted keys, no whitespace, UTF-8, no NaN."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


# --------------------------------------------------------------------------- events
_MISSING: Any = object()


def _safe_str(s: str) -> str:
    # Lone surrogates (possible in decoded JSON) cannot be UTF-8 encoded for RE2.
    try:
        s.encode("utf-8")
        return s
    except UnicodeEncodeError:
        return s.encode("utf-8", "replace").decode("utf-8")


def _json_strings(node: Any, out: list[str], budget: list[int]) -> None:
    if budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        cmd, args = node.get("command"), node.get("args")
        if isinstance(cmd, str) and isinstance(args, list):
            # MCP/stdio launch config -> one synthetic command line
            out.append(" ".join([cmd] + [str(a) for a in args]))
        for v in node.values():
            _json_strings(v, out, budget)
    elif isinstance(node, list):
        for v in node:
            _json_strings(v, out, budget)


@dataclass
class Event:
    """What the gateway observed at one interception point (one interaction).

    surface   contract Surface (`model.response`, `tool.input`, ...)
    text      prompt / completion / tool result / description text
    json      structured payload (tool args, MCP message, parsed HTTP JSON body, config.json)
    url       request URL (egress, model admin)
    method    HTTP method
    body      raw HTTP body (parsed into `json` automatically when it is JSON)
    filename  artifact file name
    data      artifact bytes
    all_spans collect every match span (redaction mode) instead of stopping at the first
    """

    surface: str
    text: str | None = None
    json: Any = _MISSING
    url: str | None = None
    method: str | None = None
    body: str | None = None
    filename: str | None = None
    data: bytes | None = None
    all_spans: bool = False
    _views: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.json is _MISSING and self.body:
            try:
                self.json = json.loads(self.body)
            except ValueError:
                pass

    @property
    def has_json(self) -> bool:
        return self.json is not _MISSING

    def view(self, name: str) -> str:
        if name in self._views:
            return self._views[name]
        if name == "text":
            v = self.text or ""
        elif name == "url":
            v = self.url or ""
        elif name == "body":
            v = self.body or ""
        elif name == "filename":
            v = self.filename or ""
        elif name == "bytes":
            v = self.data[:MAX_SCAN_CHARS].decode("utf-8", "replace") if self.data else ""
        elif name == "all":
            parts: list[str | None] = [self.text, self.url, self.body, self.filename]
            if self.data and not self.text:
                parts.append(self.view("bytes"))
            if self.has_json:
                strings: list[str] = []
                _json_strings(self.json, strings, [MAX_JSONPATH_NODES])
                parts.extend(strings)
                if not isinstance(self.json, str):
                    parts.append(json.dumps(self.json, ensure_ascii=False, sort_keys=True))
            seen: set[str] = set()
            out: list[str] = []
            for p in parts:
                if p and p not in seen:
                    seen.add(p)
                    out.append(p)
            v = "\n".join(out)
        else:
            raise FeedError(f"unknown field {name!r}")
        v = _safe_str(v[:MAX_SCAN_CHARS])
        self._views[name] = v
        return v


# --------------------------------------------------------------------------- helpers
def compile_re2(pattern: str, where: str, case_insensitive: bool = False) -> Any:
    if not isinstance(pattern, str) or not pattern:
        raise FeedError(f"{where}: empty pattern")
    if len(pattern) > MAX_REGEX_LEN:
        raise FeedError(f"{where}: pattern longer than {MAX_REGEX_LEN} chars")
    opts = re2.Options()
    opts.log_errors = False
    if case_insensitive:
        opts.case_sensitive = False
    try:
        return re2.compile(pattern, opts)
    except re2.error as e:  # lookaround, backrefs, {1001}, ...
        msg = e.args[0].decode() if e.args and isinstance(e.args[0], bytes) else str(e)
        raise FeedError(f"{where}: not valid RE2 syntax: {msg}") from None


def internal_re2(pattern: str) -> Any:
    return compile_re2(pattern, "<internal>")


_INVISIBLE_RANGES = (
    (0xE0000, 0xE01EF), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2069),
    (0xFEFF, 0xFEFF), (0xFE00, 0xFE0F),
)


def printable(s: str, limit: int = 140) -> str:
    """Make invisible / control characters visible for evidence output."""
    out: list[str] = []
    for ch in s:
        cp = ord(ch)
        if ch in "\n\t":
            out.append({"\n": "\\n", "\t": "\\t"}[ch])
        elif ch.isprintable() and not any(a <= cp <= b for a, b in _INVISIBLE_RANGES):
            out.append(ch)
        else:
            out.append(f"\\u{{{cp:X}}}")
        if len(out) >= limit:
            out.append("…")
            break
    return "".join(out)


def snippet(text: str, start: int, end: int) -> str:
    return printable(text[max(0, start - 24) : min(len(text), end + 24)])


Evidence = list  # list[dict]; None means "no match"
Matcher = Callable[[Event], "list[dict] | None"]
#: factory(node, where, depth, lists) -> Matcher
MatcherFactory = Callable[[dict, str, int, "dict | None"], Matcher]

#: canonical leaf type -> factory; filled by aegis.feed.matchers (merges every module's MATCHERS)
REGISTRY: dict[str, MatcherFactory] = {}


def register(matchers: dict[str, MatcherFactory]) -> None:
    REGISTRY.update(matchers)


def canonical_leaf(t: Any) -> Any:
    return LEAF_ALIASES.get(t, t) if isinstance(t, str) else t


# --------------------------------------------------------------------------- composition
def compile_matcher(
    node: Any, where: str = "match", depth: int = 0, lists: dict | None = None
) -> Matcher:
    if depth > MAX_MATCHER_DEPTH:
        raise FeedError(f"{where}: matcher nesting deeper than {MAX_MATCHER_DEPTH}")
    if not isinstance(node, dict):
        raise FeedError(f"{where}: matcher must be a mapping")
    if "any_of" in node:
        items = node["any_of"]
        if not isinstance(items, list) or not items:
            raise FeedError(f"{where}.any_of: must be a non-empty list")
        subs = [compile_matcher(n, f"{where}.any_of[{i}]", depth + 1, lists) for i, n in enumerate(items)]

        def any_of(ev: Event) -> list[dict] | None:
            if ev.all_spans:
                acc: list[dict] = []
                hit = False
                for s in subs:
                    r = s(ev)
                    if r is not None:
                        hit = True
                        acc.extend(r)
                return acc if hit else None
            for s in subs:
                r = s(ev)
                if r is not None:
                    return r
            return None

        return any_of
    if "all_of" in node:
        items = node["all_of"]
        if not isinstance(items, list) or not items:
            raise FeedError(f"{where}.all_of: must be a non-empty list")
        subs = [compile_matcher(n, f"{where}.all_of[{i}]", depth + 1, lists) for i, n in enumerate(items)]

        def all_of(ev: Event) -> list[dict] | None:
            ev_all: list[dict] = []
            for s in subs:
                r = s(ev)
                if r is None:
                    return None
                ev_all.extend(r)
            return ev_all

        return all_of
    if "not" in node:
        sub = compile_matcher(node["not"], f"{where}.not", depth + 1, lists)

        def not_(ev: Event) -> list[dict] | None:
            return [] if sub(ev) is None else None

        return not_
    t = canonical_leaf(node.get("type"))
    factory = REGISTRY.get(t) if isinstance(t, str) else None
    if factory is None:
        allowed = ", ".join(sorted(REGISTRY))
        raise FeedError(f"{where}: unknown matcher type {node.get('type')!r} (allowed: {allowed})")
    try:
        return factory(node, where, depth, lists)
    except FeedError:
        raise
    except (KeyError, TypeError, ValueError) as e:
        raise FeedError(f"{where}: invalid {t} matcher: {type(e).__name__}: {e}") from None


def iter_regexes(node: Any, where: str = "match") -> Iterable[tuple[str, str]]:
    """Yield (where, pattern) for every RE2 pattern in a matcher tree."""
    if isinstance(node, dict):
        for k in ("pattern", "path_regex", "query_regex", "host_regex"):
            if isinstance(node.get(k), str):
                yield f"{where}.{k}", node[k]
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                yield from iter_regexes(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from iter_regexes(v, f"{where}[{i}]")


def strongest(actions: Iterable[str]) -> str:
    """Contract precedence: block > require_approval > redact > log > allow."""
    best = "allow"
    for a in actions:
        if ACTION_PRECEDENCE.get(a, 0) > ACTION_PRECEDENCE[best]:
            best = a
    return best


_OWASP_RE = re.compile(r"^(LLM(0[1-9]|10):2026|ASI(0[1-9]|10)|MCP(0[1-9]|10):2025)$")


def owasp_tags(tags: Iterable[str]) -> list[str]:
    return [t for t in tags if isinstance(t, str) and _OWASP_RE.match(t)]


@dataclass
class CompiledSignature:
    """A compiled, immutable signature. `sig` is the normalized (contract-shaped) dict."""

    sig: dict
    match: Matcher
    surfaces: frozenset[str] = frozenset()

    @property
    def id(self) -> str:
        return str(self.sig["id"])

    @property
    def status(self) -> str:
        return str(self.sig.get("status", "stable"))

    @property
    def mode(self) -> str:
        return "monitor" if self.status in MONITOR_STATUSES else "enforce"

    @property
    def redact_scope(self) -> str:
        return str(self.sig.get("redact_scope") or "match")

    @property
    def redact_with(self) -> str | None:
        v = self.sig.get("redact_with")
        return None if v is None else str(v)

    def action_for(self, surface: str) -> str:
        return str((self.sig.get("action_overrides") or {}).get(surface, self.sig["action"]))

    def applies(self, surface: str) -> bool:
        return self.status != "withdrawn" and surface in self.surfaces

    def evaluate(self, ev: Event) -> dict | None:
        if not self.applies(ev.surface):
            return None
        evidence = self.match(ev)
        if evidence is None:
            return None
        return self.hit(ev.surface, evidence)

    def hit(self, surface: str, evidence: list[dict]) -> dict:
        s = self.sig
        return {
            "signature_id": self.id,
            "title": s.get("title", self.id),
            "severity": s.get("severity", "medium"),
            "aliases": list(s.get("aliases") or []),
            "tags": list(s.get("tags") or []),
            "action": self.action_for(surface),
            "mode": self.mode,
            "message": s.get("message") or s.get("title", self.id),
            "surface": surface,
            "evidence": evidence,
        }


def decide(hits: list[dict]) -> str:
    """Strongest enforced action wins; no enforced hits -> allow."""
    return strongest(h["action"] for h in hits if h.get("mode") == "enforce")
