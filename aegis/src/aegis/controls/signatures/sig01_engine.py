"""SIG-01 · External exploit-signature engine (signed threat feed).

Evaluates the active, verified feed snapshot (`rt.feed`) for the interaction's surface. Every
signature carries its own action; the strongest enforce-mode action wins (contract precedence).
`experimental` signatures (or `feeds.overrides.<id>.mode: monitor`) only log ("would have ...").
Redact hits locate spans per segment (`redact_scope: match`), redact whole segments
(`segment`), or drop the MCP tool (`tool`, A-16). Decisions carry `meta.feed_serial`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Literal

from aegis.controls.resilience._failsafe import internal_error_decision, is_fail_closed
from aegis.controls.signatures import _common as C
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Mutation
from aegis.feed.matchers.core import owasp_tags

log = logging.getLogger(__name__)

_MSG_INDEX = re.compile(r"^messages\[(\d+)\]")
THREAD_THRESHOLD = 64 * 1024


class SIG01Params(C.Params):
    history_scan: bool = False
    max_scan_chars: int = 262_144
    semantic_max_chars: int = 8192
    response_require_approval_as: Literal["allow", "log", "redact", "block"] = "log"
    record_hits: bool = True


def select_segments(interaction: Any, history_scan: bool) -> list[tuple[int, Any]]:
    """[(index into interaction.segments, segment)]. On `model.request` only the newest message
    (+ non-`messages` user segments such as Ollama `prompt`) unless `history_scan`."""
    segs = list(getattr(interaction, "segments", None) or [])
    indexed = list(enumerate(segs))
    if history_scan or getattr(interaction, "surface", None) != "model.request":
        return indexed
    newest = -1
    for _, s in indexed:
        mt = _MSG_INDEX.match(str(getattr(s, "path", "")))
        if mt:
            newest = max(newest, int(mt.group(1)))
    out = []
    for idx, s in indexed:
        path = str(getattr(s, "path", ""))
        mt = _MSG_INDEX.match(path)
        if mt:
            if int(mt.group(1)) == newest:
                out.append((idx, s))
        elif getattr(s, "role", "user") == "user":
            out.append((idx, s))
    return out


def _resolve(hit: dict, ov: Any, direction: str | None, p: SIG01Params) -> tuple[str, str] | None:
    """(action, mode) after policy override + response-direction downgrade; None = dropped."""
    action, mode = str(hit.get("action", "block")), str(hit.get("mode", "enforce"))
    if ov is not None:
        if ov.enabled is False or ov.mode == "off":
            return None
        if ov.mode == "monitor":
            mode = "monitor"
        elif ov.mode == "enforce":
            mode = "enforce"
        if ov.action:
            action = str(ov.action)
    if direction == "in" and action == "require_approval":
        action = p.response_require_approval_as
    return action, mode


def _locate(c: Any, surface: str, text: str) -> list[tuple[int, int]]:
    from aegis.feed.matchers import Event

    try:
        ev = Event(surface=surface, text=text, all_spans=True)
        evidence = c.match(ev) or []
    except Exception:
        return []
    spans = []
    for e in evidence:
        s, t = e.get("start"), e.get("end")
        if isinstance(s, int) and isinstance(t, int) and 0 <= s < t <= len(text):
            spans.append((s, t))
    return spans


class ExploitSignatureEngine(BaseControl):
    id, family, name, kind = "SIG-01", "SIG", "External exploit-signature engine", "deterministic"
    applies_to = AppliesTo()
    owasp = ["LLM04:2026", "ASI04", "ASI05", "MCP04:2025", "MCP05:2025"]
    priority = 100

    async def evaluate(self, ctx: Any, interaction: Any, cfg: Any) -> Decision | None:
        surface = str(getattr(interaction, "surface", ""))
        if surface == "config.change":
            return None
        feed = C.feed()
        if feed is None or not hasattr(feed, "scan"):
            return None
        snap = (
            feed.snapshot_for(ctx)
            if hasattr(feed, "snapshot_for")
            else getattr(feed, "active", None)
        )
        if snap is None or not snap.by_surface.get(surface):
            return None
        p = C.params(self.id, SIG01Params, cfg)
        selected = select_segments(interaction, p.history_scan)
        segs = [s for _, s in selected]
        size = sum(len(getattr(s, "text", "") or "") for s in segs)
        if size > THREAD_THRESHOLD:
            hits = await asyncio.to_thread(
                feed.scan, interaction, ctx=ctx, segments=segs, snapshot=snap
            )
        else:
            hits = feed.scan(interaction, ctx=ctx, segments=segs, snapshot=snap)
        degraded = any(h.get("degraded") for h in hits)
        failed = [str(h.get("signature_id")) for h in hits if h.get("degraded")]
        hits = [h for h in hits if not h.get("degraded")]
        if not hits:
            if not degraded:
                return None
            # ASI08: an erroring signature means this surface was not fully checked -> honour
            # fail_mode (closed: degraded block naming the failed signatures; else degraded allow).
            d = internal_error_decision(
                self.id,
                cfg,
                f"signature evaluation error: {', '.join(failed)[:160]}",
                what="signature evaluation error",
            )
            d.meta["failed_signatures"] = failed
            return d
        ovs = C.overrides(ctx)
        resolved: list[dict] = []
        for h in hits:
            r = _resolve(h, ovs.get(h["signature_id"]), getattr(interaction, "direction", None), p)
            if r is None:
                continue
            resolved.append({**h, "action": r[0], "mode": r[1]})
        if not resolved:
            return None
        if p.record_hits and not getattr(ctx, "dry_run", False) and hasattr(feed, "record_hits"):
            try:
                feed.record_hits(resolved, surface=surface)
            except Exception:
                log.debug("record_hits failed", exc_info=True)
        for h in resolved:
            log.info(
                "signature hit id=%s surface=%s action=%s mode=%s",
                h["signature_id"],
                surface,
                h["action"],
                h["mode"],
            )
        d = self._decide(cfg, interaction, snap, selected, resolved, degraded)
        if (
            failed
            and is_fail_closed(cfg)
            and d.mode != "monitor"
            and (C.ACTION_PRECEDENCE.get(d.action, 0) < C.ACTION_PRECEDENCE["block"])
        ):
            # ASI08: other signatures matched weakly, but some errored -> fail-closed wins.
            d.action = "block"
            d.reason = f"{d.reason}; {len(failed)} signature(s) errored (fail-closed)"
            d.meta["failed_signatures"] = failed
        return d

    def _decide(
        self,
        cfg: Any,
        interaction: Any,
        snap: Any,
        selected: list[tuple[int, Any]],
        hits: list[dict],
        degraded: bool,
    ) -> Decision:
        enforce = [h for h in hits if h["mode"] == "enforce" and h["action"] != "allow"]
        ranked = sorted(
            enforce or hits,
            key=lambda h: (
                -C.ACTION_PRECEDENCE.get(h["action"], 0),
                -C.SEVERITY_RANK.get(str(h.get("severity")), 0),
                h["signature_id"],
            ),
        )
        primary = ranked[0]
        cves = [a for a in primary.get("aliases") or [] if str(a).startswith("CVE-")]
        reason = " · ".join([primary["signature_id"], *(cves[:1]), str(primary.get("title", ""))])
        owasp = sorted({t for h in hits for t in owasp_tags(h.get("tags") or [])}) or list(
            getattr(cfg, "owasp", None) or self.owasp
        )
        findings: list[Finding] = []
        mutations: list[Mutation] = []
        surface = str(getattr(interaction, "surface", ""))
        for h in hits:
            ev = h.get("evidence") or []
            snippet = next(
                (e.get("snippet") or e.get("url") for e in ev if e.get("snippet") or e.get("url")),
                None,
            )
            findings.append(
                Finding(
                    control_id=self.id,
                    detector=h["signature_id"],
                    category="signature",
                    severity=h.get("severity", "medium"),
                    excerpt=C.mask(snippet, 120),
                    meta={
                        "signature_id": h["signature_id"],
                        "title": h.get("title"),
                        "aliases": h.get("aliases") or [],
                        "tags": h.get("tags") or [],
                        "mode": h["mode"],
                        "action": h["action"],
                        "evidence": C.sanitize_evidence(ev),
                    },
                )
            )
        final = primary["action"] if enforce else "log"
        if enforce and final == "redact":
            red_findings, red_mut = self._redactions(
                snap, surface, selected, [h for h in enforce if h["action"] == "redact"]
            )
            findings.extend(red_findings)
            mutations.extend(red_mut)
        sig_meta = [
            {
                "id": h["signature_id"],
                "action": h["action"],
                "mode": h["mode"],
                "severity": h.get("severity"),
                "title": h.get("title"),
                "aliases": h.get("aliases") or [],
            }
            for h in hits
        ]
        meta: dict[str, Any] = {
            "signatures": sig_meta,
            "feed_serial": snap.serial,
            "feed_version": snap.version,
        }
        if not enforce:
            meta["would_action"] = C.strongest([h["action"] for h in hits])
            return Decision(
                action="log",
                control_id=self.id,
                mode="monitor",
                reason="monitor: " + reason,
                severity=C.max_severity([str(h.get("severity", "medium")) for h in hits]),
                findings=findings,
                owasp=owasp,
                degraded=degraded,
                meta=meta,
            )
        return Decision(
            action=final,  # type: ignore[arg-type]
            control_id=self.id,
            reason=reason,
            severity=C.max_severity([str(h.get("severity", "medium")) for h in enforce]),  # type: ignore[arg-type]
            findings=findings,
            mutations=mutations,
            owasp=owasp,
            degraded=degraded,
            meta=meta,
        )

    def _redactions(
        self, snap: Any, surface: str, selected: list[tuple[int, Any]], hits: list[dict]
    ) -> tuple[list[Finding], list[Mutation]]:
        findings: list[Finding] = []
        mutations: list[Mutation] = []
        for h in hits:
            c = snap.sigs.get(h["signature_id"])
            if c is None:
                continue
            scope = c.redact_scope
            repl = c.redact_with if c.redact_with is not None else f"[REDACTED:{c.id}]"
            if scope == "tool" and surface == "mcp.list":
                mutations.append(
                    Mutation(op="remove", path="tool", reason=f"{c.id}: {h.get('title', '')}"[:200])
                )
                continue
            for idx, seg in selected:
                if not getattr(seg, "redactable", True):
                    continue
                text = getattr(seg, "text", "") or ""
                if not text:
                    continue
                spans = _locate(c, surface, text)
                if not spans:
                    continue
                if scope in ("segment", "tool"):
                    spans = [(0, len(text))]
                for s, e in spans:
                    findings.append(
                        Finding(
                            control_id=self.id,
                            detector=c.id,
                            category="signature",
                            entity="SIGNATURE",
                            severity=h.get("severity", "medium"),
                            segment_index=idx,
                            start=s,
                            end=e,
                            replacement=repl,
                            meta={
                                "signature_id": c.id,
                                "title": h.get("title"),
                                "aliases": h.get("aliases") or [],
                                "redact_scope": scope,
                            },
                        )
                    )
        return findings, mutations


CONTROLS = [ExploitSignatureEngine()]
