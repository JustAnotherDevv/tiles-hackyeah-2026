"""Control MCP-02: tool-definition poisoning scan (on `mcp.list`, one interaction per tool).

Scans every string of the tool definition (segments, role `tool_description`) over the normalized
text and decoded variants: hidden tags (<IMPORTANT>), ignore-previous, conceal-from-user, role
override, chat template, sensitive paths, precondition hijack, tool directive, ANSI, invisible /
Unicode TAG characters, URLs outside `params.url_allowlist`, over-long descriptions, bad names and
cross-server references (tool shadowing). `score = Σ severity` (high=3, medium=1); optional
semantic leg via `rt.semantic.injection_score` (own timeout; degraded/timeout keeps the
deterministic result).

score ≥ params.score_threshold → `cfg.action` (default redact) + `Mutation(op="remove",
path="result.tools[i]")` = the tool is dropped from tools/list. Findings carry NO spans, so the
pipeline never vaults description fragments. Below threshold but non-zero → log.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aegis.controls.mcp.mcp01_registry import mcp_section, server_of
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import (
    AppliesTo,
    ApprovalDraft,
    Decision,
    Finding,
    Interaction,
    Mutation,
    RequestContext,
)
from aegis.mcp import detect

log = logging.getLogger(__name__)


class _Params(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score_threshold: int = 3
    semantic: bool = True
    url_allowlist: list[str] = Field(default_factory=list)
    extra_markers: list[str] = Field(default_factory=list)
    cross_server_reference: bool = True


def _runtime() -> Any:
    try:
        from aegis.core.runtime import get_runtime

        return get_runtime()
    except Exception:
        try:
            from aegis.mcp.service import get_service

            svc = get_service()
            return svc.rt if svc is not None else None
        except Exception:
            return None


def _mask(rt: Any, text: str) -> str:
    try:
        return str(rt.redactor.mask_for_log(text, 160))
    except Exception:
        return detect.snippet(text, 160)


class McpPoisoning(BaseControl):
    id = "MCP-02"
    family = "MCP"
    name = "Tool-definition poisoning scan"
    kind = "hybrid"
    applies_to = AppliesTo(surfaces={"mcp.list"})
    owasp = ["MCP03:2025", "MCP06:2025", "ASI04", "LLM01:2026"]
    priority = 40

    _marker_cache: dict[tuple[str, ...], list[Any]] = {}

    def _params(self, cfg: ControlConfig) -> _Params:
        unknown = set(cfg.params) - set(_Params.model_fields)
        if unknown:
            log.warning("MCP-02 unknown params ignored: %s", sorted(unknown))
        try:
            return _Params.model_validate(cfg.params)
        except Exception:
            log.warning("MCP-02 invalid params; using defaults", exc_info=True)
            return _Params()

    def _markers(self, p: _Params) -> list[Any]:
        key = tuple(p.extra_markers)
        if key not in self._marker_cache:
            self._marker_cache[key] = detect.compile_markers(p.extra_markers)
        return self._marker_cache[key]

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p = self._params(cfg)
        server, tool = server_of(interaction)
        mcp = mcp_section(ctx)
        max_len = int(getattr(mcp, "max_description_len", 1024) or 1024)
        rt = _runtime()

        texts = [(s.path, s.text) for s in interaction.segments]
        findings = detect.scan_segments(
            texts, url_allowlist=p.url_allowlist, extra_markers=self._markers(p)
        )
        raw = interaction.raw if isinstance(interaction.raw, dict) else None
        desc = (
            str((raw or {}).get("description") or "")
            if raw
            else "\n".join(
                s.text for s in interaction.segments if s.path in ("description", "text", "")
            )
        )
        if not desc and interaction.segments and raw is None:
            desc = interaction.text()
        if len(desc) > max_len:
            findings.append(
                detect.ToolFinding(
                    "tooldef.long_description",
                    "medium",
                    "description",
                    f"{len(desc)} chars > {max_len}",
                )
            )
        if tool and not detect.NAME_RE.fullmatch(tool):
            findings.append(
                detect.ToolFinding("tooldef.bad_name", "high", "name", detect.snippet(tool))
            )
        if p.cross_server_reference and mcp is not None:
            known: dict[str, set[str]] = {s: set() for s in (getattr(mcp, "servers", {}) or {})}
            try:
                from aegis.mcp.service import get_service

                svc = get_service()
                if svc is not None:
                    for s, tools in svc.pins.pinned_tools().items():
                        if s in known:
                            known[s] |= tools
            except Exception:
                pass
            for path, text in texts:
                findings += detect.cross_reference(text, known, server, path)

        degraded = False
        sem_meta: dict[str, Any] = {}
        if p.semantic and desc and rt is not None and getattr(rt, "semantic", None) is not None:
            timeout = max(0.05, (cfg.timeout_ms - 50) / 1000.0)
            try:
                res = await asyncio.wait_for(rt.semantic.injection_score(desc), timeout)
                sem_meta = {
                    "semantic_score": round(float(res.score), 3),
                    "semantic_model": res.model,
                    "semantic_degraded": bool(res.degraded),
                }
                threshold = cfg.threshold if cfg.threshold is not None else 0.9
                if res.degraded:
                    degraded = (
                        True  # heuristic fallback: recorded, not counted (deterministic leg rules)
                    )
                elif res.score >= threshold:
                    findings.append(
                        detect.ToolFinding(
                            "sem.injection_score",
                            "high",
                            "description",
                            f"score {res.score:.2f} >= {threshold}",
                        )
                    )
            except TimeoutError:
                degraded = True
                sem_meta = {"semantic_error": "timeout"}
            except Exception as e:
                degraded = True
                sem_meta = {"semantic_error": type(e).__name__}

        score = detect.poison_score(findings)
        if not findings:
            return None
        rules = sorted({f.rule for f in findings})
        contract_findings = [
            Finding(
                control_id=self.id,
                detector=f"mcp.{f.rule}",
                category="mcp",
                severity=f.severity,  # type: ignore[arg-type]
                score=float(detect.SEVERITY_SCORE.get(f.severity, 0)),
                excerpt=_mask(rt, f.evidence),
                meta={"path": f.path},
            )
            for f in findings
        ]
        pin = interaction.meta.get("mcp.pin") or {}
        approved_by = str(pin.get("approved_by") or "")
        if (
            score >= p.score_threshold
            and approved_by.startswith("override:")
            and pin.get("status") == "match"
        ):
            return self.decide(
                cfg,
                action="log",
                score=float(score),
                findings=contract_findings,
                reason=f"tool poisoning indicators (score {score}) - admin override by "
                f"{approved_by.split(':', 1)[1]}",
                degraded=degraded,
                meta={"rules": rules, **sem_meta},
            )
        if score >= p.score_threshold:
            idx = interaction.meta.get("mcp.list_index")
            path = f"result.tools[{idx}]" if isinstance(idx, int) else "tool"
            action = cfg.action
            kw: dict[str, Any] = {}
            if action in ("redact", "allow"):
                kw["mutations"] = [Mutation(op="remove", path=path, reason="poisoned tool dropped")]
            if action == "require_approval":
                kw["approval"] = ApprovalDraft(
                    kind="mcp_pin",
                    action_type="mcp.repin",
                    title=f"Approve flagged MCP tool {server}.{tool}",
                    summary=f"tool poisoning indicators (score {score}): {', '.join(rules)}",
                    resource=f"mcp:{server}.{tool}",
                    labels={"reason": "poisoned", "server": server},
                    payload={"server": server, "tool": tool, "rules": rules},
                )
            excerpt = next(
                (f.evidence for f in findings if f.severity == "high"), findings[0].evidence
            )
            return self.decide(
                cfg,
                action=action,
                score=float(score),
                findings=contract_findings,
                reason=(
                    f"tool poisoning indicators (score {score}): {', '.join(rules)} - "
                    f"{_mask(rt, excerpt)}"
                ),
                degraded=degraded,
                meta={"rules": rules, "dropped": action != "log", **sem_meta},
                **kw,
            )
        return self.decide(
            cfg,
            action="log",
            score=float(score),
            findings=contract_findings,
            reason=f"low-confidence poisoning indicators (score {score}): {', '.join(rules)}",
            degraded=degraded,
            meta={"rules": rules, **sem_meta},
        )


CONTROLS = [McpPoisoning()]
