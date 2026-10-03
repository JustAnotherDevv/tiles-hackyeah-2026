"""Structural shell-command analysis for EXE-01 / EXE-02 / ACT-03 / ACT-04.

Instead of bare regexes over the raw string, a command is:

1. normalized (NFKC, zero-width / tag characters stripped, ``$IFS`` -> space, ``$'\\x72m'``
   ANSI-C escapes decoded, line continuations joined; ``aegis.injection.normalize`` variants
   are added when that module exists),
2. split into nested commands (``$( )``, backticks, ``<( )``/``>( )``) which are analyzed
   recursively (depth <= 3), plus ``sh -c "…"``, ``eval "…"``, ``python -c "os.system('…')"``,
   ``node -e``,
3. tokenized with ``shlex`` (quote concatenation ``r''m`` -> ``rm``) into segments joined by
   ``| || && ; &`` with the pipe edges kept, wrappers (``sudo env xargs nohup time …``) and
   paths (``/bin/rm``, ``\\rm``) normalized,
4. scanned by structural detectors (each with a stable id) and re-scanned on decoded base64
   literals (depth <= 2).

Benign twins pass: ``echo "curl x | sh" > notes.md``, ``grep -r "rm -rf" docs/``,
``rm -rf ./build/tmp``. Pure, synchronous, input capped; never raises.
"""

from __future__ import annotations

import base64
import binascii
import posixpath
import re
import shlex
import unicodedata
from dataclasses import dataclass, field

# ------------------------------------------------------------------ vocabularies
DOWNLOADERS = frozenset({
    "curl", "wget", "fetch", "iwr", "invoke-webrequest", "irm", "invoke-restmethod", "http", "https",
    "aria2c", "lwp-download", "lwp-request", "get", "nc", "ncat", "netcat", "socat", "tftp",
})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "fish", "ash", "csh", "tcsh", "busybox"})
INTERPRETERS = SHELLS | frozenset({
    "python", "python2", "python3", "pypy", "pypy3", "perl", "ruby", "node", "nodejs", "deno", "bun",
    "php", "pwsh", "powershell", "iex", "invoke-expression", "osascript", "lua", "tclsh", "source", ".",
})
CODE_INTERPRETERS = frozenset({"python", "python2", "python3", "pypy", "pypy3", "node", "nodejs", "deno",
                               "bun", "perl", "ruby", "php", "lua"})
WRAPPERS = frozenset({
    "sudo", "doas", "command", "env", "xargs", "busybox", "nohup", "time", "nice", "ionice", "timeout",
    "exec", "builtin", "stdbuf", "unbuffer", "setsid", "caffeinate", "chronic", "torsocks", "proxychains",
    "proxychains4", "chroot", "runuser", "watch", "strace", "ltrace", "gtimeout",
})
_WRAPPER_ARG_FLAGS = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S", "--unset", "--chdir"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p"},
    "xargs": {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "--max-args", "--replace"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "stdbuf": {"-i", "-o", "-e"},
    "watch": {"-n", "-d"},
    "runuser": {"-u", "-g"},
}
_WRAPPER_POSITIONAL = {"timeout": 1, "gtimeout": 1, "chroot": 1}
SQL_CLIENTS = frozenset({"psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "clickhouse-client", "duckdb",
                         "snowsql", "bq", "cockroach", "pgcli", "mycli", "litecli", "usql"})
TEXT_TOOLS = frozenset({"echo", "printf", "grep", "egrep", "fgrep", "rg", "ag", "ack", "git-grep", "man",
                        "less", "more", "cat", "head", "tail", "wc", "sort", "uniq", "tr", "cut", "jq", "yq"})
WRITE_PROGS_LAST = frozenset({"cp", "mv", "install", "ln", "rsync", "scp", "ditto"})
WRITE_PROGS_ALL = frozenset({"tee", "touch", "truncate", "chmod", "chown", "chgrp", "rm", "rmdir", "shred",
                             "unlink", "mkdir", "dd"})

_ZERO_WIDTH_RX = re.compile("[​-‏⁠-⁤﻿­᠎]|[\U000e0000-\U000e007f]")
_IFS_RX = re.compile(r"\$\{IFS(?:[^}]*)\}|\$IFS\b")
_ANSI_C_RX = re.compile(r"\$'((?:[^'\\]|\\.)*)'")
_B64_TOKEN_RX = re.compile(r"(?<![A-Za-z0-9+/=])([A-Za-z0-9+/]{8,}={0,2})(?![A-Za-z0-9+/=])")
_STR_LIT_RX = re.compile(r"""(?s)('''.*?'''|\"\"\".*?\"\"\"|'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""")
_EXEC_CALL_RX = re.compile(
    r"(?i)(os\.system|os\.popen|os\.exec\w*|subprocess\.\w+|commands\.getoutput|pty\.spawn|"
    r"child_process|execSync|exec\(|spawnSync|spawn\(|system\(|`|Runtime\.getRuntime|shell_exec|passthru|popen)"
)
_DROP_RX = re.compile(r"(?i)\b(drop|truncate)\s+table\b")
_UNSAFE_DESER_RX = re.compile(
    r"(pickle\.loads?\s*\(|cPickle\.loads?\s*\(|dill\.loads?\s*\(|marshal\.loads?\s*\(|"
    r"torch\.load\s*\([^)]*weights_only\s*=\s*False|"
    r"yaml\.load\s*\([^)]*Loader\s*=\s*(yaml\.)?(Unsafe)?Loader\b|yaml\.unsafe_load\s*\(|"
    r"jsonpickle\.decode\s*\(|shelve\.open\s*\()"
)
_REVSHELL_CODE_RX = re.compile(r"(?is)socket.*(subprocess|pty\.spawn|dup2|/bin/(ba)?sh)|fsockopen\s*\(")
AI_BYPASS_FLAGS = (
    "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "--yolo", "--trust-all-tools",
    "--dangerously-bypass-approvals-and-sandbox", "--full-auto",
)
_BROAD_RM_EXACT = {
    "/", "~", "$home", "${home}", "..", "../..", "/etc", "/usr", "/var", "/bin", "/sbin", "/lib", "/opt",
    "/boot", "/root", "/system", "/library", "/applications", "/users", "/home", "/private", "/dev",
}
SEPARATORS = {"|", "|&", "||", "&&", ";", "&", ";;", "(", ")", "&;", ";&", "{", "}"}
_SUB_RX = re.compile(r"__AEGISSUB(\d+)__")


@dataclass
class Segment:
    argv: list[str]
    prog: str
    wrappers: list[str] = field(default_factory=list)
    piped: bool = False  # stdin comes from the previous segment's stdout
    pipeline: int = 0
    redirects: list[tuple[str, str]] = field(default_factory=list)
    assigns: list[str] = field(default_factory=list)

    @property
    def args(self) -> list[str]:
        return self.argv[1:]

    def text(self) -> str:
        return " ".join(self.argv)


@dataclass
class Hit:
    id: str
    detail: str
    excerpt: str = ""
    via: str = ""  # "" | "nested" | "decoded"
    decoded: str | None = None


@dataclass
class CommandAnalysis:
    raw: str
    text: str = ""
    segments: list[Segment] = field(default_factory=list)
    inner: list[CommandAnalysis] = field(default_factory=list)
    decoded: list[tuple[str, CommandAnalysis]] = field(default_factory=list)
    code: list[str] = field(default_factory=list)  # python -c / node -e bodies
    urls: list[str] = field(default_factory=list)
    paths: list[tuple[str, str]] = field(default_factory=list)  # (path, "read"|"write")
    hits: list[Hit] = field(default_factory=list)
    parse_error: str | None = None
    depth: int = 0

    # ---- aggregated views (self + nested + decoded)
    def walk(self) -> list[CommandAnalysis]:
        out = [self]
        for a in self.inner:
            out.extend(a.walk())
        return out

    def all_segments(self) -> list[Segment]:
        return [s for a in self.walk() for s in a.segments]

    def all_urls(self) -> list[str]:
        return list(dict.fromkeys(u for a in self.walk() for u in a.urls))

    def all_paths(self) -> list[tuple[str, str]]:
        return list(dict.fromkeys(p for a in self.walk() for p in a.paths))

    def programs(self) -> list[str]:
        return list(dict.fromkeys(s.prog for s in self.all_segments() if s.prog))

    def all_hits(self) -> list[Hit]:
        out = list(self.hits)
        for a in self.inner:
            for h in a.all_hits():
                out.append(Hit(h.id, h.detail, h.excerpt, h.via or "nested", h.decoded))
        return out


# ------------------------------------------------------------------ normalization
def _ansi_c(m: re.Match[str]) -> str:
    body = m.group(1)
    try:
        decoded = bytes(body, "utf-8").decode("unicode_escape")
    except Exception:
        decoded = body
    return "'" + decoded.replace("'", "'\\''") + "'"


def normalize_command(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = _ZERO_WIDTH_RX.sub("", t)
    t = t.replace("\\\r\n", " ").replace("\\\n", " ")
    t = _IFS_RX.sub(" ", t)
    t = _ANSI_C_RX.sub(_ansi_c, t)
    return t


def _external_variants(text: str) -> list[str]:
    """Decoded layers from aegis.injection.normalize (guarded; injection-defense owns it)."""
    try:
        from aegis.injection.normalize import normalize as inj_normalize
    except Exception:  # TODO(integration): injection-defense public surface not present yet
        return []
    try:
        res = inj_normalize(text)
    except Exception:
        return []
    out = [v for v in (getattr(res, "variants", None) or []) if isinstance(v, str)]
    folded = getattr(res, "text", None)
    if isinstance(folded, str) and folded != text:
        out.append(folded)
    return out[:6]


def _b64_decode(tok: str) -> str | None:
    s = tok.strip()
    if len(s) < 8:
        return None
    pad = (-len(s)) % 4
    try:
        raw = base64.b64decode(s + "=" * pad, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        dec = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not dec.strip():
        return None
    printable = sum(1 for c in dec if c.isprintable() or c in "\n\t")
    if printable / len(dec) < 0.95 or not re.search(r"[ /|;&$~.-]", dec):
        return None
    return dec


# ------------------------------------------------------------------ nested command extraction
def _extract_subs(text: str) -> tuple[str, list[str]]:
    """Replace ``$( )``, backticks, ``<( )``, ``>( )`` with placeholders (quote-aware) and turn
    unquoted newlines into ``;``. Returns (outer text, inner texts)."""
    out: list[str] = []
    subs: list[str] = []
    i, n = 0, len(text)
    quote: str | None = None
    while i < n:
        c = text[i]
        if quote == "'":
            out.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\" and i + 1 < n and quote != "'":
            out.append(text[i : i + 2])
            i += 2
            continue
        if c == "'" and quote is None:
            quote = "'"
            out.append(c)
            i += 1
            continue
        if c == '"':
            quote = None if quote == '"' else '"'
            out.append(c)
            i += 1
            continue
        if (c == "$" or (c in "<>" and quote is None)) and i + 1 < n and text[i + 1] == "(" and not text.startswith("$((", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                j += 1
            subs.append(text[i + 2 : j - 1])
            out.append(f"__AEGISSUB{len(subs) - 1}__")
            i = j
            continue
        if c == "`":
            j = text.find("`", i + 1)
            j = n if j == -1 else j
            subs.append(text[i + 1 : j])
            out.append(f"__AEGISSUB{len(subs) - 1}__")
            i = j + 1
            continue
        if c in "\n\r" and quote is None:
            out.append(" ; ")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out), subs


def _tokenize(text: str) -> tuple[list[str], str | None]:
    def run(t: str) -> list[str]:
        lex = shlex.shlex(t, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)

    try:
        return run(text), None
    except ValueError as exc:
        for closer in ('"', "'"):
            try:
                return run(text + closer), f"unbalanced quotes ({exc})"
            except ValueError:
                continue
        return text.split(), f"unparseable ({exc})"


def _is_redirect(tok: str) -> bool:
    return bool(tok) and set(tok) <= set("<>&|") and ("<" in tok or ">" in tok) and tok not in SEPARATORS


def _strip_wrappers(argv: list[str]) -> tuple[list[str], list[str], list[str]]:
    """-> (argv without env assignments/wrappers, wrappers, assignments)."""
    wrappers: list[str] = []
    assigns: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        is_assign = bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tok))
        if is_assign and (not wrappers or wrappers[-1] == "env"):
            assigns.append(tok)
            i += 1
            continue
        base = _prog_name(tok)
        if base in WRAPPERS and i + 1 < len(argv):
            wrappers.append(base)
            i += 1
            flags = _WRAPPER_ARG_FLAGS.get(base, set())
            positional = _WRAPPER_POSITIONAL.get(base, 0)
            while i < len(argv):
                t = argv[i]
                if t == "--":
                    i += 1
                    break
                if t.startswith("-") and len(t) > 1:
                    i += 2 if (t in flags and "=" not in t) else 1
                    continue
                if base == "env" and "=" in t:
                    assigns.append(t)
                    i += 1
                    continue
                if positional:
                    positional -= 1
                    i += 1
                    continue
                break
            continue
        break
    return argv[i:], wrappers, assigns


def _prog_name(tok: str) -> str:
    t = tok.strip().lstrip("\\")
    t = posixpath.basename(t) if "/" in t and not t.startswith("__AEGISSUB") else t
    return t.lower()


def _segments(tokens: list[str]) -> list[Segment]:
    segs: list[Segment] = []
    cur: list[str] = []
    redirects: list[tuple[str, str]] = []
    piped_next = False
    pipeline = 0
    i = 0

    def flush(piped: bool) -> None:
        nonlocal cur, redirects
        if cur:
            argv, wrappers, assigns = _strip_wrappers(cur)
            if argv:
                segs.append(Segment(argv=argv, prog=_prog_name(argv[0]), wrappers=wrappers, piped=piped,
                                    pipeline=pipeline, redirects=redirects, assigns=assigns))
            elif wrappers or assigns:
                segs.append(Segment(argv=[cur[0]], prog=_prog_name(cur[0]), wrappers=wrappers, piped=piped,
                                    pipeline=pipeline, redirects=redirects, assigns=assigns))
        cur, redirects = [], []

    piped_cur = False
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("|", "|&"):
            flush(piped_cur)
            piped_cur = True
            piped_next = True
        elif tok in SEPARATORS:
            flush(piped_cur)
            piped_cur = False
            piped_next = False
            pipeline += 1
        elif _is_redirect(tok):
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            if cur and cur[-1].isdigit() and len(cur[-1]) == 1:
                cur.pop()  # "2>" fd number
            if tok in (">&", "<&") and target.isdigit():
                i += 2
                continue
            redirects.append((tok, target))
            i += 2
            continue
        else:
            cur.append(tok)
        i += 1
    flush(piped_cur)
    _ = piped_next
    return segs


# ------------------------------------------------------------------ per-segment extraction
_CURL_FILE_FLAGS = {"-d", "--data", "--data-binary", "--data-raw", "--data-ascii", "--data-urlencode", "-F",
                    "--form", "-T", "--upload-file", "-K", "--config"}
_FLAG_WITH_VALUE = {"-o", "-O", "--output", "-H", "--header", "-X", "--request", "-u", "--user", "-A",
                    "--user-agent", "-e", "--referer", "-b", "--cookie", "-c", "--cookie-jar", "-m",
                    "--max-time", "-w", "--write-out", "-x", "--proxy", "-p", "--port", "-i", "-l", "-k",
                    "-n", "-C", "--connect-timeout", "--retry", "-P", "--directory-prefix"}


def _looks_like_path(tok: str) -> bool:
    if not tok or tok.startswith("-") or "://" in tok or _SUB_RX.search(tok):
        return False
    if re.fullmatch(r"[\d.:,]+", tok):
        return False
    if tok.startswith(("~", "/", "./", "../", "$HOME", "${HOME}")) or "/" in tok:
        return True
    return bool(re.fullmatch(r"\.?[\w.\-]+", tok)) and ("." in tok or tok.startswith("."))


def _segment_urls(seg: Segment) -> list[str]:
    urls = [t for t in seg.argv if "://" in t]
    if seg.prog in ("curl", "wget", "http", "https", "fetch", "aria2c", "lwp-request", "get"):
        skip = False
        for t in seg.args:
            if skip:
                skip = False
                continue
            if t in _FLAG_WITH_VALUE or t in _CURL_FILE_FLAGS:
                skip = True
                continue
            if t.startswith("-") or "://" in t or t.startswith("@") or _SUB_RX.search(t):
                continue
            if re.match(r"^[\w.\-\[\]:]+(:\d+)?(/\S*)?$", t) and ("." in t or ":" in t):
                urls.append(f"http://{t}")
    if seg.prog in ("nc", "ncat", "netcat", "telnet", "socat"):
        pos = [t for t in seg.args if not t.startswith("-") and not t.lower().startswith(("exec:", "system:"))]
        if seg.prog == "socat":
            for t in seg.args:
                m = re.match(r"(?i)tcp[46]?(?:-connect)?:([^:,]+):(\d+)", t)
                if m:
                    urls.append(f"http://{m.group(1)}:{m.group(2)}")
        elif pos:
            host = pos[0]
            port = pos[1] if len(pos) > 1 and pos[1].isdigit() else None
            urls.append(f"http://{host}:{port}" if port else f"http://{host}")
    return urls


def _segment_paths(seg: Segment) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for op, target in seg.redirects:
        if target and not target.isdigit() and not _SUB_RX.search(target):
            out.append((target, "read" if op.startswith("<") else "write"))
    args = seg.args
    prog = seg.prog
    if prog in ("curl", "wget"):
        for i, t in enumerate(args):
            if t in _CURL_FILE_FLAGS and i + 1 < len(args):
                v = args[i + 1]
                m = re.search(r"@([^;\s]+)", v)
                if m:
                    out.append((m.group(1), "read"))
                elif t in ("-T", "--upload-file", "-K", "--config"):
                    out.append((v, "read"))
            elif t.startswith(("--data-binary=@", "--data=@", "-d@")):
                out.append((t.split("@", 1)[1], "read"))
            elif t in ("-o", "--output", "-O") and i + 1 < len(args) and t != "-O":
                out.append((args[i + 1], "write"))
        return out
    cands = [t for t in args if _looks_like_path(t)]
    if prog == "sed" and any(a.startswith("-i") for a in args):
        return out + [(c, "write") for c in cands]
    if prog in WRITE_PROGS_LAST and len(cands) >= 2:
        return out + [(c, "read") for c in cands[:-1]] + [(cands[-1], "write")]
    if prog in WRITE_PROGS_ALL:
        if prog == "dd":
            for t in args:
                if t.startswith("of="):
                    out.append((t[3:], "write"))
                elif t.startswith("if="):
                    out.append((t[3:], "read"))
            return out
        return out + [(c, "write") for c in cands]
    if prog in ("git",) and args[:1] and args[0] in ("push", "pull", "fetch", "clone", "remote", "commit", "log",
                                                      "status", "diff", "checkout", "switch", "branch"):
        return out
    return out + [(c, "read") for c in cands]


# ------------------------------------------------------------------ analysis
def analyze_command(cmd: str, *, depth: int = 0, max_depth: int = 3, decode_depth: int = 2,
                    max_chars: int = 20_000, use_external: bool = True) -> CommandAnalysis:
    """Analyze one shell command line (see module docstring)."""
    if not isinstance(cmd, str):
        cmd = str(cmd or "")
    raw = cmd if len(cmd) <= max_chars else cmd[: max_chars // 2] + "\n" + cmd[-max_chars // 2 :]
    text = normalize_command(raw)
    res = CommandAnalysis(raw=raw, text=text, depth=depth)
    try:
        outer, subs = _extract_subs(text)
        tokens, err = _tokenize(outer)
        res.parse_error = err
        res.segments = _segments(tokens)
    except Exception as exc:  # defensive: never raise from the hot path
        res.parse_error = f"{type(exc).__name__}: {exc}"
        subs = []
    if depth < max_depth:
        for s in subs:
            res.inner.append(analyze_command(s, depth=depth + 1, max_depth=max_depth, decode_depth=decode_depth,
                                             max_chars=max_chars, use_external=False))
        _nested_from_args(res, depth, max_depth, decode_depth, max_chars)
    for seg in res.segments:
        res.urls.extend(u for u in _segment_urls(seg) if u not in res.urls)
        for p in _segment_paths(seg):
            if p not in res.paths:
                res.paths.append(p)
    _detect(res, subs)
    if decode_depth > 0:
        _decoded_variants(res, depth, max_depth, decode_depth, max_chars, use_external)
    return res


def _nested_from_args(res: CommandAnalysis, depth: int, max_depth: int, decode_depth: int, max_chars: int) -> None:
    def sub(text: str) -> None:
        if text and text.strip():
            res.inner.append(analyze_command(text, depth=depth + 1, max_depth=max_depth,
                                             decode_depth=decode_depth, max_chars=max_chars, use_external=False))

    for seg in res.segments:
        args = seg.args
        if seg.prog in SHELLS:
            for i, a in enumerate(args):
                if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a) and i + 1 < len(args):
                    sub(_resolve_subs(args[i + 1], res))
                    break
        elif seg.prog == "eval":
            sub(_resolve_subs(" ".join(args), res))
        elif seg.prog in ("su",) and "-c" in args:
            i = args.index("-c")
            if i + 1 < len(args):
                sub(args[i + 1])
        elif seg.prog in CODE_INTERPRETERS:
            for i, a in enumerate(args):
                if a in ("-c", "-e", "-r", "--eval", "-E", "-p") and i + 1 < len(args):
                    code = args[i + 1]
                    res.code.append(code)
                    if _EXEC_CALL_RX.search(code):
                        for lit in _STR_LIT_RX.findall(code):
                            body = lit.strip("'\"")
                            if re.search(r"[a-z]", body) and " " in body or "|" in body:
                                sub(body)
                        for m in re.finditer(r"`([^`]+)`", code):
                            sub(m.group(1))
                    break


def _resolve_subs(text: str, res: CommandAnalysis) -> str:
    """Placeholders back to their source text (for re-analysis of -c / eval strings)."""
    return _SUB_RX.sub(lambda m: f"$({res.inner[int(m.group(1))].raw})" if int(m.group(1)) < len(res.inner) else "", text)


def _decoded_variants(res: CommandAnalysis, depth: int, max_depth: int, decode_depth: int, max_chars: int,
                      use_external: bool) -> None:
    seen: set[str] = set()
    cands: list[str] = []
    for tok in _B64_TOKEN_RX.findall(res.text):
        dec = _b64_decode(tok)
        if dec and dec not in seen:
            seen.add(dec)
            cands.append(dec)
    if use_external:
        for v in _external_variants(res.text):
            if v and v != res.text and v not in seen:
                seen.add(v)
                cands.append(v)
    for dec in cands[:6]:
        a = analyze_command(dec, depth=depth + 1, max_depth=max_depth, decode_depth=decode_depth - 1,
                            max_chars=max_chars, use_external=False)
        res.decoded.append((dec, a))
        hits = a.all_hits()
        if hits:
            first = hits[0]
            executes = any(h.id == "base64_exec" for h in res.hits)
            res.hits = [h for h in res.hits if h.id != "base64_exec"]
            detail = (f"base64 payload decodes to `{_short(dec)}`"
                      + (" and is piped into a shell" if executes else "")
                      + f" ({first.detail})")
            res.hits.insert(0, Hit("base64_exec", detail, _short(dec), "decoded", dec))


def _short(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _executes_stdin(seg: Segment) -> bool:
    """Interpreter reads its program from stdin (``| sh``, ``| python3 -``, ``| bash -s``)."""
    if seg.prog not in INTERPRETERS or seg.prog in ("source", "."):
        return False
    args = seg.args
    if seg.prog == "busybox":
        if not args or args[0] not in SHELLS:
            return False
        args = args[1:]
    for a in args:
        if a in ("-c", "-e", "-m", "-E", "--command", "-r") or re.fullmatch(r"-[a-zA-Z]*c", a) and seg.prog in SHELLS:
            return False
    positional = next((a for a in args if not a.startswith("-") or a == "-"), None)
    if positional is None or positional == "-" or "-s" in args:
        return True
    return bool(_SUB_RX.search(positional))  # bash <(curl …) handled separately


def _sub_has(res: CommandAnalysis, tok: str, progs: frozenset[str]) -> CommandAnalysis | None:
    for m in _SUB_RX.finditer(tok):
        idx = int(m.group(1))
        if idx < len(res.inner) and any(p in progs for p in res.inner[idx].programs()):
            return res.inner[idx]
    return None


def _first_prog(a: CommandAnalysis, progs: frozenset[str]) -> str:
    return next((p for p in a.programs() if p in progs), "?")


def _detect(res: CommandAnalysis, subs: list[str]) -> None:
    segs = res.segments
    hits = res.hits

    def add(hid: str, detail: str, excerpt: str = "") -> None:
        if not any(h.id == hid for h in hits):
            hits.append(Hit(hid, detail, _short(excerpt or res.text)))

    # --- pipe_to_shell / base64_exec over pipe chains
    by_pipe: dict[int, list[Segment]] = {}
    for s in segs:
        by_pipe.setdefault(s.pipeline, []).append(s)
    for chain in by_pipe.values():
        dl = next((s for s in chain if s.prog in DOWNLOADERS), None)
        b64 = next((s for s in chain if _is_decoder(s)), None)
        for s in chain:
            if not (s.piped and _executes_stdin(s)):
                continue
            if dl is not None and chain.index(dl) < chain.index(s):
                add("pipe_to_shell", f"{dl.prog} output piped into {s.prog} executes a remote script",
                    f"{dl.prog} … | {s.prog}")
            if b64 is not None and chain.index(b64) < chain.index(s):
                add("base64_exec", f"decodes a hidden base64 payload and pipes it into {s.prog}",
                    f"{b64.prog} -d | {s.prog}")
    for s in segs:
        # bash <(curl …) / source <(curl …) / sh -c "$(curl …)" / eval "$(curl …)"
        if s.prog in INTERPRETERS or s.prog == "eval":
            for a in s.args:
                inner = _sub_has(res, a, DOWNLOADERS)
                if inner is not None:
                    add("pipe_to_shell",
                        f"{_first_prog(inner, DOWNLOADERS)} output executed by {s.prog} via command substitution",
                        f"{s.prog} <({_first_prog(inner, DOWNLOADERS)} …)")
    # download-then-execute
    downloaded: set[str] = set()
    for s in segs:
        if s.prog in ("curl", "wget"):
            args = s.args
            for i, a in enumerate(args):
                if a in ("-o", "--output", "-O") and i + 1 < len(args) and a != "-O":
                    downloaded.add(posixpath.basename(args[i + 1]))
                elif a.startswith("-O") and len(a) > 2:
                    downloaded.add(posixpath.basename(a[2:]))
            for op, tgt in s.redirects:
                if op.startswith(">"):
                    downloaded.add(posixpath.basename(tgt))
            if s.prog == "wget" and "-O" not in args and "-qO-" not in args:
                for u in _segment_urls(s):
                    downloaded.add(posixpath.basename(u.rstrip("/")))
        elif downloaded:
            target = None
            if posixpath.basename(s.argv[0]) in downloaded and s.argv[0] not in ("chmod",):
                target = s.argv[0]
            elif s.prog in INTERPRETERS:
                pos = next((a for a in s.args if not a.startswith("-")), None)
                if pos and posixpath.basename(pos) in downloaded:
                    target = pos
            if target:
                add("pipe_to_shell", f"downloads a script and then executes it ({posixpath.basename(target)})",
                    f"curl -o … && {s.prog} {posixpath.basename(target)}")

    for s in segs:
        args = s.args
        lower = [a.lower() for a in args]
        # --- reverse shells
        if any("/dev/tcp/" in a or "/dev/udp/" in a for a in s.argv) or any(
            "/dev/tcp/" in t or "/dev/udp/" in t for _, t in s.redirects
        ):
            add("reverse_shell", "opens a shell over /dev/tcp to a remote host", "/dev/tcp/…")
        if s.prog in ("nc", "ncat", "netcat") and any(re.fullmatch(r"-[a-zA-Z]*[ec][a-zA-Z]*", a) for a in args):
            add("reverse_shell", f"{s.prog} -e hands a shell to a remote host", f"{s.prog} -e …")
        if s.prog == "socat" and any(a.startswith(("exec:", "system:")) for a in lower):
            add("reverse_shell", "socat exec: hands a shell to a remote host", "socat … exec:")
        if s.prog in SHELLS and "-i" in args and any(op in (">&", "&>") for op, _ in s.redirects):
            add("reverse_shell", "interactive shell with redirected I/O", f"{s.prog} -i >& …")
        # --- destructive deletes
        if s.prog == "rm":
            rec = any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", a) for a in args) or "--recursive" in args
            targets = [a for a in args if not a.startswith("-")]
            broad = next((t for t in targets if _is_broad_target(t)), None)
            if "--no-preserve-root" in args or (rec and broad is not None):
                add("rm_rf_broad", f"recursive delete of {broad or '/'}", f"rm -rf {broad or '/'}")
        if s.prog == "find" and ("-delete" in args or "-exec" in args and "rm" in args):
            start = next((a for a in args if not a.startswith("-")), None)
            if start and _is_broad_target(start):
                add("rm_rf_broad", f"find {start} -delete wipes a broad tree", f"find {start} -delete")
        # --- chmod 777
        if s.prog == "chmod":
            mode = next((a for a in args if re.fullmatch(r"0?777|a\+rwx|ugo\+rwx|o\+w|a\+w|\+rwx", a)), None)
            rec = any(re.fullmatch(r"-[a-zA-Z]*R[a-zA-Z]*", a) for a in args) or "--recursive" in args
            targets = [a for a in args if not a.startswith("-") and a != mode]
            sysdir = next((t for t in targets if _is_broad_target(t) or t.startswith(("/etc", "/usr", "/var"))), None)
            if mode and (rec or sysdir):
                add("chmod_world", f"world-writable permissions ({mode}) on {sysdir or targets[0] if targets else '?'}",
                    f"chmod {mode} …")
        # --- privilege escalation
        if any(w in ("sudo", "doas") for w in s.wrappers) or s.prog in ("sudo", "doas") or (
            s.prog == "su" and ("-c" in args or not args)
        ):
            add("sudo", "privilege escalation via sudo", "sudo …")
        # --- AI CLI permission bypass (not when merely echoed/grepped)
        if s.prog not in TEXT_TOOLS:
            flag = next((a for a in s.argv for f in AI_BYPASS_FLAGS if a == f or a.startswith(f + "=")), None)
            if flag is None and "--permission-mode" in args:
                i = args.index("--permission-mode")
                if i + 1 < len(args) and args[i + 1].lower() in ("bypasspermissions", "acceptedits"):
                    flag = f"--permission-mode {args[i + 1]}"
            if flag:
                add("ai_cli_bypass", f"AI CLI permission-bypass flag {flag}", f"{s.prog} {flag}")
        # --- crontab persistence
        if s.prog == "crontab" and "-l" not in args:
            add("crontab_write", "modifies the crontab (persistence)", "crontab …")
        # --- ollama registry admin
        if s.prog == "ollama" and args and args[0] in ("push", "create", "cp", "rm"):
            add("ollama_admin", f"model registry admin command (ollama {args[0]})", f"ollama {args[0]}")
    # --- SQL clients: DROP / TRUNCATE TABLE anywhere in the pipeline or heredoc
    if any(s.prog in SQL_CLIENTS for s in segs):
        from aegis.actions.sql import mask_sql

        unquoted = " ; ".join(seg.text() for seg in segs)  # shlex already removed shell quoting
        m = _DROP_RX.search(mask_sql(unquoted))
        if m:
            add("drop_table", f"destructive SQL ({m.group(1).upper()} TABLE) via a database client",
                f"{m.group(1).upper()} TABLE …")
    # --- code bodies: unsafe deserialization, socket reverse shells
    for code in res.code:
        m = _UNSAFE_DESER_RX.search(code)
        if m:
            add("unsafe_deser", f"unsafe deserialization ({m.group(1).rstrip('(').strip()}) executes attacker-controlled code",
                m.group(1))
        if _REVSHELL_CODE_RX.search(code):
            add("reverse_shell", "socket + shell spawn in inline code (reverse shell)", "socket … subprocess")
    _ = subs


def _is_decoder(s: Segment) -> bool:
    a = s.args
    if s.prog in ("base64", "gbase64", "b64decode") and any(x in ("-d", "--decode", "-D", "-di") for x in a):
        return True
    if s.prog == "openssl" and "base64" in a and "-d" in a:
        return True
    if s.prog == "xxd" and any(x.startswith("-r") for x in a):
        return True
    return s.prog in ("uudecode", "base32") and ("-d" in a or s.prog == "uudecode")


def _is_broad_target(t: str) -> bool:
    x = t.strip().strip('"\'').lower()
    if not x:
        return False
    x = re.sub(r"(/\*|/\.|/)+$", "", x) or "/"
    if x in ("*", ".*"):
        return False
    if x in _BROAD_RM_EXACT or x in ("~/*", "~/.") or x.startswith("~") and "/" not in x:
        return True
    if x in ("$home/*", "${home}/*"):
        return True
    return bool(re.fullmatch(r"/(users|home)/[^/]+", x))


# ------------------------------------------------------------------ SQL-arg / code-arg helpers
def sql_hits(sql: str) -> list[Hit]:
    """EXE-01 ``drop_table`` over a SQL argument (literals masked)."""
    from aegis.actions.sql import mask_sql

    m = _DROP_RX.search(mask_sql(sql or ""))
    if not m:
        return []
    return [Hit("drop_table", f"destructive SQL ({m.group(1).upper()} TABLE)", f"{m.group(1).upper()} TABLE …")]


def code_hits(code: str) -> list[Hit]:
    """Unsafe deserialization / embedded shell commands in a code argument (``*.run_python``)."""
    out: list[Hit] = []
    m = _UNSAFE_DESER_RX.search(code or "")
    if m:
        out.append(Hit("unsafe_deser", f"unsafe deserialization ({m.group(1).rstrip('(').strip()})", m.group(1)))
    if _REVSHELL_CODE_RX.search(code or ""):
        out.append(Hit("reverse_shell", "socket + shell spawn in inline code (reverse shell)", "socket … subprocess"))
    if _EXEC_CALL_RX.search(code or ""):
        for lit in _STR_LIT_RX.findall(code):
            body = lit.strip("'\"")
            if " " in body or "|" in body:
                for h in analyze_command(body, depth=1).all_hits():
                    out.append(Hit(h.id, h.detail, h.excerpt, "nested", h.decoded))
    return out


DETECTOR_IDS = (
    "pipe_to_shell", "base64_exec", "reverse_shell", "rm_rf_broad", "chmod_world", "sudo", "ai_cli_bypass",
    "drop_table", "unsafe_deser", "crontab_write", "ollama_admin",
)
DETECTOR_LABELS = {
    "pipe_to_shell": "pipe-to-shell",
    "base64_exec": "base64-to-shell",
    "reverse_shell": "reverse shell",
    "rm_rf_broad": "destructive recursive delete",
    "chmod_world": "world-writable permissions",
    "sudo": "privilege escalation",
    "ai_cli_bypass": "AI-CLI permission bypass",
    "drop_table": "destructive SQL",
    "unsafe_deser": "unsafe deserialization",
    "crontab_write": "crontab persistence",
    "ollama_admin": "model registry admin",
}

__all__ = [
    "DETECTOR_IDS",
    "DETECTOR_LABELS",
    "DOWNLOADERS",
    "INTERPRETERS",
    "SHELLS",
    "CommandAnalysis",
    "Hit",
    "Segment",
    "analyze_command",
    "code_hits",
    "normalize_command",
    "sql_hits",
]
