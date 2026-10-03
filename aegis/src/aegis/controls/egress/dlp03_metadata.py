"""DLP-03 Metadata stripping & generalization (deterministic, priority 90).

Surfaces `model.request`, `mcp.call`, `egress.request`. Produces:
- header mutations (deny/allow globs per wire kind, UA replacement, egress credential isolation),
- body mutations (`metadata.user_id` & co. pseudonymized; sanitized base64 media),
- text findings (user paths, internal hosts, private IPs, git identities, Claude Code context,
  learned identifiers) — `replacement=None` => vault placeholder, else explicit generalization.
Returns None when nothing is found, so a clean request is forwarded byte-identical.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from aegis.core.protocols import BaseControl
from aegis.core.types import ACTION_PRECEDENCE, AppliesTo, Finding, Mutation
from aegis.egress import claude_code as cc
from aegis.egress import compat, identifiers
from aegis.egress.bodyfields import plan_body_fields
from aegis.egress.cache import TEXT_CACHE
from aegis.egress.headers import plan_headers
from aegis.egress.params import Dlp03Params, effective_params, params_hash
from aegis.egress.policyview import destinations, profile_for, snapshot_for
from aegis.egress.textmeta import (
    MetaSpan,
    find_learned,
    learnable,
    mask_excerpt,
    resolve_overlaps,
    scan_text,
    usable_identifier,
)

log = logging.getLogger(__name__)

_WIRES = {"anthropic", "openai", "ollama"}


def header_kind(interaction: Any, snap: Any) -> str:
    if interaction.surface == "mcp.call":
        return "mcp"
    if interaction.surface == "egress.request":
        return "egress"
    wire = (interaction.meta or {}).get("wire")
    if wire in _WIRES:
        return str(wire)
    prov = interaction.destination.provider
    try:
        if snap is not None and prov and prov in snap.doc.providers:
            return str(snap.doc.providers[prov].wire)
    except Exception:
        pass
    if interaction.destination.name in _WIRES:
        return str(interaction.destination.name)
    hdrs = {k.lower() for k in interaction.headers}
    if "anthropic-version" in hdrs or cc.is_claude_code_headers(interaction.headers):
        return "anthropic"
    return "openai"


def _max_action(actions: list[str]) -> str | None:
    if not actions:
        return None
    return max(actions, key=lambda a: ACTION_PRECEDENCE.get(a, 0))


class MetadataStrip(BaseControl):
    id, family, name, kind = "DLP-03", "DLP", "Metadata stripping & generalization", "deterministic"
    applies_to = AppliesTo(surfaces={"model.request", "mcp.call", "egress.request"})
    owasp = ["LLM02:2026", "LLM08:2026", "MCP10:2025"]
    priority = 90

    async def evaluate(self, ctx, interaction, cfg):
        snap = snapshot_for(ctx)
        profile = await profile_for(ctx, snap)
        P = effective_params(Dlp03Params, cfg, profile, control_id=self.id)
        dest = destinations(snap)
        dclass = interaction.destination.dest_class
        findings: list[Finding] = []
        mutations: list[Mutation] = []
        actions: list[str] = []
        meta: dict[str, Any] = {"headers_removed": [], "headers_set": [], "body_fields": [],
                                "media": [], "identifiers_learned": 0, "claude_code": False,
                                "profile": profile}
        is_cc = cc.is_claude_code(interaction)
        meta["claude_code"] = is_cc

        # ---- structural: headers, body fields, media (never toward local destinations)
        if dclass != "local":
            kind = header_kind(interaction, snap)
            plan = plan_headers(interaction.headers or {}, kind=kind, params=P.headers,
                                host=interaction.destination.host)
            for name in plan.remove:
                mutations.append(Mutation(target="header", op="remove", path=name,
                                          reason="DLP-03 header policy"))
            for name, value in plan.set.items():
                mutations.append(Mutation(target="header", op="set", path=name, value=value,
                                          reason="DLP-03 header policy"))
            meta["headers_removed"] = list(plan.remove)
            meta["headers_set"] = list(plan.set)
            meta["header_kind"] = kind
            body_muts = plan_body_fields(interaction.raw, P.body_fields,
                                         pseudonymize_session=P.claude_code.pseudonymize_session_id)
            mutations += body_muts
            meta["body_fields"] = [m.path for m in body_muts]
            if P.media.enabled and interaction.raw is not None:
                m_muts, m_findings, m_actions, m_meta = await self._media(interaction, P)
                mutations += m_muts
                findings += m_findings
                actions += m_actions
                meta["media"] = m_meta
            if mutations:
                actions.append(cfg.action)

        # ---- text (gated by destinations.matrix.INTERNAL[dest_class])
        cell = str(dest.matrix.get("INTERNAL", {}).get(dclass, "redact"))
        agent_id = getattr(getattr(ctx, "identity", None), "agent_id", None)
        exempt = compat.any_glob(P.exempt_agents, agent_id)
        if cell != "allow" and not exempt and (P.text.enabled or (is_cc and P.claude_code.enabled)):
            style = P.text.style.get(dclass, "placeholder")
            t_findings, learned = self._text(ctx, interaction, P, dest, style, is_cc)
            meta["identifiers_learned"] = learned
            if t_findings:
                findings += t_findings
                actions.append(cell)

        action = _max_action(actions)
        if action is None or (not findings and not mutations):
            return None
        meta["entities"] = sorted({f.entity for f in findings if f.entity})
        self._metrics(meta, findings)
        reason = self._reason(meta, findings)
        return self.decide(cfg, action=action, reason=reason, findings=findings,
                           mutations=mutations, meta=meta)

    # ------------------------------------------------------------------ text
    def _text(self, ctx, interaction, P: Dlp03Params, dest, style: str, is_cc: bool
              ) -> tuple[list[Finding], int]:
        session_id = getattr(ctx, "session_id", None) or "default"
        known = identifiers.get(session_id) if P.text.learn_identifiers else []
        doms = list(dest.internal_domains or [])
        phash = params_hash(P)
        dkey = hashlib.sha256("|".join(doms).encode()).hexdigest()[:8]
        per_seg: list[tuple[int, list[MetaSpan]]] = []
        seg_keys: dict[int, str] = {}
        candidates: list[str] = []
        for i, seg in enumerate(interaction.segments):
            if not seg.redactable or not seg.text:
                continue
            sha = hashlib.sha256(seg.text.encode()).hexdigest()
            seg_keys[i] = sha
            key = (sha, phash, style, dkey, is_cc)
            spans = TEXT_CACHE.get(key)
            if spans is None:
                spans = scan_text(seg.text, internal_domains=doms, params=P.text, style=style,
                                  learned=False)
                if is_cc or "<system-reminder>" in seg.text:
                    spans = spans + cc.scan_segment(seg.text, P.claude_code, style=style)
                TEXT_CACHE.put(key, spans)
            if spans:
                per_seg.append((i, spans))
                candidates += learnable(spans, min_len=P.text.min_identifier_len,
                                        allow=P.text.user_allowlist)
        learned = 0
        if P.text.learn_identifiers and candidates:
            learned = identifiers.learn(session_id, candidates,
                                        max_identifiers=P.text.max_identifiers)
            known = identifiers.get(session_id)
        if P.text.learn_identifiers and known:
            idents = frozenset(i for i in known if usable_identifier(
                i, min_len=P.text.min_identifier_len, allow=P.text.user_allowlist))
            ikey = hashlib.sha256("\x00".join(sorted(idents)).encode()).hexdigest()[:16]
            seg_map = dict(per_seg)
            for i, seg in enumerate(interaction.segments):
                if not seg.redactable or not seg.text or not idents:
                    continue
                lkey = ("learned", seg_keys.get(i) or hashlib.sha256(seg.text.encode()).hexdigest(),
                        ikey, style)
                extra = TEXT_CACHE.get(lkey)
                if extra is None:
                    extra = find_learned(seg.text, idents, style=style)
                    TEXT_CACHE.put(lkey, extra)
                if extra:
                    seg_map[i] = seg_map.get(i, []) + extra
            per_seg = sorted(seg_map.items())
        findings: list[Finding] = []
        for i, spans in per_seg:
            for s in resolve_overlaps(list(spans)):
                f_meta: dict[str, Any] = {}
                if s.meta.get("block"):
                    f_meta["block"] = s.meta["block"]
                findings.append(Finding.model_construct(  # trusted values: skip validation (hot path)
                    control_id=self.id, detector=s.detector, category="metadata",
                    entity=s.entity, data_class=s.data_class,  # type: ignore[arg-type]
                    severity="low", score=s.score, segment_index=i, start=s.start, end=s.end,
                    excerpt=(mask_excerpt(s.entity, s.value) if not s.meta.get("block")
                             else f"[{s.meta['block']}]"),
                    replacement=s.replacement, meta=f_meta))
        return findings, learned

    # ------------------------------------------------------------------ media
    async def _media(self, interaction, P: Dlp03Params):
        try:
            from aegis.egress.metadata import scan_raw_media
        except Exception:  # pragma: no cover - media module optional
            return [], [], [], []
        try:
            return await scan_raw_media(interaction.raw, surface=interaction.surface,
                                        params=P.media, control_id=self.id)
        except Exception:
            log.exception("media scan failed surface=%s", interaction.surface)
            return [], [], [], []

    # ------------------------------------------------------------------ reporting
    @staticmethod
    def _reason(meta: dict[str, Any], findings: list[Finding]) -> str:
        parts: list[str] = []
        if meta["headers_removed"] or meta["headers_set"]:
            parts.append(f"{len(meta['headers_removed']) + len(meta['headers_set'])} headers")
        for p in meta["body_fields"]:
            parts.append(p.rsplit(".", 1)[-1])
        text_f = [f for f in findings if f.segment_index is not None]
        if text_f:
            parts.append(f"{len(text_f)} identifiers")
        if meta["media"]:
            parts.append(f"{len(meta['media'])} attachment{'s' if len(meta['media']) > 1 else ''}")
        return "metadata stripped: " + ", ".join(parts) if parts else "metadata stripped"

    @staticmethod
    def _metrics(meta: dict[str, Any], findings: list[Finding]) -> None:
        if meta["headers_removed"] or meta["headers_set"]:
            compat.inc_metric("aegis_metadata_stripped_total", {"kind": "header"},
                              len(meta["headers_removed"]) + len(meta["headers_set"]))
        if meta["body_fields"]:
            compat.inc_metric("aegis_metadata_stripped_total", {"kind": "body_field"},
                              len(meta["body_fields"]))
        n_text = sum(1 for f in findings if f.segment_index is not None)
        if n_text:
            compat.inc_metric("aegis_metadata_stripped_total", {"kind": "text"}, n_text)
        for m in meta["media"]:
            kind = {"jpeg": "image", "png": "image", "webp": "image", "gif": "image"}.get(
                str(m.get("format")), str(m.get("format") or "image"))
            compat.inc_metric("aegis_metadata_stripped_total", {"kind": kind})


CONTROLS = [MetadataStrip()]
