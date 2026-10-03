"""Helpers for metadata-egress unit tests (no runtime, no network, no models).

Import as `from tests.unit.metadata_egress.helpers import ...` (importlib import mode)."""

from __future__ import annotations

import os
from typing import Any

from aegis.core.policy_schema import ControlConfig, PolicyDoc, PolicySnapshot
from aegis.core.types import (
    Destination,
    Finding,
    Identity,
    Interaction,
    RequestContext,
    SessionState,
    TextSegment,
)

os.environ.setdefault("AEGIS_TEST_MODE", "1")
os.environ.setdefault("AEGIS_SEMANTIC", "off")

SNIPPET_DEFAULTS: dict[str, dict[str, Any]] = {
    "DLP-03": {"action": "redact", "severity": "medium", "fail_mode": "open"},
    "DLP-04": {"action": "block", "threshold": 0.8, "severity": "high"},
    "DLP-06": {"action": "redact", "severity": "high"},
}


def make_snapshot(**doc_overrides: Any) -> PolicySnapshot:
    base: dict[str, Any] = {
        "destinations": {
            "internal_domains": ["*.acme-capital.example", "*.corp.local"],
            "allowed_link_domains": ["docs.acme-capital.example"],
        }
    }
    for k, v in doc_overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    doc = PolicyDoc.model_validate(base)
    return PolicySnapshot(version=1, sha256="test", doc=doc,
                          controls={c.id: c for c in doc.controls})


def make_ctx(snap: PolicySnapshot | None = None, *, agent_id: str | None = "tester@platform",
             session_id: str = "ses_test", **kw: Any) -> RequestContext:
    ctx = RequestContext(request_id="req_test", session_id=session_id,
                         identity=Identity(agent_id=agent_id), **kw)
    ctx.policy = snap if snap is not None else make_snapshot()
    return ctx


def make_cfg(control_id: str, **kw: Any) -> ControlConfig:
    data = {"id": control_id, **SNIPPET_DEFAULTS.get(control_id, {}), **kw}
    return ControlConfig.model_validate(data)


def make_interaction(*texts: str, surface: str = "model.request", dest: str = "remote",
                     kind: str | None = None, direction: str | None = None,
                     **kw: Any) -> Interaction:
    kinds = {"model.request": "model_call", "model.response": "model_call",
             "tool.input": "tool_call", "tool.output": "tool_call", "mcp.call": "mcp",
             "mcp.result": "mcp", "egress.request": "egress", "egress.response": "egress"}
    segs = kw.pop("segments", None) or [
        TextSegment(path=f"messages[{i}].content", text=t) for i, t in enumerate(texts)]
    if direction is None:
        direction = "in" if surface.endswith(("response", "output", "result")) else "out"
    return Interaction(kind=kind or kinds.get(surface, "model_call"), surface=surface,
                       direction=direction, destination=Destination(name="test", dest_class=dest),
                       segments=segs, **kw)


def apply_findings(text: str, findings: list[Finding], *, segment_index: int | None = None,
                   vault: dict[tuple[str, str], str] | None = None) -> str:
    """Deterministic test applier: explicit replacement, else `[ENTITY_n]` (stable per value)."""
    vault = {} if vault is None else vault
    spans = [f for f in findings if f.start is not None and f.end is not None
             and (segment_index is None or f.segment_index == segment_index)]
    spans.sort(key=lambda f: (-(f.end - f.start), f.start))  # type: ignore[operator]
    kept: list[Finding] = []
    for f in spans:
        if any(f.start < k.end and k.start < f.end for k in kept):  # type: ignore[operator]
            continue
        kept.append(f)
    out = text
    for f in sorted(kept, key=lambda f: f.start, reverse=True):  # type: ignore[arg-type,return-value]
        val = text[f.start:f.end]
        if f.replacement is not None:
            rep = f.replacement
        else:
            key = (f.entity or "REDACTED", val)
            if key not in vault:
                n = 1 + sum(1 for k in vault if k[0] == key[0])
                vault[key] = f"[{key[0]}_{n}]"
            rep = vault[key]
        out = out[:f.start] + rep + out[f.end:]  # type: ignore[index]
    return out


def apply_all(interaction: Interaction, findings: list[Finding]) -> list[str]:
    vault: dict[tuple[str, str], str] = {}
    return [apply_findings(s.text, findings, segment_index=i, vault=vault) if s.redactable
            else s.text for i, s in enumerate(interaction.segments)]


class FakeSessions:
    def __init__(self) -> None:
        self._s: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        if session_id not in self._s:
            self._s[session_id] = SessionState(session_id=session_id)
        return self._s[session_id]

    def all(self) -> list[SessionState]:
        return list(self._s.values())


class FakeRedactor:
    def detect(self, text: str, *, entities: set[str] | None = None, use_ner: bool = False):
        return []

    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        return "".join("#" if c.isdigit() else c for c in text)[:max_len]


class FakeRt:
    def __init__(self, snap: PolicySnapshot | None = None) -> None:
        self.sessions = FakeSessions()
        self.redactor = FakeRedactor()
        self._snap = snap or make_snapshot()

        class _Policy:
            def __init__(s, snap: PolicySnapshot) -> None:
                s._snap = snap

            def snapshot(s) -> PolicySnapshot:
                return s._snap

        self.policy = _Policy(self._snap)
