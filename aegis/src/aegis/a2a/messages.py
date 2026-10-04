"""JSON-RPC A2A message helpers (A2A protocol 0.2/0.3 shapes, tolerant).

Request: ``{"jsonrpc": "2.0", "id": 1, "method": "message/send",
"params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "..."}]}}}``.
Reply: ``result`` is a Message (``parts``) or a Task (``status.message.parts``,
``artifacts[].parts``, ``history[].parts``). Text parts (``kind``/``type`` = ``text``) become
segments; string leaves of ``data`` parts become ``other`` segments. Paths are dotted with
``[i]`` and are written back verbatim by ``set_path``.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from aegis.core.types import TextSegment

METHODS = {"message/send", "message/stream", "tasks/send", "tasks/get", "tasks/cancel"}


def _parts_segments(parts: Any, base: str, role: str, trusted: bool) -> list[TextSegment]:
    out: list[TextSegment] = []
    if not isinstance(parts, list):
        return out
    for n, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        kind = part.get("kind") or part.get("type") or ("text" if "text" in part else None)
        if kind == "text" and isinstance(part.get("text"), str) and part["text"]:
            out.append(TextSegment(path=f"{base}[{n}].text", text=part["text"], role=role,
                                   trusted=trusted))  # type: ignore[arg-type]
        elif kind == "data" and isinstance(part.get("data"), (dict, list)):
            _walk(part["data"], f"{base}[{n}].data", out, trusted)
    return out


def _walk(value: Any, path: str, out: list[TextSegment], trusted: bool) -> None:
    if isinstance(value, str):
        if value:
            out.append(TextSegment(path=path, text=value, role="other", trusted=trusted))
    elif isinstance(value, dict):
        for k, v in value.items():
            key = str(k)
            if re.fullmatch(r"[A-Za-z0-9_\-]+", key):
                _walk(v, f"{path}.{key}", out, trusted)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _walk(v, f"{path}[{i}]", out, trusted)


def request_segments(body: Any, *, trusted: bool = True) -> list[TextSegment]:
    if not isinstance(body, dict):
        return []
    params = body.get("params")
    if not isinstance(params, dict):
        return []
    msg = params.get("message")
    if isinstance(msg, dict):
        return _parts_segments(msg.get("parts"), "params.message.parts", "user", trusted)
    return []


def result_segments(body: Any) -> list[TextSegment]:
    """Peer replies are untrusted everywhere (Addendum A-13 spirit, ASI07)."""
    if not isinstance(body, dict):
        return []
    res = body.get("result")
    out: list[TextSegment] = []
    if isinstance(res, dict):
        out += _parts_segments(res.get("parts"), "result.parts", "tool_result", False)
        status = res.get("status")
        if isinstance(status, dict) and isinstance(status.get("message"), dict):
            out += _parts_segments(status["message"].get("parts"), "result.status.message.parts",
                                   "tool_result", False)
        for j, art in enumerate(res.get("artifacts") or []):
            if isinstance(art, dict):
                out += _parts_segments(art.get("parts"), f"result.artifacts[{j}].parts",
                                       "tool_result", False)
        for k, h in enumerate(res.get("history") or []):
            if isinstance(h, dict) and h.get("role") != "user":
                out += _parts_segments(h.get("parts"), f"result.history[{k}].parts",
                                       "tool_result", False)
    err = body.get("error")
    if isinstance(err, dict) and isinstance(err.get("message"), str) and err["message"]:
        out.append(TextSegment(path="error.message", text=err["message"], role="tool_result",
                               trusted=False))
    return out


_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _tokens(path: str) -> list[str | int]:
    return [int(i) if i else name for name, i in _TOKEN.findall(path)]


def set_path(doc: Any, path: str, value: Any) -> bool:
    toks = _tokens(path)
    cur = doc
    for t in toks[:-1]:
        try:
            cur = cur[t]
        except (KeyError, IndexError, TypeError):
            return False
    last = toks[-1] if toks else None
    try:
        if isinstance(last, int) and isinstance(cur, list) and last < len(cur):
            cur[last] = value
            return True
        if isinstance(last, str) and isinstance(cur, dict):
            cur[last] = value
            return True
    except Exception:
        return False
    return False


def apply_segments(body: Any, segments: list[TextSegment]) -> Any:
    """Copy of ``body`` with each segment's (possibly redacted) text written to its path."""
    out = copy.deepcopy(body)
    for s in segments:
        set_path(out, s.path, s.text)
    return out


def summary_text(segments: list[TextSegment], limit: int = 200) -> str:
    txt = " ".join(s.text for s in segments)
    return txt if len(txt) <= limit else txt[: limit - 1] + "…"
