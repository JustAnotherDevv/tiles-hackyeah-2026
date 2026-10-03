"""Structured matchers: `url` (+ markdown/text URL extraction), `package` (install-command
parser, OSV-style entries) and `json_path` (alias `jsonpath`, JSONPath-lite)."""

from __future__ import annotations

import json
import re  # only for fixed, internal patterns
from typing import Any
from urllib.parse import urlsplit

from aegis.feed.matchers.core import (
    MAX_JSONPATH_NODES,
    MAX_SPANS,
    Event,
    FeedError,
    Matcher,
    compile_matcher,
    compile_re2,
    internal_re2,
    printable,
)

# --------------------------------------------------------------------------- URL
_URL_EXTRACTORS = {
    # inline image ![alt](url "title")
    "image": internal_re2(r"!\[[^\]\n]*\]\(\s*<?([^\s)>]+)"),
    # inline link [text](url) that is not an image
    "link": internal_re2(r"(?:^|[^!\]])\[[^\]\n]*\]\(\s*<?([^\s)>]+)"),
    # reference definition  [ref]: url   (EchoLeak used reference-style images)
    "refdef": internal_re2(r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*<?([^\s>]+)"),
    # raw HTML image
    "html_img": internal_re2(r"(?i)<img\b[^>]*?\bsrc\s*=\s*[\"']?([^\"'\s>]+)"),
    # autolink <https://...>
    "autolink": internal_re2(r"<((?:https?:)?//[^>\s]+)>"),
    # any bare URL in text
    "bare": internal_re2(r"(?i)\b((?:https?|ftp|file)://[^\s<>\"'\)\]]+)"),
}
MARKDOWN_KINDS = ("image", "link", "refdef", "html_img", "autolink")
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}
_ABS_URL = re.compile(r"(?i)^(?:https?:)?//")


def host_matches(host: str, patterns: list[str]) -> bool:
    for p in patterns:
        p = str(p).lower().rstrip(".")
        if p.startswith("*."):
            base = p[2:]
            if host == base or host.endswith("." + base):
                return True
        elif host == p:
            return True
    return False


def extract_urls(text: str, kinds: list[str]) -> list[tuple[str, str, int, int]]:
    """[(kind, url, start, end)] - start/end locate the URL inside `text`."""
    found: list[tuple[str, str, int, int]] = []
    for kind in kinds:
        rx = _URL_EXTRACTORS.get(kind)
        if rx is None:
            continue
        for mt in rx.finditer(text):
            u = mt.group(1)
            if kind != "bare" and not _ABS_URL.match(u):
                continue  # relative / data: / mailto: links cannot reach a third-party host
            start, end = mt.start(1), mt.end(1)
            if u.startswith("//"):
                u = "https:" + u
            found.append((kind, u, start, end))
    return found


def m_url(node: dict, where: str, depth: int = 0, lists: dict | None = None) -> Matcher:
    extract = node.get("extract", "none")
    if extract not in ("none", "markdown", "text"):
        raise FeedError(f"{where}: extract must be none|markdown|text")
    kinds = list(node.get("kinds") or (MARKDOWN_KINDS if extract == "markdown" else ["bare"]))
    for k in kinds:
        if k not in _URL_EXTRACTORS:
            raise FeedError(f"{where}: unknown URL kind {k!r}")
    fld = node.get("field", "all")
    path_rx = compile_re2(node["path_regex"], where + ".path_regex") if "path_regex" in node else None
    query_rx = (
        compile_re2(node["query_regex"], where + ".query_regex") if "query_regex" in node else None
    )
    host_rx = compile_re2(node["host_regex"], where + ".host_regex") if "host_regex" in node else None
    scheme_in = [str(s).lower() for s in node.get("scheme_in", [])]
    scheme_not_in = [str(s).lower() for s in node.get("scheme_not_in", [])]
    host_in, host_not_in = node.get("host_in"), node.get("host_not_in")
    port_in = node.get("port_in")
    method_in = [str(m).upper() for m in node.get("method_in", [])]
    qmin = node.get("query_min_length")

    def check(u: str, method: str | None) -> bool:
        try:
            parts = urlsplit(u.strip())
        except ValueError:
            return False
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower().rstrip(".")
        try:
            port = parts.port or _DEFAULT_PORTS.get(scheme)
        except ValueError:
            port = None
        path, query = parts.path or "/", parts.query
        if scheme_in and scheme not in scheme_in:
            return False
        if scheme_not_in and scheme in scheme_not_in:
            return False
        if host_in is not None and not host_matches(host, host_in):
            return False
        if host_not_in is not None and host_matches(host, host_not_in):
            return False
        if host_rx is not None and not host_rx.search(host):
            return False
        if port_in is not None and port not in port_in:
            return False
        if path_rx is not None and not path_rx.search(path):
            return False
        if query_rx is not None and not query_rx.search(query):
            return False
        if qmin is not None and len(query) < qmin:
            return False
        if method_in and (method or "GET").upper() not in method_in:
            return False
        return True

    def m(ev: Event) -> list[dict] | None:
        if extract == "none":
            if not ev.url:
                return None
            if check(ev.url, ev.method):
                return [{"matcher": "url", "at": where, "kind": "url", "url": printable(ev.url, 200)}]
            return None
        out: list[dict] = []
        for kind, u, start, end in extract_urls(ev.view(fld), kinds):
            if check(u, None):
                out.append({"matcher": "url", "at": where, "kind": kind,
                            "url": printable(u, 200), "field": fld, "start": start, "end": end})
                if not ev.all_spans or len(out) >= MAX_SPANS:
                    break
        return out or None

    return m


# --------------------------------------------------------------------------- packages
_CMD_PREFIX = r"(?:^|[\s;&|(`$'\"=])"
_PKG_COMMANDS = [
    ("pypi", internal_re2(r"(?i)" + _CMD_PREFIX
                          + r"(?:python[0-9.]*\s+-m\s+)?(?:pip[0-9.]*|uv\s+pip|pipx)\s+install\b([^\n;&|`)]*)")),
    ("pypi", internal_re2(r"(?i)" + _CMD_PREFIX + r"(?:uv|poetry|pdm|rye|hatch)\s+add\b([^\n;&|`)]*)")),
    ("npm", internal_re2(r"(?i)" + _CMD_PREFIX
                         + r"(?:npm|pnpm|yarn|bun)\s+(?:install|i|add)\b([^\n;&|`)]*)")),
    ("npm-exec", internal_re2(r"(?i)" + _CMD_PREFIX
                              + r"(?:npx|bunx|pnpx|pnpm\s+dlx|yarn\s+dlx)\b([^\n;&|`)]*)")),
    ("vscode", internal_re2(r"(?i)" + _CMD_PREFIX
                            + r"(?:code|code-insiders|cursor|windsurf)\s+--install-extension\s+([^\s;&|`)]+)")),
]
_PIP_VALUE_FLAGS = {
    "-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url",
    "--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix", "--root",
    "--python", "-p", "--platform", "--python-version", "--implementation", "--abi", "--src",
    "--upgrade-strategy", "--log", "--cache-dir", "--trusted-host", "--proxy", "--retries",
    "--timeout", "--exists-action", "--cert", "--client-cert", "-C", "--config-settings",
    "--group", "-G", "--extra", "--optional", "--source", "--index", "--spec",
}
_NPM_VALUE_FLAGS = {"--registry", "--prefix", "--tag", "-w", "--workspace", "--cache",
                    "--userconfig", "-C", "--cwd"}
_PYPI_SPEC = re.compile(
    r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?:\[[^\]]*\])?(?:\s*(===?)\s*([A-Za-z0-9.+!_-]+))?"
)
_PYPI_NORM = re.compile(r"[-_.]+")


def norm_pkg(ecosystem: str, name: str) -> str:
    if ecosystem == "pypi":
        return _PYPI_NORM.sub("-", name).lower()
    return name.lower()


def _looks_like_path(tok: str) -> bool:
    return (
        "://" in tok
        or tok.startswith((".", "/", "~", "file:", "git+", "git:", "github:", "http"))
        or tok.endswith((".whl", ".tar.gz", ".zip", ".tgz", ".txt", ".toml"))
    )


def _npm_spec(tok: str) -> tuple[str, str | None]:
    idx = tok.find("@", 1) if tok.startswith("@") else tok.find("@")
    if idx > 0:
        return tok[:idx], (tok[idx + 1 :] or None)
    return tok, None


def parse_install_commands(text: str) -> list[tuple[str, str, str | None]]:
    """Return [(ecosystem, normalized_name, exact_version_or_None)] for install commands."""
    found: list[tuple[str, str, str | None]] = []
    for eco, rx in _PKG_COMMANDS:
        for mt in rx.finditer(text):
            toks = [t.strip("'\"") for t in mt.group(1).split()]
            if eco == "vscode":
                if toks:
                    name, ver = _npm_spec(toks[0]) if "@" in toks[0] else (toks[0], None)
                    found.append(("vscode", norm_pkg("vscode", name), ver))
                continue
            skip = False
            for i, tok in enumerate(toks):
                if skip:
                    skip = False
                    continue
                if not tok:
                    continue
                if eco == "npm-exec" and (tok in ("-p", "--package") or tok.startswith("--package=")):
                    if "=" in tok:
                        name, ver = _npm_spec(tok.split("=", 1)[1])
                        found.append(("npm", norm_pkg("npm", name), ver))
                    elif i + 1 < len(toks):
                        name, ver = _npm_spec(toks[i + 1])
                        found.append(("npm", norm_pkg("npm", name), ver))
                    skip = True
                    continue
                if tok.startswith("-"):
                    flags = _PIP_VALUE_FLAGS if eco == "pypi" else _NPM_VALUE_FLAGS
                    skip = "=" not in tok and tok in flags
                    continue
                if _looks_like_path(tok):
                    if eco == "npm-exec":
                        break
                    continue
                if eco == "pypi":
                    mt2 = _PYPI_SPEC.match(tok)
                    if mt2:
                        found.append(("pypi", norm_pkg("pypi", mt2.group(1)), mt2.group(3)))
                else:
                    name, ver = _npm_spec(tok)
                    found.append(("npm", norm_pkg("npm", name), ver))
                    if eco == "npm-exec":
                        break  # npx: only the first positional is a package; the rest are its args
    return found


def m_package(node: dict, where: str, depth: int = 0, lists: dict | None = None) -> Matcher:
    fld = node.get("field", "all")
    raw = list(node.get("packages") or [])
    ref = node.get("list_ref")
    if isinstance(ref, str) and isinstance((lists or {}).get(ref), list):
        raw.extend(e for e in lists[ref] if isinstance(e, dict))  # type: ignore[index]
    if not raw and "packages" not in node:
        raise FeedError(f"{where}: package needs `packages` (or `list_ref`)")
    entries = []
    for e in raw:
        eco = str(e["ecosystem"]).lower()
        entries.append((eco, norm_pkg(eco, str(e["name"])), {str(v) for v in e.get("versions") or []}))

    def m(ev: Event) -> list[dict] | None:
        for eco, name, ver in parse_install_commands(ev.view(fld)):
            for e_eco, e_name, e_vers in entries:
                if eco == e_eco and name == e_name and (not e_vers or (ver is not None and ver in e_vers)):
                    return [{"matcher": "package", "at": where,
                             "package": f"{eco}:{name}" + (f"@{ver}" if ver else "")}]
        return None

    return m


# --------------------------------------------------------------------------- JSONPath-lite
_JP_TOKEN = re.compile(
    r"""\.\.(\*|[A-Za-z_$][\w$-]*)?|\.(\*|[A-Za-z_$][\w$-]*)|\[(\*|-?\d+|(?:'[^']*'|"[^"]*")(?:\s*,\s*(?:'[^']*'|"[^"]*"))*)\]"""
)
_JP_INT = re.compile(r"-?\d+")
_JP_NAMES = re.compile(r"""'[^']*'|"[^"]*\"""")


def parse_jsonpath(path: str, where: str = "path") -> list[tuple[str, Any]]:
    """Subset: $  .name  .*  ..name  ..*  [n]  [*]  ['a','b']  ..['a']."""
    if not isinstance(path, str) or not path.startswith("$"):
        raise FeedError(f"{where}: JSONPath must start with '$'")
    steps: list[tuple[str, Any]] = []
    i = 1
    pending_desc = False
    while i < len(path):
        mt = _JP_TOKEN.match(path, i)
        if not mt:
            raise FeedError(f"{where}: unsupported JSONPath syntax at {path[i:]!r}")
        tok = mt.group(0)
        if tok.startswith(".."):
            name = mt.group(1)
            if name is None:
                pending_desc = True
            else:
                steps.append(("desc", None if name == "*" else [name]))
        elif tok.startswith("."):
            name = mt.group(2)
            steps.append(("desc" if pending_desc else "child", None if name == "*" else [name]))
            pending_desc = False
        else:
            inner = mt.group(3)
            if inner == "*":
                steps.append(("desc" if pending_desc else "child", None))
            elif _JP_INT.fullmatch(inner):
                if pending_desc:
                    raise FeedError(f"{where}: '..[n]' is not supported")
                steps.append(("index", int(inner)))
            else:
                names = [s.strip()[1:-1] for s in _JP_NAMES.findall(inner)]
                steps.append(("desc" if pending_desc else "child", names))
            pending_desc = False
        i = mt.end()
    if pending_desc:
        raise FeedError(f"{where}: dangling '..'")
    return steps


def _children(node: Any, names: list[str] | None) -> list[Any]:
    if isinstance(node, dict):
        if names is None:
            return list(node.values())
        return [node[n] for n in names if n in node]
    if isinstance(node, list) and names is None:
        return list(node)
    return []


def _descendants(node: Any, out: list[Any]) -> None:
    if len(out) > MAX_JSONPATH_NODES:
        return
    out.append(node)
    if isinstance(node, dict):
        for v in node.values():
            _descendants(v, out)
    elif isinstance(node, list):
        for v in node:
            _descendants(v, out)


def jsonpath_select(root: Any, steps: list[tuple[str, Any]]) -> list[Any]:
    nodes = [root]
    for kind, arg in steps:
        out: list[Any] = []
        for n in nodes:
            if kind == "child":
                out.extend(_children(n, arg))
            elif kind == "desc":
                desc: list[Any] = []
                _descendants(n, desc)
                for d in desc:
                    out.extend(_children(d, arg))
            elif kind == "index" and isinstance(n, list) and -len(n) <= arg < len(n):
                out.append(n[arg])
            if len(out) > MAX_JSONPATH_NODES:
                break
        nodes = out[:MAX_JSONPATH_NODES]
    return nodes


def m_json_path(node: dict, where: str, depth: int = 0, lists: dict | None = None) -> Matcher:
    steps = parse_jsonpath(node["path"], where + ".path")
    sub = compile_matcher(node["match"], where + ".match", depth + 1, lists) if "match" in node else None
    has_equals = "equals" in node
    equals = node.get("equals")
    exists = node.get("exists", True)

    def m(ev: Event) -> list[dict] | None:
        if not ev.has_json:
            return None
        sel = jsonpath_select(ev.json, steps)
        if exists is False:
            return [{"matcher": "json_path", "at": where, "absent": node["path"]}] if not sel else None
        for v in sel:
            if has_equals and v != equals:
                continue
            if sub is not None:
                if isinstance(v, str):
                    sev = Event(surface=ev.surface, text=v, url=v, json=v)
                else:
                    sev = Event(surface=ev.surface,
                                text=json.dumps(v, ensure_ascii=False, sort_keys=True), json=v)
                r = sub(sev)
                if r is None:
                    continue
                # nested spans index the selected value, not the event text: drop them
                return [{"matcher": "json_path", "at": where, "path": node["path"]}] + [
                    {k: val for k, val in e.items() if k not in ("start", "end")} for e in r
                ]
            return [{"matcher": "json_path", "at": where, "path": node["path"],
                     "value": printable(json.dumps(v, ensure_ascii=False)[:120])}]
        return None

    return m


MATCHERS = {"url": m_url, "package": m_package, "json_path": m_json_path}
