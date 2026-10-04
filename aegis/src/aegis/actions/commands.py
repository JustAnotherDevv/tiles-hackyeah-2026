"""Command extraction + cached shell analysis shared by EXE-01, EXE-02, EXE-05 and ACT-04.

``analyze_command`` is pure, so results are memoised per (command, limits); the controls that
look at the same Bash call therefore parse it once.

``exec_profile`` (ASI05, EXE-05) is the code-execution classifier over that analysis: which
segments *execute code* (interpreter on a script file, ``-c``/``-e``/``eval`` one-liners, direct
``./script`` execution, package runners such as ``npx``/``uvx``/``pipx run``, package-manager
script hooks such as ``npm run``/``make``), which files the command itself writes or downloads
(for write-then-exec inside one command and across calls), ``chmod +x`` targets, and whether a
segment runs inside a recognised sandbox runner (``bwrap``, ``firejail``, ``nsjail``,
``sandbox-exec``, ``docker run --network none`` without host mounts).
"""

from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from aegis.actions.argpath import first_arg
from aegis.actions.classify import glob_match, normalize_tool_name
from aegis.actions.shell import DOWNLOADERS, CommandAnalysis, Segment, analyze_command
from aegis.core.types import Interaction

DEFAULT_SHELL_TOOLS = (
    "Bash",
    "*.run_command",
    "*.exec_command",
    "*.execute_command",
    "*.shell",
    "terminal.*",
    "*.run_shell",
    "shell.*",
)
DEFAULT_COMMAND_ARGS = ("command", "cmd", "script", "commands")


@lru_cache(maxsize=512)
def analyze_cached(cmd: str, decode_depth: int = 2, max_chars: int = 20_000) -> CommandAnalysis:
    return analyze_command(cmd, decode_depth=decode_depth, max_chars=max_chars)


def matches_any(tool: str | None, patterns: list[str] | tuple[str, ...]) -> bool:
    name = normalize_tool_name(tool)
    return bool(name) and any(glob_match(p, name) for p in patterns)


def _as_text(val: Any) -> str | None:
    if isinstance(val, str):
        return val
    if isinstance(val, list | tuple) and val and all(isinstance(x, str | int | float) for x in val):
        return shlex.join(str(x) for x in val)
    return None


def command_text(
    interaction: Interaction,
    shell_tools: list[str] | tuple[str, ...] = DEFAULT_SHELL_TOOLS,
    command_args: list[str] | tuple[str, ...] = DEFAULT_COMMAND_ARGS,
) -> str | None:
    """The shell command of a shell-like tool call or an ``mcp.init`` launch (A-13)."""
    if interaction.surface == "mcp.init":
        cmd = (interaction.tool_args or {}).get("command") or interaction.meta.get("mcp.command")
        return _as_text(cmd)
    if not matches_any(interaction.tool_name, shell_tools):
        return None
    _, val = first_arg(interaction, list(command_args))
    return _as_text(val)


def analysis_for(
    interaction: Interaction,
    shell_tools: list[str] | tuple[str, ...] = DEFAULT_SHELL_TOOLS,
    command_args: list[str] | tuple[str, ...] = DEFAULT_COMMAND_ARGS,
    *,
    decode_depth: int = 2,
    max_chars: int = 20_000,
) -> CommandAnalysis | None:
    cmd = command_text(interaction, shell_tools, command_args)
    if not cmd or not cmd.strip():
        return None
    return analyze_cached(cmd, decode_depth, max_chars)


# ------------------------------------------------------------------ code-execution classifier (EXE-05)
SCRIPT_SHELLS = frozenset(
    {"sh", "bash", "zsh", "dash", "ksh", "mksh", "fish", "ash", "csh", "tcsh"}
)
SCRIPT_INTERPRETERS = SCRIPT_SHELLS | frozenset(
    {
        "python",
        "python2",
        "python3",
        "pypy",
        "pypy3",
        "node",
        "nodejs",
        "deno",
        "bun",
        "ruby",
        "perl",
        "php",
        "lua",
        "luajit",
        "rscript",
        "tsx",
        "ts-node",
        "osascript",
        "pwsh",
        "powershell",
        "powershell.exe",
        "pwsh.exe",
        "julia",
        "swift",
        "groovy",
        "elixir",
        "java",
        "jshell",
        "source",
        ".",
    }
)
_PY_VERSIONED = re.compile(r"python\d(\.\d+)?|pypy\d(\.\d+)?")
# flag -> the flag consumes the next token (per interpreter family)
_VALUE_FLAGS: dict[str, frozenset[str]] = {
    "python": frozenset({"-W", "-X", "-Q"}),
    "node": frozenset(
        {
            "-r",
            "--require",
            "--import",
            "--loader",
            "--experimental-loader",
            "-C",
            "--conditions",
            "--env-file",
            "--input-type",
        }
    ),
    "ruby": frozenset({"-I", "-r", "-C"}),
    "perl": frozenset({"-I", "-M", "-m"}),
    "shell": frozenset({"-o", "-O", "+O", "+o"}),
    "pwsh": frozenset(
        {
            "-ExecutionPolicy",
            "-executionpolicy",
            "-ep",
            "-WorkingDirectory",
            "-wd",
            "-ConfigurationName",
            "-OutputFormat",
            "-InputFormat",
            "-Version",
        }
    ),
    "deno": frozenset(
        {
            "--config",
            "-c",
            "--import-map",
            "--lock",
            "--cert",
            "--location",
            "--v8-flags",
            "--env-file",
            "--allow-env",
            "--allow-read",
        }
    ),
}
_INLINE_FLAGS: dict[str, frozenset[str]] = {
    "python": frozenset({"-c"}),
    "node": frozenset({"-e", "--eval", "-p", "--print"}),
    "bun": frozenset({"-e", "--eval", "-p", "--print"}),
    "deno": frozenset(),  # `deno eval <code>`
    "ruby": frozenset({"-e"}),
    "perl": frozenset({"-e", "-E"}),
    "php": frozenset({"-r"}),
    "lua": frozenset({"-e"}),
    "osascript": frozenset({"-e"}),
    "pwsh": frozenset({"-c", "-command", "-encodedcommand", "-enc", "-e", "-ec"}),
}
PKG_RUNNERS = {  # prog -> sub-command that fetches + runs a (possibly remote) package
    "npx": None,
    "bunx": None,
    "pnpx": None,
    "uvx": None,
    "npm": ("exec", "x"),
    "pnpm": ("dlx",),
    "yarn": ("dlx",),
    "pipx": ("run",),
}
RUN_WRAPPERS = {  # prog -> sub-command after which the real argv follows
    "uv": ("run",),
    "poetry": ("run",),
    "pipenv": ("run",),
    "pdm": ("run",),
    "hatch": ("run",),
    "rye": ("run",),
    "bundle": ("exec",),
    "conda": ("run",),
    "mamba": ("run",),
    "micromamba": ("run",),
}
_RUN_WRAPPER_VALUE_FLAGS = frozenset(
    {
        "--with",
        "--python",
        "-p",
        "--project",
        "--directory",
        "--env-file",
        "--group",
        "--extra",
        "--package",
        "-n",
        "--name",
        "--prefix",
        "--index",
        "--index-url",
        "-w",
    }
)
# package-manager script hooks -> the manifest whose content decides what runs
_PKG_SCRIPT_MANIFESTS: dict[str, tuple[str, ...]] = {
    "npm": ("package.json",),
    "pnpm": ("package.json",),
    "yarn": ("package.json",),
    "bun": ("package.json",),
    "make": ("Makefile", "makefile", "GNUmakefile"),
    "gmake": ("Makefile", "makefile", "GNUmakefile"),
    "just": ("justfile", "Justfile"),
    "cargo": ("build.rs", "Cargo.toml"),
    "nox": ("noxfile.py",),
    "tox": ("tox.ini",),
    "pip": ("setup.py", "pyproject.toml"),
    "pip3": ("setup.py", "pyproject.toml"),
    "uv": ("pyproject.toml",),
    "poetry": ("pyproject.toml",),
    "rake": ("Rakefile",),
    "gradle": ("build.gradle", "build.gradle.kts"),
    "mvn": ("pom.xml",),
}
_NPM_SCRIPT_VERBS = frozenset(
    {"run", "run-script", "test", "t", "start", "restart", "stop", "rum", "urn", "tst"}
)
_YARN_NON_SCRIPT = frozenset(
    {
        "install",
        "add",
        "remove",
        "upgrade",
        "up",
        "init",
        "dlx",
        "info",
        "why",
        "config",
        "cache",
        "login",
        "logout",
        "publish",
        "pack",
        "outdated",
        "list",
        "audit",
        "set",
        "plugin",
        "workspaces",
    }
)
SANDBOX_RUNNERS = frozenset(
    {"bwrap", "firejail", "nsjail", "sandbox-exec", "minijail0", "runsc", "systemd-run"}
)
_SYSTEM_BIN = re.compile(
    r"^(/usr/|/bin/|/sbin/|/opt/homebrew/|/usr/local/|/nix/|/snap/|/System/|/Library/Apple/)"
)
_DANGEROUS_MOUNT = re.compile(
    r"^(/|~|\$HOME|\$\{HOME\}|/etc|/root|/home|/Users|/var/run/docker\.sock|/run/docker\.sock)"
    r"(/?:|:|$)"
)
_CHMOD_EXEC = re.compile(r"^([ugoa]*\+[rwX]*x[rwX]*|[0-7]?[0-7]*[1357][0-7]{0,2})$")


@dataclass(frozen=True)
class ExecIntent:
    """One segment that executes code."""

    kind: str  # interpreter_file | inline_eval | direct_exec | pkg_runner | pkg_script
    prog: str
    target: str | None  # script path as written, the package for pkg_runner, None for one-liners
    detail: str
    sandboxed: bool = False
    sandbox: str | None = None  # runner that sandboxes it
    cwd: str | None = (
        None  # effective cwd after `cd` in the same command (relative to the call cwd)
    )
    manifests: tuple[str, ...] = ()  # pkg_script: files whose content decides what runs
    index: int = 0  # order inside the command (for write-then-exec within one command)

    @property
    def action_type(self) -> str:
        return "code.script" if self.kind == "pkg_script" else "code.exec"


@dataclass(frozen=True)
class FileWrite:
    path: str
    origin: str  # shell_write | download
    cwd: str | None = None
    index: int = 0


@dataclass
class ExecProfile:
    intents: list[ExecIntent] = field(default_factory=list)
    writes: list[FileWrite] = field(default_factory=list)
    chmod_x: list[str] = field(default_factory=list)

    @property
    def executes(self) -> bool:
        return bool(self.intents)


def _family(prog: str) -> str:
    if _PY_VERSIONED.fullmatch(prog) or prog in ("python", "pypy"):
        return "python"
    if prog in ("node", "nodejs", "tsx", "ts-node"):
        return "node"
    if prog in ("pwsh", "powershell", "powershell.exe", "pwsh.exe"):
        return "pwsh"
    if prog in SCRIPT_SHELLS or prog in ("source", "."):
        return "shell"
    if prog == "luajit":
        return "lua"
    return prog


def is_script_interpreter(prog: str) -> bool:
    return prog in SCRIPT_INTERPRETERS or bool(_PY_VERSIONED.fullmatch(prog))


def _first_positional(args: list[str], value_flags: frozenset[str]) -> tuple[int, str] | None:
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return (i + 1, args[i + 1]) if i + 1 < len(args) else None
        if a.startswith("-") and a != "-":
            i += 2 if (a in value_flags and "=" not in a) else 1
            continue
        return i, a
    return None


def _interpreter_intent(prog: str, args: list[str], idx: int) -> ExecIntent | None:
    fam = _family(prog)
    inline = _INLINE_FLAGS.get(fam, frozenset())
    vflags = _VALUE_FLAGS.get(fam, frozenset())
    i = 0
    while i < len(args):  # flags before the first positional (script args are not ours)
        a = args[i]
        key = a.lower() if fam == "pwsh" else a
        if not a.startswith("-") or a == "-" or a == "--":
            break
        if key in inline or (
            (fam == "python" and re.fullmatch(r"-[a-zA-Z]*c", a))
            or (fam in ("perl", "ruby") and re.fullmatch(r"-[a-zA-Z]*[eE]", a))
        ):
            return ExecIntent("inline_eval", prog, None, f"{prog} {a} runs inline code", index=idx)
        if fam == "pwsh" and key in ("-file", "-f") and i + 1 < len(args):
            return ExecIntent(
                "interpreter_file",
                prog,
                args[i + 1],
                f"{prog} -File runs script {args[i + 1]}",
                index=idx,
            )
        i += 2 if (a in vflags and "=" not in a) else 1
    if fam == "python" and any(a == "-m" or (a.startswith("-m") and len(a) > 2) for a in args):
        return None  # `python -m pytest` - module, not a file the agent can point at
    if fam == "shell" and any(re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a) for a in args):
        return None  # `bash -c "<body>"`: the body is analysed as a nested command
    if fam == "shell" and "-s" in args:
        return None  # reads the program from stdin (EXE-01 pipe_to_shell)
    rest = list(args)
    if fam == "deno":
        if rest[:1] == ["eval"]:
            return ExecIntent("inline_eval", prog, None, "deno eval runs inline code", index=idx)
        if rest[:1] in (["run"], ["test"], ["task"]):
            rest = rest[1:]
    if fam == "bun" and rest[:1] == ["run"]:
        rest = rest[1:]
    pos = _first_positional(rest, _VALUE_FLAGS.get(fam, frozenset()))
    if pos is None:
        return None
    target = pos[1]
    if target == "-" or target.startswith("__AEGISSUB"):
        return None  # stdin / process substitution: EXE-01 territory
    if fam == "bun" and "." not in posixpath.basename(target) and "/" not in target:
        return ExecIntent(
            "pkg_script",
            prog,
            target,
            f"bun runs package.json script {target!r}",
            manifests=_PKG_SCRIPT_MANIFESTS["bun"],
            index=idx,
        )
    if prog in (
        "java",
        "swift",
        "groovy",
        "elixir",
        "julia",
        "jshell",
    ) and "." not in posixpath.basename(target):
        return None  # `java -jar`/class names etc.: not a source file
    if "://" in target:
        return ExecIntent(
            "pkg_runner", prog, target, f"{prog} runs remote code from {target}", index=idx
        )
    verb = "sources" if prog in ("source", ".") else "runs"
    return ExecIntent("interpreter_file", prog, target, f"{prog} {verb} script {target}", index=idx)


def _pkg_intent(prog: str, args: list[str], idx: int) -> ExecIntent | None:
    pos = [a for a in args if not a.startswith("-")]
    if prog in ("npx", "bunx", "pnpx", "uvx"):
        pkg = pos[0] if pos else "?"
        return ExecIntent(
            "pkg_runner", prog, pkg, f"{prog} downloads and runs package {pkg}", index=idx
        )
    if prog == "uv" and pos[:2] == ["tool", "run"]:
        pkg = pos[2] if len(pos) > 2 else "?"
        return ExecIntent(
            "pkg_runner", prog, pkg, f"uv tool run downloads and runs {pkg}", index=idx
        )
    subs = PKG_RUNNERS.get(prog)
    if subs and pos[:1] and pos[0] in subs:
        pkg = pos[1] if len(pos) > 1 else "?"
        return ExecIntent(
            "pkg_runner", prog, pkg, f"{prog} {pos[0]} downloads and runs {pkg}", index=idx
        )
    if prog in ("npm", "pnpm") and pos[:1] and pos[0] in _NPM_SCRIPT_VERBS:
        script = (
            pos[1] if pos[0] in ("run", "run-script", "rum", "urn") and len(pos) > 1 else pos[0]
        )
        return ExecIntent(
            "pkg_script",
            prog,
            script,
            f"{prog} runs package.json script {script!r}",
            manifests=_PKG_SCRIPT_MANIFESTS[prog],
            index=idx,
        )
    if prog == "yarn" and pos and pos[0] not in _YARN_NON_SCRIPT:
        script = pos[1] if pos[0] == "run" and len(pos) > 1 else pos[0]
        return ExecIntent(
            "pkg_script",
            prog,
            script,
            f"yarn runs package.json script {script!r}",
            manifests=_PKG_SCRIPT_MANIFESTS["yarn"],
            index=idx,
        )
    if prog in ("make", "gmake", "just", "rake", "nox", "tox"):
        target = pos[0] if pos else "default"
        return ExecIntent(
            "pkg_script",
            prog,
            target,
            f"{prog} runs recipe {target!r}",
            manifests=_PKG_SCRIPT_MANIFESTS[prog],
            index=idx,
        )
    if prog == "cargo" and pos[:1] and pos[0] in ("run", "build", "test", "b", "r", "t"):
        return ExecIntent(
            "pkg_script",
            prog,
            pos[0],
            f"cargo {pos[0]} compiles and runs build.rs",
            manifests=_PKG_SCRIPT_MANIFESTS["cargo"],
            index=idx,
        )
    if (
        prog in ("pip", "pip3")
        and pos[:1] == ["install"]
        and any(a in (".", "./") or a.startswith(("./", "-e.")) for a in args[1:])
    ):
        return ExecIntent(
            "pkg_script",
            prog,
            ".",
            f"{prog} install . runs the local build backend",
            manifests=_PKG_SCRIPT_MANIFESTS[prog],
            index=idx,
        )
    if prog in ("gradle", "gradlew", "mvn", "mvnw"):
        key = "gradle" if prog.startswith("gradle") else "mvn"
        return ExecIntent(
            "pkg_script",
            prog,
            pos[0] if pos else None,
            f"{prog} runs build scripts",
            manifests=_PKG_SCRIPT_MANIFESTS[key],
            index=idx,
        )
    if prog == "go" and pos[:1] == ["run"] and len(pos) > 1:
        t = pos[1]
        if "@" in t:
            return ExecIntent("pkg_runner", prog, t, f"go run downloads and runs {t}", index=idx)
        return ExecIntent("interpreter_file", prog, t, f"go run compiles and runs {t}", index=idx)
    return None


def _unwrap(argv: list[str]) -> tuple[list[str], str | None]:
    """Strip `uv run` / `poetry run` / sandbox runners -> (inner argv, sandbox runner or None)."""
    sandbox: str | None = None
    for _ in range(3):
        if not argv:
            break
        prog = posixpath.basename(argv[0]).lower()
        args = argv[1:]
        if prog in SANDBOX_RUNNERS:
            sandbox = prog
            if "--" in args:
                argv = args[args.index("--") + 1 :]
                continue
            j = next(
                (
                    k
                    for k, a in enumerate(args)
                    if not a.startswith("-")
                    and is_script_interpreter(posixpath.basename(a).lower())
                ),
                None,
            )
            argv = args[j:] if j is not None else []
            continue
        if prog in RUN_WRAPPERS and args[:1] and args[0] in RUN_WRAPPERS[prog]:
            rest = args[1:]
            i = 0
            while i < len(rest) and rest[i].startswith("-"):
                i += 2 if (rest[i] in _RUN_WRAPPER_VALUE_FLAGS and "=" not in rest[i]) else 1
            if i < len(rest):
                argv = rest[i:]
                continue
        break
    return argv, sandbox


def _docker_sandboxed(args: list[str]) -> bool:
    """`docker run --network none` without --privileged / host-root mounts (ACT-04 decides the run)."""
    low = [a.lower() for a in args]
    if "--privileged" in low or any(a.startswith("--pid=host") or a == "--net=host" for a in low):
        return False
    net_none = any(a in ("--network=none", "--net=none") for a in low) or any(
        low[i] in ("--network", "--net") and i + 1 < len(low) and low[i + 1] == "none"
        for i in range(len(low))
    )
    if not net_none:
        return False
    for i, a in enumerate(args):
        if a in ("-v", "--volume", "--mount") and i + 1 < len(args):
            src = args[i + 1].split(",")[0].replace("source=", "").replace("src=", "")
            if _DANGEROUS_MOUNT.match(src):
                return False
        elif a.startswith(("--volume=", "-v=")):
            if _DANGEROUS_MOUNT.match(a.split("=", 1)[1]):
                return False
    return True


def classify_segment(seg: Segment, idx: int = 0, cwd: str | None = None) -> ExecIntent | None:
    """The code-execution intent of one shell segment (None = does not run code)."""
    argv, sandbox = _unwrap(list(seg.argv))
    if not argv:
        return None
    raw0 = argv[0]
    prog = posixpath.basename(raw0).lower() if "/" in raw0 else raw0.lower()
    args = argv[1:]
    if prog in ("docker", "podman"):
        return None  # ACT-04 code.exec container_run; sandbox label set by EXE-05 enrich
    intent: ExecIntent | None = None
    if prog == "eval":
        intent = ExecIntent(
            "inline_eval", "eval", None, "eval runs a constructed string as code", index=idx
        )
    elif is_script_interpreter(prog):
        intent = _interpreter_intent(prog, args, idx)
    else:
        intent = _pkg_intent(prog, args, idx)
        if (
            intent is None
            and "/" in raw0
            and not raw0.startswith("__AEGISSUB")
            and not _SYSTEM_BIN.match(raw0)
        ):
            intent = ExecIntent("direct_exec", prog, raw0, f"executes {raw0} directly", index=idx)
    if intent is None:
        return None
    return ExecIntent(
        intent.kind,
        intent.prog,
        intent.target,
        intent.detail,
        sandboxed=sandbox is not None,
        sandbox=sandbox,
        cwd=cwd,
        manifests=intent.manifests,
        index=idx,
    )


def _segment_writes(seg: Segment) -> list[tuple[str, str]]:
    """(path, origin) the segment creates or modifies with content (not rm/mkdir/touch)."""
    out: list[tuple[str, str]] = []
    dl = seg.prog in DOWNLOADERS
    for op, tgt in seg.redirects:
        if (
            op.startswith(">")
            and tgt
            and not tgt.isdigit()
            and tgt not in ("/dev/null", "/dev/stderr", "/dev/stdout")
        ):
            out.append((tgt, "download" if dl else "shell_write"))
    args = seg.args
    if seg.prog in ("curl", "wget", "aria2c", "fetch"):
        for i, a in enumerate(args):
            if a in ("-o", "--output", "--output-document") and i + 1 < len(args):
                out.append((args[i + 1], "download"))
            elif seg.prog == "wget" and a == "-O" and i + 1 < len(args) and args[i + 1] != "-":
                out.append((args[i + 1], "download"))
            elif a.startswith("--output=") or a.startswith("--output-document="):
                out.append((a.split("=", 1)[1], "download"))
            elif a.startswith("-o") and len(a) > 2 and seg.prog == "curl":
                out.append((a[2:], "download"))
        if seg.prog == "wget" and not any(
            a in ("-O", "-qO-", "-qO", "--output-document") or a.startswith("-O") for a in args
        ):
            for a in args:
                if "://" in a:
                    name = posixpath.basename(a.split("?", 1)[0].rstrip("/"))
                    if name:
                        out.append((name, "download"))
        if seg.prog == "curl" and any(
            a in ("-O", "--remote-name") or re.fullmatch(r"-[a-zA-Z]*O[a-zA-Z]*", a) for a in args
        ):
            for a in args:
                if "://" in a:
                    name = posixpath.basename(a.split("?", 1)[0].rstrip("/"))
                    if name:
                        out.append((name, "download"))
    elif seg.prog == "tee":
        out += [(a, "shell_write") for a in args if not a.startswith("-")]
    elif seg.prog in ("cp", "mv", "install", "ln", "ditto", "rsync"):
        pos = [a for a in args if not a.startswith("-")]
        if len(pos) >= 2:
            out.append((pos[-1], "shell_write"))
    elif seg.prog == "sed" and any(a.startswith("-i") for a in args):
        pos = [a for a in args if not a.startswith("-")]
        out += [(a, "shell_write") for a in pos[1:]]
    elif seg.prog == "dd":
        out += [(a[3:], "shell_write") for a in args if a.startswith("of=")]
    elif seg.prog == "git" and args[:1] in (["apply"], ["am"]):
        pass  # patches: target files unknown here (still tracked per Write/Edit)
    return out


def _walk(a: CommandAnalysis) -> list[CommandAnalysis]:
    out = [a]
    for x in a.inner:
        out.extend(_walk(x))
    for _, d in a.decoded:
        out.extend(_walk(d))
    return out


def _cd(cwd: str | None, target: str) -> str | None:
    if not target or target in ("-",) or target.startswith(("~", "$")):
        return None
    if target.startswith("/"):
        return posixpath.normpath(target)
    return posixpath.normpath(posixpath.join(cwd, target)) if cwd else posixpath.normpath(target)


def exec_profile(analysis: CommandAnalysis, cwd: str | None = None) -> ExecProfile:
    """Code-execution intents + file writes + chmod +x targets of a command (pure)."""
    prof = ExecProfile()
    idx = 0
    for a in _walk(analysis):
        cur = cwd
        for seg in a.segments:
            idx += 1
            if seg.prog == "cd" and a is analysis:
                tgt = next((x for x in seg.args if not x.startswith("-")), "")
                nxt = _cd(cur, tgt)
                cur = nxt if nxt is not None else cur
                continue
            for path, origin in _segment_writes(seg):
                prof.writes.append(FileWrite(path, origin, cur, idx))
            if seg.prog == "chmod":
                mode = next((x for x in seg.args if _CHMOD_EXEC.match(x)), None)
                if mode:
                    prof.chmod_x += [x for x in seg.args if x != mode and not x.startswith("-")]
            intent = classify_segment(seg, idx, cur)
            if intent is None and seg.prog in ("docker", "podman") and seg.args[:1] == ["run"]:
                if _docker_sandboxed(seg.args[1:]):
                    intent = ExecIntent(
                        "container",
                        seg.prog,
                        None,
                        f"{seg.prog} run --network none",
                        sandboxed=True,
                        sandbox=f"{seg.prog} --network none",
                        cwd=cur,
                        index=idx,
                    )
            if intent is not None:
                prof.intents.append(intent)
    return prof


def resolve_path(path: str, cwd: str | None = None) -> str:
    """Normalised path (absolute when ``cwd`` is known); ``~`` is kept literal."""
    p = (path or "").strip().strip("'\"")
    if p.startswith("file://"):
        p = p[7:]
    if not p:
        return ""
    if p.startswith(("/", "~")):
        return posixpath.normpath(p)
    if cwd and cwd.startswith("/"):
        return posixpath.normpath(posixpath.join(cwd, p))
    return posixpath.normpath(p)


def same_file(written: str, target: str) -> bool:
    """Exact match on normalised paths; when either side is relative, a path-suffix match."""
    if not written or not target:
        return False
    if written == target:
        return True
    w_abs, t_abs = written.startswith(("/", "~")), target.startswith(("/", "~"))
    if w_abs and t_abs:
        return False
    if not t_abs:
        return written.endswith("/" + target.lstrip("./")) or written == target.lstrip("./")
    return target.endswith("/" + written.lstrip("./"))


__all__ = [
    "ExecIntent",
    "ExecProfile",
    "FileWrite",
    "analysis_for",
    "analyze_cached",
    "classify_segment",
    "command_text",
    "exec_profile",
    "is_script_interpreter",
    "matches_any",
    "resolve_path",
    "same_file",
]
