"""Text metadata detectors for DLP-03: user paths, internal hostnames, private IPs, git
identities and learned identifiers. Pure, synchronous, deterministic; regexes are bounded.

Ported from `staging/pii/detectors.py` (PATH_USER, path_user_allow, IPV4/IPV6, VERSION_TAIL),
adapted to contract entities (`USERNAME`, `HOSTNAME`, `IP_ADDRESS`, `GIT_EMAIL`).
"""

from __future__ import annotations

import ipaddress
import re
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from aegis.egress.compat import host_matches

# ---------------------------------------------------------------- span type
GENERALIZED = {
    "USERNAME": "[USERNAME]",
    "HOSTNAME": "[HOST]",
    "IP_ADDRESS": "[PRIVATE_IP]",
    "GIT_EMAIL": "[GIT_EMAIL]",
    "EMAIL": "[EMAIL]",
    "MAC_ADDRESS": "[MAC]",
}
DATA_CLASS = {"EMAIL": "CONFIDENTIAL"}


@dataclass(slots=True)
class MetaSpan:
    """One metadata hit in a text. `value` is local-only (never logged / persisted)."""

    start: int
    end: int
    entity: str
    detector: str
    value: str
    replacement: str | None = None  # None => vault placeholder (reversible)
    score: float = 1.0
    category: str = "metadata"
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def data_class(self) -> str:
        return DATA_CLASS.get(self.entity, "INTERNAL")


# ---------------------------------------------------------------- regexes (bounded)
PATH_USER = re.compile(
    r"(?:/Users/|/home/|[A-Za-z]:(?:\\\\|\\|/)(?i:users)(?:\\\\|\\|/))([^/\\\s\"'<>:|*?`;,)(\]\[]{1,64})")
PATH_USER_ALLOW = frozenset({
    "shared", "root", "runner", "public", "default", "all users", "user", "username", "<user>",
    "$user", "${user}", "%username%", "you", "yourname", "your-name", "guest", "me", "name",
    "<username>", "ubuntu", "admin", "users", "home", "example", "someone", "default user",
    "linuxbrew", "[username]", "...", "…",
})
IPV4 = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}")
IPV6 = re.compile(r"(?:[0-9A-Fa-f]{0,4}:){2,7}(?:[0-9A-Fa-f]{1,4}|[0-9]{1,3}(?:\.[0-9]{1,3}){3})?")
VERSION_TAIL = re.compile(
    r"(?i:version|wersja|wersji|ver|v|release|build|firmware|python|node|java|golang|ruby|php|libc|"
    r"kernel|chrome|safari|firefox|edge)[ \t:=/]{0,3}$|(?:==|>=|<=|~=|\^|@|~)[ \t]*$")
FQDN = re.compile(
    r"(?<![A-Za-z0-9_\-@])((?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.){1,8}"
    r"[A-Za-z][A-Za-z0-9\-]{0,61}[A-Za-z0-9])(?![A-Za-z0-9\-])")
MACHINE = re.compile(
    r"(?<![A-Za-z0-9_\-.@/])([A-Za-z][A-Za-z0-9]{0,30}(?:[-_'][A-Za-z0-9]{1,30}){0,3}[-_]"
    r"(?i:mbp|macbook(?:-pro|-air)?|imac|mac-?mini|laptop|desktop|pc|ws|workstation|thinkpad)"
    r"[0-9]{0,3})(?![A-Za-z0-9_\-])")
GIT_USER = re.compile(r"(?m)^[ \t]*Git user:[ \t]*([^\n<>]{1,80}?)[ \t]*$")
GIT_AUTHOR = re.compile(
    r"(?m)^[ \t]*(?:Author|Commit|Committer|AuthorName|CommitterName)[ \t]*:[ \t]*"
    r"([^\n<>]{1,80}?)[ \t]*<([^\s<>@]{1,64}@[^\s<>]{1,190})>")
GIT_CONFIG = re.compile(r"(?m)\buser\.(name|email)[ \t]*=[ \t]*\"?([^\n\"]{1,120}?)\"?[ \t]*$")
MAC = re.compile(
    r"(?<![0-9A-Fa-f:\-.])((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}|(?:[0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}"
    r"|[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})(?![0-9A-Fa-f:\-.])")
EMAILISH = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}$")


def _private_ip(s: str, *, loopback: bool) -> bool:
    try:
        ip = ipaddress.ip_address(s)
    except ValueError:
        return False
    if ip.is_unspecified or ip.is_multicast:
        return False
    if ip.is_loopback:
        return loopback
    if ip.version == 4 and ip in _CGNAT:
        return True
    return bool(ip.is_private or ip.is_link_local)


_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _alnum(c: str) -> bool:
    return c.isalnum() or c == "_"


# ---------------------------------------------------------------- excerpt masking
def mask_excerpt(entity: str, value: str) -> str:
    """Type-aware irreversible masking for `Finding.excerpt` (never the raw value)."""
    v = value.strip()
    if not v:
        return f"[{entity}]"
    if entity in ("EMAIL", "GIT_EMAIL") and "@" in v:
        local, _, dom = v.partition("@")
        return f"{local[:1]}***@{dom[:1]}***"
    if entity == "IP_ADDRESS":
        if ":" in v:
            return v.split(":", 1)[0] + ":…"
        return v.split(".", 1)[0] + ".x.x.x"
    if entity == "HOSTNAME":
        parts = v.split(".")
        if len(parts) >= 3:
            return "***." + ".".join(parts[-2:])
        return v[:1] + "***"
    if entity == "FILE_PATH":
        return "…/" + v.rsplit("/", 1)[-1][:24]
    return v[:1] + "***"


# ---------------------------------------------------------------- detectors
def find_path_users(text: str, *, allow: Iterable[str] = (), style: str = "placeholder"
                    ) -> list[MetaSpan]:
    if "/Users/" not in text and "/home/" not in text and ":\\" not in text and ":/" not in text:
        return []
    allow_l = PATH_USER_ALLOW | {a.lower() for a in allow}
    out: list[MetaSpan] = []
    for m in PATH_USER.finditer(text):
        u = m.group(1)
        if u.lower() in allow_l or u.startswith(("$", "%", "<", "{", "[", ".", "~")):
            continue
        if u.isdigit():
            continue
        if style == "generalize":
            out.append(MetaSpan(m.start(), m.end(1), "USERNAME", "meta.path_username", u, "~",
                                0.9, meta={"learn": u}))
        else:
            out.append(MetaSpan(m.start(1), m.end(1), "USERNAME", "meta.path_username", u, None,
                                0.9, meta={"learn": u}))
    return out


def find_hostnames(text: str, *, internal_domains: Iterable[str], suffixes: Iterable[str],
                   style: str = "placeholder") -> list[MetaSpan]:
    out: list[MetaSpan] = []
    repl = GENERALIZED["HOSTNAME"] if style == "generalize" else None
    doms = list(internal_domains)
    sufs = tuple(s.lower() if s.startswith(".") else "." + s.lower() for s in suffixes)
    if "." in text:
        for m in FQDN.finditer(text):
            a, b = m.span(1)
            prev = text[a - 1] if a > 0 else ""
            if prev in ".\\" or (prev == "/" and text[max(0, a - 2):a] != "//"):
                continue
            host = m.group(1)
            h = host.lower()
            if not host_matches(doms, h):
                suf = next((s for s in sufs if h.endswith(s)), None)
                if suf is None:
                    continue
                head = h[: -len(suf)]
                # one bare label + suffix ("settings.local") is usually a file name: require a
                # machine-like label (digit or hyphen) unless there are >= 2 labels.
                if "." not in head and not any(c.isdigit() or c == "-" for c in head):
                    continue
            out.append(MetaSpan(a, b, "HOSTNAME", "meta.hostname", host, repl, 0.85))
    if "-" in text or "_" in text:
        for m in MACHINE.finditer(text):
            a, b = m.span(1)
            out.append(MetaSpan(a, b, "HOSTNAME", "meta.hostname", m.group(1), repl, 0.8))
    return out


def find_private_ips(text: str, *, style: str = "placeholder", loopback: bool = False
                     ) -> list[MetaSpan]:
    out: list[MetaSpan] = []
    repl = GENERALIZED["IP_ADDRESS"] if style == "generalize" else None
    n = len(text)
    if "." in text:
        for m in IPV4.finditer(text):
            a, b = m.span()
            if a > 0 and (_alnum(text[a - 1]) or text[a - 1] == "."):
                continue
            if b < n and (text[b].isdigit() or (text[b] == "." and b + 1 < n and text[b + 1].isdigit())):
                continue
            if VERSION_TAIL.search(text, max(0, a - 16), a):
                continue
            if _private_ip(m.group(0), loopback=loopback):
                out.append(MetaSpan(a, b, "IP_ADDRESS", "meta.private_ip", m.group(0), repl, 0.9))
    if text.count(":") >= 2:
        for m in IPV6.finditer(text):
            a, b = m.span()
            s = m.group(0)
            if s.endswith(":") and not s.endswith("::"):
                s, b = s[:-1], b - 1
            if s.count(":") < 2 or len(s) < 3:
                continue
            if a > 0 and (_alnum(text[a - 1]) or text[a - 1] in ":."):
                continue
            if b < n and (_alnum(text[b]) or text[b] == ":"):
                continue
            if _private_ip(s, loopback=loopback):
                out.append(MetaSpan(a, b, "IP_ADDRESS", "meta.private_ip", s, repl, 0.85))
    return out


def find_macs(text: str, *, style: str = "placeholder") -> list[MetaSpan]:
    if ":" not in text and "-" not in text and "." not in text:
        return []
    repl = GENERALIZED["MAC_ADDRESS"] if style == "generalize" else None
    out: list[MetaSpan] = []
    for m in MAC.finditer(text):
        v = m.group(1)
        hexd = re.sub(r"[^0-9A-Fa-f]", "", v)
        if len(set(hexd.lower())) <= 1:  # 00:00:00:00:00:00, ff:ff:... are not device ids
            continue
        if not any(c.isdigit() for c in hexd):  # "dead-beef-cafe"-style words
            continue
        out.append(MetaSpan(m.start(1), m.end(1), "MAC_ADDRESS", "meta.mac_address", v, repl, 0.9))
    return out


def find_git_identities(text: str, *, style: str = "placeholder") -> list[MetaSpan]:
    out: list[MetaSpan] = []
    gen = style == "generalize"
    if "Git user:" in text:
        for m in GIT_USER.finditer(text):
            name = m.group(1).strip()
            if name:
                out.append(MetaSpan(m.start(1), m.start(1) + len(name), "USERNAME", "meta.git_user",
                                    name, GENERALIZED["USERNAME"] if gen else None, 0.95,
                                    meta={"learn": name}))
    if "<" in text and "@" in text:
        for m in GIT_AUTHOR.finditer(text):
            name = m.group(1).strip()
            if name:
                out.append(MetaSpan(m.start(1), m.start(1) + len(name), "USERNAME",
                                    "meta.git_author", name,
                                    GENERALIZED["USERNAME"] if gen else None, 0.9,
                                    meta={"learn": name}))
            out.append(MetaSpan(m.start(2), m.end(2), "GIT_EMAIL", "meta.git_email", m.group(2),
                                GENERALIZED["GIT_EMAIL"] if gen else None, 0.95))
    if "user." in text:
        for m in GIT_CONFIG.finditer(text):
            val = m.group(2).strip()
            if not val:
                continue
            if m.group(1) == "email" and EMAILISH.match(val):
                out.append(MetaSpan(m.start(2), m.start(2) + len(val), "GIT_EMAIL",
                                    "meta.git_email", val,
                                    GENERALIZED["GIT_EMAIL"] if gen else None, 0.95))
            elif m.group(1) == "name":
                out.append(MetaSpan(m.start(2), m.start(2) + len(val), "USERNAME",
                                    "meta.git_user", val,
                                    GENERALIZED["USERNAME"] if gen else None, 0.9,
                                    meta={"learn": val}))
    return out


@lru_cache(maxsize=256)
def _identifier_regex(idents: frozenset[str]) -> re.Pattern[str] | None:
    if not idents:
        return None
    alts = "|".join(re.escape(i) for i in sorted(idents, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alts})(?![A-Za-z0-9])", re.IGNORECASE)


def usable_identifier(value: str, *, min_len: int = 4, allow: Iterable[str] = ()) -> bool:
    v = value.strip()
    if len(v) < min_len or len(v) > 64:
        return False
    low = v.lower()
    if low in PATH_USER_ALLOW or low in {a.lower() for a in allow}:
        return False
    return any(c.isalpha() for c in v)


def find_learned(text: str, identifiers: Iterable[str], *, style: str = "placeholder"
                 ) -> list[MetaSpan]:
    rx = _identifier_regex(frozenset(identifiers))
    if rx is None:
        return []
    repl = GENERALIZED["USERNAME"] if style == "generalize" else None
    return [MetaSpan(m.start(), m.end(), "USERNAME", "meta.learned_identifier", m.group(0), repl,
                     0.8) for m in rx.finditer(text)]


# ---------------------------------------------------------------- overlap resolution
def resolve_overlaps(spans: list[MetaSpan]) -> list[MetaSpan]:
    """Longest span wins (then earliest, then higher score); result sorted by start."""
    if len(spans) <= 1:
        return [s for s in spans if s.end > s.start]
    ordered = sorted(spans, key=lambda s: (-(s.end - s.start), s.start, -s.score))
    starts: list[int] = []  # kept spans never overlap -> sorted by start == sorted by end
    kept: list[MetaSpan] = []
    for s in ordered:
        if s.end <= s.start:
            continue
        i = bisect_right(starts, s.start)
        if i > 0 and kept[i - 1].end > s.start:
            continue
        if i < len(kept) and kept[i].start < s.end:
            continue
        starts.insert(i, s.start)
        kept.insert(i, s)
    return kept


# ---------------------------------------------------------------- facade
def scan_text(text: str, *, internal_domains: Iterable[str] = (), params: Any = None,
              identifiers: Iterable[str] = (), style: str = "placeholder",
              learned: bool = True) -> list[MetaSpan]:
    """All text metadata spans of one text, overlaps resolved.

    `params` is a `TextParams` (or None for defaults). `identifiers` = learned identifiers to
    scrub (boundary-delimited). Spans carrying `meta["learn"]` are candidates for learning.
    """
    from aegis.egress.params import TextParams

    p = params if params is not None else TextParams()
    if not text or not p.enabled:
        return []
    spans: list[MetaSpan] = []
    if p.paths:
        spans += find_path_users(text, allow=p.user_allowlist, style=style)
    if p.hostnames:
        spans += find_hostnames(text, internal_domains=internal_domains,
                                suffixes=p.internal_suffixes, style=style)
    if p.private_ips:
        spans += find_private_ips(text, style=style,
                                  loopback=bool(getattr(p, "loopback", False)))
    if getattr(p, "mac_addresses", True):
        spans += find_macs(text, style=style)
    if p.git:
        spans += find_git_identities(text, style=style)
    if learned and p.learn_identifiers:
        idents = [i for i in identifiers
                  if usable_identifier(i, min_len=p.min_identifier_len, allow=p.user_allowlist)]
        spans += find_learned(text, idents, style=style)
    return resolve_overlaps(spans)


def learnable(spans: Iterable[MetaSpan], *, min_len: int = 4, allow: Iterable[str] = ()
              ) -> list[str]:
    out: list[str] = []
    for s in spans:
        v = s.meta.get("learn")
        if v and usable_identifier(v, min_len=min_len, allow=allow) and v not in out:
            out.append(v)
    return out
