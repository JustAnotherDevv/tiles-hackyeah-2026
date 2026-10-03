"""Governed policy changes: `propose()` internals + approval executors.

propose(actor, yaml|patch):
  1 base_version check -> conflict          2 candidate text (patch rebased on the live text)
  3 validate + self-test gate (no swap)     4 diff_docs -> noop / comments-only -> apply
  5 persist proposal (pol_...) + build the `config.change` Interaction (segments=[], resource =
    "policy:<sha16>" so different proposals never share an approval fingerprint)
  6 rt.pipeline.evaluate (live policy; GOV-05 routes via approvals.config_rules):
      allow/log/redact -> apply · require_approval + approval -> pending_approval · else rejected
  7 GOV-05 not registered -> rt.approvals.route() fallback; approvals unavailable -> owner only.
Executors (`config_change`, `budget_raise`) apply the approved proposal: patches are rebased on
the current text; full-YAML proposals conflict if the policy moved on meanwhile.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

from aegis.core.policy_schema import ApplyResult, PatchOp, PolicyChange, ValidationIssue
from aegis.core.types import (
    APPROVER_RANK,
    ROLE_RANK,
    ApprovalDraft,
    ApprovalRequest,
    Destination,
    Identity,
    Interaction,
    new_id,
)
from aegis.policy.diff import diff_docs, primary_kind, summarize
from aegis.policy.patch import PatchError, apply_patch_text

if TYPE_CHECKING:
    from aegis.policy.store import PolicyStoreImpl

log = logging.getLogger(__name__)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _who(actor: Identity | None) -> str:
    if actor is None:
        return "file"
    return actor.member_id or actor.agent_id or "anonymous"


def _is_null(obj: Any) -> bool:
    try:
        from aegis.core.nulls import is_null

        return bool(is_null(obj))
    except Exception:
        return obj is None


async def propose(
    store: PolicyStoreImpl,
    actor: Identity,
    *,
    yaml_text: str | None = None,
    patch: list[PatchOp] | None = None,
    reason: str | None = None,
    base_version: int | None = None,
    source: str = "dashboard",
    apply_source: str = "api",
) -> ApplyResult:
    rt = store.rt
    cur = store.snapshot()
    if base_version is not None and base_version != cur.version:
        return ApplyResult(status="conflict", version=cur.version, previous_version=cur.version,
                           message=f"policy is at v{cur.version}, you edited v{base_version}")
    patch_ops = [p if isinstance(p, PatchOp) else PatchOp.model_validate(p) for p in (patch or [])]
    if yaml_text is None and not patch_ops:
        return ApplyResult(status="rejected", version=cur.version, message="nothing to apply",
                           errors=[ValidationIssue(message="provide yaml or a non-empty patch")])
    if yaml_text is None:
        try:
            candidate_text = apply_patch_text(store.current_yaml(), patch_ops)
        except PatchError as exc:
            err = ValidationIssue(path=exc.path, message=exc.message)
            return ApplyResult(status="rejected", version=cur.version, errors=[err],
                               message=f"rejected: {exc.path}: {exc.message}")
    else:
        candidate_text = yaml_text
    sha = _sha(candidate_text)
    if sha == cur.sha256:
        return ApplyResult(status="noop", version=cur.version, previous_version=cur.version,
                           message="no changes")

    cand, validated, _profiles = store.build_candidate(candidate_text, version=cur.version + 1,
                                                      source=apply_source, actor=actor)
    if cand is None:
        await store.publish_rejected(source, validated.errors, sha)
        return store.rejected_result(validated.errors, cur.version)
    gate_errors, _gate_warnings, _run = await store.gate(cand, cur)
    if gate_errors:
        await store.publish_rejected(source, gate_errors, sha)
        return store.rejected_result(gate_errors, cur.version)

    changes = diff_docs(cur.doc, cand.doc)
    if not changes:  # comments / formatting only: never routed to approval
        return await store.apply_yaml(candidate_text, actor=actor, source=apply_source, reason=reason,
                                      base_version=cur.version)

    proposal_id = new_id("pol")
    proposal: dict[str, Any] = {"proposal_id": proposal_id, "sha256": sha, "base_version": cur.version,
                                "reason": reason, "source": source}
    if patch_ops and yaml_text is None:
        proposal["patch"] = [p.model_dump(mode="json") for p in patch_ops]
    else:
        proposal["yaml_sha256"] = sha  # full text stays in policy_proposals (not in approval payloads)
    store.versions.insert_proposal(
        id=proposal_id, actor=actor, source=source, base_version=cur.version, sha256=sha,
        yaml=candidate_text if yaml_text is not None else None,
        patch=proposal.get("patch"), reason=reason, changes=changes)
    pkind = primary_kind(changes)
    interaction = Interaction(
        kind="config_change", surface="config.change", direction="out",
        destination=Destination(name="aegis", dest_class="local"), segments=[],
        action_type=pkind, resource=f"policy:{sha[:16]}",
        meta={"changes": [c.model_dump(mode="json") for c in changes], "proposal": proposal},
    )

    def apply_now(decision_id: str | None = None) -> Any:
        return _apply_proposal_now(store, actor, candidate_text, sha, apply_source, reason, cur.version,
                                   proposal_id, changes, decision_id)

    controls = getattr(rt, "controls", None)
    gov05 = None
    try:
        gov05 = controls.get("GOV-05") if controls is not None else None
    except Exception:
        gov05 = None
    pipeline = getattr(rt, "pipeline", None)
    if gov05 is not None and pipeline is not None and cur.controls.get("GOV-05") is not None:
        try:
            ctx = pipeline.new_context(source=source if source in _SOURCES else "dashboard", identity=actor,
                                       session_id=f"ses_policy_{actor.member_id or actor.agent_id or 'anon'}")
            verdict = await pipeline.evaluate(ctx, interaction)
        except Exception:
            log.exception("governance pipeline failed proposal=%s", proposal_id)
            store.versions.update_proposal(proposal_id, status="rejected")
            return ApplyResult(status="rejected", version=cur.version, changes=changes,
                               message="governance unavailable (fail-closed)")
        action = verdict.action
        if action in ("allow", "log", "redact"):
            return await apply_now(verdict.id)
        if action == "require_approval" and verdict.approval is not None:
            apr = verdict.approval
            store.versions.update_proposal(proposal_id, status="pending", approval_id=apr.id,
                                           decision_id=verdict.id)
            return ApplyResult(status="pending_approval", version=cur.version, approval=apr,
                               decision_id=verdict.id, changes=changes,
                               message=f"needs {apr.required_role} approval ({apr.id})")
        store.versions.update_proposal(proposal_id, status="rejected", decision_id=verdict.id)
        msg = (verdict.primary.reason if verdict.primary else "") or "rejected by policy"
        return ApplyResult(status="rejected", version=cur.version, decision_id=verdict.id, changes=changes,
                           message=msg)

    # ---- fallback: GOV-05 not registered -> route ourselves
    approvals = getattr(rt, "approvals", None)
    if approvals is None or _is_null(approvals):
        if actor.role == "owner":
            return await apply_now()
        store.versions.update_proposal(proposal_id, status="rejected")
        return ApplyResult(status="rejected", version=cur.version, changes=changes,
                           message="approvals unavailable (fail-closed): only an owner may change the policy")
    try:
        route = approvals.route(kind="config_change", action_type=pkind, requester=actor, changes=changes)
    except Exception:
        log.exception("approvals.route failed proposal=%s", proposal_id)
        if actor.role == "owner":
            return await apply_now()
        store.versions.update_proposal(proposal_id, status="rejected")
        return ApplyResult(status="rejected", version=cur.version, changes=changes,
                           message="approvals unavailable (fail-closed)")
    need = route.required_role
    if need == "deny":
        store.versions.update_proposal(proposal_id, status="rejected")
        return ApplyResult(status="rejected", version=cur.version, changes=changes,
                           message=f"denied by approval rule {route.rule_id}")
    if need == "auto" or (APPROVER_RANK.get(need, 99) <= ROLE_RANK.get(actor.role, 0) and actor.role != "agent"
                          and not route.two_person):
        return await apply_now()
    try:
        draft = ApprovalDraft(kind="config_change", action_type=pkind, title=summarize(changes),
                              summary=reason, resource=f"policy:{sha[:16]}",
                              payload={"proposal": proposal, "changes": [c.model_dump(mode="json") for c in changes]})
        apr = await approvals.create_manual(actor, draft)
    except Exception:
        log.exception("approvals.create_manual failed proposal=%s", proposal_id)
        store.versions.update_proposal(proposal_id, status="rejected")
        return ApplyResult(status="rejected", version=cur.version, changes=changes,
                           message="approvals unavailable (fail-closed)")
    if apr.status == "approved":
        cur2 = store.snapshot()
        if cur2.sha256 == sha:
            return ApplyResult(status="applied", version=cur2.version, previous_version=cur.version,
                               approval=apr, changes=changes, message=f"applied v{cur2.version}")
        return await apply_now()
    if apr.status in ("denied", "expired", "cancelled"):
        store.versions.update_proposal(proposal_id, status=apr.status, approval_id=apr.id)
        return ApplyResult(status="rejected", version=cur.version, approval=apr, changes=changes,
                           message=f"approval {apr.status}")
    store.versions.update_proposal(proposal_id, status="pending", approval_id=apr.id)
    return ApplyResult(status="pending_approval", version=cur.version, approval=apr, changes=changes,
                       message=f"needs {apr.required_role} approval ({apr.id})")


_SOURCES = {"proxy", "mcp", "hook", "guard", "egress", "playground", "dashboard", "selftest", "test"}


async def _apply_proposal_now(store: PolicyStoreImpl, actor: Identity, text: str, sha: str, apply_source: str,
                              reason: str | None, base_version: int, proposal_id: str,
                              changes: list[PolicyChange], decision_id: str | None) -> ApplyResult:
    cur = store.snapshot()
    if cur.sha256 == sha:  # already applied (e.g. auto-approved executor ran inside the pipeline)
        store.versions.update_proposal(proposal_id, status="applied", applied_version=cur.version,
                                       decision_id=decision_id)
        return ApplyResult(status="applied", version=cur.version, previous_version=base_version,
                           decision_id=decision_id, changes=changes, message=f"applied v{cur.version}")
    res = await store.apply_yaml(text, actor=actor, source=apply_source, reason=reason, base_version=base_version,
                                 _proposal_id=proposal_id)
    res.decision_id = decision_id
    store.versions.update_proposal(proposal_id, status=res.status, decision_id=decision_id,
                                   applied_version=res.version if res.status == "applied" else None)
    return res


# ---------------------------------------------------------------- executors
def _lookup(store: PolicyStoreImpl, req: ApprovalRequest) -> dict[str, Any] | None:
    payload = req.payload or {}
    prop = payload.get("proposal") if isinstance(payload.get("proposal"), dict) else None
    row = None
    if prop and prop.get("proposal_id"):
        row = store.versions.get_proposal(str(prop["proposal_id"]))
    if row is None and req.decision_id:
        row = store.versions.find_proposal_by_decision(req.decision_id)
    if row is None and req.resource and str(req.resource).startswith("policy:"):
        row = store.versions.find_proposal_by_sha_prefix(str(req.resource).split(":", 1)[1])
    if row is not None:
        return row
    patch = payload.get("patch") or (prop or {}).get("patch")
    yaml_text = payload.get("yaml") or (prop or {}).get("yaml")
    if patch or yaml_text:
        return {"id": None, "patch": patch, "yaml": yaml_text,
                "base_version": (prop or {}).get("base_version"), "reason": (prop or {}).get("reason") or req.summary}
    return None


async def execute(store: PolicyStoreImpl, req: ApprovalRequest) -> dict[str, Any]:
    """Approval executor for kinds config_change and budget_raise."""
    prop = _lookup(store, req)
    if prop is None:
        return {"status": "rejected", "errors": [{"message": "proposal not found"}],
                "message": "proposal not found"}
    approvers = ", ".join(req.decided_by) or "approver"
    base_reason = prop.get("reason") or req.title
    reason = f"{base_reason} · approved by {approvers} ({req.id})"
    cur = store.snapshot()
    patch = prop.get("patch")
    if isinstance(patch, str):
        try:
            patch = json.loads(patch)
        except ValueError:
            patch = None
    try:
        if patch:
            text = apply_patch_text(store.current_yaml(), [PatchOp.model_validate(p) for p in patch])
        elif prop.get("yaml"):
            if prop.get("base_version") is not None and int(prop["base_version"]) != cur.version:
                if prop.get("id"):
                    store.versions.update_proposal(prop["id"], status="conflict")
                return {"status": "conflict", "errors": [],
                        "message": f"policy moved to v{cur.version} since v{prop['base_version']}; re-propose"}
            text = prop["yaml"]
        else:
            return {"status": "rejected", "errors": [{"message": "empty proposal"}], "message": "empty proposal"}
    except PatchError as exc:
        if prop.get("id"):
            store.versions.update_proposal(prop["id"], status="rejected")
        return {"status": "rejected", "errors": [{"path": exc.path, "message": exc.message}],
                "message": f"patch no longer applies: {exc.message}"}
    res = await store.apply_yaml(text, actor=req.requester, source="approval", reason=reason,
                                 _proposal_id=prop.get("id"), _approval_id=req.id)
    if prop.get("id"):
        store.versions.update_proposal(prop["id"], status=res.status if res.status != "noop" else "applied",
                                       approval_id=req.id,
                                       applied_version=res.version if res.status in ("applied", "noop") else None)
    if res.status in ("applied", "noop"):
        return {"status": "applied", "policy_version": res.version, "message": res.message}
    return {"status": res.status, "errors": [e.model_dump(mode="json") for e in res.errors],
            "message": res.message, "policy_version": res.version}


def register_executors(store: PolicyStoreImpl) -> bool:
    approvals = getattr(store.rt, "approvals", None)
    reg = getattr(approvals, "register_executor", None)
    if not callable(reg):
        return False

    async def _exec(req: ApprovalRequest) -> dict[str, Any] | None:
        return await execute(store, req)

    try:
        reg("config_change", _exec)
        reg("budget_raise", _exec)
        return True
    except Exception:
        log.exception("register_executor failed")
        return False


__all__ = ["execute", "propose", "register_executors"]
_ = _who
