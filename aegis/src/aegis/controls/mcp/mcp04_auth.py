"""Control MCP-04: token & auth hygiene.

* `meta["mcp.header_mismatch"]` (2026 routing header ≠ body) → block "request smuggling"
* `mcp.result`: `Authorization: Bearer …` / bearer JWTs in tool output → redact with spans
  (entity GENERIC_SECRET / JWT; the pipeline replaces them via the redactor)
* `mcp.init` OAuth metadata (`authorization_endpoint`, `token_endpoint`, `registration_endpoint`)
  that is not https or contains `$(`, a backtick, `%24%28`, whitespace, `javascript:`, `data:`,
  `file:` → block (CVE-2025-6514 class)
* `tool_args` scopes in `params.forbidden_scopes` → block
Client-credential stripping is always on in the transport (never forwarded upstream).
"""

from __future__ import annotations

import fnmatch
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Interaction, RequestContext

log = logging.getLogger(__name__)

BEARER_RE = re.compile(r"(?i)\b(?:authorization\s*[:=]\s*)?bearer\s+([A-Za-z0-9\-._~+/]{16,}=*)")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
OAUTH_KEYS = ("authorization_endpoint", "token_endpoint", "registration_endpoint",
              "revocation_endpoint", "issuer", "jwks_uri")
SCOPE_KEYS = {"scope", "scopes", "oauth_scope", "permissions"}


class _OAuthRules(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemes: list[str] = Field(default_factory=lambda: ["https"])
    deny_substrings: list[str] = Field(default_factory=lambda: [
        "$(", "`", "%24%28", " ", "javascript:", "data:", "file:"])


class _Params(BaseModel):
    model_config = ConfigDict(extra="ignore")

    redact_bearer_in_results: bool = True
    forbidden_scopes: list[str] = Field(default_factory=lambda: ["*", "admin:*", "files:*"])
    oauth_url_rules: _OAuthRules = Field(default_factory=_OAuthRules)


def _walk(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            out.append((p, v))
            out += _walk(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _walk(v, f"{path}[{i}]")
    return out


class McpAuthHygiene(BaseControl):
    id = "MCP-04"
    family = "MCP"
    name = "Token & auth hygiene"
    kind = "deterministic"
    applies_to = AppliesTo(surfaces={"mcp.init", "mcp.call", "mcp.result"})
    owasp = ["MCP01:2025", "MCP02:2025", "MCP07:2025", "ASI03"]
    priority = 25

    def _params(self, cfg: ControlConfig) -> _Params:
        unknown = set(cfg.params) - set(_Params.model_fields)
        if unknown:
            log.warning("MCP-04 unknown params ignored: %s", sorted(unknown))
        try:
            return _Params.model_validate(cfg.params)
        except Exception:
            log.warning("MCP-04 invalid params; using defaults", exc_info=True)
            return _Params()

    async def evaluate(self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
                       ) -> Decision | None:
        p = self._params(cfg)
        mismatch = interaction.meta.get("mcp.header_mismatch")
        if mismatch:
            return self.decide(cfg, action="block",
                               reason=f"request smuggling: routing header != body ({mismatch})",
                               findings=[Finding(control_id=self.id, detector="mcp.header_mismatch",
                                                 category="mcp", severity="high")])
        if interaction.surface == "mcp.init":
            return self._oauth(cfg, p, interaction)
        if interaction.surface == "mcp.call":
            return self._scopes(cfg, p, interaction)
        if interaction.surface == "mcp.result" and p.redact_bearer_in_results:
            return self._bearer(cfg, interaction)
        return None

    def _oauth(self, cfg: ControlConfig, p: _Params, i: Interaction) -> Decision | None:
        sources: list[tuple[str, Any]] = _walk(i.meta.get("mcp.oauth") or {})
        if isinstance(i.raw, dict):
            sources += _walk(i.raw)
        bad: list[str] = []
        for path, value in sources:
            key = path.rsplit(".", 1)[-1]
            if key not in OAUTH_KEYS or not isinstance(value, str):
                continue
            low = value.lower()
            scheme_ok = any(low.startswith(f"{s}://") for s in p.oauth_url_rules.schemes)
            deny = [d for d in p.oauth_url_rules.deny_substrings if d.lower() in low]
            if not scheme_ok or deny:
                bad.append(key)
        if not bad:
            return None
        return self.decide(cfg, action="block",
                           reason=f"unsafe OAuth metadata ({', '.join(sorted(set(bad)))}): "
                                  "non-https or shell/script characters (CVE-2025-6514 class)",
                           findings=[Finding(control_id=self.id, detector="mcp.oauth_url",
                                             category="mcp", severity="high",
                                             meta={"fields": sorted(set(bad))})])

    def _scopes(self, cfg: ControlConfig, p: _Params, i: Interaction) -> Decision | None:
        hits: list[str] = []
        for path, value in _walk(i.tool_args or {}):
            key = path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
            if key not in SCOPE_KEYS:
                continue
            values = value if isinstance(value, list) else str(value).replace(",", " ").split()
            for v in values:
                if not isinstance(v, str):
                    continue
                for pat in p.forbidden_scopes:
                    if v == pat or (pat != "*" and fnmatch.fnmatchcase(v, pat)):
                        hits.append(v)
        if not hits:
            return None
        return self.decide(cfg, action="block",
                           reason=f"forbidden OAuth scope requested: {', '.join(sorted(set(hits)))}",
                           findings=[Finding(control_id=self.id, detector="mcp.forbidden_scope",
                                             category="scope", severity="high",
                                             excerpt=", ".join(sorted(set(hits)))[:160])])

    def _bearer(self, cfg: ControlConfig, i: Interaction) -> Decision | None:
        findings: list[Finding] = []
        for idx, seg in enumerate(i.segments):
            taken: list[tuple[int, int]] = []
            for m in JWT_RE.finditer(seg.text):
                taken.append((m.start(), m.end()))
                findings.append(Finding(control_id=self.id, detector="mcp.bearer_jwt", category="secret",
                                        entity="JWT", data_class="SECRET", severity="high",
                                        segment_index=idx, start=m.start(), end=m.end()))
            for m in BEARER_RE.finditer(seg.text):
                s, e = m.start(1), m.end(1)
                if any(s < te and ts < e for ts, te in taken):
                    continue
                findings.append(Finding(control_id=self.id, detector="mcp.bearer_token",
                                        category="secret", entity="GENERIC_SECRET",
                                        data_class="SECRET", severity="high",
                                        segment_index=idx, start=s, end=e))
        if not findings:
            return None
        return self.decide(cfg, action="redact",
                           reason=f"{len(findings)} bearer credential(s) in MCP tool output redacted",
                           findings=findings)


CONTROLS = [McpAuthHygiene()]
