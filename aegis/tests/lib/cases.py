"""Case schema (plan 18 §2.4) + loader for `tests/cases/*.yaml`.

A file is either a list of cases or `{defaults: {...}, cases: [...]}`. Files starting with `_`
are not case files. Unknown keys are errors (`extra="forbid"`), reported as `file:line: message`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CASES_DIR = Path(__file__).resolve().parents[1] / "cases"

Via = Literal[
    "guard",
    "anthropic",
    "openai",
    "ollama",
    "hook",
    "mcp",
    "egress",
    "playground",
    "simulate",
    "api",
]
ACTIONS = {"allow", "log", "redact", "require_approval", "block"}
ATTACK = {"block", "require_approval"}


class CaseAssert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upstream_must_contain: list[str] = Field(default_factory=list)
    upstream_must_not_contain: list[str] = Field(default_factory=list)
    response_must_contain: list[str] = Field(default_factory=list)
    response_must_not_contain: list[str] = Field(default_factory=list)
    audit_must_not_contain: list[str] = Field(default_factory=list)
    sink_hits: int | None = None
    tool_listed: list[str] = Field(default_factory=list)  # mcp tools/list must include
    tool_not_listed: list[str] = Field(default_factory=list)  # mcp tools/list must not include


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    control: str | list[str] | None = None
    polarity: Literal["attack", "benign", "error"]
    expect: str
    via: Via = "guard"
    surface: str | None = None
    kind: str | None = None
    dest: Literal["local", "remote", "third_party"] | None = None
    as_: str | None = Field(default=None, alias="as")
    input: str | None = None
    segments: list[dict[str, Any]] | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    url: str | None = None
    method: str | None = None
    path: str | None = None  # via: api
    json_body: Any = Field(default=None, alias="json")  # via: api / egress
    view_as: str | None = None  # via: api
    amount_usd: float | None = None
    action_type: str | None = None  # via: simulate
    resource: str | None = None
    model: str | None = None
    stream: bool = False
    max_tokens: int | None = None
    hook_event: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    meta: dict[str, Any] | None = None
    labels: dict[str, str] | None = None  # interaction / simulate labels
    changes: list[dict[str, Any]] | None = None  # via: simulate (config_change)
    expect_entities: list[str] = Field(default_factory=list)
    expect_route: str | None = None
    expect_rule: str | None = None
    expect_status: int | None = None
    expect_monitor: dict[str, str] | None = None
    assert_: CaseAssert = Field(default_factory=CaseAssert, alias="assert")
    steps: list[dict[str, Any]] | None = None
    repeat: int = 1
    mode: Literal["deterministic", "semantic", "both"] = "deterministic"
    tier: Literal["core", "stretch"] = "core"
    profiles: list[str] | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = ""
    note: str = ""
    hermetic_only: bool = False
    # filled by the loader
    file: str = ""
    line: int = 0

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_\-]*", v):
            raise ValueError(f"id {v!r} must match [A-Z0-9-]+")
        return v

    @field_validator("expect")
    @classmethod
    def _expect(cls, v: str) -> str:
        if v in ACTIONS or re.fullmatch(r"error:-?\d+", v):
            return v
        raise ValueError(f"expect {v!r} must be one of {sorted(ACTIONS)} or error:<code>")

    @model_validator(mode="after")
    def _polarity(self) -> Case:
        col = column_of(self.expect)
        ok = {"attack": {"attack", "redact"}, "benign": {"benign"}, "error": {"error"}}[
            self.polarity
        ]
        if col not in ok:
            raise ValueError(f"polarity {self.polarity!r} disagrees with expect {self.expect!r}")
        if self.via in ("guard", "anthropic", "openai", "playground", "hook") and not (
            self.input is not None
            or self.segments
            or self.tool
            or self.url
            or self.steps
            or self.args is not None
        ):
            raise ValueError("case needs input, segments, tool, args, url or steps")
        return self

    @property
    def controls(self) -> list[str]:
        if self.control is None:
            return []
        return [self.control] if isinstance(self.control, str) else list(self.control)

    @property
    def column(self) -> str:
        return column_of(self.expect)

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"


def column_of(expect: str) -> str:
    if expect in ATTACK:
        return "attack"
    if expect == "redact":
        return "redact"
    if expect.startswith("error:"):
        return "error"
    return "benign"


class CaseError(Exception):
    def __init__(self, messages: list[str]):
        super().__init__("\n".join(messages))
        self.messages = messages


def _ruamel_load(text: str) -> Any:
    from ruamel.yaml import YAML

    return YAML(typ="rt").load(text)


def _line_of(node: Any, default: int) -> int:
    lc = getattr(node, "lc", None)
    return (lc.line + 1) if lc is not None and lc.line is not None else default


def _plain(node: Any) -> Any:
    if isinstance(node, dict):
        return {str(k): _plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain(x) for x in node]
    return node


def _fmt(err: ValidationError) -> str:
    parts = []
    for e in err.errors():
        loc = ".".join(str(x) for x in e["loc"])
        if e["type"] == "extra_forbidden":
            parts.append(f"extra field '{loc}'")
        else:
            parts.append(f"{loc + ': ' if loc else ''}{e['msg']}")
    return "; ".join(parts)


def load_file(path: Path, root: Path | None = None) -> tuple[list[Case], list[str]]:
    rel = str(path.relative_to(root)) if root and path.is_relative_to(root) else str(path)
    errors: list[str] = []
    try:
        doc = _ruamel_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        mark = getattr(exc, "problem_mark", None)
        line = (mark.line + 1) if mark is not None else 1
        return [], [f"{rel}:{line}: YAML error: {getattr(exc, 'problem', exc)}"]
    if doc is None:
        return [], []
    defaults: dict[str, Any] = {}
    items = doc
    if isinstance(doc, dict):
        defaults = _plain(doc.get("defaults") or {})
        items = doc.get("cases") or []
        extra = set(doc) - {"defaults", "cases"}
        if extra:
            errors.append(f"{rel}:1: unknown top-level keys {sorted(extra)} (use defaults/cases)")
    if not isinstance(items, list):
        return [], [*errors, f"{rel}:1: expected a list of cases"]
    cases: list[Case] = []
    for i, node in enumerate(items):
        line = _line_of(node, i + 1)
        if not isinstance(node, dict):
            errors.append(f"{rel}:{line}: case must be a mapping")
            continue
        data = {**defaults, **_plain(node)}
        try:
            c = Case.model_validate(data)
        except ValidationError as exc:
            errors.append(f"{rel}:{line}: {data.get('id', '?')}: {_fmt(exc)}")
            continue
        c.file, c.line = rel, line
        cases.append(c)
    return cases, errors


def load_all(
    directory: Path | None = None, *, profile: str | None = None, strict: bool = False
) -> tuple[list[Case], list[str]]:
    d = directory or CASES_DIR
    root = d.parent.parent if d.parent.name == "tests" else d.parent
    out: list[Case] = []
    errors: list[str] = []
    seen: dict[str, str] = {}
    for p in sorted(d.glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        cases, errs = load_file(p, root)
        errors.extend(errs)
        for c in cases:
            if c.id in seen:
                errors.append(f"{c.where}: duplicate id {c.id} (first at {seen[c.id]})")
                continue
            seen[c.id] = c.where
            if profile and c.profiles and profile not in c.profiles:
                continue
            out.append(c)
    if strict and errors:
        raise CaseError(errors)
    return out, errors


def harness_settings(directory: Path | None = None) -> dict[str, Any]:
    import yaml

    p = (directory or CASES_DIR) / "_harness.yaml"
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


__all__ = [
    "ACTIONS",
    "CASES_DIR",
    "Case",
    "CaseAssert",
    "CaseError",
    "column_of",
    "harness_settings",
    "load_all",
    "load_file",
]
