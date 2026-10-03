"""Payload trimming and masking for SSE / list views (never broadcast raw values)."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from aegis.core.types import ApprovalRequest

MAX_BOUND_BYTES = 2048

_DIGITS = re.compile(r"\d[\d \-]{7,}\d")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def fallback_mask(text: str, max_len: int = 160) -> str:
    """Used when rt.redactor is unavailable: mask long digit runs (PAN, PESEL, IBAN) and emails."""

    def _digits(m: re.Match[str]) -> str:
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 9:
            return raw
        return digits[:2] + "*" * (len(digits) - 4) + digits[-2:]

    out = _EMAIL.sub("[EMAIL]", _DIGITS.sub(_digits, text))
    return out if len(out) <= max_len else out[: max_len - 1] + "…"


class Masker:
    """`rt.redactor.mask_for_log` with a local fallback; masks every string leaf."""

    def __init__(self, redactor: Any | None) -> None:
        self.redactor = redactor

    def text(self, value: str, max_len: int = 160) -> str:
        if self.redactor is not None:
            try:
                return str(self.redactor.mask_for_log(value, max_len=max_len))
            except Exception:
                pass
        return fallback_mask(value, max_len)

    def tree(self, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "…"
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, bool) or value is None or isinstance(value, float):
            return value
        if isinstance(value, int):
            return self.text(str(value)) if len(str(abs(value))) >= 9 else value
        if isinstance(value, Mapping):
            return {str(k): self.tree(v, depth + 1) for k, v in list(value.items())[:50]}
        if isinstance(value, (list, tuple)):
            return [self.tree(v, depth + 1) for v in list(value)[:50]]
        return self.text(str(value))


def bound_params(masker: Masker, tool_name: str | None, args: Any, extra: dict[str, Any]) -> dict[str, Any]:
    """`payload.bound` (A-24): what exactly the approval authorizes — `{tool_name, args_masked,
    …}` rendered from the bound parameters, masked and capped at 2 KB."""
    bound: dict[str, Any] = {
        "tool_name": tool_name,
        **{k: v for k, v in extra.items() if v is not None},
    }
    if args is not None:
        bound["args_masked"] = masker.tree(args)
    text = json.dumps(bound, ensure_ascii=False, default=str)
    if len(text.encode()) > MAX_BOUND_BYTES:
        preview = masker.text(json.dumps(bound.get("args_masked"), default=str), 400)
        bound["args_masked"] = {"_truncated": True, "_preview": preview}
    return bound


def trimmed(req: ApprovalRequest) -> dict[str, Any]:
    """JSON for SSE / list rows: `payload.proposal.yaml` -> {yaml_sha256, yaml_bytes}."""
    data = req.model_dump(mode="json")
    payload = data.get("payload") or {}
    proposal = payload.get("proposal")
    if isinstance(proposal, dict) and isinstance(proposal.get("yaml"), str):
        proposal = copy.copy(proposal)
        y = proposal.pop("yaml")
        proposal["yaml_sha256"] = hashlib.sha256(y.encode()).hexdigest()
        proposal["yaml_bytes"] = len(y.encode())
        payload = {**payload, "proposal": proposal}
    if isinstance(payload.get("yaml"), str):
        y = payload["yaml"]
        payload = {k: v for k, v in payload.items() if k != "yaml"}
        payload["yaml_sha256"] = hashlib.sha256(y.encode()).hexdigest()
        payload["yaml_bytes"] = len(y.encode())
    data["payload"] = payload
    return data


__all__ = ["MAX_BOUND_BYTES", "Masker", "bound_params", "fallback_mask", "trimmed"]
