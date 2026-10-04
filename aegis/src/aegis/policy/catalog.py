"""Control catalog as data (CONTRACTS section 4.4 + Addendum A GOV-06).

Used by the profile merge (kind defaults), the validator (unknown ids -> warning), the control
views (`owner`, `surfaces`) and the JSON schema enrichment. Pure data, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FAMILIES: dict[str, str] = {
    "GOV": "Identity, model & tool governance",
    "ACT": "Agent action guards (spend, data access, external send, code exec, deploy)",
    "DLP": "Local data minimization (PII, PCI, secrets, metadata, exfil)",
    "INJ": "Injection, content & behaviour",
    "EXE": "Tool & execution safety",
    "MCP": "MCP server & tool supply chain",
    "BUD": "Budgets, cost & compute",
    "SIG": "External threat signatures & artifacts",
    "CUS": "Customer-defined rules",
    "A2A": "Agent-to-agent communication",
    "RES": "Resilience & cascading failures",
    "MEM": "Persistent memory & context",
    "ROG": "Rogue-agent detection",
}
FAMILY_ORDER: tuple[str, ...] = tuple(FAMILIES)

# Surfaces shorthand
_ALL: tuple[str, ...] = ()  # empty = every surface
_OUT_ALL = (
    "prompt.user", "model.request", "model.admin", "tool.input", "mcp.init", "mcp.call",
    "egress.request", "a2a.message", "artifact.file",
)
_INJ = ("prompt.user", "model.request", "tool.output", "mcp.result", "mcp.list", "egress.response")


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    family: str
    name: str
    owner: str
    kind: str  # deterministic | semantic | hybrid | stateful
    surfaces: tuple[str, ...]
    default_action: str
    prio: str  # MVP | stretch | reserved
    owasp: tuple[str, ...] = field(default_factory=tuple)
    default_mode: str | None = None  # catalog default mode (only for stretch controls)

    @property
    def reserved(self) -> bool:
        return self.prio == "reserved"


_ENTRIES: list[CatalogEntry] = [
    # ------------------------------------------------------------------ GOV
    CatalogEntry("GOV-01", "GOV", "Caller identity & attribution", "org-rbac", "deterministic",
                 _ALL, "log", "MVP", ("ASI03", "ASI07", "MCP07:2025", "LLM03:2026")),
    CatalogEntry("GOV-02", "GOV", "Model allowlist & destination tiering", "org-rbac", "deterministic",
                 ("model.request", "model.admin"), "block", "MVP",
                 ("LLM03:2026", "LLM06:2026", "LLM02:2026", "ASI10")),
    CatalogEntry("GOV-03", "GOV", "Tool authorization (RBAC + arg constraints)", "action-guards",
                 "deterministic", ("tool.input", "mcp.call"), "block", "MVP",
                 ("LLM03:2026", "ASI02", "ASI03", "MCP02:2025")),
    CatalogEntry("GOV-04", "GOV", "Human approval gate for other high-impact tools", "action-guards",
                 "deterministic", ("tool.input", "mcp.call", "egress.request"), "require_approval",
                 "MVP", ("ASI09", "ASI02", "LLM03:2026")),
    CatalogEntry("GOV-05", "GOV", "Config-change governance (who may change what)", "approvals-engine",
                 "deterministic", ("config.change",), "require_approval", "MVP", ("ASI03", "ASI09")),
    CatalogEntry("GOV-06", "GOV", "Agent harness integrity (Claude Code)", "claude-code-integration",
                 "deterministic", ("tool.input", "config.change", "prompt.user"), "block", "MVP",
                 ("ASI03", "ASI10", "LLM06:2026")),
    # ------------------------------------------------------------------ ACT
    CatalogEntry("ACT-01", "ACT", "Spend guard (purchases, subscriptions, top-ups)", "action-guards",
                 "deterministic", ("tool.input", "mcp.call", "egress.request"), "require_approval",
                 "MVP", ("LLM03:2026", "ASI02", "ASI09", "LLM06:2026")),
    CatalogEntry("ACT-02", "ACT", "Data access guard (tables by sensitivity & environment)",
                 "action-guards", "deterministic", ("tool.input", "mcp.call"), "require_approval",
                 "MVP", ("LLM02:2026", "LLM03:2026", "ASI02", "ASI03", "MCP02:2025")),
    CatalogEntry("ACT-03", "ACT", "External send guard (email, webhooks, uploads)", "action-guards",
                 "deterministic", ("tool.input", "mcp.call", "egress.request"), "require_approval",
                 "MVP", ("LLM02:2026", "ASI01", "ASI02", "MCP10:2025")),
    CatalogEntry("ACT-04", "ACT", "Code execution & deploy guard", "action-guards", "deterministic",
                 ("tool.input", "mcp.call"), "require_approval", "MVP",
                 ("ASI05", "LLM10:2026", "MCP05:2025")),
    # ------------------------------------------------------------------ DLP
    CatalogEntry("DLP-01", "DLP", "PII/PCI/Polish-ID tokenization (destination matrix)",
                 "redaction-engine", "deterministic",
                 ("prompt.user", "model.request", "tool.input", "mcp.call", "egress.request"),
                 "redact", "MVP", ("LLM02:2026", "MCP10:2025", "ASI03")),
    CatalogEntry("DLP-02", "DLP", "Secrets & credentials", "redaction-engine", "deterministic",
                 (*_OUT_ALL, "tool.output", "mcp.result"), "block", "MVP",
                 ("MCP01:2025", "LLM02:2026", "LLM08:2026", "ASI03")),
    CatalogEntry("DLP-03", "DLP", "Metadata stripping & generalization", "metadata-egress",
                 "deterministic", ("model.request", "mcp.call", "egress.request"), "redact", "MVP",
                 ("LLM02:2026", "LLM08:2026", "MCP10:2025")),
    CatalogEntry("DLP-04", "DLP", "Tool-arg / egress exfiltration scan", "metadata-egress", "hybrid",
                 ("tool.input", "mcp.call", "egress.request"), "block", "MVP",
                 ("LLM02:2026", "MCP10:2025", "ASI02", "ASI01")),
    CatalogEntry("DLP-05", "DLP", "Output & tool-result leak detection (+ canary)", "redaction-engine",
                 "deterministic", ("model.response", "tool.output", "mcp.result", "egress.response"),
                 "redact", "MVP", ("LLM02:2026", "LLM08:2026", "MCP10:2025")),
    CatalogEntry("DLP-06", "DLP", "Exfil-channel neutralization (md images/links, ANSI)",
                 "metadata-egress", "deterministic", ("model.response", "tool.output", "mcp.result"),
                 "redact", "MVP", ("LLM10:2026", "LLM02:2026", "ASI01")),
    CatalogEntry("DLP-07", "DLP", "Multilingual NER sensitive data (incl. Polish)", "redaction-engine",
                 "semantic", ("prompt.user", "model.request", "tool.output", "mcp.result"), "redact",
                 "MVP", ("LLM02:2026", "MCP10:2025")),
    CatalogEntry("DLP-08", "DLP", "Vault & controlled re-identification", "redaction-engine",
                 "deterministic", ("model.response", "tool.input"), "allow", "MVP",
                 ("LLM02:2026", "MCP10:2025", "ASI03")),
    # ------------------------------------------------------------------ INJ
    CatalogEntry("INJ-01", "INJ", "Normalization + deterministic injection signatures",
                 "injection-defense", "deterministic", _INJ, "block", "MVP",
                 ("LLM01:2026", "ASI01", "MCP06:2025")),
    CatalogEntry("INJ-02", "INJ", "Semantic injection / jailbreak classifier", "injection-defense",
                 "semantic", _INJ, "block", "MVP", ("LLM01:2026", "ASI01", "ASI06", "MCP06:2025")),
    CatalogEntry("INJ-03", "INJ", "Content safety + topic adherence %", "semantic-models", "semantic",
                 ("prompt.user", "model.request", "model.response"), "block", "MVP",
                 ("LLM07:2026", "ASI10", "ASI01")),
    CatalogEntry("INJ-04", "INJ", "Hidden-context exposure (extraction + canary + overlap)",
                 "injection-defense", "hybrid", ("prompt.user", "model.request", "model.response"),
                 "block", "MVP", ("LLM08:2026", "ASI01")),
    CatalogEntry("INJ-05", "INJ", "Goal-drift / grounding check", "injection-defense", "hybrid",
                 ("tool.input", "mcp.call"), "require_approval", "stretch",
                 ("ASI01", "ASI10", "ASI09"), default_mode="monitor"),
    # ------------------------------------------------------------------ EXE
    CatalogEntry("EXE-01", "EXE", "Dangerous command guard", "action-guards", "deterministic",
                 ("tool.input", "mcp.call", "mcp.init"), "block", "MVP",
                 ("ASI05", "MCP05:2025", "LLM10:2026")),
    CatalogEntry("EXE-02", "EXE", "Filesystem & network scope (SSRF)", "action-guards", "deterministic",
                 ("tool.input", "mcp.call", "egress.request"), "block", "MVP",
                 ("ASI02", "MCP05:2025", "MCP10:2025", "LLM03:2026")),
    CatalogEntry("EXE-03", "EXE", "Taint-flow breaker (lethal trifecta)", "action-guards", "stateful",
                 ("tool.input", "mcp.call", "egress.request"), "require_approval", "MVP",
                 ("ASI01", "ASI02", "MCP06:2025", "MCP10:2025", "LLM02:2026")),
    CatalogEntry("EXE-04", "EXE", "Loop / rate / circuit breaker / kill switch", "budgets-ledger",
                 "stateful", _OUT_ALL, "block", "MVP", ("ASI08", "ASI10", "LLM06:2026")),
    CatalogEntry("EXE-05", "EXE", "Code-execution provenance & sandbox guard", "action-guards",
                 "stateful", ("tool.input", "mcp.call"), "require_approval", "MVP",
                 ("ASI05", "LLM10:2026", "MCP05:2025")),
    # ------------------------------------------------------------------ MCP
    CatalogEntry("MCP-01", "MCP", "Server registry & launch check", "mcp-proxy", "deterministic",
                 ("mcp.init", "mcp.call"), "block", "MVP", ("MCP09:2025", "MCP04:2025", "ASI04")),
    CatalogEntry("MCP-02", "MCP", "Tool-definition poisoning scan", "mcp-proxy", "hybrid",
                 ("mcp.list",), "redact", "MVP",
                 ("MCP03:2025", "MCP06:2025", "ASI04", "LLM01:2026")),
    CatalogEntry("MCP-03", "MCP", "Tool pinning (rug pull) & shadowing", "mcp-proxy", "stateful",
                 ("mcp.list", "mcp.call"), "block", "MVP",
                 ("MCP03:2025", "MCP04:2025", "ASI02", "ASI04")),
    CatalogEntry("MCP-04", "MCP", "Token & auth hygiene", "mcp-proxy", "deterministic",
                 ("mcp.init", "mcp.call", "mcp.result"), "block", "stretch",
                 ("MCP01:2025", "MCP02:2025", "MCP07:2025", "ASI03"), default_mode="monitor"),
    # ------------------------------------------------------------------ BUD
    CatalogEntry("BUD-01", "BUD", "Token & cost budgets (remote + local, spend)", "budgets-ledger",
                 "deterministic", ("model.request", "tool.input", "mcp.call", "egress.request"),
                 "block", "MVP", ("LLM06:2026", "ASI08", "ASI10")),
    CatalogEntry("BUD-02", "BUD", "Local compute & concurrency", "budgets-ledger", "deterministic",
                 ("model.request", "model.admin"), "block", "MVP", ("LLM06:2026", "ASI08")),
    # ------------------------------------------------------------------ SIG
    CatalogEntry("SIG-01", "SIG", "External exploit-signature engine", "threat-feed", "deterministic",
                 _ALL, "block", "MVP",
                 ("LLM04:2026", "ASI04", "ASI05", "MCP04:2025", "MCP05:2025")),
    CatalogEntry("SIG-02", "SIG", "Model-artifact gate (pickle / GGUF)", "threat-feed", "deterministic",
                 ("model.admin", "artifact.file"), "block", "MVP",
                 ("LLM04:2026", "LLM05:2026", "ASI04", "ASI05")),
    CatalogEntry("SIG-03", "SIG", "Package-install / slopsquatting guard", "threat-feed",
                 "deterministic", ("tool.input", "mcp.init"), "block", "MVP",
                 ("LLM04:2026", "ASI04", "MCP04:2025")),
    # ------------------------------------------------------------------ CUS
    CatalogEntry("CUS-01", "CUS", "Customer-defined rules (deal code names must not leave the firm)",
                 "semantic-models", "hybrid",
                 ("prompt.user", "model.request", "tool.input", "mcp.call"), "block", "MVP",
                 ("LLM02:2026",)),
    # ------------------------------------------------------------------ A2A (reserved)
    CatalogEntry("A2A-01", "A2A", "Peer identity & message integrity", "asi-a2a",
                 "deterministic", ("a2a.message", "a2a.result"), "block", "MVP",
                 ("ASI07", "ASI03")),
    CatalogEntry("A2A-02", "A2A", "Inter-agent smuggling & delegation guard", "asi-a2a", "hybrid",
                 ("a2a.message", "a2a.result"), "block", "MVP",
                 ("ASI01", "ASI07", "ASI08")),
    # ------------------------------------------------------------------ MEM
    CatalogEntry("MEM-01", "MEM", "Persistent memory guard (memory & context poisoning)", "asi-memory", "stateful",
                 ("tool.input", "mcp.call", "tool.output", "mcp.result", "a2a.result", "egress.response",
                  "model.request"), "require_approval", "MVP", ("ASI06", "ASI01", "LLM01:2026", "LLM04:2026")),
    # ------------------------------------------------------------------ RES
    CatalogEntry("RES-01", "RES", "Cascading-failure breaker (quarantine + circuit + taint)", "asi-failclosed",
                 "stateful", ("tool.input", "mcp.call", "mcp.init", "egress.request", "a2a.message", "a2a.result",
                              "tool.output", "mcp.result"), "require_approval", "MVP", ("ASI08", "ASI10", "ASI07")),
    # ------------------------------------------------------------------ ROG
    CatalogEntry("ROG-01", "ROG", "Rogue-agent behavioural anomaly detector (baseline + quarantine)", "asi-rogue",
                 "stateful", ("tool.input", "mcp.call", "mcp.init", "egress.request", "a2a.message", "tool.output",
                              "mcp.result", "egress.response", "a2a.result"), "require_approval", "MVP",
                 ("ASI10", "ASI08", "LLM06:2026")),
]

#: id -> CatalogEntry, in family order (GOV, ACT, DLP, INJ, EXE, MCP, BUD, SIG, CUS, A2A).
CATALOG: dict[str, CatalogEntry] = {e.id: e for e in _ENTRIES}


def get(control_id: str) -> CatalogEntry | None:
    return CATALOG.get(control_id)


def kind_of(control_id: str, default: str = "deterministic") -> str:
    entry = CATALOG.get(control_id)
    return entry.kind if entry else default


def family_of(control_id: str) -> str:
    entry = CATALOG.get(control_id)
    if entry:
        return entry.family
    return control_id.split("-", 1)[0] if "-" in control_id else "CUS"


def sort_key(control_id: str) -> tuple[int, str]:
    fam = family_of(control_id)
    idx = FAMILY_ORDER.index(fam) if fam in FAMILY_ORDER else len(FAMILY_ORDER)
    return idx, control_id
