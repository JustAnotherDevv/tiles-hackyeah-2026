"""Built-in action classification table.

Used ONLY when the evaluated policy has an empty ``actions:`` list (logged once as degraded).
It mirrors ``config/snippets/action-guards.yaml`` ``actions:`` (kept in sync by
``tests/unit/action_guards/test_snippet.py``). ORDER MATTERS: first match wins; ACT-02/03/04
refine ``db.*`` / ``email.*`` / ``code.*`` during enrich.
"""

from __future__ import annotations

from typing import Any

from aegis.core.policy_schema import ActionRule

DB_TOOLS = ["acme-db.query", "*.query_sql", "*.run_sql", "*.execute_sql", "sql.*"]
# SF-27: CRM lookups are NOT db.read (no per-call approval); acme-crm.export_* -> GOV-04.

_RAW: list[dict[str, Any]] = [
    # --- spend (ACT-01): MCP / tool calls
    {
        "id": "spend.subscription",
        "category": "spend",
        "tools": ["marketpulse.purchase_subscription", "*.purchase_subscription", "*.subscribe"],
        "amount_arg": "amount_usd",
        "resource_arg": "vendor",
        "resource_prefix": "vendor:",
        "title": "{agent} wants to spend ${amount} on {vendor_name} {plan}",
    },
    {
        "id": "spend.charge",
        "category": "spend",
        "tools": [
            "payments.create_charge",
            "*.create_charge",
            "*.checkout*",
            "*.top_up*",
            "*.purchase*",
        ],
        "amount_arg": "amount_usd",
        "resource_arg": "vendor",
        "resource_prefix": "vendor:",
        "title": "{agent} wants to pay ${amount} to {vendor_name} {plan}",
    },
    {
        "id": "spend.transfer",
        "category": "spend",
        "tools": ["*.transfer_funds", "*.wire_transfer", "*.send_payment", "payments.transfer*"],
        "amount_arg": "amount_usd",
        "title": "{agent} wants to transfer ${amount}",
    },
    # --- spend via /egress to the mock payments API (Addendum A-13: tool_args = {method, url, json, body})
    {
        "id": "spend.subscription",
        "category": "spend",
        "surfaces": ["egress.request"],
        "url_hosts": ["pay.saas.test"],
        "args_match": {"method": "^POST$", "url": "/payments/subscriptions"},
        "amount_arg": "json.amount_usd",
        "resource_arg": "json.vendor",
        "resource_prefix": "vendor:",
        "title": "{agent} wants to spend ${amount} on {vendor_name} {plan}",
    },
    {
        "id": "spend.charge",
        "category": "spend",
        "surfaces": ["egress.request"],
        "url_hosts": ["pay.saas.test"],
        "args_match": {"method": "^POST$", "url": "/payments/charges"},
        "amount_arg": "json.amount_usd",
        "resource_arg": "json.vendor",
        "resource_prefix": "vendor:",
        "title": "{agent} wants to pay ${amount} to {vendor_name} {plan}",
    },
    # --- data (ACT-02 refines operation/tables/sensitivity/env from the SQL + rt.org.resources())
    {
        "id": "db.schema",
        "category": "data_write",
        "tools": DB_TOOLS,
        "args_match": {"sql": r"(?i)^\s*(drop|alter|truncate|create|grant|revoke|rename)\b"},
        "resource_arg": "sql",
        "resource_regex": r"(?i)\b(?:table|into|from)\s+([a-z_][a-z0-9_\.]*)",
        "resource_prefix": "db:",
    },
    {
        "id": "db.write",
        "category": "data_write",
        "tools": DB_TOOLS,
        "args_match": {"sql": r"(?i)^\s*(insert|update|delete|merge|replace|upsert|copy)\b"},
        "resource_arg": "sql",
        "resource_regex": r"(?i)\b(?:into|update|from|table)\s+([a-z_][a-z0-9_\.]*)",
        "resource_prefix": "db:",
    },
    {
        "id": "db.read",
        "category": "data_read",
        "tools": DB_TOOLS,
        "resource_arg": "sql",
        "resource_regex": r"(?i)\bfrom\s+([a-z_][a-z0-9_\.]*)",
        "resource_prefix": "db:",
    },
    # --- external send (ACT-03 decides internal vs external per recipient)
    {
        "id": "email.external",
        "category": "external_send",
        "tools": ["mailer.send_email", "*.send_email"],
        "args_match": {"to": "@"},
        "args_not_match": {"to": r"(?i)@([a-z0-9-]+\.)*acme-capital\.example\s*$"},
        "title": "{agent} wants to email {args.to}",
    },
    {"id": "email.internal", "category": "other", "tools": ["mailer.send_email", "*.send_email"]},
    {
        "id": "egress.post",
        "category": "external_send",
        "surfaces": ["egress.request"],
        "args_match": {"method": "^(POST|PUT|PATCH)$"},
    },
    {
        "id": "egress.post",
        "category": "external_send",
        "tools": [
            "*.post_message",
            "*.send_message",
            "*.upload*",
            "*.webhook*",
            "slack.*",
            "http.post",
            "http.put",
            "http.patch",
        ],
    },
    {
        "id": "egress.get",
        "category": "other",
        "tools": ["WebFetch", "web.fetch_url", "http.get", "*.fetch_url"],
    },
    {"id": "egress.get", "category": "other", "surfaces": ["egress.request"]},
    # --- code (ACT-04 / SIG-03); SIG-03 owns approval of unknown packages, ACT-04 logs package.install
    {
        "id": "code.deploy",
        "category": "code_exec",
        "tools": ["Bash"],
        "args_match": {
            "command": r"(?i)\b(terraform\s+(apply|destroy)|kubectl\s+(apply|delete|rollout|scale)|helm\s+(install|upgrade|uninstall)|git\s+push\b|vercel\b.*--prod|fly\s+deploy|serverless\s+deploy|gcloud\s+run\s+deploy|docker\s+push)"
        },
    },
    {
        "id": "package.install",
        "category": "code_exec",
        "tools": ["Bash"],
        "args_match": {
            "command": r"(?i)\b(pip3?|uv\s+pip|uv|poetry|npm|pnpm|yarn|brew|apt(-get)?|gem|cargo|go)\s+(install|add|i)\b"
        },
    },
    {
        "id": "egress.post",
        "category": "external_send",
        "tools": ["Bash"],
        "args_match": {
            "command": r"(?i)\bcurl\b.*\s(-d|--data[a-z-]*|-F|--form|-T|--upload-file|-X\s*(POST|PUT|PATCH))(\s|=|$)"
        },
    },
    {
        "id": "code.exec",
        "category": "code_exec",
        "tools": ["Bash"],
        "args_match": {
            "command": r"(?i)\b((docker|podman)\s+run|ssh|scp|rsync|python3?\s+-c|node\s+-e)\b"
        },
    },
]

BUILTIN_RULES: list[ActionRule] = [ActionRule.model_validate(r) for r in _RAW]

__all__ = ["BUILTIN_RULES", "DB_TOOLS"]
