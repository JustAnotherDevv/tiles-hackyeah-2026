"""Fakes for the injection-defense unit tests (no models, no app, no network).

* ``FakeSemantic``: scripted ``injection_score`` / ``moderate`` / ``embed`` results;
* ``FakeRedactor``: ``mask_for_log`` that masks digits/emails;
* ``FakeRuntime``: ``semantic`` + ``redactor`` + ``sessions``;
* builders: ``make_ctx()``, ``make_interaction()``, ``make_cfg()``.

The ``rt`` fixture monkeypatches ``aegis.controls.injection._common.get_rt``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from aegis.core.policy_schema import ControlConfig
from aegis.core.types import Interaction, RequestContext, ScoreResult, TextSegment

FIXTURES = Path(__file__).with_name("fixtures")


class FakeSemantic:
    def __init__(self) -> None:
        self.scores: dict[str, float] = {}  # substring -> injection score
        self.default = 0.0
        self.degraded = False
        self.guard_label = "Safe"
        self.guard_degraded = False
        self.guard_categories: list[str] | None = None  # None -> ["Jailbreak"] when unsafe
        self.calls: list[str] = []
        self.guard_calls: list[str] = []
        self.vectors: dict[str, list[float]] = {}

    async def injection_score(self, text: str, **kw: Any) -> ScoreResult:
        self.calls.append(text)
        s = self.default
        for k, v in self.scores.items():
            if k in text:
                s = max(s, v)
        return ScoreResult(
            score=s,
            model="heuristic" if self.degraded else "horizon-small",
            degraded=self.degraded,
            reason="fallback:off" if self.degraded else None,
        )

    async def moderate(self, text: str, **kw: Any) -> ScoreResult:
        self.guard_calls.append(text)
        sc = {"Safe": 0.0, "Controversial": 0.5, "Unsafe": 1.0}[self.guard_label]
        return ScoreResult(
            score=sc,
            label=self.guard_label,
            model="aegis-guard",
            degraded=self.guard_degraded,
            categories=(self.guard_categories if self.guard_categories is not None else ["Jailbreak"])
            if sc
            else [],
            reason="fallback:timeout" if self.guard_degraded else None,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.vectors:
            return []
        out = []
        for t in texts:
            v = [0.0, 0.0, 1.0]
            for k, vec in self.vectors.items():
                if k in t.lower():
                    v = vec
            out.append(v)
        return out

    async def similarity(self, text: str, references: list[str]) -> float:
        return 0.0

    def status(self) -> dict[str, Any]:
        return {"mode": "fake", "degraded": self.degraded, "models": []}


class FakeRedactor:
    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]", text or "")
        t = re.sub(r"\d", "•", t)
        t = " ".join(t.split())
        return t if len(t) <= max_len else t[: max_len - 1] + "…"


class _Session:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}


class FakeSessions:
    def __init__(self) -> None:
        self._s: dict[str, _Session] = {}

    def get(self, sid: str) -> _Session:
        return self._s.setdefault(sid, _Session())


class FakeRuntime:
    def __init__(self) -> None:
        self.semantic = FakeSemantic()
        self.redactor = FakeRedactor()
        self.sessions = FakeSessions()


def make_ctx(**kw: Any) -> RequestContext:
    kw.setdefault("request_id", "req_test")
    kw.setdefault("source", "test")
    return RequestContext(**kw)


_DEFAULT_ROLE = {
    "prompt.user": ("prompt", "user", True),
    "model.request": ("messages[0].content", "user", True),
    "model.response": ("content[0].text", "assistant", True),
    "tool.output": ("tool_response", "tool_result", False),
    "mcp.result": ("result.content[0].text", "tool_result", False),
    "mcp.list": ("result.tools[0].description", "tool_description", False),
    "egress.response": ("body", "other", False),
    "tool.input": ("tool_input", "tool_args", True),
    "mcp.call": ("params.arguments", "tool_args", True),
}
_KIND = {
    "tool.output": "tool_call",
    "tool.input": "tool_call",
    "mcp.result": "mcp",
    "mcp.list": "mcp",
    "mcp.call": "mcp",
    "egress.response": "egress",
}


def make_interaction(
    surface: str, text: str | None = None, *, segments: list[TextSegment] | None = None, **kw: Any
) -> Interaction:
    if segments is None:
        path, role, trusted = _DEFAULT_ROLE.get(surface, ("text", "user", True))
        segments = [TextSegment(path=path, text=text or "", role=role, trusted=trusted)]
    kw.setdefault("kind", _KIND.get(surface, "model_call"))
    kw.setdefault(
        "direction",
        "in"
        if surface in ("tool.output", "mcp.result", "model.response", "egress.response", "mcp.list")
        else "out",
    )
    return Interaction(surface=surface, segments=segments, **kw)


def make_cfg(cid: str, **kw: Any) -> ControlConfig:
    return ControlConfig(id=cid, **kw)


def load_jsonl(name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
