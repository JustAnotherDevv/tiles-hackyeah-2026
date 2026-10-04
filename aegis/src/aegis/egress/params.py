"""Parameter models for DLP-03 / DLP-04 / DLP-06 and profile-aware defaults.

`effective_params(Model, cfg, profile)` = model defaults (balanced) ⊕ `PROFILE_DEFAULTS[profile]`
⊕ keys explicitly present in `cfg.params` (deep merge; lists replace). Unknown keys are kept
(`extra="allow"`) and reported once per (control, params hash) as a WARNING.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

Style = Literal["placeholder", "generalize"]


class _P(BaseModel):
    model_config = ConfigDict(extra="allow")


# ================================================================ DLP-03
class TextParams(_P):
    enabled: bool = True
    paths: bool = True
    hostnames: bool = True
    private_ips: bool = True
    public_ips: bool = False  # opt-in (strict/paranoid): routable client IPs are personal data
    mac_addresses: bool = True
    loopback: bool = False  # 127.0.0.0/8, ::1 reveal nothing about the user; off by default
    git: bool = False
    learn_identifiers: bool = True
    style: dict[str, Style] = Field(
        default_factory=lambda: {"remote": "placeholder", "third_party": "generalize"})
    user_allowlist: list[str] = Field(default_factory=list)
    internal_suffixes: list[str] = Field(
        default_factory=lambda: [".local", ".lan", ".internal", ".corp", ".intranet",
                                 ".home.arpa"])
    min_identifier_len: int = 4
    max_identifiers: int = 32


DEFAULT_DENY_HEADERS = [
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "forwarded", "via",
    "true-client-ip", "cf-connecting-ip", "x-client-ip", "cookie", "referer", "origin",
    "x-stainless-*", "x-client-*", "x-internal-*", "x-amzn-trace-id",
]


def _default_allow() -> dict[str, list[str]]:
    return {
        "anthropic": ["anthropic-*", "authorization", "x-api-key", "content-type", "accept",
                      "user-agent", "x-app", "x-claude-code-session-id"],
        "openai": ["openai-*", "authorization", "content-type", "accept", "user-agent"],
        "ollama": ["content-type", "accept"],
        "mcp": ["mcp-*", "content-type", "accept", "last-event-id"],
        "egress": ["accept", "accept-language", "content-type", "if-match", "if-none-match",
                   "idempotency-key", "user-agent"],
    }


class HeaderParams(_P):
    enabled: bool = True
    mode: Literal["denylist", "allowlist"] = "denylist"
    deny: list[str] = Field(default_factory=lambda: list(DEFAULT_DENY_HEADERS))
    allow: dict[str, list[str]] = Field(default_factory=_default_allow)
    replace: dict[str, str] = Field(default_factory=lambda: {"user-agent": "aegis/0.1"})
    keep_user_agent_for: list[str] = Field(default_factory=lambda: ["anthropic"])
    pass_auth_hosts: list[str] = Field(default_factory=list)


class BodyFieldRule(_P):
    path: str
    op: Literal["pseudonymize", "remove", "keep"] = "pseudonymize"


class ClaudeCodeParams(_P):
    enabled: bool = True
    user_email: bool = True
    git_user: bool = True
    git_status: Literal["keep", "strip"] = "keep"
    project_claude_md: Literal["keep", "strip"] = "keep"
    user_claude_md: Literal["keep", "strip"] = "keep"
    environment: Literal["keep", "generalize"] = "keep"
    pseudonymize_session_id: bool = False


class MediaParams(_P):
    enabled: bool = True
    images: Literal["strip", "keep"] = "strip"
    pdf: Literal["strip", "keep"] = "strip"
    office: Literal["strip", "keep"] = "strip"
    unsupported: Literal["block", "log", "allow"] = "block"
    max_bytes: int = 10_000_000
    generic_base64_min_len: int = 1024
    pdf_active_content: Literal["block", "log"] = "log"


class Dlp03Params(_P):
    text: TextParams = Field(default_factory=TextParams)
    headers: HeaderParams = Field(default_factory=HeaderParams)
    body_fields: list[BodyFieldRule] = Field(default_factory=lambda: [
        BodyFieldRule(path="metadata.user_id"), BodyFieldRule(path="user"),
        BodyFieldRule(path="safety_identifier")])
    claude_code: ClaudeCodeParams = Field(default_factory=ClaudeCodeParams)
    media: MediaParams = Field(default_factory=MediaParams)
    exempt_agents: list[str] = Field(default_factory=list)


# ================================================================ DLP-04
class Dlp04Params(_P):
    max_encoded_len: int = 64
    url_encoded_min_len: int = 16
    decode_depth: int = 2
    query_max_len: int = 256
    dns_label_max: int = 40
    dns_label_entropy_min: float = 3.5
    dns_max_labels: int = 8
    blob_entropy_min: float = 4.0
    exfil_hosts_extra: list[str] = Field(default_factory=list)
    trusted_params: list[str] = Field(
        default_factory=lambda: ["X-Amz-*", "sig", "signature", "state", "code_challenge"])
    scan_local_tool_urls: bool = True
    semantic_judge: bool = False
    default_threshold: float = 0.8  # used when cfg.threshold is unset (profile-sensitive)


# ================================================================ DLP-06
class Dlp06Params(_P):
    max_query_len: int = 64
    reference_style: bool = True
    strip_html_tags: list[str] = Field(default_factory=lambda: [
        "img", "iframe", "script", "object", "embed", "meta", "link", "form", "base"])
    strip_ansi: bool = True
    extra_allowed_domains: list[str] = Field(default_factory=list)
    strip_images: Literal["external", "all", "none"] = "external"
    defang_links: Literal["suspicious", "all_external", "none"] = "suspicious"


# ================================================================ profiles
PROFILE_DEFAULTS: dict[str, dict[str, dict[str, Any]]] = {
    "permissive": {
        "DLP-03": {"text": {"enabled": False}, "claude_code": {"enabled": False},
                   "media": {"unsupported": "allow"}},
        "DLP-04": {"default_threshold": 0.95},
        "DLP-06": {"strip_images": "external", "defang_links": "none"},
    },
    "balanced": {
        "DLP-03": {},
        "DLP-04": {"default_threshold": 0.8},
        "DLP-06": {"strip_images": "external", "defang_links": "suspicious"},
    },
    "strict": {
        "DLP-03": {"text": {"git": True}, "headers": {"mode": "allowlist"},
                   "claude_code": {"git_status": "strip", "user_claude_md": "strip",
                                   "pseudonymize_session_id": True}},
        "DLP-04": {"default_threshold": 0.6},
        "DLP-06": {"defang_links": "all_external"},
    },
    "paranoid": {
        "DLP-03": {"text": {"git": True}, "headers": {"mode": "allowlist"},
                   "claude_code": {"git_status": "strip", "user_claude_md": "strip",
                                   "project_claude_md": "strip", "environment": "generalize",
                                   "pseudonymize_session_id": True}},
        "DLP-04": {"default_threshold": 0.5},
        "DLP-06": {"defang_links": "all_external", "strip_images": "all"},
    },
}

KNOWN_PROFILES = frozenset(PROFILE_DEFAULTS)


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


#: staging-style keys still present in docs/seed-fixes/policy.yaml (accepted, mapped, no warning)
LEGACY_KEYS = {"DLP-03": {"strip_body_fields", "generalize", "strip_headers"}}


def _legacy(control_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Map staging DLP-03 keys (`strip_body_fields`, `generalize: {paths, hostnames, ips, ...}`)
    onto the param model. Only explicit `false` generalize flags are honoured (they can switch a
    detector off); new-style keys always win."""
    if control_id != "DLP-03":
        return params
    out = {k: v for k, v in params.items() if k not in LEGACY_KEYS["DLP-03"]}
    sbf = params.get("strip_body_fields")
    if isinstance(sbf, list) and "body_fields" not in params:
        out["body_fields"] = [{"path": str(p), "op": "pseudonymize"} for p in sbf]
    gen = params.get("generalize")
    if isinstance(gen, dict):
        text = dict(out.get("text") or {})
        for legacy, key in (("paths", "paths"), ("hostnames", "hostnames"),
                            ("ips", "private_ips"), ("usernames", "learn_identifiers")):
            if gen.get(legacy) is False and key not in text:
                text[key] = False
        if text:
            out["text"] = text
    return out


def _unknown_keys(model_cls: type[BaseModel], params: dict[str, Any], prefix: str = "") -> list[str]:
    out: list[str] = []
    fields = model_cls.model_fields
    for k, v in params.items():
        if k not in fields:
            out.append(prefix + k)
            continue
        ann = fields[k].annotation
        if isinstance(v, dict) and isinstance(ann, type) and issubclass(ann, BaseModel):
            out.extend(_unknown_keys(ann, v, prefix + k + "."))
    return out


_CACHE: OrderedDict[str, BaseModel] = OrderedDict()
_WARNED: set[str] = set()


def effective_params[M: BaseModel](
    model_cls: type[M], cfg: Any, profile: str | None, *, control_id: str | None = None
) -> M:
    """Profile defaults ⊕ explicit `cfg.params`. Cached by (model, profile, params hash)."""
    params = dict(getattr(cfg, "params", None) or {})
    cid = control_id or getattr(cfg, "id", None) or model_cls.__name__
    prof = profile if profile in KNOWN_PROFILES else "balanced"
    try:
        raw = json.dumps(params, sort_keys=True, default=str)
    except Exception:
        raw = repr(params)
    key = f"{model_cls.__name__}|{prof}|{hashlib.sha256(raw.encode()).hexdigest()[:16]}"
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit  # type: ignore[return-value]
    params = _legacy(str(cid), params)
    merged = deep_merge(PROFILE_DEFAULTS.get(prof, {}).get(cid, {}), params)
    try:
        model = model_cls.model_validate(merged)
    except Exception as exc:
        log.warning("invalid params; using profile defaults control=%s error=%s", cid, exc)
        model = model_cls.model_validate(PROFILE_DEFAULTS.get(prof, {}).get(cid, {}))
    unknown = _unknown_keys(model_cls, params)
    if unknown and key not in _WARNED:
        _WARNED.add(key)
        log.warning("unknown params ignored control=%s keys=%s", cid, ",".join(unknown))
    _CACHE[key] = model
    if len(_CACHE) > 64:
        _CACHE.popitem(last=False)
    return model


def params_hash(model: BaseModel) -> str:
    return hashlib.sha256(model.model_dump_json().encode()).hexdigest()[:16]
