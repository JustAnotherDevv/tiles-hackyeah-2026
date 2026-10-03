"""URL / host canonicalization and SSRF checks (pure, no I/O, no DNS by default).

Handles the classic SSRF evasions: userinfo (``good@169.254.169.254``), backslash confusion,
percent-encoding, trailing dots, fullwidth digits (NFKC), decimal ``2130706433``, octal
``0177.0.0.1``, hex ``0x7f000001`` / ``0x7f.1``, short ``127.1``, IPv6 ``[::1]``, IPv4-mapped
``[::ffff:a9fe:a9fe]`` and rebinding helper domains (``10.0.0.1.nip.io``).
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from urllib.parse import unquote

IPAddr = ipaddress.IPv4Address | ipaddress.IPv6Address

ALWAYS_BLOCKED_SCHEMES = frozenset(
    {"file", "gopher", "dict", "ftp", "ldap", "ldaps", "jar", "netdoc", "tftp", "smb", "sftp"}
)
DEFAULT_METADATA_HOSTS = (
    "169.254.169.254",
    "fd00:ec2::254",
    "metadata.google.internal",
    "metadata",
    "instance-data",
    "100.100.100.200",
    "169.254.170.2",
)
_LOOPBACK_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_REBIND_RX = re.compile(
    r"(?:^|\.)((?:\d{1,3}[.-]){3}\d{1,3})\.(?:nip\.io|sslip\.io|xip\.io|nip\.direct|traefik\.me)$"
)
_SCHEME_RX = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
URL_RX = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]{1,15}://[^\s'\"<>|;`)]+")


def domain_match(pattern: str, host: str | None) -> bool:
    """Host glob with apex semantics: ``*.x`` matches ``a.x`` and ``x`` itself."""
    if not host or not pattern:
        return False
    h = host.lower().rstrip(".")
    p = pattern.lower().strip()
    if p.startswith("*."):
        return h == p[2:] or h.endswith(p[1:])
    return fnmatchcase(h, p)


# ------------------------------------------------------------------ IP parsing
def _int_part(part: str) -> int | None:
    p = part.strip().lower()
    if not p:
        return None
    try:
        if p.startswith("0x"):
            return int(p[2:] or "0", 16)
        if len(p) > 1 and p.startswith("0"):
            return int(p, 8)
        return int(p, 10)
    except ValueError:
        return None


def parse_inet_aton(host: str) -> ipaddress.IPv4Address | None:
    """BSD ``inet_aton`` semantics: 1-4 parts, each decimal/octal/hex; last part fills the rest."""
    if not host or not re.fullmatch(r"[0-9a-fA-Fx.]+", host) or host.count(".") > 3:
        return None
    parts = host.split(".")
    if parts and parts[-1] == "":
        parts = parts[:-1]
    nums = [_int_part(p) for p in parts]
    if not nums or any(n is None for n in nums):
        return None
    vals: list[int] = [n for n in nums if n is not None]
    widths = {1: [32], 2: [8, 24], 3: [8, 8, 16], 4: [8, 8, 8, 8]}[len(vals)]
    total = 0
    for v, w in zip(vals, widths, strict=True):
        if v >= (1 << w):
            return None
        total = (total << w) | v
    return ipaddress.IPv4Address(total)


def canonical_ip(host: str | None) -> IPAddr | None:
    """IP address behind ``host`` (any encoding), IPv4-mapped IPv6 unwrapped; else None."""
    if not host:
        return None
    h = host.strip().lower().rstrip(".")
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    h = h.split("%", 1)[0]  # IPv6 zone id
    try:
        ip: IPAddr = ipaddress.ip_address(h)
    except ValueError:
        v4 = parse_inet_aton(h)
        if v4 is None:
            m = _REBIND_RX.search(h)
            if m:
                return canonical_ip(m.group(1).replace("-", "."))
            return None
        ip = v4
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
    return ip


def ip_class(ip: IPAddr) -> str | None:
    """Why an IP is not a public destination (None = public)."""
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_multicast:
        return "multicast"
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
        return "shared (CGNAT)"
    if ip.is_private:
        return "private"
    if ip.is_reserved:
        return "reserved"
    return None


# ------------------------------------------------------------------ URL parsing
@dataclass
class ParsedUrl:
    raw: str
    scheme: str
    hosts: list[str] = field(default_factory=list)  # candidate hosts (all interpretations)
    port: int | None = None
    userinfo: bool = False
    path: str = "/"

    @property
    def host(self) -> str | None:
        return self.hosts[0] if self.hosts else None


def _clean_host(h: str) -> str:
    h = unicodedata.normalize("NFKC", unquote(h)).strip().lower()
    h = h.replace("。", ".").replace("．", ".")
    return h.rstrip(".")


def _split_authority(auth: str) -> tuple[str, int | None, bool]:
    userinfo = "@" in auth
    hostport = auth.rsplit("@", 1)[-1]
    port: int | None = None
    if hostport.startswith("["):
        end = hostport.find("]")
        host = hostport[: end + 1] if end != -1 else hostport
        rest = hostport[end + 1 :] if end != -1 else ""
        if rest.startswith(":") and rest[1:].isdigit():
            port = int(rest[1:])
    else:
        host, sep, p = hostport.rpartition(":")
        if sep and p.isdigit():
            port = int(p)
        else:
            host = hostport
    return host, port, userinfo


def parse_url(url: str) -> ParsedUrl | None:
    """Parse ``url`` (scheme optional; default http) into candidate hosts. None if hopeless."""
    if not isinstance(url, str):
        return None
    raw = unicodedata.normalize("NFKC", url.strip())
    if not raw:
        return None
    scheme = "http"
    rest = raw
    m = _SCHEME_RX.match(raw)
    if m:
        cand = m.group(1).lower()
        after = raw[m.end() :]
        if after.startswith("//") or after.startswith("\\\\") or cand in ALWAYS_BLOCKED_SCHEMES:
            scheme = cand
            rest = after
        elif not after[:1].isdigit():  # e.g. "mailto:x" or "javascript:..."
            scheme = cand
            rest = after
    rest = rest.lstrip("/\\") if rest.startswith(("//", "\\\\")) else rest
    # (a) WHATWG-ish: backslash acts as a path separator
    auth_a = re.split(r"[/\\?#]", rest, maxsplit=1)[0]
    # (b) RFC-ish (python/curl): backslash belongs to the authority
    auth_b = re.split(r"[/?#]", rest, maxsplit=1)[0]
    hosts: list[str] = []
    port: int | None = None
    userinfo = False
    for auth in (auth_b, auth_a):
        host, p, ui = _split_authority(auth)
        host = _clean_host(host)
        userinfo = userinfo or ui
        if p is not None and port is None:
            port = p
        if host and host not in hosts:
            hosts.append(host)
    path_part = rest[len(auth_a) :]
    path = "/" + path_part.lstrip("/") if path_part else "/"
    if port is None:
        port = {"https": 443, "http": 80, "ftp": 21, "gopher": 70}.get(scheme)
    return ParsedUrl(raw=raw, scheme=scheme, hosts=hosts, port=port, userinfo=userinfo, path=path)


def host_of(url: str | None) -> str | None:
    p = parse_url(url) if url else None
    return p.host if p else None


def extract_urls(text: str | None) -> list[str]:
    return URL_RX.findall(text or "")


def host_port_match(spec: str, host: str, port: int | None, ip: IPAddr | None = None) -> bool:
    """``spec`` = ``host``, ``host:port`` or ``host:lo-hi`` (host may be a glob or an IP)."""
    s = spec.strip().lower()
    sh, sep, sp = s.rpartition(":")
    if not sep or not re.fullmatch(r"\d+(-\d+)?", sp) or sh.endswith(":"):
        sh, sp = s, ""
    if sh.startswith("[") and sh.endswith("]"):
        sh = sh[1:-1]
    host_ok = domain_match(sh, host) or (ip is not None and canonical_ip(sh) == ip)
    if not host_ok:
        return False
    if not sp:
        return True
    if port is None:
        return False
    lo, _, hi = sp.partition("-")
    return int(lo) <= port <= int(hi or lo)


@dataclass
class NetCheck:
    ok: bool
    rule: str = ""  # scheme | metadata | loopback | private | link-local | deny_host | not_allowlisted | unparseable
    detail: str = ""
    host: str | None = None
    port: int | None = None
    ip: str | None = None


def check_url(
    url: str,
    *,
    allowed_schemes: list[str] | tuple[str, ...] = ("http", "https"),
    block_private_ranges: bool = True,
    metadata_hosts: list[str] | tuple[str, ...] = DEFAULT_METADATA_HOSTS,
    allow_hosts: list[str] | tuple[str, ...] = (),
    deny_hosts: list[str] | tuple[str, ...] = (),
    egress_allowlist: list[str] | tuple[str, ...] = (),
    internal_domains: list[str] | tuple[str, ...] = (),
) -> NetCheck:
    """Decide whether an agent may reach ``url``. First failing rule wins."""
    parsed = parse_url(url)
    if parsed is None or not parsed.hosts:
        if parsed is not None and parsed.scheme in ALWAYS_BLOCKED_SCHEMES:
            return NetCheck(False, "scheme", f"{parsed.scheme}: URLs are never allowed")
        return NetCheck(True, "unparseable")
    scheme = parsed.scheme
    if scheme in ALWAYS_BLOCKED_SCHEMES:
        return NetCheck(False, "scheme", f"{scheme}: URLs are never allowed", parsed.host, parsed.port)
    if allowed_schemes and scheme not in {s.lower() for s in allowed_schemes}:
        return NetCheck(False, "scheme", f"scheme {scheme} is not allowed", parsed.host, parsed.port)
    meta = {m.lower() for m in metadata_hosts}
    meta_ips = {canonical_ip(m) for m in metadata_hosts} - {None}
    for host in parsed.hosts:
        ip = canonical_ip(host)
        allowed = any(host_port_match(a, host, parsed.port, ip) for a in allow_hosts)
        if host in meta or (ip is not None and ip in meta_ips):
            if not allowed:
                return NetCheck(False, "metadata", "cloud metadata endpoint", host, parsed.port, str(ip) if ip else None)
        if block_private_ranges and not allowed:
            if ip is not None:
                cls = ip_class(ip)
                if cls:
                    note = "" if str(ip) == host else f" (decodes to {ip})"
                    return NetCheck(False, cls if cls in ("loopback", "link-local") else "private",
                                    f"{cls} address{note}", host, parsed.port, str(ip))
            elif host in _LOOPBACK_NAMES or host.endswith(".localhost"):
                return NetCheck(False, "loopback", "loopback host name", host, parsed.port)
        if any(domain_match(d, host) for d in deny_hosts):
            return NetCheck(False, "deny_host", "host is on the deny list", host, parsed.port)
        if egress_allowlist and not allowed:
            internal = any(domain_match(d, host) for d in internal_domains)
            local = ip is not None and ip_class(ip) is not None
            if not internal and not local and not any(domain_match(a, host) for a in egress_allowlist):
                return NetCheck(False, "not_allowlisted", "host is not on destinations.egress_allowlist",
                                host, parsed.port)
    return NetCheck(True, "", "", parsed.host, parsed.port)


__all__ = [
    "ALWAYS_BLOCKED_SCHEMES",
    "DEFAULT_METADATA_HOSTS",
    "NetCheck",
    "ParsedUrl",
    "canonical_ip",
    "check_url",
    "domain_match",
    "extract_urls",
    "host_of",
    "host_port_match",
    "ip_class",
    "parse_inet_aton",
    "parse_url",
]
