"""Command extraction + cached shell analysis shared by EXE-01, EXE-02 and ACT-04.

``analyze_command`` is pure, so results are memoised per (command, limits); the three
controls that look at the same Bash call therefore parse it once.
"""

from __future__ import annotations

import shlex
from functools import lru_cache
from typing import Any

from aegis.actions.argpath import first_arg
from aegis.actions.classify import glob_match, normalize_tool_name
from aegis.actions.shell import CommandAnalysis, analyze_command
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


__all__ = ["analysis_for", "analyze_cached", "command_text", "matches_any"]
