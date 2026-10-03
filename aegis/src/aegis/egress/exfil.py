"""DLP-04 exfiltration analysis: URLs in tool args / egress requests, DNS-label tricks,
OAST hosts, userinfo host confusion, IP-literal forms, encoded query/path values and
encoded argument blobs. Scores per research 01 / plan 04 §2.5. Never logs values.
"""

from __future__ import annotations

import base64
import ipaddress
import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any
from urllib.parse import parse_qsl, unquote

from aegis.egress.compat import any_glob, host_matches
from aegis.egress.encoded import (
    decode_layers,
    entropy,
    looks_like_words,
    printable_ratio,
    sensitive_hits,
)

URL_RX = re.compile(r"(?i)\b(?:https?|wss?|ftp)://[^\s\"'<>|\\]{1,4096}")
SHELL_NET = re.compile(
    r"(?i)\b(?:curl|wget|http|https|nc|ncat|telnet|ping|nslookup|dig|host)\b[^\n;|&]{0,512}")
BARE_HOST = re.compile(r"(?<![\w./@-])((?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.){1,8}[a-z]{2,24}"
                       r"(?::\d{1,5})?(?:/[^\s\"'<>|;&]{0,2048})?)", re.I)
BLOB_RX = re.compile(r"[A-Za-z0-9+/_\-]{32,}={0,2}")
MEDIA_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"%PDF", b"PK\x03\x04", b"GIF8", b"RIFF")
DECODE_MIN_LABEL = 12


@dataclass(slots=True)
class UrlRef:
    path: str
    url: str
    in_shell: bool = False


@dataclass(slots=True)
class ExfilHit:
    channel: str
    score: float
    host: str | None = None
    detail: str = ""
    decoded_kinds: list[str] = field(default_factory=list)
    category: str = "exfil"
    path: str | None = None
    url: str | None = None  # local only; findings carry mask_url()


@cache
def builtin_exfil_hosts() -> tuple[str, ...]:
    try:
        text = resources.files("aegis.egress").joinpath("data/exfil_hosts.txt").read_text()
    except Exception:
        return ()
    return tuple(ln.strip().lower() for ln in text.splitlines()
                 if ln.strip() and not ln.lstrip().startswith("#"))


# ---------------------------------------------------------------- URL parsing
@dataclass(slots=True)
class ParsedUrl:
    scheme: str
    userinfo: str | None
    host: str
    port: str | None
    path: str
    query: str
    fragment: str


def parse_url(url: str) -> ParsedUrl | None:
    """Manual authority parse (urlsplit hides some host-confusion tricks)."""
    m = re.match(r"(?i)^([a-z][a-z0-9+.\-]{0,15}):(//)?", url)
    if not m:
        return None
    scheme = m.group(1).lower()
    rest = url[m.end():]
    frag = ""
    if "#" in rest:
        rest, frag = rest.split("#", 1)
    query = ""
    if "?" in rest:
        rest, query = rest.split("?", 1)
    slash = rest.find("/")
    authority, path = (rest, "") if slash < 0 else (rest[:slash], rest[slash:])
    userinfo = None
    if "@" in authority:
        userinfo, authority = authority.rsplit("@", 1)
    host, port = authority, None
    if host.startswith("["):
        end = host.find("]")
        host, tail = host[1:end] if end > 0 else host[1:], host[end + 1:] if end > 0 else ""
        port = tail[1:] if tail.startswith(":") else None
    elif host.count(":") == 1:
        host, port = host.split(":", 1)
    return ParsedUrl(scheme, userinfo, host.lower().rstrip("."), port, path, query, frag)


def mask_url(url: str) -> str:
    """`https://host/…?<3 params>` — safe for findings, logs and SSE (no values)."""
    p = parse_url(url)
    if p is None:
        return "<url>"
    out = f"{p.scheme}://{'<userinfo>@' if p.userinfo is not None else ''}{p.host}"
    if p.port:
        out += f":{p.port}"
    if p.path and p.path != "/":
        out += "/…"
    if p.query:
        n = len(parse_qsl(p.query, keep_blank_values=True)) or 1
        out += f"?<{n} param{'s' if n != 1 else ''}>"
    if p.fragment:
        out += "#<fragment>"
    return out


def _ip_literal(host: str) -> tuple[float, str] | None:
    if not host:
        return None
    if re.fullmatch(r"\d{4,10}", host):
        return 0.85, "decimal IPv4 host"
    parts = host.split(".")
    if 1 <= len(parts) <= 4 and all(re.fullmatch(r"0x[0-9a-f]{1,8}|0[0-7]{1,11}|\d{1,10}", p)
                                    for p in parts):
        if any(p.startswith("0x") or (len(p) > 1 and p.startswith("0")) for p in parts):
            return 0.85, "hex/octal IPv4 host"
    try:
        ipaddress.ip_address(host)
        return 0.6, "IP literal host"
    except ValueError:
        return None


def _label_decodes(label: str) -> tuple[str | None, str | None]:
    """(kind, text) if a DNS label decodes (base32 / hex / base64url) to printable ≥ 8 chars."""
    lab = label.strip()
    cands: list[tuple[str, bytes]] = []
    if re.fullmatch(r"[a-z2-7]+", lab, re.I):
        try:
            cands.append(("base32", base64.b32decode(lab.upper() + "=" * (-len(lab) % 8))))
        except Exception:
            pass
    if re.fullmatch(r"(?:[0-9a-f]{2})+", lab, re.I):
        try:
            cands.append(("hex", bytes.fromhex(lab)))
        except ValueError:
            pass
    if re.fullmatch(r"[A-Za-z0-9_\-]+", lab):
        try:
            cands.append(("base64url", base64.urlsafe_b64decode(lab + "=" * (-len(lab) % 4))))
        except Exception:
            pass
    for kind, raw in cands:
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if len(txt) >= 8 and printable_ratio(txt) >= 0.95 and sum(
                c.isalnum() or c in " .,:;-_@/" for c in txt) / len(txt) >= 0.9:
            return kind, txt
    return None, None


def _registrable_split(host: str) -> list[str]:
    """Labels left of the registrable domain (approximation: last two labels, three for
    common two-level public suffixes)."""
    labels = host.split(".")
    keep = 3 if len(labels) >= 3 and labels[-2] in {"co", "com", "org", "net", "gov", "ac"} \
        and len(labels[-1]) == 2 else 2
    return labels[:-keep] if len(labels) > keep else []


def _value_hits(value: str, *, where: str, host: str, params: Any, trusted: bool,
                rt: Any) -> list[ExfilHit]:
    hits: list[ExfilHit] = []
    v = value
    if len(v) >= params.url_encoded_min_len:
        for d in decode_layers(v, params.decode_depth, min_len=params.url_encoded_min_len):
            kinds = sensitive_hits(d.text, rt)
            if kinds:
                hits.append(ExfilHit("decoded_sensitive", 1.0, host,
                                     f"{where} decodes ({d.kind}) to {', '.join(kinds)}",
                                     kinds))
                break
    if not hits and not trusted and len(v) >= 32 and not looks_like_words(unquote(v)):
        if entropy(v) >= params.blob_entropy_min and BLOB_RX.fullmatch(v.strip()):
            hits.append(ExfilHit("query_blob", 0.7, host, f"high-entropy {where} ({len(v)} chars)"))
    return hits


def analyze_url(url: str, *, params: Any, allowlist: list[str] | tuple[str, ...] = (),
                in_shell: bool = False, rt: Any | None = None) -> list[ExfilHit]:
    p = parse_url(url)
    if p is None or not p.host:
        return []
    host = p.host
    hits: list[ExfilHit] = []
    allowlisted = host_matches(allowlist, host)
    if allowlist and not allowlisted:
        hits.append(ExfilHit("allowlist", 1.0, host, f"host {host} not in egress_allowlist",
                             category="scope"))
    if p.userinfo is not None:
        hits.append(ExfilHit("userinfo", 0.9, host,
                             "userinfo before host (host confusion)"))
    oast = tuple(builtin_exfil_hosts()) + tuple(x.lower() for x in params.exfil_hosts_extra)
    if host_matches(oast, host):
        hits.append(ExfilHit("oast_host", 1.0, host, f"known exfil/OAST host {host}"))
    ipl = _ip_literal(host)
    if ipl and not allowlisted:
        hits.append(ExfilHit("ip_literal", ipl[0], host, ipl[1]))
    if not allowlisted and any(lab.startswith("xn--") for lab in host.split(".")):
        hits.append(ExfilHit("idn", 0.6, host, "punycode (possible homograph) host"))
    if in_shell and any(tok in url for tok in ("$(", "`", "${")):
        hits.append(ExfilHit("shell_subst", 0.9, host, "shell substitution inside URL"))
    # ---- DNS labels
    if ipl is None:
        sub = _registrable_split(host)
        if len(host.split(".")) > params.dns_max_labels:
            hits.append(ExfilHit("dns_label", 0.6, host, "many DNS labels"))
        for lab in sub:
            if len(lab) > params.dns_label_max:
                hits.append(ExfilHit("dns_label", 0.9, host, f"DNS label of {len(lab)} chars"))
            kind, txt = (_label_decodes(lab) if len(lab) >= DECODE_MIN_LABEL else (None, None))
            if txt:
                kinds = sensitive_hits(txt, rt)
                if kinds:
                    hits.append(ExfilHit("decoded_sensitive", 1.0, host,
                                         f"DNS label decodes ({kind}) to {', '.join(kinds)}",
                                         kinds))
                else:
                    hits.append(ExfilHit("dns_label", 0.9, host, f"DNS label decodes ({kind})"))
            elif (len(lab) >= 20 and "-" not in lab and sum(c.isdigit() for c in lab) >= 2
                  and entropy(lab) >= params.dns_label_entropy_min):
                hits.append(ExfilHit("dns_label", 0.85, host, "high-entropy DNS label"))
    # ---- query / fragment / path values
    pairs = parse_qsl(p.query, keep_blank_values=True) if p.query else []
    blob_hit = False
    for k, v in pairs:
        trusted = allowlisted and any_glob(params.trusted_params, k)
        for h in _value_hits(v, where=f"query value '{k[:24]}'", host=host, params=params,
                             trusted=trusted, rt=rt):
            hits.append(h)
            blob_hit = blob_hit or h.channel == "query_blob"
    if p.query and not pairs and len(p.query) >= params.url_encoded_min_len:
        hits += _value_hits(p.query, where="query", host=host, params=params, trusted=False, rt=rt)
    if p.fragment:
        hits += _value_hits(p.fragment, where="fragment", host=host, params=params,
                            trusted=False, rt=rt)
    for seg in p.path.split("/"):
        if len(seg) >= params.url_encoded_min_len:
            for h in _value_hits(seg, where="path segment", host=host, params=params,
                                 trusted=allowlisted, rt=rt):
                if h.channel == "query_blob" and len(seg) < 40:
                    continue
                hits.append(h)
    if len(p.query) > params.query_max_len:
        hits.append(ExfilHit("query_len", 0.9 if blob_hit else 0.6, host,
                             f"query of {len(p.query)} chars"))
    for h in hits:
        h.url = url
    return hits


# ---------------------------------------------------------------- collection
def _leaves(obj: Any, prefix: str, depth: int = 0) -> list[tuple[str, str]]:
    if depth > 12:
        return []
    out: list[tuple[str, str]] = []
    if isinstance(obj, str):
        out.append((prefix, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += _leaves(v, f"{prefix}.{k}" if prefix else str(k), depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:500]):
            out += _leaves(v, f"{prefix}[{i}]", depth + 1)
    return out


def _is_shell(interaction: Any, path: str) -> bool:
    tn = (interaction.tool_name or "").lower()
    return tn in ("bash", "shell", "exec", "terminal") or path.endswith((".command", ".cmd",
                                                                          ".script"))


def extract_urls(interaction: Any, params: Any = None) -> list[UrlRef]:
    refs: list[UrlRef] = []
    seen: set[tuple[str, str]] = set()

    def add(path: str, url: str, shell: bool) -> None:
        url = url.rstrip(").,;:!?]}'\"")
        if (path, url) not in seen:
            seen.add((path, url))
            refs.append(UrlRef(path, url, shell))

    if interaction.url:
        add("url", interaction.url, False)
    leaves = _leaves(interaction.tool_args or {}, "tool_args")
    for path, val in leaves:
        if path == "tool_args.url" and interaction.url and val == interaction.url:
            continue
        shell = _is_shell(interaction, path)
        for m in URL_RX.finditer(val[:MAX_SCAN]):
            add(path, m.group(0), shell)
        if shell:
            for m in SHELL_NET.finditer(val[:MAX_SCAN]):
                frag = m.group(0)
                if "://" in frag:
                    continue
                for hm in BARE_HOST.finditer(frag):
                    cand = hm.group(1)
                    if "." in cand.split("/")[0] and not cand.lower().endswith(
                            (".sh", ".py", ".txt", ".json", ".log", ".env", ".md")):
                        add(path, "http://" + cand, True)
    return refs


MAX_SCAN = 65536


def scan_arg_blobs(interaction: Any, params: Any, rt: Any | None = None) -> list[ExfilHit]:
    """Encoded runs in tool-arg string leaves (third_party destinations only)."""
    if interaction.destination.dest_class != "third_party":
        return []
    hits: list[ExfilHit] = []
    src = interaction.tool_args or {}
    if not src and interaction.surface == "egress.request" and isinstance(interaction.raw, dict):
        src = {"json": interaction.raw}
    for path, val in _leaves(src, "tool_args"):
        if path.endswith(".url") or len(val) < params.max_encoded_len:
            continue
        for m in BLOB_RX.finditer(val[:MAX_SCAN]):
            run = m.group(0)
            if len(run) < params.max_encoded_len or looks_like_words(run):
                continue
            head = _b64_head(run)
            if head is not None and head.startswith(MEDIA_MAGIC):
                continue  # media: DLP-03 sanitizes attachments
            decoded = decode_layers(run, params.decode_depth, min_len=params.max_encoded_len)
            sens: list[str] = []
            for d in decoded:
                sens = sensitive_hits(d.text, rt)
                if sens:
                    break
            if sens:
                hits.append(ExfilHit("arg_blob", 1.0, None,
                                     f"encoded arg {path} decodes to {', '.join(sens)}", sens,
                                     path=path))
            elif decoded:
                hits.append(ExfilHit("arg_blob", 0.4, None, f"encoded text in arg {path}",
                                     path=path))
            elif entropy(run) >= params.blob_entropy_min:
                hits.append(ExfilHit("arg_blob", 0.7, None,
                                     f"high-entropy blob in arg {path} ({len(run)} chars)",
                                     path=path))
            if len(hits) >= 16:
                return hits
    return hits


def _b64_head(run: str) -> bytes | None:
    try:
        return base64.b64decode(run[:16] + "=" * (-len(run[:16]) % 4), validate=False)
    except Exception:
        return None
