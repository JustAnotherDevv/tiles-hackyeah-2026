"""Peer-agent registry (A2A-01 ``params``), key resolution and typosquat hints.

Policy shape (``controls[A2A-01].params``)::

    gateway_id: aegis-gateway          # our identity in signatures
    peers:
      research-agent:
        url: http://127.0.0.1:8795/a2a/research-agent
        destination: third_party       # local | remote | third_party
        key_id: k1
        key_env: AEGIS_A2A_KEY_RESEARCH_AGENT   # optional; else a derived local demo key
        card: {name: research-agent, sha256: null}
        allowed_callers: ["*"]         # agent-id globs allowed to talk to this peer
        enabled: true

Keys never live in the policy file. ``key_env`` names an environment variable; without it the
gateway derives a per-peer key from its own HMAC key (``aegis.core.crypto``), which a local mock
peer started with the same data dir derives identically (demo only).
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

CONTROL_ID = "A2A-01"
DEFAULT_GATEWAY_ID = "aegis-gateway"


class CardSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None  # expected agent-card `name` (default: the peer id)
    sha256: str | None = None  # optional pin of the canonical card JSON
    url: str | None = None  # where to fetch it (default: <url>/.well-known/agent-card.json)


class PeerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    url: str | None = None
    destination: str = "third_party"
    key_id: str = "k1"
    key_env: str | None = None
    card: CardSpec = Field(default_factory=CardSpec)
    allowed_callers: list[str] = Field(default_factory=lambda: ["*"])
    enabled: bool = True
    description: str | None = None

    @property
    def host(self) -> str | None:
        return urlsplit(self.url).hostname if self.url else None

    @property
    def card_url(self) -> str | None:
        if self.card.url:
            return self.card.url
        if not self.url:
            return None
        return self.url.rstrip("/") + "/.well-known/agent-card.json"


def a2a01_params(snap: Any) -> dict[str, Any]:
    """A2A-01 params from a policy snapshot (effective controls first, then the raw doc)."""
    if snap is None:
        return {}
    cfg = None
    try:
        cfg = snap.control(CONTROL_ID)
    except Exception:
        cfg = None
    if cfg is None:
        for c in getattr(getattr(snap, "doc", None), "controls", []) or []:
            if getattr(c, "id", None) == CONTROL_ID:
                cfg = c
                break
    return dict(getattr(cfg, "params", None) or {})


def parse_peers(params: dict[str, Any] | None) -> dict[str, PeerConfig]:
    out: dict[str, PeerConfig] = {}
    raw = (params or {}).get("peers") or {}
    if isinstance(raw, list):  # list form: [{id: ..., url: ...}]
        raw = {str(p.get("id")): p for p in raw if isinstance(p, dict) and p.get("id")}
    for pid, spec in (raw or {}).items():
        if not isinstance(spec, dict):
            continue
        try:
            peer = PeerConfig.model_validate({**spec, "id": str(pid)})
        except Exception:
            continue
        out[str(pid)] = peer
    return out


def peers_from_snapshot(snap: Any) -> dict[str, PeerConfig]:
    return parse_peers(a2a01_params(snap))


def gateway_id(params: dict[str, Any] | None) -> str:
    return str((params or {}).get("gateway_id") or DEFAULT_GATEWAY_ID)


def env_name(peer_id: str) -> str:
    return "AEGIS_A2A_KEY_" + "".join(c if c.isalnum() else "_" for c in peer_id).upper()


def derived_key(peer_id: str) -> str:
    """Local demo key: HMAC(gateway key, 'a2a:<peer>'). Same data dir -> same key."""
    from aegis.core import crypto

    return crypto.hmac_hex(f"a2a:{peer_id}", purpose="a2a.peer-key")


def peer_key(peer: PeerConfig | str) -> str:
    """Shared HMAC key for a peer: ``key_env`` -> ``AEGIS_A2A_KEY_<PEER>`` -> derived."""
    pid = peer if isinstance(peer, str) else peer.id
    names = []
    if not isinstance(peer, str) and peer.key_env:
        names.append(peer.key_env)
    names.append(env_name(pid))
    for name in names:
        val = os.environ.get(name)
        if val:
            return val
    return derived_key(pid)


def _distance(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein distance with an early exit above ``cap``."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def lookalike(peer_id: str, peers: dict[str, PeerConfig], max_distance: int = 2) -> str | None:
    """A registered peer this unknown id imitates (typosquat / homoglyph-ish), else None."""
    norm = peer_id.lower().replace("_", "-").replace("0", "o").replace("1", "l")
    best: tuple[int, str] | None = None
    for pid in peers:
        cand = pid.lower().replace("_", "-").replace("0", "o").replace("1", "l")
        d = _distance(norm, cand, max_distance)
        if d <= max_distance and (best is None or d < best[0]):
            best = (d, pid)
    return best[1] if best else None


def peer_from_interaction(interaction: Any) -> str | None:
    """Target peer id: ``meta['a2a']['peer']`` (route) or ``tool_name='a2a.<peer>[.<method>]'``."""
    meta = getattr(interaction, "meta", None) or {}
    a2a = meta.get("a2a") if isinstance(meta, dict) else None
    if isinstance(a2a, dict) and a2a.get("peer"):
        return str(a2a["peer"])
    tool = getattr(interaction, "tool_name", None) or ""
    if tool.startswith("a2a."):
        rest = tool[4:]
        # peer ids may contain dots? no - registry ids are [a-z0-9-_]; method follows the first '.'
        return rest.split(".", 1)[0] or None
    dest = getattr(interaction, "destination", None)
    name = getattr(dest, "name", "") or ""
    if name.startswith("a2a:"):
        return name[4:] or None
    return None
