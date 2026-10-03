"""Threat-feed data shapes (CONTRACTS section 4.7; threat-feed owns the details).

Pydantic models: `SigExample`, `SigTests`, `SigAppliesTo`, `Signature`, `BundleHeader`,
`Bundle`, `FeedPointer`; plus `normalize_signature()` which accepts the staging vocabulary
(`matcher`, list-form `applies_to`, leaf `literal`/`pickle_opcode`/`jsonpath`/
`semantic_exemplar`, actions `quarantine`/`strip_tool`/`alert`) and returns the contract shape.

Pure module: no imports from `aegis.feed.matchers` (they import us).
"""

from __future__ import annotations

import copy
import datetime as _dt
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aegis.core.types import Action, Severity, Surface

FEED_NAME = "aegis-threat-intel"
SCHEMA_VERSION = 1

SURFACES: tuple[str, ...] = tuple(get_args(Surface))
ACTIONS: tuple[str, ...] = tuple(get_args(Action))
STATUSES = ("experimental", "test", "stable", "deprecated", "withdrawn")
ENFORCED = frozenset({"test", "stable", "deprecated"})
MONITOR = frozenset({"experimental"})

#: staging coarse surface -> contract surfaces (generic default for list-form `applies_to`)
STAGING_SURFACES: dict[str, list[str]] = {
    "model_call": ["prompt.user", "model.request"],
    "tool_call": ["tool.input", "mcp.call", "tool.output", "mcp.result", "mcp.list"],
    "mcp": ["mcp.init", "mcp.call", "mcp.result"],
    "egress": ["egress.request"],
    "output": ["model.response", "tool.output", "mcp.result"],
    "model_download": ["model.admin", "artifact.file", "egress.request"],
}
#: staging example surface -> contract surface used to evaluate the vector
STAGING_EXAMPLE_SURFACE: dict[str, str] = {
    "model_call": "model.request",
    "tool_call": "tool.input",
    "mcp": "mcp.call",
    "egress": "egress.request",
    "output": "model.response",
    "model_download": "artifact.file",
}
ACTION_ALIASES: dict[str, str] = {"quarantine": "redact", "strip_tool": "redact", "alert": "log"}
LEAF_ALIASES: dict[str, str] = {
    "literal": "literal_set",
    "pickle_opcode": "pickle_globals",
    "jsonpath": "json_path",
    "semantic_exemplar": "semantic",
}
#: authoring-only keys stripped from published bundles
AUTHORING_ONLY = ("enabled",)


def to_plain(obj: Any) -> Any:
    """YAML -> JSON-safe data (dates become ISO strings, keys become str)."""
    if isinstance(obj, _dt.datetime):
        return obj.isoformat().replace("+00:00", "Z")
    if isinstance(obj, _dt.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        raise ValueError("raw bytes are not allowed in signatures; use bytes_hex/bytes_b64")
    return obj


def _canon_match(node: Any) -> Any:
    if isinstance(node, dict):
        out = {k: _canon_match(v) for k, v in node.items()}
        t = out.get("type")
        if isinstance(t, str) and t in LEAF_ALIASES:
            out["type"] = LEAF_ALIASES[t]
        return out
    if isinstance(node, list):
        return [_canon_match(v) for v in node]
    return node


def _expand_surfaces(items: Any) -> list[str]:
    out: list[str] = []
    for s in items or []:
        s = str(s)
        for x in STAGING_SURFACES.get(s, [s]):
            if x not in out:
                out.append(x)
    return out


def normalize_signature(sig: dict) -> dict:
    """Return a deep-copied, contract-shaped signature dict (idempotent)."""
    d = to_plain(copy.deepcopy(sig))
    if "match" not in d and "matcher" in d:
        d["match"] = d.pop("matcher")
    if "match" in d:
        d["match"] = _canon_match(d["match"])
    at = d.get("applies_to")
    if isinstance(at, list):
        d["applies_to"] = {"surfaces": _expand_surfaces(at)}
    elif isinstance(at, dict) and isinstance(at.get("surfaces"), list):
        at = dict(at)
        at["surfaces"] = _expand_surfaces(at["surfaces"])
        d["applies_to"] = at
    act = d.get("action")
    if isinstance(act, str) and act in ACTION_ALIASES:
        if act in ("quarantine", "strip_tool"):
            d.setdefault("redact_scope", "tool" if act == "strip_tool" else "segment")
        d["action"] = ACTION_ALIASES[act]
    ov = d.get("action_overrides")
    if isinstance(ov, dict):
        new: dict[str, str] = {}
        for k, v in ov.items():
            v2 = ACTION_ALIASES.get(str(v), str(v))
            for s in STAGING_SURFACES.get(str(k), [str(k)]):
                new[s] = v2
        d["action_overrides"] = new
    tests = d.get("tests")
    if isinstance(tests, dict):
        for kind in ("positive", "negative"):
            for ex in tests.get(kind) or []:
                if isinstance(ex, dict) and ex.get("surface") in STAGING_EXAMPLE_SURFACE:
                    ex["surface"] = STAGING_EXAMPLE_SURFACE[ex["surface"]]
    return d


# --------------------------------------------------------------------------- models
class _M(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class SigExample(_M):
    name: str = Field(min_length=1, max_length=200)
    surface: Surface
    note: str | None = None
    text: str | None = None
    json_: Any = Field(default=None, alias="json")
    url: str | None = None
    method: str | None = None
    body: str | None = None
    filename: str | None = None
    bytes_hex: str | None = None
    bytes_b64: str | None = None
    # contract keys (A-49): replayable through /v1/guard
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    http_method: str | None = None
    raw: Any = None
    meta: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _has_input(self) -> SigExample:
        fields = self.model_fields_set
        inputs = {
            "text",
            "json_",
            "url",
            "body",
            "bytes_hex",
            "bytes_b64",
            "filename",
            "tool_args",
            "raw",
            "meta",
        }
        if not (inputs & fields):
            raise ValueError(
                "an example needs at least one input: text, tool_args, url, raw, "
                "meta.artifact_b64 (or staging json/body/bytes_hex/bytes_b64)"
            )
        return self


class SigTests(_M):
    positive: list[SigExample] = Field(min_length=1)
    negative: list[SigExample] = Field(min_length=1)


class SigAppliesTo(_M):
    surfaces: list[Surface] = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)


class Signature(_M):
    id: str = Field(pattern=r"^AEGIS-TI-\d{3,4}$")
    title: str = Field(min_length=3, max_length=200)
    description: str | None = None
    status: Literal["experimental", "test", "stable", "deprecated", "withdrawn"] = "stable"
    severity: Severity = "medium"
    confidence: Literal["low", "medium", "high"] | None = None
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    published: str | None = None
    modified: str | None = None
    applies_to: SigAppliesTo
    match: dict[str, Any]
    action: Action
    action_overrides: dict[Surface, Action] = Field(default_factory=dict)
    #: match = redact the matched span; segment = the whole segment; tool = drop the MCP tool
    #: (mcp.list: Mutation remove `tool`, A-16), the whole segment elsewhere
    redact_scope: Literal["match", "segment", "tool"] = "match"
    redact_with: str | None = None
    message: str | None = Field(default=None, max_length=600)
    notes: str | None = None
    tests: SigTests
    enabled: bool | None = None  # authoring only (feed service); stripped from bundles

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        return normalize_signature(data) if isinstance(data, dict) else data

    @field_validator("aliases", "tags", "references", mode="before")
    @classmethod
    def _none_list(cls, v: Any) -> Any:
        return [] if v is None else v

    @model_validator(mode="after")
    def _surfaces_cover_tests(self) -> Signature:
        allowed = set(self.applies_to.surfaces)
        for kind in ("positive", "negative"):
            for i, ex in enumerate(getattr(self.tests, kind)):
                if ex.surface not in allowed:
                    raise ValueError(
                        f"tests.{kind}[{i}] ({ex.name}): surface {ex.surface} not in applies_to.surfaces"
                    )
        return self


class BundleHeader(_M):
    name: str = FEED_NAME
    schema_version: int = SCHEMA_VERSION
    serial: int = Field(ge=0)
    version: str = ""
    published: str | None = None
    expires: str | None = None
    min_gateway_version: str | None = None
    key_id: str | None = None
    signature_count: int | None = None


class Bundle(_M):
    feed: BundleHeader
    lists: dict[str, Any] = Field(default_factory=dict)
    signatures: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


class FeedPointer(_M):
    feed: str
    serial: int = Field(ge=0)
    version: str = ""
    bundle: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    published: str | None = None
    expires: str | None = None
    key_id: str | None = None


def signature_problems(sig: Any) -> list[str]:
    """Schema problems as readable strings (empty = valid)."""
    try:
        Signature.model_validate(sig)
    except Exception as e:  # pydantic.ValidationError or a normalization ValueError
        errs = getattr(e, "errors", None)
        if callable(errs):
            out = []
            for err in errs():
                loc = ".".join(str(x) for x in err.get("loc", ()))
                out.append(f"schema: {loc or '<root>'}: {err.get('msg')}")
            return out
        return [f"schema: {e}"]
    return []


def public_signature(sig: dict) -> dict:
    """Contract-shaped signature as it ships in a bundle (authoring-only keys removed)."""
    d = normalize_signature(sig)
    for k in AUTHORING_ONLY:
        d.pop(k, None)
    return d


def parse_iso(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        v = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return v if v.tzinfo else v.replace(tzinfo=_dt.UTC)


def iso(ts: _dt.datetime) -> str:
    return ts.astimezone(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0)
