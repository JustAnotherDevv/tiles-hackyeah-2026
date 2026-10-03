"""Params models (``controls[<id>].params``) for every action-guard control.

Defaults = the balanced profile. Unknown keys are allowed (reported once as a warning by
``runtime.params_for``) so a judge's typo never crashes a request.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aegis.actions.money import DEFAULT_FX
from aegis.actions.net import DEFAULT_METADATA_HOSTS
from aegis.actions.rules_builtin import DB_TOOLS

Sensitivity = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "SECRET"]
SoftAction = Literal["allow", "log", "require_approval", "block"]


class _P(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class PatternSpec(_P):
    id: str = "custom"
    pattern: str
    reason: str | None = None


# ------------------------------------------------------------------ GOV-03
class Gov03Params(_P):
    deny_tools: list[str] = Field(default_factory=list)  # global tool globs -> block
    arg_rules: dict[str, dict[str, str]] = Field(
        default_factory=dict
    )  # tool glob -> {arg: deny RE2}
    check_action_types: bool = True  # agent may only request its Agent.meta.action_types
    enforce_agent_allowlists: bool = True


# ------------------------------------------------------------------ GOV-04
class Gov04Params(_P):
    approve_tools: list[str] = Field(
        default_factory=lambda: ["*.delete_*", "*.drop_*", "acme-crm.export_*"]
    )
    max_pending_per_agent: int = (
        3  # anti human-in-the-loop flooding (shared by every soft decision)
    )
    flood_check: bool = True


# ------------------------------------------------------------------ ACT-01
class Act01Params(_P):
    auto_allow_max_usd: float = 0.0
    hard_block_above_usd: float = 5000.0
    fx_to_usd: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_FX))
    missing_amount: Literal["route_as_max", "block", "require_approval"] = "route_as_max"
    unapproved_vendor: Literal["require_approval", "block", "allow"] = "require_approval"
    price_check: bool = True
    amount_args: list[str] = Field(
        default_factory=lambda: [
            "amount_usd",
            "price.usd",
            "amount",
            "price",
            "total",
            "value",
            "cost",
        ]
    )
    currency_args: list[str] = Field(default_factory=lambda: ["currency", "ccy", "price.currency"])
    vendor_args: list[str] = Field(
        default_factory=lambda: ["vendor", "vendor_id", "merchant", "provider", "payee"]
    )
    plan_args: list[str] = Field(
        default_factory=lambda: ["plan", "plan_id", "sku", "product", "product_id"]
    )
    amount_from_text: bool = False
    text_args: list[str] = Field(
        default_factory=lambda: ["description", "text", "request", "note", "memo"]
    )


# ------------------------------------------------------------------ ACT-02
class TableOverride(_P):
    sensitivity: Sensitivity | None = None
    categories: list[str] | None = None


class Act02Params(_P):
    db_tools: list[str] = Field(default_factory=lambda: list(DB_TOOLS))
    sql_args: list[str] = Field(default_factory=lambda: ["sql", "query", "statement", "q"])
    # tool glob -> {table, rows (int | "all"), database?}; applies only to calls classified db.*
    # (SF-27: CRM lookups are not db.read by default)
    tool_tables: dict[str, dict[str, object]] = Field(default_factory=dict)
    server_databases: dict[str, str] = Field(
        default_factory=lambda: {"acme-db": "acme-prod-pg", "acme-crm": "acme-prod-pg"}
    )
    default_database: str = "acme-prod-pg"
    tables: dict[str, TableOverride] = Field(
        default_factory=dict
    )  # judge lever: per-table overrides
    sensitive_columns: dict[str, Sensitivity] = Field(
        default_factory=lambda: {
            "pan": "RESTRICTED",
            "card_number": "RESTRICTED",
            "*card_no*": "RESTRICTED",
            "cvv": "RESTRICTED",
            "cvc": "RESTRICTED",
            "track*": "RESTRICTED",
            "pesel": "CONFIDENTIAL",
            "*email*": "CONFIDENTIAL",
            "*phone*": "CONFIDENTIAL",
            "iban": "CONFIDENTIAL",
            "*address*": "CONFIDENTIAL",
            "dob": "CONFIDENTIAL",
            "date_of_birth": "CONFIDENTIAL",
            "*passport*": "CONFIDENTIAL",
            "*password*": "SECRET",
            "*api_key*": "SECRET",
            "*secret*": "SECRET",
        }
    )
    unknown_table_sensitivity: Sensitivity = "CONFIDENTIAL"
    auto_allow_max_sensitivity: Sensitivity = "PUBLIC"
    auto_allow_max_rows: int = 1
    aggregate_max_sensitivity: Sensitivity = "INTERNAL"
    block_statements_in_prod: list[str] = Field(
        default_factory=lambda: ["DROP", "TRUNCATE", "ALTER", "GRANT", "REVOKE", "RENAME", "CREATE"]
    )
    restricted_action: Literal["block", "require_approval"] = "block"
    unparseable: SoftAction = "require_approval"
    clamp_rows: int | None = None  # could: append LIMIT n to granted CONFIDENTIAL reads


# ------------------------------------------------------------------ ACT-03
class Act03Params(_P):
    send_tools: list[str] = Field(
        default_factory=lambda: [
            "mailer.send_email",
            "*.send_email",
            "*.post_message",
            "*.send_message",
            "*.upload*",
            "*.webhook*",
            "slack.*",
            "http.post",
            "http.put",
            "http.patch",
        ]
    )
    recipient_args: list[str] = Field(
        default_factory=lambda: ["to", "cc", "bcc", "recipient", "recipients", "channel"]
    )
    body_args: list[str] = Field(
        default_factory=lambda: [
            "body",
            "text",
            "message",
            "content",
            "subject",
            "html",
            "json",
            "data",
            "payload",
            "attachment",
        ]
    )
    url_args: list[str] = Field(default_factory=lambda: ["url", "webhook_url", "endpoint", "uri"])
    max_recipients: int = 10
    deny_recipients: list[str] = Field(default_factory=list)  # domain globs -> block
    denylisted_hosts_action: Literal["block", "require_approval"] = "block"
    deny_hosts: list[str] = Field(default_factory=list)
    block_data_classes: list[Sensitivity] = Field(default_factory=lambda: ["RESTRICTED", "SECRET"])
    internal_domains: list[str] = Field(
        default_factory=list
    )  # extra, on top of destinations.internal_domains


# ------------------------------------------------------------------ ACT-04
class Act04Params(_P):
    deploy_tools: list[str] = Field(default_factory=lambda: ["deploy.*", "*.deploy", "*.deploy_*"])
    shell_tools: list[str] = Field(
        default_factory=lambda: ["Bash", "*.run_command", "*.exec_command", "*.shell"]
    )
    protected_branches: list[str] = Field(
        default_factory=lambda: ["main", "master", "release/*", "prod", "production"]
    )
    env_aliases: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "prod": ["prod", "production", "live", "prd"],
            "staging": ["staging", "stage", "preprod", "stg"],
            "dev": ["dev", "development", "local", "sandbox", "test"],
            "mainline": ["main", "master", "release"],
        }
    )
    category_actions: dict[str, SoftAction] = Field(
        default_factory=lambda: {
            "code.deploy": "require_approval",
            "package.install": "log",
            "code.exec": "log",
        }
    )
    feature_branch_push: SoftAction = "allow"


# ------------------------------------------------------------------ EXE-01
class Exe01Params(_P):
    shell_tools: list[str] = Field(
        default_factory=lambda: [
            "Bash",
            "*.run_command",
            "*.exec_command",
            "*.execute_command",
            "*.shell",
            "terminal.*",
            "*.run_shell",
            "*.exec",
            "shell.*",
        ]
    )
    code_tools: list[str] = Field(
        default_factory=lambda: ["*.run_python", "*.execute_code", "*.run_code", "code.*"]
    )
    command_args: list[str] = Field(
        default_factory=lambda: ["command", "cmd", "script", "code", "commands"]
    )
    sql_args: list[str] = Field(default_factory=lambda: ["sql", "query", "statement"])
    deny_patterns: list[PatternSpec] = Field(default_factory=list)
    approve_patterns: list[PatternSpec] = Field(default_factory=list)
    allow_patterns: list[str] = Field(
        default_factory=lambda: [
            r"^(ls|pwd|cat|head|tail|wc|grep|rg|find|echo|git (status|diff|log|show|branch)|pytest|npm (test|run (build|lint|test))|make (test|lint))\b"
        ]
    )
    unknown_command: SoftAction = "allow"
    disabled_detectors: list[str] = Field(default_factory=list)
    max_scan_chars: int = 20_000
    decode_depth: int = 2


# ------------------------------------------------------------------ EXE-02
class Exe02Params(_P):
    path_args: list[str] = Field(
        default_factory=lambda: [
            "file_path",
            "path",
            "notebook_path",
            "file",
            "filename",
            "source",
            "destination",
            "target",
            "dir",
            "directory",
            "src",
            "dst",
        ]
    )
    url_args: list[str] = Field(
        default_factory=lambda: [
            "url",
            "uri",
            "endpoint",
            "href",
            "webhook",
            "webhook_url",
            "link",
            "base_url",
        ]
    )
    write_tools: list[str] = Field(
        default_factory=lambda: [
            "Write",
            "Edit",
            "MultiEdit",
            "NotebookEdit",
            "*.write_*",
            "*.edit_*",
            "*.create_file",
            "*.delete_file",
            "*.move_file",
        ]
    )
    fs_allow_exceptions: list[str] = Field(
        default_factory=lambda: [
            "**/.env.example",
            "**/.env.sample",
            "**/.env.template",
            "**/.env.dist",
            "**/*.pub",
        ]
    )
    fs_deny: list[str] = Field(
        default_factory=lambda: [
            "~/.ssh/**",
            "~/.aws/**",
            "~/.gnupg/**",
            "~/.config/gcloud/**",
            "~/.kube/config",
            "~/.docker/config.json",
            "~/.netrc",
            "~/.npmrc",
            "~/.pypirc",
            "**/.env",
            "**/.env.*",
            "**/*.pem",
            "**/*.key",
            "**/id_rsa",
            "**/id_ed25519",
            "**/id_ecdsa",
            "~/.claude/**",
            "~/.cursor/mcp.json",
            "**/.mcp.json",
            "~/Library/Keychains/**",
            "/etc/shadow",
            "/etc/sudoers",
            "**/demo/claude/settings*.json",
            "**/demo/claude/mcp.json",
            "**/demo/claude/.agent_key",
            "**/.claude/settings*.json",
            "**/scripts/aegis-hook",
        ]
    )
    fs_write_deny: list[str] = Field(
        default_factory=lambda: [
            "~/.zshrc",
            "~/.bashrc",
            "~/.bash_profile",
            "~/.profile",
            "~/.zprofile",
            "~/.zshenv",
            "**/.git/hooks/**",
            "**/.git/config",
            "~/Library/LaunchAgents/**",
            "/Library/LaunchDaemons/**",
            "**/.claude/settings*.json",
            "**/.mcp.json",
            "~/.cursor/**",
            "/etc/**",
            "~/.ssh/authorized_keys",
        ]
    )
    fs_allow: list[str] = Field(default_factory=list)  # non-empty -> everything else is blocked
    resolve_symlinks: bool = True
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    block_private_ranges: bool = True
    metadata_hosts: list[str] = Field(default_factory=lambda: list(DEFAULT_METADATA_HOSTS))
    allow_hosts: list[str] = Field(
        default_factory=lambda: [
            "127.0.0.1:8790-8799",
            "localhost:8790-8799",
            "127.0.0.1:11434",
            "localhost:11434",
        ]
    )
    deny_hosts: list[str] = Field(default_factory=list)
    use_catalog_denylist: bool = False  # DLP-04 / ACT-03 own the seed external-host denylist
    max_scan_chars: int = 20_000


# ------------------------------------------------------------------ EXE-03
class Exe03Params(_P):
    private_sources: list[str] = Field(
        default_factory=lambda: ["acme-crm.*", "*.lookup_customer", "*.get_customer"]
    )
    private_min_sensitivity: Sensitivity = "CONFIDENTIAL"
    untrusted_sources: list[str] = Field(
        default_factory=lambda: [
            "web.*",
            "WebFetch",
            "WebSearch",
            "*.fetch_url",
            "http.get",
            "browser.*",
        ]
    )
    untrusted_destinations: list[str] = Field(default_factory=lambda: ["third_party"])
    exfil_actions: list[str] = Field(
        default_factory=lambda: ["email.external", "egress.post", "code.deploy"]
    )
    exfil_tools: list[str] = Field(
        default_factory=lambda: ["*.upload*", "*.webhook*", "slack.*", "http.post"]
    )
    taint_ttl_turns: int = 20
    taint_ttl_s: float = 3600.0


CONTROL_PARAMS: dict[str, type[_P]] = {
    "GOV-03": Gov03Params,
    "GOV-04": Gov04Params,
    "ACT-01": Act01Params,
    "ACT-02": Act02Params,
    "ACT-03": Act03Params,
    "ACT-04": Act04Params,
    "EXE-01": Exe01Params,
    "EXE-02": Exe02Params,
    "EXE-03": Exe03Params,
}

__all__ = [
    "CONTROL_PARAMS",
    "Act01Params",
    "Act02Params",
    "Act03Params",
    "Act04Params",
    "Exe01Params",
    "Exe02Params",
    "Exe03Params",
    "Gov03Params",
    "Gov04Params",
    "PatternSpec",
    "TableOverride",
]
