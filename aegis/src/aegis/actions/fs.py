"""Filesystem scope policy for EXE-02 (pure; ``realpath`` only when the file exists locally).

Globs support ``**`` (any depth, including none), ``*`` (one path segment) and ``~``. A path is
matched in several forms so evasions don't slip through: as given, with ``~``/``$HOME``
expanded, ``..`` resolved lexically, joined with the hook ``cwd`` (``meta.cwd``), symlinks
resolved (``resolve_symlinks``), and a generic ``~/…`` form of any ``/Users/<u>/…`` or
``/home/<u>/…`` path (remote agents have a different home). Matching is case-insensitive on
macOS (APFS), so ``.ENV`` is ``.env``.
"""

from __future__ import annotations

import os
import posixpath
import re
import sys
from dataclasses import dataclass
from functools import lru_cache

CASE_INSENSITIVE = sys.platform == "darwin"
_HOME_RX = re.compile(r"^/(?:Users|home)/[^/]+(?=/|$)")


def _home() -> str:
    return os.path.expanduser("~")


@lru_cache(maxsize=512)
def compile_glob(pattern: str, home: str, ci: bool) -> re.Pattern[str]:
    p = pattern.strip()
    if p.startswith("~") and home:
        p = home + p[1:]
    out: list[str] = []
    i = 0
    if p.startswith("**/"):
        out.append(r"(?:.*/)?")
        i = 3
    while i < len(p):
        if p.startswith("/**", i) and i + 3 == len(p):
            out.append(r"(?:/.*)?")
            i += 3
        elif p.startswith("/**/", i):
            out.append(r"(?:/.*)?/")
            i += 4
        elif p.startswith("**", i):
            out.append(r".*")
            i += 2
        elif p[i] == "*":
            out.append(r"[^/]*")
            i += 1
        elif p[i] == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(p[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE if ci else 0)


def path_forms(path: str, cwd: str | None = None, *, resolve_symlinks: bool = True) -> list[str]:
    """Every form of ``path`` the policy is matched against (see module docstring)."""
    if not path:
        return []
    raw = path.strip().strip("'\"")
    home = _home()
    forms: list[str] = []

    def add(p: str | None) -> None:
        if p and p not in forms:
            forms.append(p)

    add(posixpath.normpath(raw) if raw not in (".", "") else raw)
    exp = raw
    for token in ("${HOME}", "$HOME"):
        if exp.startswith(token):
            exp = "~" + exp[len(token) :]
    if exp.startswith("~"):
        add(posixpath.normpath(exp))
        exp = home + exp[1:] if exp == "~" or exp.startswith("~/") else exp
    exp = posixpath.normpath(exp)
    add(exp)
    if not exp.startswith("/") and not exp.startswith("~") and cwd:
        add(posixpath.normpath(posixpath.join(cwd, exp)))
    if resolve_symlinks:
        for p in list(forms):
            if p.startswith("/"):
                try:
                    if os.path.lexists(p):
                        add(os.path.realpath(p))
                except OSError:
                    pass
    for p in list(forms):
        if p.startswith("/"):
            add(_HOME_RX.sub("~", p) if _HOME_RX.match(p) else None)
            if home and (p == home or p.startswith(home + "/")):
                add("~" + p[len(home) :])
    return forms


@dataclass
class PathCheck:
    ok: bool
    rule: str = ""  # fs_deny | fs_write_deny | fs_allow
    pattern: str = ""
    path: str = ""  # best display form (home shown as ~)
    exception: str | None = None


def _match_any(patterns: list[str], forms: list[str]) -> str | None:
    home = _home()
    for pat in patterns:
        rx_home = compile_glob(pat, home, CASE_INSENSITIVE)
        rx_raw = compile_glob(pat, "", CASE_INSENSITIVE) if pat.startswith("~") else None
        for f in forms:
            if rx_home.match(f) or (rx_raw is not None and rx_raw.match(f)):
                return pat
    return None


def display_form(forms: list[str]) -> str:
    for f in forms:
        if f.startswith("~"):
            return f
    return forms[-1] if forms else ""


def check_path(
    path: str,
    op: str,
    *,
    deny: list[str],
    write_deny: list[str],
    exceptions: list[str],
    allow: list[str] | None = None,
    cwd: str | None = None,
    resolve_symlinks: bool = True,
) -> PathCheck:
    """Exceptions first, then ``fs_deny``, then ``fs_write_deny`` (writes), then ``fs_allow``."""
    forms = path_forms(path, cwd, resolve_symlinks=resolve_symlinks)
    shown = display_form(forms) or path
    if not forms:
        return PathCheck(True, path=shown)
    exc = _match_any(exceptions, forms)
    if exc:
        return PathCheck(True, path=shown, exception=exc)
    hit = _match_any(deny, forms)
    if hit:
        return PathCheck(False, "fs_deny", hit, shown)
    if op == "write":
        hit = _match_any(write_deny, forms)
        if hit:
            return PathCheck(False, "fs_write_deny", hit, shown)
    if allow:
        if not _match_any(allow, forms):
            return PathCheck(False, "fs_allow", "", shown)
    return PathCheck(True, path=shown)


__all__ = [
    "CASE_INSENSITIVE",
    "PathCheck",
    "check_path",
    "compile_glob",
    "display_form",
    "path_forms",
]
