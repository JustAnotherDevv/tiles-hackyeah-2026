"""Agent-to-agent (A2A) support for the gateway (ASI07 / ASI01).

* ``signing``  - HMAC-SHA256 message signatures (sender, recipient, timestamp, nonce, reply
  binding, body hash) carried in ``X-A2A-*`` headers; verify + freshness.
* ``nonces``   - single-use nonce cache (replay protection, TTL-bounded).
* ``peers``    - the peer-agent registry read from the A2A-01 ``params.peers`` policy block,
  key resolution (``key_env`` or a derived local demo key), typosquat hints.
* ``messages`` - JSON-RPC A2A message helpers: text parts -> segments, write-back by path.
* ``card``     - agent-card fetch + verification (name, host, optional sha256 pin).

Enforcement lives in the controls ``aegis.controls.a2a`` (A2A-01, A2A-02); the HTTP surface is
``POST /a2a/{peer}`` (``aegis.api.routes.a2a``).
"""
