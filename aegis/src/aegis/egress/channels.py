"""DLP-06 exfil-channel neutralization: markdown/HTML image beacons, reference-style images
(EchoLeak), suspicious links/autolinks and ANSI OSC/OSC-8 escapes in model/tool output.

Regexes ported from staging/spikes/streaming/aegis_stream/detectors.py (`_MD_IMG`,
`_HTML_IMG`, `_host_if_external`) and extended. All quantifiers are bounded.
Every span carries an explicit (irreversible) replacement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl

from aegis.egress.compat import host_matches
from aegis.egress.encoded import decode_layers
from aegis.egress.exfil import builtin_exfil_hosts, parse_url
from aegis.egress.textmeta import MetaSpan, resolve_overlaps

MD_IMG = re.compile(
    r"!\[[^\]\n]{0,1000}\]\(\s*<?(?P<url>[^)\s>]{1,4096})>?"
    r"(?:\s+(?:\"[^\"\n]{0,512}\"|'[^'\n]{0,512}'))?\s*\)")
MD_REF_IMG = re.compile(r"!\[(?P<alt>[^\]\n]{0,1000})\](?:\[(?P<ref>[^\]\n]{0,200})\])?")
MD_REF_DEF = re.compile(
    r"(?m)^[ \t]{0,3}\[(?P<ref>[^\]\n]{1,200})\]:[ \t]*<?(?P<url>[^\s>]{1,4096})>?"
    r"(?:[ \t]+(?:\"[^\"\n]{0,512}\"|'[^'\n]{0,512}'|\([^)\n]{0,512}\)))?[ \t]*$")
MD_LINK = re.compile(
    r"(?<!!)\[(?P<text>[^\]\n]{0,1000})\]\(\s*<?(?P<url>[^)\s>]{1,4096})>?"
    r"(?:\s+(?:\"[^\"\n]{0,512}\"|'[^'\n]{0,512}'))?\s*\)")
AUTOLINK = re.compile(r"<(?P<url>(?i:https?|ftp)://[^\s<>]{1,4096})>")
BARE_URL = re.compile(r"(?<![\w(<\"'=/])(?P<url>(?i:https?)://[^\s<>()\[\]\"'`]{1,4096})")
HTML_TAG = re.compile(r"<(?P<tag>[A-Za-z][A-Za-z0-9]{0,15})\b(?P<attrs>[^<>]{0,4096})>", re.S)
ATTR_URL = re.compile(
    r"\b(?P<name>src|href|data|action|poster|background|srcset|formaction|content)\s*=\s*"
    r"(?:\"(?P<d>[^\"]{0,4096})\"|'(?P<s>[^']{0,4096})'|(?P<u>[^\s\"'>]{1,4096}))", re.I)
CLOSE_TAG = {"script", "iframe", "object", "style", "svg"}
OSC = re.compile(r"\x1b\][^\x07\x1b]{0,4096}(?:\x07|\x1b\\)")
CSI = re.compile(r"\x1b\[[0-?]{0,32}[ -/]{0,8}[@-~]")
OSC8_START = re.compile(r"\x1b\]8;[^;\x07\x1b]{0,256};(?P<url>[^\x07\x1b]{0,4096})(?:\x07|\x1b\\)")


def _host(url: str) -> str | None:
    u = url.strip().replace("\\/", "/")
    if u.startswith("//"):
        u = "https:" + u
    if not re.match(r"(?i)^[a-z][a-z0-9+.\-]{0,15}:", u):
        return None  # relative URL: same origin, not a network channel to a third party
    if u.lower().startswith("data:"):
        return None
    p = parse_url(u)
    return p.host if p and p.host else None


def defang(url: str) -> str:
    """`https://evil.example/path?x=1` → `hxxps://evil[.]example/path` (query/fragment dropped)."""
    p = parse_url(url.strip())
    if p is None:
        return "[link removed by Aegis]"
    scheme = {"http": "hxxp", "https": "hxxps", "ftp": "fxp"}.get(p.scheme, p.scheme)
    host = p.host.replace(".", "[.]")
    return f"{scheme}://{host}{p.path}"


class _Ctx:
    def __init__(self, allowed: Iterable[str], params: Any) -> None:
        self.allowed = [a.lower() for a in allowed]
        self.p = params
        self.oast = builtin_exfil_hosts()

    def external(self, url: str) -> str | None:
        """Host when `url` points to a non-allowed network destination, else None."""
        h = _host(url)
        if h is None or host_matches(self.allowed, h):
            return None
        return h

    def image_host(self, url: str) -> str | None:
        mode = self.p.strip_images
        if mode == "none":
            return None
        if mode == "all":
            return _host(url)
        return self.external(url)

    def link_suspicious(self, url: str) -> str | None:
        mode = self.p.defang_links
        h = self.external(url)
        if h is None or mode == "none":
            return None
        if mode == "all_external":
            return h
        p = parse_url(url)
        if p is None:
            return None
        if host_matches(self.oast, h):
            return h
        if len(p.query) > self.p.max_query_len or len(p.fragment) > self.p.max_query_len:
            return h
        for _, v in parse_qsl(p.query, keep_blank_values=True):
            if len(v) >= 16 and decode_layers(v, 1):
                return h
        return None


def find_channels(text: str, allowed_domains: Iterable[str], params: Any) -> list[MetaSpan]:
    """Spans (with explicit replacements) that neutralize exfil channels in `text`."""
    if not text:
        return []
    c = _Ctx(allowed_domains, params)
    spans: list[MetaSpan] = []

    def add(a: int, b: int, det: str, rep: str, construct: str, host: str | None) -> None:
        spans.append(MetaSpan(a, b, "EXFIL_CHANNEL", det, construct, rep, 1.0, category="exfil",
                              meta={"construct": construct, "host": host}))

    if "![" in text:
        for m in MD_IMG.finditer(text):
            h = c.image_host(m.group("url"))
            if h:
                add(m.start(), m.end(), "exfil.md_image", f"[image removed by Aegis: {h}]",
                    "markdown image", h)
        if params.reference_style and "]:" in text:
            defs: dict[str, tuple[int, int, str]] = {}
            for m in MD_REF_DEF.finditer(text):
                defs[m.group("ref").strip().lower()] = (m.start("url"), m.end("url"), m.group("url"))
            used: set[str] = set()
            for m in MD_REF_IMG.finditer(text):
                if text[m.end():m.end() + 1] == "(":
                    continue  # inline image, handled above
                ref = (m.group("ref") or m.group("alt") or "").strip().lower()
                if ref in defs:
                    h = c.image_host(defs[ref][2])
                    if h:
                        add(m.start(), m.end(), "exfil.md_image",
                            f"[image removed by Aegis: {h}]", "reference image", h)
                        used.add(ref)
            for ref in used:
                a, b, url = defs[ref]
                add(a, b, "exfil.md_image_ref", defang(url), "reference definition", _host(url))
    if "<" in text:
        for m in HTML_TAG.finditer(text):
            tag = m.group("tag").lower()
            if tag not in {t.lower() for t in params.strip_html_tags}:
                continue
            attrs = m.group("attrs")
            if tag == "meta" and "refresh" not in attrs.lower():
                continue
            host = None
            for am in ATTR_URL.finditer(attrs):
                val = am.group("d") or am.group("s") or am.group("u") or ""
                if am.group("name").lower() == "content":
                    um = re.search(r"(?i)url\s*=\s*(\S+)", val)
                    val = um.group(1) if um else ""
                if am.group("name").lower() == "srcset":
                    val = val.split()[0] if val.split() else ""
                host = c.external(val) if tag != "img" else c.image_host(val)
                if host:
                    break
            if not host:
                continue
            end = m.end()
            if tag in CLOSE_TAG:
                close = re.compile(rf"</{tag}\s*>", re.I).search(text, m.end(), m.end() + 8192)
                if close:
                    end = close.end()
            add(m.start(), end, "exfil.html_tag", f"[html {tag} removed by Aegis: {host}]",
                f"html {tag}", host)
    if "://" in text and params.defang_links != "none":
        for rx, construct in ((MD_LINK, "markdown link"), (AUTOLINK, "autolink"),
                              (BARE_URL, "url")):
            for m in rx.finditer(text):
                url = m.group("url")
                h = c.link_suspicious(url)
                if not h:
                    continue
                a, b = m.span("url")
                if construct == "autolink":
                    a, b = m.span()
                add(a, b, "exfil.link", defang(url), construct, h)
    if params.strip_ansi and "\x1b" in text:
        for m in OSC.finditer(text):
            u = OSC8_START.match(m.group(0))
            host = _host(u.group("url")) if u and u.group("url") else None
            add(m.start(), m.end(), "exfil.ansi", "", "osc-8 hyperlink" if u else "ansi osc", host)
        for m in CSI.finditer(text):
            if m.group(0).endswith("m"):
                continue  # SGR colours are harmless
            add(m.start(), m.end(), "exfil.ansi", "", "ansi csi", None)
    return resolve_overlaps(spans)
