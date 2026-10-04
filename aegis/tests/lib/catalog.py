"""Control catalog (CONTRACTS §4.4 + Addendum A-48 GOV-06) as data: the rows of the matrix."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogControl:
    id: str
    name: str
    owner: str
    kind: str  # D deterministic, S semantic, H hybrid, St stateful
    prio: str  # mvp | stretch

    @property
    def family(self) -> str:
        return self.id.split("-")[0]


_ROWS = """
GOV-01|Caller identity & attribution|org-rbac|D|mvp
GOV-02|Model allowlist & destination tiering|org-rbac|D|mvp
GOV-03|Tool authorization (RBAC + arg constraints)|action-guards|D|mvp
GOV-04|Human approval gate for high-impact tools|action-guards|D|mvp
GOV-05|Config-change governance|approvals-engine|D|mvp
GOV-06|Agent harness integrity|claude-code-integration|D|mvp
ACT-01|Spend guard|action-guards|D|mvp
ACT-02|Data access guard|action-guards|D|mvp
ACT-03|External send guard|action-guards|D|mvp
ACT-04|Code execution & deploy guard|action-guards|D|mvp
DLP-01|PII/PCI/Polish-ID tokenization|redaction-engine|D|mvp
DLP-02|Secrets & credentials|redaction-engine|D|mvp
DLP-03|Metadata stripping & generalization|metadata-egress|D|mvp
DLP-04|Tool-arg / egress exfiltration scan|metadata-egress|H|mvp
DLP-05|Output & tool-result leak detection|redaction-engine|D|mvp
DLP-06|Exfil-channel neutralization|metadata-egress|D|mvp
DLP-07|Multilingual NER (incl. Polish)|redaction-engine|S|mvp
DLP-08|Vault & controlled re-identification|redaction-engine|D|mvp
INJ-01|Deterministic injection signatures|injection-defense|D|mvp
INJ-02|Semantic injection / jailbreak classifier|injection-defense|S|mvp
INJ-03|Content safety + topic adherence|semantic-models|S|mvp
INJ-04|Hidden-context exposure|injection-defense|H|mvp
INJ-05|Goal-drift / grounding check|injection-defense|H|mvp
EXE-01|Dangerous command guard|action-guards|D|mvp
EXE-02|Filesystem & network scope (SSRF)|action-guards|D|mvp
EXE-03|Taint-flow breaker (lethal trifecta)|action-guards|St|mvp
EXE-04|Loop / rate / circuit breaker / kill switch|budgets-ledger|St|mvp
EXE-05|Code-execution provenance & sandbox guard|action-guards|St|mvp
MCP-01|Server registry & launch check|mcp-proxy|D|mvp
MCP-02|Tool-definition poisoning scan|mcp-proxy|H|mvp
MCP-03|Tool pinning (rug pull) & shadowing|mcp-proxy|St|mvp
MCP-04|Token & auth hygiene|mcp-proxy|D|stretch
BUD-01|Token & cost budgets|budgets-ledger|D|mvp
BUD-02|Local compute & concurrency|budgets-ledger|D|mvp
SIG-01|External exploit-signature engine|threat-feed|D|mvp
SIG-02|Model-artifact gate (pickle / GGUF)|threat-feed|D|mvp
SIG-03|Package-install / slopsquatting guard|threat-feed|D|mvp
CUS-01|Customer-defined rules|semantic-models|H|mvp
MEM-01|Persistent memory guard (memory & context poisoning)|asi-memory|St|mvp
RES-01|Cascading-failure breaker (quarantine + circuit + taint)|asi-failclosed|St|mvp
A2A-01|Peer identity & message integrity|asi-a2a|D|mvp
A2A-02|Inter-agent smuggling & delegation guard|asi-a2a|H|mvp
ROG-01|Rogue-agent behavioural anomaly detector|asi-rogue|St|mvp
"""

CATALOG: list[CatalogControl] = [
    CatalogControl(*line.split("|")) for line in _ROWS.strip().splitlines()
]
BY_ID: dict[str, CatalogControl] = {c.id: c for c in CATALOG}
STRETCH: set[str] = {c.id for c in CATALOG if c.prio == "stretch"}

FAMILY_FILES = {
    "GOV": "gov.yaml",
    "ACT": "act.yaml",
    "DLP": "dlp.yaml",
    "INJ": "inj.yaml",
    "EXE": "exe.yaml",
    "MCP": "mcp.yaml",
    "BUD": "bud.yaml",
    "SIG": "sig.yaml",
    "CUS": "cus.yaml",
    "MEM": "asi06.yaml",
    "RES": "asi08.yaml",
    "A2A": "asi07.yaml",
    "ROG": "asi10.yaml",
}

SUITES = {
    "cases": "Data-driven cases",
    "approvals": "Approvals & RBAC",
    "budgets": "Budgets & loops",
    "hot-reload": "Hot reload",
    "feed": "Threat feed",
    "mcp": "MCP integrity",
    "hooks": "Claude Code hooks",
    "audit": "Audit & privacy",
    "errors": "Errors",
    "streaming": "Streaming & egress",
    "inline": "Inline policy/feed tests",
    "corpora": "Corpora (rates)",
    "coverage": "Coverage & hygiene",
}

__all__ = ["BY_ID", "CATALOG", "FAMILY_FILES", "STRETCH", "SUITES", "CatalogControl"]
