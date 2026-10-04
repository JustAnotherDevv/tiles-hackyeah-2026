"""Agent-card fetch + verification (A2A-01 "forged / typosquatted agent card").

The route fetches ``<peer url>/.well-known/agent-card.json`` (or ``card.url``) and records the
facts in ``Interaction.meta['a2a']['card']``; A2A-01 decides. Checks:

* ``name`` equals the expected name (``card.name`` or the peer id);
* the card's ``url`` host (when present) equals the registered peer host (a forged card that
  points traffic elsewhere is rejected);
* optional ``card.sha256`` pin over the canonical JSON (sorted keys, compact separators).

Results are cached per peer for ``ttl_s`` (default 300 s).
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from urllib.parse import urlsplit

from aegis.a2a.peers import PeerConfig

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def canonical_sha256(card: Any) -> str:
    data = json.dumps(card, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def check_card(peer: PeerConfig, card: Any) -> dict[str, Any]:
    """Facts dict: {status: ok|mismatch|invalid, problems: [...], name, sha256}."""
    if not isinstance(card, dict):
        return {"status": "invalid", "problems": ["agent card is not a JSON object"]}
    problems: list[str] = []
    expected = peer.card.name or peer.id
    name = card.get("name")
    if name != expected:
        problems.append(f"card name '{name}' != registered '{expected}'")
    url = card.get("url")
    if isinstance(url, str) and url and peer.host:
        host = urlsplit(url).hostname
        if host and host != peer.host:
            problems.append(f"card url host '{host}' != registered host '{peer.host}'")
    digest = canonical_sha256(card)
    if peer.card.sha256 and digest != peer.card.sha256.lower():
        problems.append("card sha256 does not match the pinned value")
    return {
        "status": "mismatch" if problems else "ok",
        "problems": problems,
        "name": name if isinstance(name, str) else None,
        "sha256": digest[:16],
    }


async def fetch_and_check(client: Any, peer: PeerConfig, *, ttl_s: float = 300.0,
                          timeout_s: float = 5.0) -> dict[str, Any]:
    now = time.monotonic()
    hit = _CACHE.get(peer.id)
    if hit is not None and hit[0] > now:
        return hit[1]
    url = peer.card_url
    if not url or client is None:
        facts: dict[str, Any] = {"status": "unavailable", "problems": ["no card url"]}
    else:
        try:
            resp = await client.get(url, timeout=timeout_s)
            if resp.status_code != 200:
                facts = {"status": "unavailable",
                         "problems": [f"agent card fetch returned HTTP {resp.status_code}"]}
            else:
                facts = check_card(peer, resp.json())
        except Exception as exc:  # unreachable / invalid JSON
            facts = {"status": "unavailable",
                     "problems": [f"agent card fetch failed ({type(exc).__name__})"]}
    # cache good results for ttl, failures briefly (the peer may be starting)
    _CACHE[peer.id] = (now + (ttl_s if facts["status"] == "ok" else 5.0), facts)
    return facts


def reset() -> None:
    _CACHE.clear()
