"""DLP-04 Tool-arg / egress exfiltration scan (hybrid; semantic leg optional).

Surfaces `tool.input`, `mcp.call`, `egress.request`. URLs in the request (and in Bash
commands) are scored for exfil channels; encoded tool-arg blobs to third parties are decoded
and re-scanned. `score >= threshold` → `cfg.action` (block); lower scores → `log`.
"""

from __future__ import annotations

import logging
from typing import Any

from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Finding
from aegis.egress import compat
from aegis.egress.exfil import ExfilHit, analyze_url, extract_urls, mask_url, scan_arg_blobs
from aegis.egress.params import Dlp04Params, effective_params
from aegis.egress.policyview import destinations, profile_for, snapshot_for

log = logging.getLogger(__name__)
SEMANTIC_RULE = "Does this tool call smuggle data to an external endpoint?"


class EgressExfilScan(BaseControl):
    id, family, name, kind = "DLP-04", "DLP", "Tool-arg / egress exfiltration scan", "hybrid"
    applies_to = AppliesTo(surfaces={"tool.input", "mcp.call", "egress.request"})
    owasp = ["LLM02:2026", "MCP10:2025", "ASI02", "ASI01"]
    priority = 100

    async def evaluate(self, ctx, interaction, cfg):
        snap = snapshot_for(ctx)
        profile = await profile_for(ctx, snap)
        P = effective_params(Dlp04Params, cfg, profile, control_id=self.id)
        thr = float(cfg.threshold) if cfg.threshold is not None else P.default_threshold
        dest = destinations(snap)
        allowlist = list(dest.egress_allowlist or [])
        rt = compat.runtime_or_none()
        hits: list[ExfilHit] = []
        local = interaction.destination.dest_class == "local"
        if not local or P.scan_local_tool_urls:
            for ref in extract_urls(interaction, P)[:32]:
                for h in analyze_url(ref.url, params=P, allowlist=allowlist,
                                     in_shell=ref.in_shell, rt=rt):
                    h.path = ref.path
                    hits.append(h)
        hits += scan_arg_blobs(interaction, P, rt)
        if not hits:
            return None
        hits.sort(key=lambda h: -h.score)
        score = hits[0].score
        semantic_meta: dict[str, Any] | None = None
        if P.semantic_judge and 0.5 <= score < thr and rt is not None:
            score, semantic_meta = await self._judge(rt, interaction, hits, score)
        action = cfg.action if score >= thr else "log"
        findings = [self._finding(h, thr) for h in hits[:16]]
        for h in hits:
            compat.inc_metric("aegis_exfil_hits_total", {"channel": h.channel})
        top = hits[0]
        reason = top.detail + (f" ({top.host})" if top.host and top.host not in top.detail else "")
        meta: dict[str, Any] = {
            "channels": sorted({h.channel for h in hits}),
            "hosts": sorted({h.host for h in hits if h.host}),
            "decoded_kinds": sorted({k for h in hits for k in h.decoded_kinds}),
            "profile": profile,
        }
        if semantic_meta:
            meta["semantic"] = semantic_meta
        return self.decide(cfg, action=action, reason=reason, score=round(score, 3),
                           findings=findings, meta=meta, threshold=thr)

    def _finding(self, h: ExfilHit, thr: float) -> Finding:
        excerpt = mask_url(h.url) if h.url else f"<arg {h.path or '?'}>"
        return Finding(control_id=self.id, detector=f"exfil.{h.channel}", category=h.category,
                       severity="high" if h.score >= thr else "low", score=h.score,
                       excerpt=excerpt[:160],
                       meta={"channel": h.channel, "host": h.host, "path": h.path,
                             "decoded_kinds": list(h.decoded_kinds), "detail": h.detail})

    async def _judge(self, rt, interaction, hits: list[ExfilHit], score: float):
        """META-15: gray-zone semantic leg on a masked summary (never raw values)."""
        summary = (f"tool={interaction.tool_name or interaction.surface}; "
                   + "; ".join(f"{h.channel}: {h.detail[:80]} -> "
                               f"{mask_url(h.url) if h.url else h.path}" for h in hits[:6]))
        try:
            res = await rt.semantic.judge(SEMANTIC_RULE, summary)
        except Exception:
            return score, {"error": "judge unavailable"}
        meta = {"score": res.score, "model": res.model, "degraded": res.degraded}
        if not res.degraded and res.score >= 0.7:
            return max(score, 1.0), meta
        return score, meta

    # BaseControl.decide passes threshold=cfg.threshold; override to report the effective one
    def decide(self, cfg, *, action=None, reason="", score=None, findings=None, **kw):
        thr = kw.pop("threshold", None)
        d = super().decide(cfg, action=action, reason=reason, score=score, findings=findings, **kw)
        if thr is not None:
            d.threshold = thr
        return d


CONTROLS = [EgressExfilScan()]
