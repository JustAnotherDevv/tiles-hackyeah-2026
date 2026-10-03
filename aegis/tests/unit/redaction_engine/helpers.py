"""Helpers for redaction-engine unit tests (no models, no servers, no network)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

os.environ.setdefault("AEGIS_TEST_MODE", "1")
os.environ.setdefault("AEGIS_SEMANTIC", "off")

from aegis.core.policy_schema import ControlConfig, PolicyDoc, PolicySnapshot
from aegis.core.types import Destination, Interaction, RequestContext, TextSegment
from aegis.redaction.engine import RedactionEngineImpl, create

ROOT = Path(__file__).resolve().parents[3]
SNIPPET = ROOT / "config" / "snippets" / "redaction-engine.yaml"

# Demo / contract vectors (checksum-valid test values, not real people).
PESEL = "44051401359"
IBAN = "PL61 1090 1014 0000 0712 1981 2874"
PAN = "4111 1111 1111 1111"
EMAIL = "anna.nowak@poczta.example"
F1 = (
    f"Please draft a reply confirming the refund to IBAN {IBAN}. His PESEL is {PESEL} and the "
    f"card on file is {PAN} exp 12/27, CVV 123. Contact: {EMAIL}"
)
# Secret-shaped values are assembled at runtime (keeps literal secret shapes out of the repo).
AWS_KEY = "AKIA" + "0123456789ABCDEF"
AWS_DOC_KEY = "AKIA" + "IOSFODNN7" + "EXAMPLE"


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def publish(self, topic: str, payload: Any) -> None:
        self.events.append((topic, payload))


class FakePolicy:
    def __init__(self, snap: PolicySnapshot) -> None:
        self.snap = snap
        self.cbs: list[Any] = []

    def snapshot(self) -> PolicySnapshot:
        return self.snap

    def on_change(self, cb: Any) -> None:
        self.cbs.append(cb)


class FakeSettings:
    semantic = "off"
    test_mode = True
    models_dir = "models"
    vault_secret = None


class FakeRT:
    def __init__(self, snap: PolicySnapshot) -> None:
        self.settings = FakeSettings()
        self.bus = FakeBus()
        self.policy = FakePolicy(snap)
        self.semantic = None
        self.redactor: RedactionEngineImpl = create(self)


def snippet_controls() -> dict[str, ControlConfig]:
    doc = yaml.safe_load(SNIPPET.read_text(encoding="utf-8"))
    return {c["id"]: ControlConfig.model_validate(c) for c in doc["controls"]}


def make_snapshot(
    matrix: dict[str, dict[str, str]] | None = None,
    controls: dict[str, ControlConfig] | None = None,
    version: int = 1,
) -> PolicySnapshot:
    doc = PolicyDoc()
    if matrix:
        for cls, row in matrix.items():
            doc.destinations.matrix.setdefault(cls, {}).update(row)  # type: ignore[index]
    ctrls = controls if controls is not None else snippet_controls()
    doc.controls = list(ctrls.values())
    return PolicySnapshot(version=version, sha256="test", doc=doc, controls=dict(ctrls))


def make_ctx(snap: PolicySnapshot, session_id: str = "sess-1") -> RequestContext:
    return RequestContext(request_id="req-1", session_id=session_id, policy=snap)


def make_interaction(
    surface: str = "model.request",
    dest: str = "remote",
    text: str | None = None,
    *,
    role: str | None = None,
    tool_name: str | None = None,
    tool_args: dict[str, Any] | None = None,
    segments: list[TextSegment] | None = None,
) -> Interaction:
    kind = "model_call"
    if surface.startswith("mcp."):
        kind = "mcp"
    elif surface.startswith("tool."):
        kind = "tool_call"
    elif surface.startswith("egress."):
        kind = "egress"
    segs: list[TextSegment] = list(segments or [])
    if text is not None:
        default_role = {
            "model.response": "assistant",
            "mcp.result": "tool_result",
            "tool.output": "tool_result",
            "egress.response": "tool_result",
        }.get(surface, "user")
        segs.append(TextSegment(path="messages[0].content", text=text, role=role or default_role))
    for k, v in (tool_args or {}).items():
        if isinstance(v, str):
            segs.append(TextSegment(path=f"tool_args.{k}", text=v, role="tool_args"))
    return Interaction(
        kind=kind,  # type: ignore[arg-type]
        surface=surface,  # type: ignore[arg-type]
        destination=Destination(name=f"test:{dest}", dest_class=dest),  # type: ignore[arg-type]
        tool_name=tool_name,
        tool_args=tool_args,
        segments=segs,
    )
