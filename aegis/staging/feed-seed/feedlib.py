"""Reference engine for the Aegis threat-intel signature feed.

A signature is *data*: YAML/JSON evaluated by a closed set of matcher types.
Nothing in a feed is ever executed, imported, unpickled or eval'd.  Feed
regexes are compiled with RE2 (linear time; no backreferences/lookaround).

Used by validate.py / sign.py / verify.py / scan.py.  The gateway FeedManager
can import this module as-is or port it; the semantics documented in README.md
are normative, this file is the executable reference.

Dependencies: google-re2, pyyaml (PyNaCl only for signing/verification).
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import hashlib
import io
import json
import pickletools
import re  # only for fixed, internal patterns (never for feed-supplied regexes)
import unicodedata
import zipfile
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import re2
import yaml

FEED_NAME = "aegis-threat-intel"
SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parent

SURFACES = ("model_call", "tool_call", "mcp", "egress", "model_download", "output")
# Strongest first.  The gateway combines hits by taking the strongest action.
ACTIONS = ("block", "require_approval", "quarantine", "strip_tool", "redact", "alert")
STATUSES = ("experimental", "test", "stable", "deprecated", "withdrawn")
ENFORCED_STATUSES = frozenset({"test", "stable", "deprecated"})
MONITOR_STATUSES = frozenset({"experimental"})  # evaluated, logged, never enforced
LEAF_TYPES = (
    "regex", "literal", "url", "package", "hash", "bytes",
    "pickle_opcode", "jsonpath", "semantic_exemplar",
)
FIELDS = ("all", "text", "url", "body", "filename", "bytes")

MAX_REGEX_LEN = 2048
MAX_SCAN_CHARS = 256 * 1024
MAX_JSONPATH_NODES = 10_000
MAX_MATCHER_DEPTH = 6
MAX_PICKLE_OPS = 2_000_000
MAX_ZIP_MEMBERS = 4096
MAX_ZIP_MEMBER_BYTES = 64 * 1024 * 1024

PICKLE_EXTENSIONS = (".pkl", ".pickle", ".pt", ".pth", ".bin", ".ckpt", ".joblib", ".dat", ".npy", ".npz")


class FeedError(Exception):
    """A signature or bundle is invalid (schema, RE2, structure, crypto)."""


# --------------------------------------------------------------------------- #
# Loading                                                                     #
# --------------------------------------------------------------------------- #

def to_plain(obj: Any) -> Any:
    """YAML -> JSON-safe data (dates become ISO strings, keys become str)."""
    if isinstance(obj, _dt.datetime):
        s = obj.isoformat()
        return s.replace("+00:00", "Z")
    if isinstance(obj, _dt.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    if isinstance(obj, bytes):
        raise FeedError("raw bytes are not allowed in signatures; use bytes_hex/bytes_b64")
    return obj


def load_signature_file(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    docs = list(yaml.safe_load_all(text))  # safe_load only: no YAML tags/objects
    if len(docs) != 1 or not isinstance(docs[0], dict):
        raise FeedError(f"{path}: expected exactly one YAML mapping")
    return to_plain(docs[0])


def load_signatures_dir(directory: Path) -> list[tuple[Path, dict]]:
    out = []
    for p in sorted(Path(directory).glob("*.y*ml")):
        out.append((p, load_signature_file(p)))
    return out


def canonical_json(obj: Any) -> bytes:
    """Bytes that are signed: sorted keys, no whitespace, UTF-8, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


# --------------------------------------------------------------------------- #
# Events                                                                      #
# --------------------------------------------------------------------------- #

_MISSING = object()


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
    """What the gateway observed at one interception point.

    surface   one of SURFACES
    text      prompt / completion / tool result / description text
    json      structured payload (tool args, MCP message, parsed HTTP JSON body, config.json, GGUF KV)
    url       request URL (egress, model_download)
    method    HTTP method
    body      raw HTTP body (parsed into `json` automatically when it is JSON)
    filename  artifact file name (model_download)
    data      artifact bytes (model_download)
    """

    surface: str
    text: str | None = None
    json: Any = _MISSING
    url: str | None = None
    method: str | None = None
    body: str | None = None
    filename: str | None = None
    data: bytes | None = None
    _views: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.json is _MISSING and self.body:
            try:
                self.json = json.loads(self.body)
            except ValueError:
                pass

    @property
    def has_json(self) -> bool:
        return self.json is not _MISSING

    @classmethod
    def from_example(cls, ex: dict) -> "Event":
        data = None
        if "bytes_hex" in ex:
            data = bytes.fromhex("".join(str(ex["bytes_hex"]).split()))
        elif "bytes_b64" in ex:
            data = base64.b64decode("".join(str(ex["bytes_b64"]).split()), validate=True)
        return cls(
            surface=ex["surface"], text=ex.get("text"), json=ex.get("json", _MISSING),
            url=ex.get("url"), method=ex.get("method"), body=ex.get("body"),
            filename=ex.get("filename"), data=data,
        )

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
            parts = [self.text, self.url, self.body, self.filename]
            if self.data and not self.text:
                parts.append(self.view("bytes"))
            if self.has_json:
                strings: list[str] = []
                _json_strings(self.json, strings, [MAX_JSONPATH_NODES])
                parts.extend(strings)
                if not isinstance(self.json, str):
                    parts.append(json.dumps(self.json, ensure_ascii=False, sort_keys=True))
            v = "\n".join(p for p in parts if p)
        else:
            raise FeedError(f"unknown field {name!r}")
        v = _safe_str(v[:MAX_SCAN_CHARS])
        self._views[name] = v
        return v


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def compile_re2(pattern: str, where: str, case_insensitive: bool = False):
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


def printable(s: str, limit: int = 140) -> str:
    """Make invisible / control characters visible for evidence output."""
    out = []
    for ch in s:
        cp = ord(ch)
        if ch in "\n\t":
            out.append({"\n": "\\n", "\t": "\\t"}[ch])
        elif ch.isprintable() and not (0xE0000 <= cp <= 0xE01EF or 0x200B <= cp <= 0x200F
                                      or 0x202A <= cp <= 0x202E or 0x2060 <= cp <= 0x2069
                                      or cp == 0xFEFF or 0xFE00 <= cp <= 0xFE0F):
            out.append(ch)
        else:
            out.append(f"\\u{{{cp:X}}}")
        if len(out) >= limit:
            out.append("…")
            break
    return "".join(out)


def _snippet(text: str, start: int, end: int) -> str:
    return printable(text[max(0, start - 24):min(len(text), end + 24)])


Evidence = list  # list[dict]; None means "no match"
Matcher = Callable[[Event], "Evidence | None"]


# --------------------------------------------------------------------------- #
# Leaf matchers                                                               #
# --------------------------------------------------------------------------- #

def _m_regex(node: dict, where: str) -> Matcher:
    rx = compile_re2(node["pattern"], where, node.get("case_insensitive", False))
    fld = node.get("field", "all")

    def m(ev: Event):
        text = ev.view(fld)
        if not text:
            return None
        hit = rx.search(text)
        if hit is None:
            return None
        return [{"matcher": "regex", "at": where, "field": fld,
                 "snippet": _snippet(text, hit.start(), hit.end())}]
    return m


def _m_literal(node: dict, where: str) -> Matcher:
    ci = node.get("case_insensitive", True)
    values = [v.casefold() if ci else v for v in node["values"]]
    fld = node.get("field", "all")

    def m(ev: Event):
        text = ev.view(fld)
        hay = text.casefold() if ci else text
        for v in values:
            i = hay.find(v)
            if i >= 0:
                return [{"matcher": "literal", "at": where, "field": fld, "value": v,
                         "snippet": _snippet(text, i, i + len(v))}]
        return None
    return m


# --- URL --------------------------------------------------------------------

_RE2 = lambda p: compile_re2(p, "<internal>")  # noqa: E731
_URL_EXTRACTORS = {
    # inline image ![alt](url "title")
    "image": _RE2(r"!\[[^\]\n]*\]\(\s*<?([^\s)>]+)"),
    # inline link [text](url) that is not an image
    "link": _RE2(r"(?:^|[^!\]])\[[^\]\n]*\]\(\s*<?([^\s)>]+)"),
    # reference definition  [ref]: url   (EchoLeak used reference-style images)
    "refdef": _RE2(r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*<?([^\s>]+)"),
    # raw HTML image
    "html_img": _RE2(r"(?i)<img\b[^>]*?\bsrc\s*=\s*[\"']?([^\"'\s>]+)"),
    # autolink <https://...>
    "autolink": _RE2(r"<((?:https?:)?//[^>\s]+)>"),
    # any bare URL in text
    "bare": _RE2(r"(?i)\b((?:https?|ftp|file)://[^\s<>\"'\)\]]+)"),
}
_MARKDOWN_KINDS = ("image", "link", "refdef", "html_img", "autolink")
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}


def _host_matches(host: str, patterns: list[str]) -> bool:
    for p in patterns:
        p = p.lower().rstrip(".")
        if p.startswith("*."):
            base = p[2:]
            if host == base or host.endswith("." + base):
                return True
        elif host == p:
            return True
    return False


def extract_urls(text: str, kinds: list[str]) -> list[tuple[str, str]]:
    found = []
    for kind in kinds:
        for mt in _URL_EXTRACTORS[kind].finditer(text):
            u = mt.group(1)
            if kind != "bare" and not re.match(r"(?i)^(?:https?:)?//", u):
                continue  # relative / data: / mailto: links cannot reach a third-party host
            if u.startswith("//"):
                u = "https:" + u
            found.append((kind, u))
    return found


def _m_url(node: dict, where: str) -> Matcher:
    extract = node.get("extract", "none")
    kinds = node.get("kinds") or (list(_MARKDOWN_KINDS) if extract == "markdown" else ["bare"])
    fld = node.get("field", "all")
    path_rx = compile_re2(node["path_regex"], where + ".path_regex") if "path_regex" in node else None
    query_rx = compile_re2(node["query_regex"], where + ".query_regex") if "query_regex" in node else None
    host_rx = compile_re2(node["host_regex"], where + ".host_regex") if "host_regex" in node else None
    scheme_in = [s.lower() for s in node.get("scheme_in", [])]
    scheme_not_in = [s.lower() for s in node.get("scheme_not_in", [])]
    host_in, host_not_in = node.get("host_in"), node.get("host_not_in")
    port_in, method_in = node.get("port_in"), [m.upper() for m in node.get("method_in", [])]
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
        if host_in is not None and not _host_matches(host, host_in):
            return False
        if host_not_in is not None and _host_matches(host, host_not_in):
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

    def m(ev: Event):
        if extract == "none":
            if not ev.url:
                return None
            cands = [("url", ev.url)]
        else:
            cands = extract_urls(ev.view(fld), kinds)
        for kind, u in cands:
            if check(u, ev.method if extract == "none" else None):
                return [{"matcher": "url", "at": where, "kind": kind, "url": printable(u, 200)}]
        return None
    return m


# --- Package install commands -------------------------------------------------

_CMD_PREFIX = r"(?:^|[\s;&|(`$'\"=])"
_PKG_COMMANDS = [
    ("pypi", _RE2(r"(?i)" + _CMD_PREFIX + r"(?:python[0-9.]*\s+-m\s+)?(?:pip[0-9.]*|uv\s+pip|pipx)\s+install\b([^\n;&|`)]*)")),
    ("pypi", _RE2(r"(?i)" + _CMD_PREFIX + r"(?:uv|poetry|pdm|rye|hatch)\s+add\b([^\n;&|`)]*)")),
    ("npm", _RE2(r"(?i)" + _CMD_PREFIX + r"(?:npm|pnpm|yarn|bun)\s+(?:install|i|add)\b([^\n;&|`)]*)")),
    ("npm-exec", _RE2(r"(?i)" + _CMD_PREFIX + r"(?:npx|bunx|pnpx|pnpm\s+dlx|yarn\s+dlx)\b([^\n;&|`)]*)")),
    ("vscode", _RE2(r"(?i)" + _CMD_PREFIX + r"(?:code|code-insiders|cursor|windsurf)\s+--install-extension\s+([^\s;&|`)]+)")),
]
_PIP_VALUE_FLAGS = {
    "-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url",
    "--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix", "--root",
    "--python", "-p", "--platform", "--python-version", "--implementation", "--abi", "--src",
    "--upgrade-strategy", "--log", "--cache-dir", "--trusted-host", "--proxy", "--retries",
    "--timeout", "--exists-action", "--cert", "--client-cert", "-C", "--config-settings",
    "--group", "-G", "--extra", "--optional", "--source", "--index", "--spec",
}
_NPM_VALUE_FLAGS = {"--registry", "--prefix", "--tag", "-w", "--workspace", "--cache", "--userconfig", "-C", "--cwd"}
_PYPI_SPEC = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?:\[[^\]]*\])?(?:\s*(===?)\s*([A-Za-z0-9.+!_-]+))?")


def norm_pkg(ecosystem: str, name: str) -> str:
    if ecosystem == "pypi":
        return re.sub(r"[-_.]+", "-", name).lower()
    return name.lower()


def _looks_like_path(tok: str) -> bool:
    return ("://" in tok or tok.startswith((".", "/", "~", "file:", "git+", "git:", "github:", "http"))
            or tok.endswith((".whl", ".tar.gz", ".zip", ".tgz", ".txt", ".toml")))


def _npm_spec(tok: str) -> tuple[str, str | None]:
    idx = tok.find("@", 1) if tok.startswith("@") else tok.find("@")
    if idx > 0:
        return tok[:idx], (tok[idx + 1:] or None)
    return tok, None


def parse_install_commands(text: str) -> list[tuple[str, str, str | None]]:
    """Return [(ecosystem, normalized_name, exact_version_or_None)] for install commands in text."""
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


def _m_package(node: dict, where: str) -> Matcher:
    fld = node.get("field", "all")
    entries = []
    for e in node["packages"]:
        eco = e["ecosystem"].lower()
        entries.append((eco, norm_pkg(eco, e["name"]), set(e.get("versions") or [])))

    def m(ev: Event):
        for eco, name, ver in parse_install_commands(ev.view(fld)):
            for e_eco, e_name, e_vers in entries:
                if eco == e_eco and name == e_name and (not e_vers or (ver is not None and ver in e_vers)):
                    return [{"matcher": "package", "at": where,
                             "package": f"{eco}:{name}" + (f"@{ver}" if ver else "")}]
        return None
    return m


# --- Hash / bytes ---------------------------------------------------------------

def _m_hash(node: dict, where: str) -> Matcher:
    values = {v.lower() for v in node["sha256"]}
    fld = node.get("field", "auto")
    normalize = node.get("normalize", "none")

    def m(ev: Event):
        if fld in ("auto", "bytes") and ev.data is not None:
            payload = ev.data
        elif fld == "bytes":
            return None
        else:
            s = ev.view("text" if fld == "auto" else fld)
            if not s:
                return None
            if normalize == "whitespace":
                s = " ".join(s.split())
            payload = s.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        if digest in values:
            return [{"matcher": "hash", "at": where, "sha256": digest}]
        return None
    return m


def _m_bytes(node: dict, where: str) -> Matcher:
    magic = bytes.fromhex(node["magic_hex"])
    off = node.get("offset", 0)

    def m(ev: Event):
        if ev.data is not None and ev.data[off:off + len(magic)] == magic:
            return [{"matcher": "bytes", "at": where, "magic": magic.hex(), "offset": off}]
        return None
    return m


# --- Pickle opcode analysis (never unpickles) ------------------------------------

_STRING_OPS = {"STRING", "BINSTRING", "SHORT_BINSTRING", "UNICODE", "BINUNICODE",
               "SHORT_BINUNICODE", "BINUNICODE8"}
_SAFE_MAGIC = (b"GGUF", b"\x89HDF", b"PK\x03\x04", b"7z\xbc\xaf\x27\x1c")


def looks_like_pickle(data: bytes) -> bool:
    if len(data) >= 2 and data[0] == 0x80 and data[1] <= 5:
        return True
    return re.match(rb"c[A-Za-z_][\w.]*\n[A-Za-z_][\w.]*\n", data[:256]) is not None


def _is_safetensors(data: bytes) -> bool:
    if len(data) < 10:
        return False
    n = int.from_bytes(data[:8], "little")
    return 0 < n < 100_000_000 and data[8:9] == b"{"


def scan_pickle_stream(data: bytes, max_ops: int = MAX_PICKLE_OPS) -> tuple[list[str], str | None]:
    """Walk opcodes with pickletools.genops (no execution).  Returns (globals, error)."""
    found: list[str] = []
    offset, n_pickles, ops = 0, 0, 0
    while offset < len(data) and n_pickles < 16:
        memo: dict[int, Any] = {}
        strings: list[str] = []
        last: Any = None
        stream = io.BytesIO(data[offset:])
        stopped = False
        try:
            for op, arg, pos in pickletools.genops(stream):
                ops += 1
                if ops > max_ops:
                    return found, "opcode budget exceeded"
                name = op.name
                if name in ("GLOBAL", "INST"):
                    mod, _, attr = str(arg).partition(" ")
                    found.append(f"{mod}.{attr}")
                    last = None
                elif name == "STACK_GLOBAL":
                    found.append(f"{strings[-2]}.{strings[-1]}" if len(strings) >= 2 else "<unresolved>")
                    last = None
                elif name in _STRING_OPS:
                    last = arg.decode("utf-8", "replace") if isinstance(arg, bytes) else str(arg)
                    strings.append(last)
                elif name == "MEMOIZE":
                    memo[len(memo)] = last
                elif name in ("PUT", "BINPUT", "LONG_BINPUT"):
                    memo[arg] = last
                elif name in ("GET", "BINGET", "LONG_BINGET"):
                    last = memo.get(arg)
                    if isinstance(last, str):
                        strings.append(last)
                elif name == "STOP":
                    stopped = True
                    offset += pos + 1
                else:
                    last = None
        except Exception as e:  # malformed stream: nullifAI-style -> caller fails closed
            return found, f"{type(e).__name__}: {e}"
        if not stopped:
            return found, "no STOP opcode"
        n_pickles += 1
        if offset >= len(data) or data[offset] != 0x80:
            break  # trailing non-pickle data (e.g. legacy torch storages)
    return found, None


def _zip_members(data: bytes) -> tuple[list[tuple[str, bytes]], str | None]:
    """Yield pickle-looking members regardless of extension; flag header tricks."""
    out = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                return out, "too many ZIP members"
            for info in infos:
                off = info.header_offset
                hdr = data[off:off + 30]
                if len(hdr) < 30 or hdr[:4] != b"PK\x03\x04":
                    return out, f"bad local header for {info.filename!r}"
                n = int.from_bytes(hdr[26:28], "little")
                enc = "utf-8" if info.flag_bits & 0x800 else "cp437"
                local = data[off + 30:off + 30 + n].decode(enc, "replace")
                if local != info.orig_filename:
                    return out, f"central/local name mismatch {info.orig_filename!r} != {local!r}"
                if info.file_size > MAX_ZIP_MEMBER_BYTES:
                    continue
                with zf.open(info) as fh:
                    head = fh.read(256)
                if info.filename.endswith((".pkl", ".pickle")) or looks_like_pickle(head):
                    out.append((info.filename, zf.read(info)))
    except Exception as e:  # bad CRC, truncated archive, ...
        return out, f"{type(e).__name__}: {e}"
    return out, None


def _m_pickle(node: dict, where: str) -> Matcher:
    allow = list(node.get("allow_globals", []))
    deny = list(node.get("deny_globals", []))
    on_err = node.get("on_parse_error", "match")
    scan_zip = node.get("scan_zip_members", True)

    def bad_globals(globs: list[str]) -> list[str]:
        bad = []
        for g in globs:
            if any(fnmatchcase(g, p) for p in deny) or not any(fnmatchcase(g, p) for p in allow):
                bad.append(g)
        return bad

    def scan_one(blob: bytes, label: str):
        globs, err = scan_pickle_stream(blob)
        bad = bad_globals(globs)
        if bad:
            return [{"matcher": "pickle_opcode", "at": where, "member": label, "globals": bad[:8]}]
        if err and on_err == "match":
            return [{"matcher": "pickle_opcode", "at": where, "member": label, "parse_error": err[:160]}]
        return None

    def m(ev: Event):
        data = ev.data
        if not data:
            return None
        if data[:4] == b"PK\x03\x04":
            if not scan_zip:
                return None
            members, err = _zip_members(data)
            for name, blob in members:
                r = scan_one(blob, name)
                if r:
                    return r
            if err and on_err == "match":
                return [{"matcher": "pickle_opcode", "at": where, "member": "<zip>", "parse_error": err[:160]}]
            return None
        ext_hint = (ev.filename or "").lower().endswith(PICKLE_EXTENSIONS)
        if looks_like_pickle(data) or (ext_hint and not data.startswith(_SAFE_MAGIC) and not _is_safetensors(data)):
            return scan_one(data, ev.filename or "<stream>")
        return None
    return m


# --- JSONPath-lite ----------------------------------------------------------------

_JP_TOKEN = re.compile(r"""\.\.(\*|[A-Za-z_$][\w$-]*)?|\.(\*|[A-Za-z_$][\w$-]*)|\[(\*|-?\d+|(?:'[^']*'|"[^"]*")(?:\s*,\s*(?:'[^']*'|"[^"]*"))*)\]""")


def parse_jsonpath(path: str, where: str = "path") -> list[tuple[str, Any]]:
    """Subset: $  .name  .*  ..name  ..*  [n]  [*]  ['a','b']  ..['a'] (via ..  then [..])."""
    if not path.startswith("$"):
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
            elif re.fullmatch(r"-?\d+", inner):
                if pending_desc:
                    raise FeedError(f"{where}: '..[n]' is not supported")
                steps.append(("index", int(inner)))
            else:
                names = [s.strip()[1:-1] for s in re.findall(r"""'[^']*'|"[^"]*\"""", inner)]
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


def _m_jsonpath(node: dict, where: str, depth: int) -> Matcher:
    steps = parse_jsonpath(node["path"], where + ".path")
    sub = compile_matcher(node["match"], where + ".match", depth + 1) if "match" in node else None
    has_equals = "equals" in node
    equals = node.get("equals")
    exists = node.get("exists", True)

    def m(ev: Event):
        if not ev.has_json:
            return None
        sel = jsonpath_select(ev.json, steps)
        if exists is False:
            return [{"matcher": "jsonpath", "at": where, "absent": node["path"]}] if not sel else None
        for v in sel:
            if has_equals and v != equals:
                continue
            if sub is not None:
                if isinstance(v, str):
                    sev = Event(surface=ev.surface, text=v, url=v, json=v)
                else:
                    sev = Event(surface=ev.surface, text=json.dumps(v, ensure_ascii=False, sort_keys=True), json=v)
                r = sub(sev)
                if r is None:
                    continue
                return [{"matcher": "jsonpath", "at": where, "path": node["path"]}] + r
            return [{"matcher": "jsonpath", "at": where, "path": node["path"],
                     "value": printable(json.dumps(v, ensure_ascii=False)[:120])}]
        return None
    return m


# --- Semantic exemplars -----------------------------------------------------------

_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss", "đ": "d", "Đ": "D"})


def normalize_for_similarity(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.translate(_FOLD))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _trigrams(s: str) -> set[str]:
    s = f" {s} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def lexical_similarity(exemplar: str, text: str) -> float:
    """Reference/offline score: share of the exemplar's char-trigrams present in text.
    The gateway uses embedding cosine (`threshold`); this keeps vectors testable
    without a model and is a sound pre-filter."""
    g_ex = _trigrams(normalize_for_similarity(exemplar))
    g_in = _trigrams(normalize_for_similarity(text))
    return len(g_ex & g_in) / len(g_ex) if g_ex else 0.0


def _m_semantic(node: dict, where: str) -> Matcher:
    exemplars = list(node["exemplars"])
    thr = node.get("lexical_threshold", 0.8)
    fld = node.get("field", "all")

    def m(ev: Event):
        text = ev.view(fld)
        if not text:
            return None
        best, best_ex = 0.0, ""
        for ex in exemplars:
            s = lexical_similarity(ex, text)
            if s > best:
                best, best_ex = s, ex
        if best >= thr:
            return [{"matcher": "semantic_exemplar", "at": where, "score": round(best, 3),
                     "mode": "lexical-reference", "exemplar": best_ex[:80]}]
        return None
    return m


# --------------------------------------------------------------------------- #
# Composition                                                                 #
# --------------------------------------------------------------------------- #

def compile_matcher(node: dict, where: str = "matcher", depth: int = 0) -> Matcher:
    if depth > MAX_MATCHER_DEPTH:
        raise FeedError(f"{where}: matcher nesting deeper than {MAX_MATCHER_DEPTH}")
    if not isinstance(node, dict):
        raise FeedError(f"{where}: matcher must be a mapping")
    if "any_of" in node:
        subs = [compile_matcher(n, f"{where}.any_of[{i}]", depth + 1) for i, n in enumerate(node["any_of"])]

        def any_of(ev: Event):
            for s in subs:
                r = s(ev)
                if r is not None:
                    return r
            return None
        return any_of
    if "all_of" in node:
        subs = [compile_matcher(n, f"{where}.all_of[{i}]", depth + 1) for i, n in enumerate(node["all_of"])]

        def all_of(ev: Event):
            ev_all: list = []
            for s in subs:
                r = s(ev)
                if r is None:
                    return None
                ev_all.extend(r)
            return ev_all
        return all_of
    if "not" in node:
        sub = compile_matcher(node["not"], f"{where}.not", depth + 1)

        def not_(ev: Event):
            return [] if sub(ev) is None else None
        return not_
    t = node.get("type")
    if t == "regex":
        return _m_regex(node, where)
    if t == "literal":
        return _m_literal(node, where)
    if t == "url":
        return _m_url(node, where)
    if t == "package":
        return _m_package(node, where)
    if t == "hash":
        return _m_hash(node, where)
    if t == "bytes":
        return _m_bytes(node, where)
    if t == "pickle_opcode":
        return _m_pickle(node, where)
    if t == "jsonpath":
        return _m_jsonpath(node, where, depth)
    if t == "semantic_exemplar":
        return _m_semantic(node, where)
    raise FeedError(f"{where}: unknown matcher type {t!r} (allowed: {', '.join(LEAF_TYPES)})")


def iter_regexes(node: Any, where: str = "matcher"):
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


@dataclass
class CompiledSignature:
    sig: dict
    match: Matcher

    @property
    def id(self) -> str:
        return self.sig["id"]

    @property
    def status(self) -> str:
        return self.sig["status"]

    def action_for(self, surface: str) -> str:
        return self.sig.get("action_overrides", {}).get(surface, self.sig["action"])

    def evaluate(self, ev: Event) -> "dict | None":
        if self.status == "withdrawn" or ev.surface not in self.sig["applies_to"]:
            return None
        evidence = self.match(ev)
        if evidence is None:
            return None
        return {
            "signature_id": self.id,
            "title": self.sig["title"],
            "severity": self.sig["severity"],
            "aliases": self.sig.get("aliases", []),
            "action": self.action_for(ev.surface),
            "mode": "monitor" if self.status in MONITOR_STATUSES else "enforce",
            "message": self.sig.get("message", self.sig["title"]),
            "evidence": evidence,
        }


def compile_signature(sig: dict) -> CompiledSignature:
    return CompiledSignature(sig=sig, match=compile_matcher(sig["matcher"], f"{sig.get('id', '?')}.matcher"))


def decide(hits: list[dict]) -> str:
    """Strongest enforced action wins; no enforced hits -> allow."""
    enforced = [h["action"] for h in hits if h["mode"] == "enforce"]
    if not enforced:
        return "allow"
    return min(enforced, key=ACTIONS.index)


def scan_event(compiled: list[CompiledSignature], ev: Event) -> tuple[str, list[dict]]:
    hits = [h for c in compiled if (h := c.evaluate(ev)) is not None]
    return decide(hits), hits


# --------------------------------------------------------------------------- #
# Keys, bundles, signatures (Ed25519 via PyNaCl)                              #
# --------------------------------------------------------------------------- #

def key_id_for(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:16]


def read_hex_key(path: Path, expected_len: int = 32) -> bytes:
    raw = "".join(l for l in Path(path).read_text().splitlines() if not l.startswith("#")).strip()
    try:
        key = binascii.unhexlify(raw)
    except binascii.Error as e:
        raise FeedError(f"{path}: not a hex key: {e}") from None
    if len(key) != expected_len:
        raise FeedError(f"{path}: expected {expected_len} bytes, got {len(key)}")
    return key


def sign_document(doc: dict, seed: bytes) -> dict:
    from nacl.signing import SigningKey

    sk = SigningKey(seed)
    pub = bytes(sk.verify_key)
    body = {k: v for k, v in doc.items() if k != "signature"}
    body["alg"] = "ed25519"
    body["key_id"] = key_id_for(pub)
    sig = sk.sign(canonical_json(body)).signature
    return {**body, "signature": base64.b64encode(sig).decode("ascii")}


def verify_document(doc: dict, public_key: bytes) -> None:
    """Raise FeedError unless doc['signature'] is a valid Ed25519 signature over
    canonical_json(doc minus 'signature') by public_key."""
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey

    if not isinstance(doc, dict) or "signature" not in doc:
        raise FeedError("unsigned document")
    if doc.get("alg") != "ed25519":
        raise FeedError(f"unsupported alg {doc.get('alg')!r}")
    if doc.get("key_id") != key_id_for(public_key):
        raise FeedError(f"key_id {doc.get('key_id')!r} does not match pinned key {key_id_for(public_key)}")
    try:
        sig = base64.b64decode(doc["signature"], validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise FeedError("signature is not valid base64") from None
    body = {k: v for k, v in doc.items() if k != "signature"}
    try:
        VerifyKey(public_key).verify(canonical_json(body), sig)
    except BadSignatureError:
        raise FeedError("bad signature (bundle was modified or signed with another key)") from None


def utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def iso(ts: _dt.datetime) -> str:
    return ts.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> _dt.datetime:
    return _dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
