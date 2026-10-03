"""`aegis.sdk` — tiny client for demo agents, scenes and tests (owner: demo-mocks-docs).

Public import surface (CONTRACTS section 3.3, extended additively per plan 20 section 2.4):

    from aegis.sdk import AegisClient, AegisAdmin, DEMO_AGENTS, DEMO_MEMBERS
    c = AegisClient("http://127.0.0.1:8787", "chaos-agent@platform")   # key from the seed cast
    c.guard(kind="model_call", surface="model.request", text="PESEL 44051401359",
            destination="remote")
    c.chat("hi", model="mock-echo")                     # OpenAI wire; wire="anthropic"/"ollama"
    c.mcp_call("marketpulse", "purchase_subscription", {...}, await_approval_s=120)
    c.egress("POST", "http://pay.saas.test/payments/subscriptions", json={...})
    AegisAdmin(view_as="u_emily").approve("apr_...")

No heavy imports: only httpx (+ `aegis.mcp.client` lazily for MCP calls).
"""

from aegis.sdk.admin import AegisAdmin
from aegis.sdk.cast import (
    DEFAULT_URL,
    DEFAULT_VIEWER,
    DEMO_AGENT_SPONSORS,
    DEMO_AGENT_TEAMS,
    DEMO_AGENTS,
    DEMO_MEMBER_TEAMS,
    DEMO_MEMBERS,
    DISABLED_AGENT,
    EXPIRED_KEY,
    REVOKED_KEY,
    ROLE_ALIASES,
    default_url,
    resolve_member,
)
from aegis.sdk.client import AegisClient, kind_for_surface
from aegis.sdk.results import (
    AegisError,
    ApprovalRequired,
    BudgetExceeded,
    ChatResult,
    Conflict,
    EgressResult,
    Forbidden,
    GatewayUnavailable,
    GuardResult,
    InvalidRequest,
    Killed,
    McpResult,
    NotFound,
    PolicyBlocked,
    RateLimited,
    Unauthenticated,
    UpstreamError,
    approval_from_text,
    control_from_text,
    error_from_response,
)

__all__ = [
    "DEFAULT_URL",
    "DEFAULT_VIEWER",
    "DEMO_AGENTS",
    "DEMO_AGENT_SPONSORS",
    "DEMO_AGENT_TEAMS",
    "DEMO_MEMBERS",
    "DEMO_MEMBER_TEAMS",
    "DISABLED_AGENT",
    "EXPIRED_KEY",
    "REVOKED_KEY",
    "ROLE_ALIASES",
    "AegisAdmin",
    "AegisClient",
    "AegisError",
    "ApprovalRequired",
    "BudgetExceeded",
    "ChatResult",
    "Conflict",
    "EgressResult",
    "Forbidden",
    "GatewayUnavailable",
    "GuardResult",
    "InvalidRequest",
    "Killed",
    "McpResult",
    "NotFound",
    "PolicyBlocked",
    "RateLimited",
    "Unauthenticated",
    "UpstreamError",
    "approval_from_text",
    "control_from_text",
    "default_url",
    "error_from_response",
    "kind_for_surface",
    "resolve_member",
]
