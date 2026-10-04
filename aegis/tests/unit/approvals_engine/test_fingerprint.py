"""APR-V04 (fingerprint part): parameter binding, normalization, volatile keys."""

from __future__ import annotations

from aegis.approvals.fingerprint import canonical_json, fp_draft, fp_interaction
from aegis.core.types import ApprovalDraft, Interaction


def test_numbers_normalized_and_keys_sorted() -> None:
    assert canonical_json({"b": 50.0, "a": [1.0, 2.5]}) == canonical_json({"a": [1, 2.5], "b": 50})


def test_volatile_keys_ignored(h) -> None:
    ident = h.agent("trading-copilot@trading")
    a = h.spend(50.0, extra_args={"request_id": "1", "_meta": {"x": 1}, "cache_control": "e"})
    b = h.spend(50, extra_args={"request_id": "2", "nonce": "n"})
    assert fp_interaction(ident, a) == fp_interaction(ident, b)


def test_params_bound(h) -> None:
    ident = h.agent("trading-copilot@trading")
    assert fp_interaction(ident, h.spend(50.0)) != fp_interaction(ident, h.spend(50.0, plan="other"))
    assert fp_interaction(ident, h.spend(50.0)) != fp_interaction(h.agent("chaos-agent@platform"), h.spend(50.0))


def test_builtin_tool_volatile_keys_but_not_for_mcp_tools(h) -> None:
    ident = h.agent("claude-code@platform")

    def bash(desc: str) -> Interaction:
        return Interaction(kind="tool_call", surface="tool.input", tool_name="Bash",
                           tool_args={"command": "terraform apply", "description": desc, "timeout": 5})

    assert fp_interaction(ident, bash("a")) == fp_interaction(ident, bash("b"))

    def ticket(desc: str) -> Interaction:
        return Interaction(kind="mcp", surface="mcp.call", tool_name="crm.create_ticket",
                           tool_args={"title": "t", "description": desc})

    assert fp_interaction(ident, ticket("a")) != fp_interaction(ident, ticket("b"))


def test_hook_and_mcp_paths_agree(h) -> None:
    """Same normalized tool name + args from the hook (tool.input) and the proxy (mcp.call)."""
    ident = h.agent("claude-code@platform")
    via_proxy = h.spend(480.0, tool="payments.create_charge", vendor="gpucloud")
    via_hook = via_proxy.model_copy(update={"kind": "tool_call", "surface": "tool.input"})
    assert fp_interaction(ident, via_proxy) == fp_interaction(ident, via_hook)


def test_budget_raise_dedupes_per_scope(h) -> None:
    ident = h.agent("chaos-agent@platform")

    def draft(after: float) -> ApprovalDraft:
        return ApprovalDraft(kind="budget_raise", action_type="budget.override", title="raise",
                             resource="budget:agent:chaos-agent@platform",
                             labels={"scope": "agent:chaos-agent@platform", "window": "day",
                                     "dimension": "usd"},
                             payload={"patch": [{"op": "set", "path": "x", "value": after}],
                                      "scope": "agent:chaos-agent@platform", "after": after})

    assert fp_draft(ident, draft(1.0)) == fp_draft(ident, draft(1.37))


def test_fingerprint_is_hmac_not_plain_hash(h) -> None:
    import hashlib

    from aegis.approvals.fingerprint import interaction_material

    ident = h.agent("trading-copilot@trading")
    i = h.spend(50.0)
    plain = hashlib.sha256(canonical_json(interaction_material(ident, i)).encode()).hexdigest()
    fp = fp_interaction(ident, i)
    assert len(fp) == 64 and fp != plain
