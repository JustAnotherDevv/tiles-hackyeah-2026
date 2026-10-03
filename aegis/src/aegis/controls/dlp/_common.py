"""Helpers shared by the DLP controls (module name starts with `_` -> skipped by discovery)."""

from __future__ import annotations

import fnmatch
import logging
import re
from typing import Any

from aegis.core.types import Interaction, RequestContext
from aegis.redaction import entities as E
from aegis.redaction.engine import RedactionEngineImpl, create
from aegis.redaction.policy import SpanIn
from aegis.redaction.scan import Hit

log = logging.getLogger(__name__)

_override_rt: Any = None
_local_engine: RedactionEngineImpl | None = None


def set_runtime(rt: Any) -> None:
    """Tests / embedding: use this runtime instead of ``aegis.core.runtime.get_runtime()``."""
    global _override_rt, _local_engine
    _override_rt = rt
    _local_engine = None


def get_rt() -> Any:
    if _override_rt is not None:
        return _override_rt
    try:
        from aegis.core.runtime import get_runtime

        return get_runtime()
    except Exception:  # TODO(integration): runtime not started (unit tests, self-test tools)
        return None


def get_engine() -> RedactionEngineImpl:
    """``rt.redactor`` when it is our engine (shared session vault), else a local engine."""
    global _local_engine
    rt = get_rt()
    red = getattr(rt, "redactor", None)
    if isinstance(red, RedactionEngineImpl):
        return red
    if _local_engine is None:
        _local_engine = create(rt)
        log.warning("dlp controls using a local redaction engine (rt.redactor unavailable)")
    return _local_engine


def snapshot(ctx: RequestContext) -> Any:
    snap = getattr(ctx, "policy", None)
    if snap is not None:
        return snap
    rt = get_rt()
    try:
        return rt.policy.snapshot() if rt is not None else None
    except Exception:
        return None


def to_span_in(i: int, h: Hit) -> SpanIn:
    return SpanIn(
        segment_index=i,
        start=h.start,
        end=h.end,
        entity=h.entity,
        data_class=E.data_class(h.entity),
        detector_id=h.detector_id,
        score=float(h.score),
        category=E.category(h.entity),
        canonical=h.canonical,
        meta={
            k: v for k, v in (h.meta or {}).items() if k in ("doc_example", "fragment", "encoding")
        },
    )


def overlaps(s: SpanIn, others: list[SpanIn]) -> bool:
    return any(s.start < o.end and o.start < s.end for o in others)


_IDX = re.compile(r"\[[^\]]*\]")


def arg_name(path: str) -> str | None:
    """'tool_args.to' / 'tool_args.recipients[0]' / 'params.arguments.to' -> 'to'/'recipients'."""
    for prefix in ("tool_args.", "params.arguments.", "tool_input.", "arguments."):
        if path.startswith(prefix):
            rest = path[len(prefix) :]
            first = rest.split(".", 1)[0]
            return _IDX.sub("", first) or None
    return None


def routing_args(interaction: Interaction, mapping: dict[str, list[str]]) -> set[str]:
    tool = interaction.tool_name or ""
    if not tool:
        return set()
    out: set[str] = set()
    for glob, names in (mapping or {}).items():
        if fnmatch.fnmatchcase(tool, glob):
            out.update(str(n) for n in names or [])
    return out


def tool_matches(tool: str | None, globs: list[str]) -> bool:
    return bool(tool) and any(fnmatch.fnmatchcase(tool or "", g) for g in globs or [])


_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)


def blank_code(text: str) -> str:
    """Replace fenced code blocks with spaces (offsets preserved) - DLP-07 skip_code."""
    if "```" not in text:
        return text
    return _FENCE.sub(lambda m: " " * len(m.group(0)), text)


def all_context_spans(spans: list[SpanIn]) -> list[tuple[int, int, str, str]]:
    return [(s.start, s.end, s.entity, s.canonical) for s in spans]
