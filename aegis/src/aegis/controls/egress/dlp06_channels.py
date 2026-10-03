"""DLP-06 Exfil-channel neutralization (md images/links, HTML beacons, ANSI) — deterministic.

Surfaces `model.response`, `tool.output`, `mcp.result` (+ `egress.response`, Addendum A-42
[could]). Findings carry explicit replacements, e.g. `[image removed by Aegis: exfil.test]`.
"""

from __future__ import annotations

from collections import Counter

from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Finding
from aegis.egress import compat
from aegis.egress.channels import find_channels
from aegis.egress.params import Dlp06Params, effective_params
from aegis.egress.policyview import destinations, profile_for, snapshot_for


class ExfilChannelNeutralizer(BaseControl):
    id, family = "DLP-06", "DLP"
    name, kind = "Exfil-channel neutralization (md images/links, ANSI)", "deterministic"
    applies_to = AppliesTo(surfaces={"model.response", "tool.output", "mcp.result",
                                     "egress.response"})
    owasp = ["LLM10:2026", "LLM02:2026", "ASI01"]
    priority = 100

    async def evaluate(self, ctx, interaction, cfg):
        snap = snapshot_for(ctx)
        profile = await profile_for(ctx, snap)
        P = effective_params(Dlp06Params, cfg, profile, control_id=self.id)
        allowed = list(destinations(snap).allowed_link_domains or []) + list(P.extra_allowed_domains)
        findings: list[Finding] = []
        for i, seg in enumerate(interaction.segments):
            if not seg.redactable or not seg.text:
                continue
            for s in find_channels(seg.text, allowed, P):
                host = s.meta.get("host")
                construct = s.meta.get("construct", "")
                findings.append(Finding(
                    control_id=self.id, detector=s.detector, category="exfil", entity="EXFIL_CHANNEL",
                    severity="high", segment_index=i, start=s.start, end=s.end,
                    excerpt=f"{construct} → {host}" if host else construct,
                    replacement=s.replacement, meta={"construct": construct, "host": host}))
        if not findings:
            return None
        counts = Counter(f.meta["construct"] for f in findings)
        hosts = sorted({f.meta["host"] for f in findings if f.meta.get("host")})
        reason = "neutralized " + ", ".join(f"{n} {k}{'s' if n > 1 else ''}"
                                            for k, n in counts.items())
        if hosts:
            reason += f" ({', '.join(hosts[:3])})"
        for f in findings:
            compat.inc_metric("aegis_exfil_hits_total", {"channel": f.detector.split(".", 1)[-1]})
        return self.decide(cfg, action=cfg.action, reason=reason, findings=findings,
                           meta={"constructs": dict(counts), "hosts": hosts, "profile": profile})


CONTROLS = [ExfilChannelNeutralizer()]
