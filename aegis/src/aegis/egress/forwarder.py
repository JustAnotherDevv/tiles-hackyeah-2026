"""Governed third-party HTTP egress (`POST /egress`) building blocks.

Request -> `Interaction(egress.request)` (A-13) -> pipeline verdict -> write redacted segments
back + apply DLP-03 header/body mutations -> resolve the logical host (AEGIS_HOST_MAP) ->
send (no redirects, trust_env=False, identity encoding, 5 MB cap) -> `Interaction
(egress.response)` -> response verdict -> shaped 200 body.

Never logs header values, query values or bodies (names, hosts and counts only).
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from aegis.core.types import Destination, Interaction, TextSegment, Verdict
from aegis.egress import compat
from aegis.egress.headers import CREDENTIAL_HEADERS, HOP_BY_HOP, filter_response_headers
from aegis.egress.hostmap import HostMap, Target

log = logging.getLogger(__name__)

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_SEGMENTS = 2000
_NEVER_FORWARD = frozenset({"host", "content-length", "transfer-encoding", "connection",
                            "accept-encoding", "keep-alive", "upgrade", "te", "trailer",
                            "proxy-connection"})
_TEXTUAL = ("text/", "application/json", "application/xml", "application/javascript",
            "application/x-www-form-urlencoded", "+json", "+xml")


class EgressValidationError(ValueError):
    pass


class EgressRequest(BaseModel):
    """Contract section 5.1 body: {method, url, headers?, json?, body?, tool_name?, wait_s?}."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    method: str = "GET"
    url: str
    headers: dict[str, str] | None = None
    json_body: Any = Field(default=None, alias="json")
    body: str | None = None
    tool_name: str | None = None
    wait_s: float | None = None
    session_id: str | None = None
    has_json: bool = Field(default=False, exclude=True)

    @classmethod
    def parse(cls, data: Any, *, max_body_bytes: int = 8_000_000) -> EgressRequest:
        if not isinstance(data, dict):
            raise EgressValidationError("request body must be a JSON object")
        try:
            req = cls.model_validate(data)
        except Exception as e:
            raise EgressValidationError(f"invalid request: {str(e).splitlines()[0]}") from e
        req.has_json = "json" in data and data["json"] is not None
        req.method = req.method.upper()
        if req.method not in METHODS:
            raise EgressValidationError(f"method must be one of {', '.join(METHODS)}")
        parts = urlsplit(req.url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise EgressValidationError("url must be an absolute http(s) URL")
        if req.has_json and req.body is not None:
            raise EgressValidationError("give either json or body, not both")
        size = len(req.body.encode()) if req.body is not None else 0
        if req.has_json:
            size = len(json.dumps(req.json_body, default=str))
        if size > max_body_bytes:
            raise EgressValidationError(f"body exceeds max_body_bytes ({max_body_bytes})")
        return req

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower()


# ---------------------------------------------------------------- request interaction
def clean_headers(headers: dict[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (headers or {}).items():
        lk = str(k).lower().strip()
        if not lk or lk in _NEVER_FORWARD or lk in HOP_BY_HOP or lk.startswith("x-aegis-"):
            continue
        out[lk] = str(v)
    return out


def _leaves(obj: Any, prefix: str, out: list[tuple[str, str]], depth: int = 0) -> None:
    if depth > 16 or len(out) >= MAX_SEGMENTS:
        return
    if isinstance(obj, str):
        out.append((prefix, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _leaves(v, f"{prefix}.{k}", out, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _leaves(v, f"{prefix}[{i}]", out, depth + 1)


def dest_class_for(host: str, snap: Any) -> str:
    try:
        internal = list(snap.doc.destinations.internal_domains or []) if snap is not None else []
    except Exception:
        internal = []
    return "local" if compat.host_matches(internal, host) else "third_party"


def build_interaction(req: EgressRequest, *, snap: Any = None) -> tuple[Interaction, dict[str, str]]:
    """-> (interaction, real outbound headers). `interaction.headers` masks credential values."""
    host = req.host
    headers = clean_headers(req.headers)
    masked = {k: ("<redacted>" if k in CREDENTIAL_HEADERS else v) for k, v in headers.items()}
    segs: list[TextSegment] = [TextSegment(path="url", text=req.url, role="url")]
    leaves: list[tuple[str, str]] = []
    if req.has_json:
        _leaves(req.json_body, "json", leaves)
    for path, text in leaves:
        segs.append(TextSegment(path=path, text=text, role="tool_args"))
    if req.body is not None:
        segs.append(TextSegment(path="body", text=req.body, role="tool_args"))
    for k, v in headers.items():
        if k not in CREDENTIAL_HEADERS and v:
            segs.append(TextSegment(path=f"headers.{k}", text=v, role="header"))
    tool_args: dict[str, Any] = {"method": req.method, "url": req.url}
    if req.has_json:
        tool_args["json"] = copy.deepcopy(req.json_body)
    if req.body is not None:
        tool_args["body"] = req.body
    raw: Any = copy.deepcopy(req.json_body) if req.has_json else req.body
    inter = Interaction(
        kind="egress", surface="egress.request", direction="out",
        destination=Destination(name=f"egress:{host}", dest_class=dest_class_for(host, snap),
                                host=host, url=req.url),
        http_method=req.method, url=req.url,
        tool_name=req.tool_name or f"http.{req.method.lower()}",
        tool_args=tool_args, headers=masked, segments=segs, resource=f"host:{host}", raw=raw,
        meta={"egress": {"has_json": req.has_json, "has_body": req.body is not None}},
    )
    return inter, headers


@dataclass
class Outbound:
    method: str
    url: str
    headers: dict[str, str]
    json_body: Any = None
    body: str | None = None
    has_json: bool = False
    applied: list[str] = field(default_factory=list)  # names of mutations applied (no values)


def apply_verdict(req: EgressRequest, interaction: Interaction, headers: dict[str, str],
                  verdict: Verdict) -> Outbound:
    """Write redacted segments back by path, then apply header/body mutations."""
    out = Outbound(method=req.method, url=req.url, headers=dict(headers),
                   json_body=copy.deepcopy(req.json_body) if req.has_json else None,
                   body=req.body, has_json=req.has_json)
    originals = {s.path: s.text for s in interaction.segments}
    for seg in verdict.segments or []:
        if originals.get(seg.path) == seg.text:
            continue
        if seg.path == "url":
            out.url = seg.text
        elif seg.path == "body":
            out.body = seg.text
        elif seg.path == "json":
            out.json_body = seg.text
        elif seg.path.startswith("json.") or seg.path.startswith("json["):
            compat.set_path(out.json_body, seg.path[5:] if seg.path.startswith("json.")
                            else seg.path[4:], seg.text)
        elif seg.path.startswith("headers."):
            name = seg.path[8:]
            if name in out.headers:
                out.headers[name] = seg.text
        else:
            continue
        out.applied.append(f"segment:{seg.path}")
    for m in verdict.mutations or []:
        if m.target == "header":
            name = str(m.path).lower()
            if m.op == "remove":
                out.headers.pop(name, None)
            elif m.value is not None:
                out.headers[name] = str(m.value)
            out.applied.append(f"header:{m.op}:{name}")
        elif m.target == "body":
            if out.has_json and isinstance(out.json_body, (dict, list)):
                ok = (compat.remove_path(out.json_body, m.path) if m.op == "remove"
                      else compat.set_path(out.json_body, m.path, m.value))
                if ok:
                    out.applied.append(f"body:{m.op}:{m.path}")
    return out


# ---------------------------------------------------------------- upstream
@dataclass
class UpstreamResponse:
    status: int
    headers: dict[str, str]
    content: bytes
    truncated: bool
    upstream_ms: float
    content_type: str = ""


class EgressForwarder:
    def __init__(self, host_map: HostMap | None = None, *, timeout_s: float = 15.0) -> None:
        self.host_map = host_map or HostMap.from_settings()
        self.timeout_s = timeout_s
        self._transport: httpx.AsyncBaseTransport | None = None
        self._client: httpx.AsyncClient | None = None

    def set_transport(self, transport: httpx.AsyncBaseTransport | None) -> None:
        """Tests: route upstream calls through a mock transport (closes the current client)."""
        self._transport = transport
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=False,
                                             trust_env=False, transport=self._transport)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    def resolve(self, url: str) -> Target:
        return self.host_map.resolve(url)

    async def send(self, out: Outbound, target: Target) -> UpstreamResponse:
        headers = {k: v for k, v in out.headers.items() if k not in _NEVER_FORWARD}
        headers["accept-encoding"] = "identity"
        if target.host_header:
            headers["host"] = target.host_header
        content: bytes | None = None
        if out.has_json:
            content = json.dumps(out.json_body, ensure_ascii=False).encode()
            headers.setdefault("content-type", "application/json")
        elif out.body is not None:
            content = out.body.encode()
        t0 = time.perf_counter()
        req = self.client.build_request(out.method, target.connect_url, headers=headers,
                                        content=content)
        resp = await self.client.send(req, stream=True)
        try:
            buf = bytearray()
            truncated = False
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_RESPONSE_BYTES:
                    del buf[MAX_RESPONSE_BYTES:]
                    truncated = True
                    break
        finally:
            await resp.aclose()
        ms = (time.perf_counter() - t0) * 1000
        log.debug("egress upstream host=%s mapped=%s status=%s bytes=%d ms=%.1f",
                  target.host, target.mapped, resp.status_code, len(buf), ms)
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        return UpstreamResponse(status=resp.status_code, headers=hdrs, content=bytes(buf),
                                truncated=truncated, upstream_ms=ms,
                                content_type=hdrs.get("content-type", ""))


# ---------------------------------------------------------------- response interaction
@dataclass
class ParsedBody:
    kind: str  # json | text | binary | empty
    value: Any = None
    b64: str | None = None


def parse_body(up: UpstreamResponse) -> ParsedBody:
    if not up.content:
        return ParsedBody(kind="empty")
    ct = up.content_type.lower()
    if "json" in ct and not up.truncated:
        try:
            return ParsedBody(kind="json", value=json.loads(up.content))
        except ValueError:
            pass
    textual = any(t in ct for t in _TEXTUAL) or not ct
    try:
        text = up.content.decode("utf-8")
        if textual or text.isprintable():
            return ParsedBody(kind="text", value=text)
    except UnicodeDecodeError:
        pass
    return ParsedBody(kind="binary", b64=base64.b64encode(up.content).decode())


def build_response_interaction(req_inter: Interaction, parsed: ParsedBody, *,
                               dest_class: str = "remote") -> Interaction:
    segs: list[TextSegment] = []
    if parsed.kind == "json":
        leaves: list[tuple[str, str]] = []
        _leaves(parsed.value, "body", leaves)
        segs = [TextSegment(path=p, text=t, role="tool_result", trusted=False) for p, t in leaves]
    elif parsed.kind == "text":
        segs = [TextSegment(path="body", text=parsed.value, role="tool_result", trusted=False)]
    return Interaction(
        kind="egress", surface="egress.response", direction="in",
        destination=Destination(name="agent", dest_class=dest_class),  # type: ignore[arg-type]
        http_method=req_inter.http_method, url=req_inter.url, tool_name=req_inter.tool_name,
        resource=req_inter.resource, parent_id=req_inter.id or None, segments=segs,
        raw=parsed.value, meta={"egress": {"body_kind": parsed.kind}},
    )


def apply_response_verdict(parsed: ParsedBody, resp_inter: Interaction, verdict: Verdict) -> Any:
    """Return the (possibly redacted) body value to hand back to the agent."""
    if parsed.kind not in ("json", "text"):
        return None
    originals = {s.path: s.text for s in resp_inter.segments}
    value = copy.deepcopy(parsed.value)
    for seg in verdict.segments or []:
        if originals.get(seg.path) == seg.text:
            continue
        if seg.path == "body":
            value = seg.text
        elif seg.path.startswith("body.") or seg.path.startswith("body["):
            compat.set_path(value, seg.path[5:] if seg.path.startswith("body.") else seg.path[4:],
                            seg.text)
    return value


def shape_response(up: UpstreamResponse, body: Any, parsed: ParsedBody, *, decision_id: str,
                   redactions: list[Any], response_decision_id: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": up.status,
        "headers": filter_response_headers(up.headers),
        "body": body,
        "decision_id": decision_id,
        "redactions": [r.model_dump(mode="json") if hasattr(r, "model_dump") else r
                       for r in redactions],
        "response_decision_id": response_decision_id,
        "truncated": up.truncated,
    }
    if parsed.kind == "binary":
        out["body_b64"] = parsed.b64
    return out
