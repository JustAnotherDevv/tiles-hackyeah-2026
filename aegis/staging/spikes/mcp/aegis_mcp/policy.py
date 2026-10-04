"""MCP slice of the policy: the upstream server catalog plus per-surface actions.

In the gateway this is the `mcp:` section of the single YAML control catalog (hot reloaded,
validated, stamped with a policy version). The spike reads the same shape from JSON so it
needs no extra dependency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class ServerEntry:
    name: str
    url: str | None = None  # Streamable HTTP upstream; None for stdio-only servers
    trust: str = "external"  # internal | external  (drives PII redaction and blob limits)
    headers: dict[str, str] = field(default_factory=dict)  # upstream credentials injected by the proxy (MCP-04)
    allow_tools: list[str] | None = None  # optional explicit allowlist
    deny_tools: list[str] = field(default_factory=list)


@dataclass
class Policy:
    servers: dict[str, ServerEntry] = field(default_factory=dict)
    version: str = "dev"

    # tools/list (MCP-02 / MCP-03)
    poison_threshold: int = 3  # sum of finding severities (high=3, medium=1) at which a tool is hidden
    max_description_len: int = 2000
    url_allowlist: list[str] = field(default_factory=list)
    on_definition_change: str = "block"  # block | alert
    new_tool_after_baseline: str = "quarantine"  # quarantine | pin
    unvetted_call: str = "block"  # tools/call for a tool never seen in a listing: block | allow

    # tools/call arguments (DLP-02 / DLP-04)
    secrets_action: str = "block"  # block | redact
    hidden_payload_action: str = "block"  # base64/hex that decodes to a secret or injection
    large_blob_action: dict[str, str] = field(default_factory=lambda: {"internal": "allow", "external": "block"})
    pii_action: dict[str, str] = field(default_factory=lambda: {"internal": "allow", "external": "redact"})
    max_encoded_len: int = 512

    # results (INJ-01 / DLP-05)
    result_injection_action: str = "sanitize"  # sanitize | block | alert
    result_secrets_action: str = "redact"  # redact | alert

    # transport
    allowed_origins: list[str] = field(default_factory=lambda: ["http://localhost", "http://127.0.0.1"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Policy:
        known = {f.name for f in fields(cls)} - {"servers"}
        servers = {name: ServerEntry(name=name, **cfg) for name, cfg in (data.get("servers") or {}).items()}
        return cls(servers=servers, **{k: v for k, v in data.items() if k in known})

    @classmethod
    def load(cls, path: str | Path) -> Policy:
        return cls.from_dict(json.loads(Path(path).read_text()))

    def trust(self, server: str) -> str:
        entry = self.servers.get(server)
        return entry.trust if entry else "external"
