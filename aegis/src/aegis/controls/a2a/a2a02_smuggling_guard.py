"""A2A-02 Inter-agent smuggling & delegation guard (ASI07, ASI01, ASI08).

Peer agents are untrusted. On ``a2a.result`` (and on ``a2a.message`` that arrives *from* a peer)
every text part is scanned with the INJ-01 engine (``aegis.injection`` normalize + signatures:
homoglyphs, zero-width / tag-char smuggling, base64 / hex layers, hidden HTML / markdown
comments) and the INJ-02 cascade score (``rt.semantic`` with the local signature heuristic as
fallback):

* score >= ``block_threshold``         -> ``block`` (the reply never reaches the agent);
* score >= ``threshold``               -> ``injection_action`` (default ``redact`` = the injected
  spans are replaced with ``[AEGIS-QUARANTINE: ...]``, the rest of the reply is delivered);
* exfil links (markdown images / URLs with a query string to hosts that are neither the
  peer, an internal domain nor ``allowed_link_hosts``) -> stripped (``exfil_action``).

On ``a2a.message`` the delegation chain is bounded: ``X-Aegis-Hop`` (hops already taken) must
stay below ``max_hops`` and the chain (``X-Aegis-Chain`` + the caller) must not revisit the
target peer or any agent (loop) -> ``block``.

``on_complete`` of a delivered peer exchange marks the session **untrusted** (EXE-03 taint,
source ``a2a.<peer>``), so a later external send in a session that also read private data hits
the lethal-trifecta approval (``send-tainted``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from aegis.a2a import peers
from aegis.controls.injection._common import get_rt, mask
from aegis.core.paths import glob_match
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding
from aegis.injection.signatures import ScanOptions, scan_text

log = logging.getLogger(__name__)

_LINK = re.compile(r"!?\[[^\]\n]{0,200}\]\(\s*(https?://[^)\s]+)[^)]*\)|(https?://[^\s<>\"')\]]+)")
_ACTIONS = {"allow", "log", "redact", "require_approval", "block"}


class A2A02Params(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_hops: int = 3
    hop_action: str = "block"
    loop_action: str = "block"
    threshold: float = 0.6
    block_threshold: float = 0.9
    injection_action: str = "redact"
    semantic: bool = True
    semantic_timeout_s: float = 0.4
    replacement: str = "[AEGIS-QUARANTINE: peer instruction removed ({family})]"
    strip_exfil_links: bool = True
    exfil_action: str = "redact"
    exfil_replacement: str = "[AEGIS-QUARANTINE: external link removed]"
    allowed_link_hosts: list[str] = []
    scan_inbound_messages: bool = True


def _act(v: str, default: str) -> str:
    return v if v in _ACTIONS else default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class SmugglingGuard(BaseControl):
    id: ClassVar[str] = "A2A-02"
    family: ClassVar[str] = "A2A"
    name: ClassVar[str] = "Inter-agent smuggling & delegation guard"
    kind: ClassVar[str] = "hybrid"  # type: ignore[misc]
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"a2a.message", "a2a.result"})
    owasp: ClassVar[list[str]] = ["ASI07", "ASI01", "ASI08"]
    priority: ClassVar[int] = 45

    def _params(self, cfg: Any) -> A2A02Params:
        try:
            return A2A02Params.model_validate(dict(getattr(cfg, "params", None) or {}))
        except Exception:
            log.error("A2A-02 invalid params - using defaults")
            return A2A02Params()

    async def on_complete(self, ctx: Any, interaction: Any, verdict: Any, outcome: Any,
                          cfg: Any) -> None:
        if interaction.surface != "a2a.message" or getattr(ctx, "dry_run", False) \
                or getattr(ctx, "source", None) == "selftest":
            return
        if getattr(outcome, "status_code", 0) >= 400 or getattr(outcome, "error", None):
            return
        try:
            from aegis.actions import taint

            taint.mark(ctx.session_id, "untrusted",
                       f"a2a.{peers.peer_from_interaction(interaction) or 'peer'}")
        except Exception:
            log.debug("A2A-02 taint mark failed", exc_info=True)

    async def evaluate(self, ctx: Any, interaction: Any, cfg: Any) -> Decision | None:
        try:
            return await self._evaluate(ctx, interaction, cfg)
        except Exception:
            log.exception("A2A-02 internal error (fail closed)")
            return Decision(action="block", control_id=self.id, degraded=True,
                            reason="A2A-02 internal error (fail closed)", severity="high",
                            owasp=list(self.owasp))

    # ------------------------------------------------------------ delegation chain
    def _chain(self, ctx: Any, i: Any, cfg: Any, p: A2A02Params) -> Decision | None:
        meta = (i.meta or {}).get("a2a") or {}
        if not isinstance(meta, dict):
            return None
        hop = _int(meta.get("hop"), 0)
        target = peers.peer_from_interaction(i)
        chain = [str(c) for c in (meta.get("chain") or []) if str(c)]
        caller = getattr(getattr(ctx, "identity", None), "agent_id", None)
        path = chain + ([caller] if caller and (not chain or chain[-1] != caller) else [])
        shown = " → ".join([*path, target or "?"])
        if hop + 1 > p.max_hops:
            return self._deny(cfg, _act(p.hop_action, "block"),
                              f"delegation depth {hop + 1} exceeds max_hops {p.max_hops} "
                              f"({shown})", "a2a.hop_limit", hop=hop, max_hops=p.max_hops,
                              chain=path)
        seen: set[str] = set()
        for a in path:
            if a in seen:
                return self._deny(cfg, _act(p.loop_action, "block"),
                                  f"delegation loop: '{a}' appears twice ({shown})",
                                  "a2a.loop", chain=path)
            seen.add(a)
        if target and target in seen:
            return self._deny(cfg, _act(p.loop_action, "block"),
                              f"delegation loop: peer '{target}' is already in the chain "
                              f"({shown})", "a2a.loop", chain=path)
        return None

    def _deny(self, cfg: Any, action: str, reason: str, detector: str, **meta: Any) -> Decision:
        f = Finding(control_id=self.id, detector=detector, category="loop", severity="high",
                    meta=meta)
        return self.decide(cfg, action=action, reason=reason, findings=[f],
                           meta={"a2a": {"check": detector, **meta}})

    # ------------------------------------------------------------ content scan
    def _allowed_hosts(self, ctx: Any, i: Any, p: A2A02Params) -> list[str]:
        hosts = list(p.allowed_link_hosts)
        snap = getattr(ctx, "policy", None)
        try:
            hosts += list(snap.doc.destinations.internal_domains or [])
        except Exception:
            pass
        peer_id = peers.peer_from_interaction(i)
        if peer_id and snap is not None:
            peer = peers.peers_from_snapshot(snap).get(peer_id)
            if peer is not None and peer.host:
                hosts.append(peer.host)
        if i.destination is not None and i.destination.host:
            hosts.append(i.destination.host)
        return hosts

    async def _score(self, rt: Any, text: str, p: A2A02Params) -> tuple[float, str, bool]:
        """(INJ-02 cascade score, model, degraded). Degraded = heuristic fallback, models off."""
        if not p.semantic or rt is None or getattr(rt, "semantic", None) is None:
            return 0.0, "none", True
        try:
            from aegis.injection import cascade

            s = await asyncio.wait_for(
                cascade.score_text(rt, text, trusted=False, timeout_s=p.semantic_timeout_s),
                p.semantic_timeout_s + 0.2)
            return float(s.score), str(s.model), bool(s.degraded)
        except Exception:
            return 0.0, "error", True

    async def _evaluate(self, ctx: Any, i: Any, cfg: Any) -> Decision | None:
        p = self._params(cfg)
        meta = (i.meta or {}).get("a2a") or {}
        if i.surface == "a2a.message":
            d = self._chain(ctx, i, cfg, p)
            if d is not None:
                return d
            headers = {str(k).lower() for k in (i.headers or {})}
            from_peer = "x-a2a-sender" in headers or (isinstance(meta, dict)
                                                      and meta.get("from_peer"))
            if not (from_peer and p.scan_inbound_messages):
                return None
        if not i.segments:
            return None

        from aegis.controls.injection.inj01_signatures import quarantine_spans

        rt = get_rt()
        opts = ScanOptions()
        hosts = self._allowed_hosts(ctx, i, p)
        findings: list[Finding] = []
        max_score = 0.0
        block = False
        families: list[str] = []
        exfil = 0
        signals: list[dict[str, Any]] = []
        for idx, seg in enumerate(i.segments):
            text = seg.text or ""
            if not text.strip():
                continue
            res = scan_text(text, trust="untrusted", opts=opts)
            sem, model, degraded = await self._score(rt, text, p)
            score = max(res.score, sem)
            # a degraded (heuristic-only) semantic score can quarantine but never block alone
            block_score = max(res.score, 0.0 if degraded else sem)
            signals.append({"segment": idx, "signature": res.score, "semantic": sem,
                            "model": model, "degraded": degraded})
            max_score = max(max_score, score)
            if score >= p.threshold:
                spans = quarantine_spans(res, text) if res.hits or res.norm.hidden else []
                if not spans:
                    spans = [(0, len(text), next(iter(res.families), "semantic"))]
                if block_score >= p.block_threshold:
                    block = True
                for a, b, fam in spans:
                    if fam not in families:
                        families.append(fam)
                    rep = p.replacement.format(family=fam) if "{family}" in p.replacement \
                        else p.replacement
                    findings.append(Finding(
                        control_id=self.id, detector=f"a2a.inj.{fam}", category="injection",
                        entity="PROMPT_INJECTION", severity="high", score=round(score, 4),
                        segment_index=idx, start=a, end=b, excerpt=mask(rt, text[a:b], 80),
                        replacement=rep, meta={"family": fam}))
            if p.strip_exfil_links:
                taken = [(f.start, f.end) for f in findings if f.segment_index == idx]
                for m in _LINK.finditer(text):
                    url = m.group(1) or m.group(2) or ""
                    host = urlsplit(url).hostname or ""
                    image = m.group(0).startswith("!")
                    if any(glob_match(h, host) for h in hosts):
                        continue
                    if not (image or "?" in url):
                        continue  # plain link without a data channel: leave it
                    a, b = m.start(), m.end()
                    if any(x <= a < y or x < b <= y for x, y in taken if x is not None
                           and y is not None):
                        continue
                    exfil += 1
                    findings.append(Finding(
                        control_id=self.id, detector="a2a.exfil_link", category="exfil",
                        severity="high", segment_index=idx, start=a, end=b,
                        excerpt=mask(rt, host, 80), replacement=p.exfil_replacement,
                        meta={"host": host, "image": image}))
        if not findings:
            return Decision(action="allow", control_id=self.id, score=round(max_score, 4),
                            threshold=p.threshold, severity=cfg.severity,
                            owasp=list(cfg.owasp or self.owasp),
                            reason=f"peer content clean (score {max_score:.2f} < "
                                   f"{p.threshold:.2f})",
                            meta={"a2a": {"check": "scan", "signals": signals}})
        n_inj = len(findings) - exfil
        parts = []
        if n_inj:
            parts.append(f"{n_inj} injected span(s) [{', '.join(families)}] "
                         f"score {max_score:.2f}")
        if exfil:
            parts.append(f"{exfil} exfil link(s)")
        where = "peer reply" if i.surface == "a2a.result" else "peer-originated message"
        if block:
            action = "block"
            reason = f"Blocked {where}: " + "; ".join(parts) + f" >= {p.block_threshold:.2f}"
        else:
            action = _act(p.injection_action if n_inj else p.exfil_action, "redact")
            verb = "Quarantined" if action == "redact" else "Flagged"
            reason = f"{verb} in {where}: " + "; ".join(parts)
        d = self.decide(cfg, action=action, reason=reason, score=round(max_score, 4),
                        findings=findings[:64],
                        meta={"a2a": {"check": "scan", "signals": signals,
                                      "families": families, "exfil_links": exfil}})
        d.threshold = p.block_threshold if block else p.threshold
        return d


CONTROLS = [SmugglingGuard()]
