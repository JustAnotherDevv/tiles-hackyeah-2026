"""Classify an interaction as a persistent-memory write or read (MEM-01).

``classify(interaction, params) -> MemoryOp | None``

Writes (surfaces ``tool.input`` / ``mcp.call``):
* file tools (``Write``/``Edit``/``MultiEdit``/``NotebookEdit``/``*.write_file`` ...) whose path
  matches ``memory_paths`` -> ``kind="file"``;
* shell tools (``Bash`` ...) whose command redirects / ``tee``s / copies into a memory path;
* MCP memory-server tools (``*.create_entities``, ``*.add_observations`` ...) -> ``kind="mcp_memory"``;
* RAG ingestion tools (``*.upsert``, ``*.ingest``, ``*.add_documents`` ...) -> ``kind="rag"``.

Reads (surfaces ``tool.output`` / ``mcp.result``): a file read of a memory path, or a memory /
retrieval tool result -> ``op="read"``.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from aegis.actions.classify import glob_match, normalize_tool_name
from aegis.actions.fs import CASE_INSENSITIVE, _home, compile_glob, path_forms
from aegis.core.types import Interaction

WRITE_SURFACES = frozenset({"tool.input", "mcp.call"})
READ_SURFACES = frozenset({"tool.output", "mcp.result"})

PATH_KEYS = ("file_path", "path", "notebook_path", "filename", "file", "target", "dest",
             "destination")
#: tool-arg keys that carry the written content, per built-in tool (first match wins)
CONTENT_KEYS = ("content", "new_string", "new_source", "text", "body", "data", "contents")

# `> file`, `>> file`, `tee [-a] file`, `cp|mv src file`, `sed -i ... file`
_REDIR = re.compile(r"(?:^|[^>&0-9])>{1,2}\s*(?P<p>\"[^\"]+\"|'[^']+'|[^\s;&|]+)")
_TEE = re.compile(r"\btee\s+(?:-\w+\s+)*(?P<p>\"[^\"]+\"|'[^']+'|[^\s;&|]+)")


@dataclass
class MemoryOp:
    op: str  # write | read
    kind: str  # file | mcp_memory | rag
    target: str  # path or tool name
    via: str  # tool name
    content: str = ""
    pattern: str = ""  # the memory_paths glob / tool glob that matched
    paths: list[str] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        return {"op": self.op, "kind": self.kind, "target": self.target, "via": self.via,
                "matched": self.pattern, "content_chars": len(self.content)}


def _tool_match(name: str | None, patterns: list[str] | tuple[str, ...]) -> str | None:
    n = normalize_tool_name(name)
    if not n:
        return None
    for p in patterns:
        if glob_match(p, n) or glob_match(p.lower(), n.lower()):
            return p
    return None


def match_memory_path(path: str, patterns: list[str], cwd: str | None = None) -> str | None:
    """The first ``memory_paths`` glob matching any form of ``path`` (see ``aegis.actions.fs``)."""
    if not path or not isinstance(path, str):
        return None
    forms = path_forms(path, cwd, resolve_symlinks=False)
    home = _home()
    for pat in patterns:
        rx = compile_glob(pat, home, CASE_INSENSITIVE)
        rx_raw = compile_glob(pat, "", CASE_INSENSITIVE) if pat.startswith("~") else None
        for f in forms:
            if rx.match(f) or (rx_raw is not None and rx_raw.match(f)):
                return pat
    return None


def string_leaves(obj: Any, skip: frozenset[str] = frozenset()) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in skip:
                continue
            yield from string_leaves(v, skip)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from string_leaves(v, skip)


def _args(i: Interaction) -> dict[str, Any]:
    a = i.tool_args
    if isinstance(a, dict):
        args = a.get("arguments") if i.surface == "mcp.call" and isinstance(a.get("arguments"), dict) else a
        return args if isinstance(args, dict) else {}
    return {}


def _paths(args: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for k in PATH_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v:
            out.append(v)
        elif isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str) and x)
    return out


def written_content(tool: str, args: dict[str, Any]) -> str:
    """Text a file-write tool puts on disk (Edit: ``new_string``; MultiEdit: every edit)."""
    edits = args.get("edits")
    if isinstance(edits, list):
        parts = [e.get("new_string") or e.get("newText") or "" for e in edits if isinstance(e, dict)]
        if any(parts):
            return "\n".join(p for p in parts if isinstance(p, str))
    for k in CONTENT_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v:
            return v
    return "\n".join(string_leaves(args, frozenset(PATH_KEYS)))


def shell_targets(cmd: str) -> list[str]:
    """Paths a shell command writes to via ``>``/``>>``/``tee``/``cp``/``mv``/``sed -i``."""
    out = [m.group("p").strip("'\"") for m in _REDIR.finditer(cmd)]
    out += [m.group("p").strip("'\"") for m in _TEE.finditer(cmd)]
    try:
        toks = shlex.split(cmd, posix=True)
    except ValueError:
        toks = cmd.split()
    seg: list[str] = []
    for t in [*toks, ";"]:
        if t in (";", "&&", "||", "|"):
            if seg and seg[0] in ("cp", "mv", "install", "ln") and len(seg) >= 3:
                out.append(seg[-1])
            if seg and seg[0] == "sed" and any(x.startswith("-i") for x in seg[1:]):
                out.append(seg[-1])
            seg = []
        else:
            seg.append(t)
    return [p for p in out if p and not p.startswith("&")]


def classify(i: Interaction, p: Any) -> MemoryOp | None:
    """``p`` is a :class:`aegis.controls.memory.mem01_memory_guard.Mem01Params`."""
    tool = normalize_tool_name(i.tool_name) or ""
    args = _args(i)
    cwd = i.meta.get("cwd") if isinstance(i.meta.get("cwd"), str) else None
    if i.surface in WRITE_SURFACES:
        if _tool_match(tool, p.write_tools):
            for path in _paths(args):
                pat = match_memory_path(path, p.memory_paths, cwd)
                if pat:
                    return MemoryOp("write", "file", path, tool, written_content(tool, args), pat,
                                    [path])
        if _tool_match(tool, p.shell_tools):
            cmd = next((args[k] for k in ("command", "cmd", "script") if isinstance(args.get(k), str)),
                       "")
            for path in shell_targets(cmd) if cmd else []:
                pat = match_memory_path(path, p.memory_paths, cwd)
                if pat:
                    return MemoryOp("write", "file", path, tool, cmd, pat, [path])
        pat = _tool_match(tool, p.memory_tools)
        if pat:
            return MemoryOp("write", "mcp_memory", tool, tool,
                            "\n".join(string_leaves(args)), pat)
        pat = _tool_match(tool, p.rag_tools)
        if pat:
            return MemoryOp("write", "rag", tool, tool, "\n".join(string_leaves(args)), pat)
        return None
    if i.surface in READ_SURFACES:
        if _tool_match(tool, p.read_tools):
            for path in _paths(args):
                pat = match_memory_path(path, p.memory_paths, cwd)
                if pat:
                    return MemoryOp("read", "file", path, tool, i.text(), pat, [path])
        pat = _tool_match(tool, p.memory_read_tools)
        if pat:
            kind = "rag" if _tool_match(tool, p.rag_read_tools) else "mcp_memory"
            return MemoryOp("read", kind, tool, tool, i.text(), pat)
    return None


# ---------------------------------------------------------------- memory blocks in model context
_CTX_HDR = re.compile(
    r"Contents of (?P<path>[^\n]{1,400}?(?:CLAUDE(?:\.local)?|AGENTS|GEMINI|MEMORY)\.md)[^\n]*\n"
)
_CTX_END = re.compile(r"\nContents of [^\n]{1,400}?\.md|</system-reminder>")


def context_memory_blocks(text: str) -> list[tuple[str, str]]:
    """``(path, content)`` of agent memory files a harness inlined into the model context
    (Claude Code: ``Contents of /repo/CLAUDE.md (project instructions...):``)."""
    out: list[tuple[str, str]] = []
    for m in _CTX_HDR.finditer(text):
        rest = text[m.end():]
        e = _CTX_END.search(rest)
        out.append((m.group("path").strip(), rest[: e.start()] if e else rest))
    return out


__all__ = ["MemoryOp", "classify", "context_memory_blocks", "match_memory_path", "shell_targets",
           "string_leaves", "written_content"]
