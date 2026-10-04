"""A2A-01 Peer identity & message integrity (ASI07, ASI03).

``a2a.message`` (agent -> peer, via ``POST /a2a/{peer}``):
* the target peer must be registered and enabled (``params.peers``) - unknown peers are denied
  with a typosquat hint when the id imitates a registered one;
* the calling agent must be in the peer's ``allowed_callers`` (mutual identity: who may talk to
  whom);
* the peer's agent card (fetched by the route) must match the registry (name, host, optional
  sha256 pin) - a forged / redirected card is denied;
* a message that arrives *from* a peer (``x-a2a-sender`` present) must carry a valid HMAC
  signature for the registered sender, be addressed to this gateway, be fresh (``ttl_s``) and
  use a never-seen nonce.

``a2a.result`` (peer -> agent): the reply must be signed by the peer the request went to,
addressed to this gateway, bound to the request nonce (``x-a2a-in-reply-to``), fresh and carry a
single-use nonce. Tampered, forged, stale, replayed or unsigned replies are blocked before the
agent sees them.

Without transport facts (``meta.a2a.transport != "gateway"``, e.g. ``/v1/guard`` or the policy
self-test) only the registry checks apply - signatures can only be verified on the gateway's own
A2A surface. Never raises: internal errors -> ``fail_mode`` via a degraded block.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from aegis.a2a import nonces, peers, signing
from aegis.core.paths import glob_match
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding

log = logging.getLogger(__name__)


class A2A01Params(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gateway_id: str = peers.DEFAULT_GATEWAY_ID
    peers: dict[str, Any] | list[Any] = {}
    unknown_peer_action: str = "block"
    caller_not_allowed_action: str = "block"
    require_signed_results: bool = True
    require_signed_inbound: bool = True
    ttl_s: float = 120.0
    verify_card: bool = True
    card_mismatch_action: str = "block"
    card_unavailable_action: str = "log"
    typosquat_distance: int = 2


_ACTIONS = {"allow", "log", "redact", "require_approval", "block"}


def _envelope_source(ctx: Any, i: Any) -> tuple[dict[str, str], Any]:
    """(x-a2a-* headers, exact body bytes). The gateway route stashes the full envelope (incl.
    signature + nonce) in ``ctx.state[signing.ENVELOPE_KEY][interaction.id]`` so it never lands
    in audited fields; ``/v1/guard`` callers may pass it in ``Interaction.headers``."""
    headers = {str(k).lower(): str(v) for k, v in (i.headers or {}).items()}
    state = getattr(ctx, "state", None) or {}
    stashed = (state.get(signing.ENVELOPE_KEY) or {}).get(getattr(i, "id", None) or "")
    if stashed:
        headers.update({str(k).lower(): str(v) for k, v in stashed.items()})
    return headers, getattr(i, "raw", None)


def _act(value: str, default: str = "block") -> str:
    return value if value in _ACTIONS else default


class PeerIdentity(BaseControl):
    id: ClassVar[str] = "A2A-01"
    family: ClassVar[str] = "A2A"
    name: ClassVar[str] = "Peer identity & message integrity"
    kind: ClassVar[str] = "deterministic"  # type: ignore[misc]
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"a2a.message", "a2a.result"})
    owasp: ClassVar[list[str]] = ["ASI07", "ASI03"]
    priority: ClassVar[int] = 5

    # ------------------------------------------------------------ helpers
    def _params(self, cfg: Any) -> A2A01Params:
        try:
            return A2A01Params.model_validate(dict(getattr(cfg, "params", None) or {}))
        except Exception:
            log.error("A2A-01 invalid params - using defaults")
            return A2A01Params()

    def _deny(self, cfg: Any, action: str, reason: str, detector: str, *, severity: str = "high",
              status: int | None = None, error_type: str | None = None,
              **meta: Any) -> Decision | None:
        if action == "allow":
            return None
        kw: dict[str, Any] = {}
        if action == "block" and status is not None:
            kw = {"http_status": status, "error_type": error_type}
        finding = Finding(control_id=self.id, detector=detector, category="governance",
                          severity=severity, meta=meta)  # type: ignore[arg-type]
        return self.decide(cfg, action=action, reason=reason, findings=[finding],
                           meta={"a2a": {"check": detector, **meta}}, **kw)

    def _ok(self, cfg: Any, reason: str, **meta: Any) -> Decision:
        return Decision(action="allow", control_id=self.id, reason=reason,
                        severity=cfg.severity, owasp=list(cfg.owasp or self.owasp),
                        meta={"a2a": {"check": "ok", **meta}})

    def _verify_envelope(self, cfg: Any, p: A2A01Params, ctx: Any, env: signing.Envelope,
                         key: str, body: Any, *, direction: str,
                         status: int | None = None) -> Decision | None:
        """Signature + freshness + single-use nonce. Returns a deny decision or None."""
        et = "unauthenticated" if status == 401 else None
        chk = signing.verify(env, key, body, ttl_s=p.ttl_s)
        if not chk.ok:
            what = {
                "bad_signature": "signature mismatch (tampered or forged message)",
                "stale": f"stale message ({chk.detail})",
                "future": f"timestamp in the future ({chk.detail})",
            }.get(chk.code, chk.detail)
            return self._deny(cfg, "block", f"{direction} from '{env.sender}': {what}",
                              f"a2a.sig.{chk.code}", severity="critical", status=status,
                              error_type=et, sender=env.sender, key_id=env.key_id)
        dry = bool(getattr(ctx, "dry_run", False)) or getattr(ctx, "source", None) == "selftest"
        replay = (nonces.NONCES.seen(env.sender, env.nonce) if dry
                  else not nonces.NONCES.use(env.sender, env.nonce, p.ttl_s))
        if replay:
            return self._deny(cfg, "block",
                              f"{direction} from '{env.sender}': replayed nonce "
                              f"{env.nonce[:8]}… (message already seen)",
                              "a2a.replay", severity="critical", status=status, error_type=et,
                              sender=env.sender)
        return None

    # ------------------------------------------------------------ evaluate
    async def evaluate(self, ctx: Any, interaction: Any, cfg: Any) -> Decision | None:
        try:
            return await self._evaluate(ctx, interaction, cfg)
        except Exception:
            log.exception("A2A-01 internal error (fail closed)")
            return Decision(action="block", control_id=self.id, degraded=True,
                            reason="A2A-01 internal error (fail closed)", severity="high",
                            owasp=list(self.owasp))

    async def _evaluate(self, ctx: Any, i: Any, cfg: Any) -> Decision | None:
        p = self._params(cfg)
        registry = peers.parse_peers({"peers": p.peers})
        gw = p.gateway_id
        meta = (i.meta or {}).get("a2a") or {}
        transport = isinstance(meta, dict) and meta.get("transport") == "gateway"
        peer_id = peers.peer_from_interaction(i)
        headers, body = _envelope_source(ctx, i)

        # ---- registry: who is the peer?
        if not peer_id:
            if i.surface == "a2a.message":
                return self._deny(cfg, _act(p.unknown_peer_action), "A2A message without a "
                                  "target peer id", "a2a.no_peer")
            return None  # descriptive a2a.result without a peer: nothing to verify
        peer = registry.get(peer_id)
        if peer is None:
            hint = peers.lookalike(peer_id, registry, p.typosquat_distance)
            reason = f"unknown peer agent '{peer_id}' (not in the A2A registry)"
            if hint:
                reason += f" - looks like registered peer '{hint}' (possible typosquat)"
            return self._deny(cfg, _act(p.unknown_peer_action), reason,
                              "a2a.typosquat" if hint else "a2a.unknown_peer",
                              severity="critical" if hint else "high", peer=peer_id,
                              lookalike=hint)
        if not peer.enabled:
            return self._deny(cfg, "block", f"peer agent '{peer_id}' is disabled in the registry",
                              "a2a.peer_disabled", peer=peer_id)

        if i.surface == "a2a.message":
            return await self._message(ctx, i, cfg, p, registry, peer, gw, meta, headers,
                                       body, transport)
        if i.surface == "a2a.result":
            if not transport:
                return self._ok(cfg, f"peer '{peer_id}' registered (signature verified only on "
                                     "the gateway A2A surface)", peer=peer_id, verified=False)
            return self._result(ctx, i, cfg, p, peer, gw, meta, headers, body)
        return None

    async def _message(self, ctx: Any, i: Any, cfg: Any, p: A2A01Params,
                       registry: dict[str, peers.PeerConfig], peer: peers.PeerConfig, gw: str,
                       meta: dict[str, Any], headers: dict[str, str], body: Any,
                       transport: bool) -> Decision | None:
        ident = getattr(ctx, "identity", None)
        caller = getattr(ident, "agent_id", None) or "anonymous"
        if caller != "selftest" and not any(glob_match(g, caller) for g in peer.allowed_callers):
            return self._deny(cfg, _act(p.caller_not_allowed_action),
                              f"agent '{caller}' is not allowed to message peer '{peer.id}'",
                              "a2a.caller_not_allowed", peer=peer.id, caller=caller)
        card = meta.get("card") if isinstance(meta, dict) else None
        if p.verify_card and transport and isinstance(card, dict):
            st = card.get("status")
            probs = "; ".join(card.get("problems") or [])
            if st in ("mismatch", "invalid"):
                return self._deny(cfg, _act(p.card_mismatch_action),
                                  f"agent card of '{peer.id}' failed verification: {probs}",
                                  "a2a.card_mismatch", severity="critical", peer=peer.id)
            if st == "unavailable":
                d = self._deny(cfg, _act(p.card_unavailable_action, "log"),
                               f"agent card of '{peer.id}' unavailable: {probs}",
                               "a2a.card_unavailable", severity="medium", peer=peer.id)
                if d is not None and d.action != "log":
                    return d
                # log-only: fall through to the inbound checks, keep the signal
                card_note = d
            else:
                card_note = None
        else:
            card_note = None

        # ---- inbound: the message itself claims to come from a peer agent
        env = signing.Envelope.from_headers(headers)
        claimed = headers.get(signing.H_SENDER)
        if env is None and claimed and p.require_signed_inbound:
            return self._deny(cfg, "block", f"message claims peer sender '{claimed}' but is "
                              "unsigned", "a2a.unsigned_inbound", status=401,
                              error_type="unauthenticated", sender=claimed)
        if env is not None:
            sender = registry.get(env.sender)
            if sender is None or not sender.enabled:
                return self._deny(cfg, "block", f"inbound message signed by unknown peer "
                                  f"'{env.sender}'", "a2a.unknown_sender", status=401,
                                  error_type="unauthenticated", sender=env.sender)
            if env.recipient != gw:
                return self._deny(cfg, "block", f"inbound message addressed to '{env.recipient}'"
                                  f", not this gateway ('{gw}')", "a2a.wrong_recipient",
                                  status=401, error_type="unauthenticated")
            bad = self._verify_envelope(cfg, p, ctx, env, peers.peer_key(sender), body,
                                        direction="inbound message", status=401)
            if bad is not None:
                return bad
            return self._ok(cfg, f"inbound message from '{env.sender}' verified; peer "
                                 f"'{peer.id}' registered", peer=peer.id, sender=env.sender,
                            verified=True)
        if card_note is not None:
            return card_note
        return self._ok(cfg, f"peer '{peer.id}' registered"
                        + (", agent card verified" if isinstance(card, dict)
                           and card.get("status") == "ok" else ""),
                        peer=peer.id, caller=caller)

    def _result(self, ctx: Any, i: Any, cfg: Any, p: A2A01Params, peer: peers.PeerConfig,
                gw: str, meta: dict[str, Any], headers: dict[str, str],
                body: Any) -> Decision | None:
        env = signing.Envelope.from_headers(headers)
        if env is None:
            if not p.require_signed_results:
                return self._deny(cfg, "log", f"unsigned reply from '{peer.id}'",
                                  "a2a.unsigned_result", severity="medium", peer=peer.id)
            return self._deny(cfg, "block", f"reply from '{peer.id}' is unsigned (peer identity "
                              "cannot be verified)", "a2a.unsigned_result", peer=peer.id)
        if env.sender != peer.id:
            return self._deny(cfg, "block", f"reply signed as '{env.sender}', expected peer "
                              f"'{peer.id}' (spoofed sender)", "a2a.sender_mismatch",
                              severity="critical", peer=peer.id, sender=env.sender)
        if env.recipient != gw:
            return self._deny(cfg, "block", f"reply addressed to '{env.recipient}', not this "
                              f"gateway ('{gw}')", "a2a.wrong_recipient", peer=peer.id)
        bad = self._verify_envelope(cfg, p, ctx, env, peers.peer_key(peer), body,
                                    direction="reply")
        if bad is not None:
            return bad
        want = str(meta.get("request_nonce") or "")
        if want and env.in_reply_to != want:
            return self._deny(cfg, "block", f"reply from '{peer.id}' is not bound to this "
                              "request (x-a2a-in-reply-to mismatch)", "a2a.reply_unbound",
                              severity="critical", peer=peer.id)
        return self._ok(cfg, f"reply signature from '{peer.id}' verified (fresh, single-use "
                             "nonce, bound to request)", peer=peer.id, verified=True,
                        key_id=env.key_id)


CONTROLS = [PeerIdentity()]
