"""Executor registry ("apply approved changes").

`register_executor(kind, fn)` follows the contract (last registration wins). Built-in FALLBACKS
live in a separate layer and run only when nobody registered that kind, so registration order
between policy-engine (config_change, budget_raise), mcp-proxy (mcp_pin) and org-rbac (action,
org.* only) is irrelevant.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aegis.core.policy_schema import PatchOp
from aegis.core.types import ApprovalRequest, Identity

log = logging.getLogger(__name__)

Executor = Callable[[ApprovalRequest], Awaitable[dict[str, Any] | None]]
EXECUTOR_TIMEOUT_S = 10.0
#: kinds whose effect is the executor (a grant is consumed by executing it)
EXECUTOR_KINDS = frozenset({"config_change", "budget_raise", "mcp_pin"})


def _approver_identity(req: ApprovalRequest) -> Identity | None:
    approves = [v for v in req.votes if v.decision == "approve"]
    if not approves:
        return None
    last = approves[-1]
    role = last.role if last.role in ("owner", "admin", "member") else "member"
    return Identity(org_id=req.org_id, member_id=last.member_id, role=role)  # type: ignore[arg-type]


def _reason(req: ApprovalRequest) -> str:
    by = ", ".join(req.decided_by) or "auto"
    return f"approved {req.id} (rule {req.rule_id or 'default'}) by {by}"


def _apply_result(result: Any, executor: str) -> dict[str, Any]:
    status = getattr(result, "status", None) or "error"
    errors = [
        getattr(e, "message", str(e)) for e in (getattr(result, "errors", None) or [])
    ]
    return {
        "status": status,
        "policy_version": getattr(result, "version", None),
        "previous_version": getattr(result, "previous_version", None),
        "message": getattr(result, "message", "") or "",
        "errors": errors,
        "executor": executor,
    }


class ExecutorRegistry:
    def __init__(self, rt: Any) -> None:
        self.rt = rt
        self.registered: dict[str, Executor] = {}
        self.fallbacks: dict[str, Executor] = {
            "config_change": self._fallback_policy,
            "budget_raise": self._fallback_policy,
        }

    def register(self, kind: str, fn: Executor) -> None:
        if kind in self.registered:
            log.info("approval executor replaced kind=%s", kind)
        self.registered[kind] = fn

    def has(self, kind: str) -> bool:
        return kind in self.registered or kind in self.fallbacks

    async def run(self, req: ApprovalRequest) -> dict[str, Any] | None:
        """Execute an approved request. Returns the `execution` dict, or None when there is
        nothing to execute (plain agent actions pass via find_preapproved instead)."""
        fn = self.registered.get(req.kind)
        name = "registered"
        if fn is None:
            fn = self.fallbacks.get(req.kind)
            name = "fallback"
        if fn is None:
            if req.kind == "mcp_pin":
                return {"status": "no_executor", "message": "no mcp_pin executor registered",
                        "executor": None}
            return None
        try:
            result = await asyncio.wait_for(fn(req), timeout=EXECUTOR_TIMEOUT_S)
        except TimeoutError:
            log.error("approval executor timed out kind=%s id=%s", req.kind, req.id)
            return {"status": "error", "message": "executor timed out", "executor": name}
        except Exception as exc:
            log.exception("approval executor failed kind=%s id=%s", req.kind, req.id)
            return {"status": "error", "message": f"{type(exc).__name__}: {exc}", "executor": name}
        if result is None:
            if req.kind == "action":
                return None  # e.g. org-rbac's executor ignores non-org actions
            return {"status": "applied", "executor": name}
        out = dict(result) if isinstance(result, dict) else {"result": str(result)}
        out.setdefault("status", "applied")
        out.setdefault("executor", name)
        return out

    # -------------------------------------------------------------- fallback (policy apply)
    async def _fallback_policy(self, req: ApprovalRequest) -> dict[str, Any]:
        policy = getattr(self.rt, "policy", None)
        if policy is None:
            return {"status": "error", "message": "policy store unavailable", "executor": "fallback"}
        payload = req.payload or {}
        proposal = payload.get("proposal") if isinstance(payload.get("proposal"), dict) else {}
        patch = payload.get("patch") or (proposal or {}).get("patch")
        actor = _approver_identity(req)
        if patch:
            try:
                ops = [p if isinstance(p, PatchOp) else PatchOp.model_validate(p) for p in patch]
            except Exception as exc:
                return {"status": "error", "message": f"invalid patch: {exc}", "executor": "fallback"}
            result = await policy.apply_patch(ops, actor=actor, source="approval", reason=_reason(req))
            return _apply_result(result, "fallback")
        yaml_text = (proposal or {}).get("yaml") or payload.get("yaml")
        if isinstance(yaml_text, str) and yaml_text.strip():
            base = (proposal or {}).get("base_version", payload.get("base_version"))
            try:
                current = policy.snapshot().version
            except Exception:
                current = None
            if base is not None and current is not None and int(base) != int(current):
                return {
                    "status": "conflict",
                    "message": f"policy moved on (proposal based on v{base}, current v{current}); "
                    "re-propose the change",
                    "executor": "fallback",
                }
            result = await policy.apply_yaml(
                yaml_text, actor=actor, source="approval", reason=_reason(req), base_version=base
            )
            return _apply_result(result, "fallback")
        return {"status": "error", "message": "approved change has no patch or yaml to apply",
                "executor": "fallback"}


__all__ = ["EXECUTOR_KINDS", "EXECUTOR_TIMEOUT_S", "Executor", "ExecutorRegistry"]
