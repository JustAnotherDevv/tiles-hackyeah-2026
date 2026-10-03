# 09 · approvals-engine — Approvals engine & approval policies

Workstream `approvals-engine` · task prefix `APR` · owner paths (CONTRACTS §1.2): `src/aegis/approvals/**`, `src/aegis/controls/config/**` (GOV-05), route `src/aegis/api/routes/approvals.py`, `config/snippets/approvals-engine.yaml`, `tests/unit/approvals_engine/**`, this file.
Inputs read: `docs/BRIEF.md`, `docs/CONTRACTS.md` (§1–§8, especially §3.1 approvals types, §3.2 `ApprovalService`, §3.5 approval semantics, §4.2 `ApprovalsSection`, §5.4/§5.5 approvals API, §6.1 `approvals` table, §6.3 SSE, §8 F4/F5/F6/F9), `staging/seed/approvals.yaml` (65 rules, 34 routing tests), `staging/seed/org.seed.yaml`, `staging/seed/SCENARIOS.md` (#2–#12), `staging/seed/policy.yaml` (GOV-04, control severities), `staging/spikes/claude-code/FINDINGS.md`, research `01` (ASI09, T10, ACS `ask`) and `02` (hook decisions, MCP pinning approvals).

---

## 1. Goal & demo value

Approvals are the governance differentiator. Other teams will show "blocked". We show who in the organisation may say yes, and the system enforcing that decision. What judges see:

- **F4, agent action approvals by role.** `trading-copilot@trading` buys MarketPulse Pro for $50. The call is held (MCP proxy or Claude Code hook), a toast appears, and an Approvals card says **"needs admin — rule spend-admin"**.
  - View as **Piotr** (the sponsor): Approve is disabled, with the reason *"Separation of duties: you sponsor trading-copilot@trading"*.
  - Switch to **Emily** (admin) → Approve → the held call goes through within about 100 ms. The live feed shows `allow · approved by u_emily (apr_…)`.
  - $12 dataset → Agnieszka self-approves. $480 GPU → owner only. $1,500 → owner plus a second admin (shows 1/2 → 2/2). `payment_cards` → **denied, no button**. `DELETE FROM trades` on prod → owner.
- **F5, config governance.** Piotr raises `team:trading` from $60 to $75 a day (+25 %). GOV-05 routes it to an admin. Emily approves → the executor applies the patch → policy v+1 → the budget gauges rescale live. $60 → $150 needs the owner. Marek (admin) disabling DLP-02 (critical) needs the owner. When the owner makes an edit, it applies immediately.
- **F6 / F9.** A BUD-01 `budget_raise` and an MCP-03 `mcp_pin` re-pin go through the same inbox and executors.
- **Proof.** Every transition is in the hash-chained audit log (`approval.created/decided/expired/executed`). There are SSE live updates, Prometheus counters (`aegis_approvals_total`, `aegis_approvals_pending`), and **34 ported routing tests plus the contract-flow tests**, which also re-run after every live policy edit and warn if a judge's edit breaks a routing expectation.

Judging criteria served: guardrail robustness (fail-closed approvals, parameter-bound single-use grants, replay protection, anti-flooding: ASI09 and T10), security reporting (audit trail, metrics, inbox), architecture (one routing engine for agent actions and config changes, plug-in executors), self-testing (routing tests run in the unit suite and after every policy reload), and practical implementability (role-based, legible rules in the single `policy.yaml`; aligned with the ACS `ask` disposition).

---

## 2. Design

### 2.1 Files (all inside owned paths)

| Path | Purpose |
|---|---|
| `src/aegis/approvals/__init__.py` | empty (no import-time side effects) |
| `src/aegis/approvals/service.py` | `create(rt) -> ApprovalsService`. Implements `ApprovalService` (§3.2) + `start()/stop()`; extras used by my route: `view(req, viewer)`, `counts()`, `rules_view()`, `simulate()`, `sweep()`, `run_routing_selftest()` |
| `src/aegis/approvals/routing.py` | Pure, sync rule engine: `compile_rules(doc)`, `match(rule, facts)`, `route_one(...)`, `route_many(...)`, `describe_when(rule) -> str`. Cached per policy version in `snap.compiled["approvals-engine:rules"]` |
| `src/aegis/approvals/facts.py` | Builds the fact dict a rule is matched against: `facts_for_action(...)`, `facts_for_change(change, snap, org_cache, requester)`, `OrgCache` (members/agents/resources snapshot) |
| `src/aegis/approvals/eligibility.py` | `satisfies(role, level)`, `can_approve(voter, req, org_cache) -> (bool, why)`, `tally(req) -> "approved"|"pending"|"denied"`, `proposer_satisfies(identity, route)`, `eligible_members(req, org_cache)` |
| `src/aegis/approvals/fingerprint.py` | `canonical_json()`, `VOLATILE_KEYS`, `fp_interaction(identity, interaction)`, `fp_draft(identity, draft)` via `aegis.core.crypto.hmac_hex(purpose="approval")` (guarded fallback: local HMAC + WARNING) |
| `src/aegis/approvals/store.py` | SQLite DDL (exactly §6.1) + row↔`ApprovalRequest` mapping, CRUD, `pending_by_fp`, `redeemable_by_fp`, `due_for_expiry`, `counts` |
| `src/aegis/approvals/expiry.py` | `sweep(now)`: expire pending, (could) remind/escalate; background loop (skipped when `AEGIS_TEST_MODE=1`) |
| `src/aegis/approvals/executors.py` | Executor registry with **separate fallback layer**; fallback `config_change`/`budget_raise` executor → `rt.policy.apply_patch` / `apply_yaml`; `run_executor(req)` with timeout and error capture |
| `src/aegis/approvals/notify.py` | One choke point per transition: audit `AuditEvent`, SSE `approval.created`/`approval.updated` (payload trimmed), metrics, waking waiters |
| `src/aegis/approvals/views.py` | `ApprovalRuleView` building, human-readable `when`, `why_not` texts, SSE/list payload trimming |
| `src/aegis/approvals/seed.py` | (should) seeds `demo_state.approval_history` (3 resolved requests) when the table is empty |
| `src/aegis/approvals/selftest.py` | Runs `approvals.tests` (ported routing tests) against a snapshot and returns results; used by unit tests and post-apply checks |
| `src/aegis/controls/config/__init__.py` | empty |
| `src/aegis/controls/config/gov05_config.py` | `CONTROLS = [ConfigChangeGovernance()]` (GOV-05) |
| `src/aegis/api/routes/approvals.py` | `router` serving `/api/approvals*` (§5.4) + 1 extension (`/wait`) |
| `config/snippets/approvals-engine.yaml` | `approvals:` section (defaults, `rules`, `config_rules`, `tests`) + GOV-05 control entry (§7 below) |
| `tests/unit/approvals_engine/conftest.py` | Fakes (FakeRuntime/Policy/Org/Bus/Audit/Metrics/Redactor/Feed) + fixtures. Fakes live in conftest because of `--import-mode=importlib` |
| `tests/unit/approvals_engine/test_*.py` | routing (seed + contract flows), eligibility, fingerprint, lifecycle, executors, GOV-05, API, privacy, integration (skips if the runtime is missing) |

### 2.2 Data flow

```
                      ┌────────────── policy.yaml approvals: {defaults, rules, config_rules, tests}
                      ▼
 ACT-01..04 / GOV-04 / BUD-01 / MCP-03 ──ApprovalDraft──┐
 GOV-05 (config.change via rt.policy.propose) ─────────┤
                                                        ▼
 pipeline §3.5 step 9:  find_preapproved(ctx,i) ── hit ──► allow ("approved by u_emily (apr_…)")
                          │ miss
                          ▼
                       request(ctx,i,decision) ── route() → auto ⇒ approved · deny ⇒ denied · else pending
                          │   (reuse pending by fingerprint; flood caps; co-sign; SQLite; audit; SSE; metrics)
                          ▼
                       wait(id, hold_s[source])  ◄── vote() / cancel() / sweep() wake the waiter
                          │
     dashboard ── POST /api/approvals/{id}/approve ──► vote(): can_approve → tally → approved
                          │                                   └─► executor(kind) → execution{policy_version…}
                          ▼                                       (config_change/budget_raise → policy apply → hot reload
 held surface passes / agent retries (same fingerprint or X-Aegis-Approval)  → policy.applied → ledger limits)
```

### 2.3 Routing (`route()`) — adapting staging's "most restrictive wins" to the contract's "first match wins"

- **Contract semantics are kept.** The first matching rule wins: `approvals.rules` for kinds `action|budget_raise|mcp_pin`, `approvals.config_rules` for `config_change`. With no match, the result is `defaults.default_approver` (admin) / `default_config_approver` (owner). A config proposal with N changes routes each change and takes the max `APPROVER_RANK`, with `two_person` OR-ed, the min TTL, and the rule id of the max.
- **Staging semantics are kept by ordering.** Every family is written *most restrictive first* (deny → owner two-person → owner → admin → self → auto), followed by a fail-closed catch-all. Staging's TTL-only rule (`APR-DATA-STRICT-SHORT-GRANTS`) is folded into rule TTLs. All 65 staging rules are mapped in §3.2. The routing tests are the safety net.
- **Rule conditions are matched against a fact dict.**
  - Contract `ApprovalWhen` fields: `kind`, `action` (globs over `action_type` or change kind), `amount_usd_gt/lte`, `resource_in`, `labels` (glob per key), `teams`, `agents`, `scope_type`, `increase_pct_gt/lte`.
  - Extras I add (allowed: `_Section` has `extra="allow"`): `profiles: [strict|balanced|…]` (active `doc.profile`), `labels_in: {key: [values]}`, `signals_any: [..]` (comma-split `labels["signals"]`).
  - Missing numbers are fail-closed: `amount_usd`/`increase_pct` = `None` makes `*_gt` true and `*_lte` false, so routing goes to the highest tier (ACT-01 `missing_amount: route_as_max`).
  - An unknown condition key means the rule is not satisfied, with a WARNING logged once per policy version. A typo can therefore never quietly route to `auto`, because the fail-closed catch-alls follow.
- **Facts for actions.** These are `interaction.labels ∪ draft.labels`, plus derived facts when a label is missing:
  - `dest` (destination class), `requester_kind`, `requester_role`.
  - For `resource=vendor:<id>`: `vendor_approved` and `recurring` (from the matching plan) via `rt.org.resources()["vendors"]`.
  - For `resource=db:<table>`: `sensitivity` and `env` from `resources.databases` (prod first). ACT-02 normally sets these already.
- **Facts for config changes** (`facts_for_change`, one per `PolicyChange`):
  - `control_id` and `control_severity` (the max of the current snapshot and the proposed value, so you cannot lower a severity and disable the control in one edit).
  - `loosening` (`"true"/"false"`), `scope`, `scope_type` (prefix of `change.scope`; `global` for the global kill switch), `increase_pct`.
  - For `model.allow`: `model_dest` (destination of the provider the model routes to) and `provider_new` (no currently allowed pattern routes to that provider).
  - For `feed.override`: `signature_severity` via `rt.feed.signatures()`.
  - For kill-switch changes on `agent:<id>`: `requester_is_sponsor`.
- **`ApprovalRoute`** carries `required_role`, `two_person`, `rule_id`, `ttl_s` (rule `ttl_s` or `defaults.ttl_s`; the *pending* TTL) and `max_uses`. The grant TTL (rule extra `grant_ttl_s`, else `defaults.grant_ttl_s`, else `ttl_s`) and the explanation are stored in `payload.routing`.

### 2.4 Eligibility (`can_approve`) — contract §3.5 plus explicit interpretations

1. Agents never vote: a voter with `agent_id` or role `agent` → *"Agents can never approve."* Inactive members cannot vote either.
2. `auto` / `deny` levels → no button (*"No human approval possible: rule db-restricted (deny)"*).
3. `self` = the requester's member or any admin/owner. For an agent, the requester's member is its **sponsor**: `Identity.member_id`, falling back to the cached `Agent.owner_member_id`.
4. `admin` = role ≥ admin; `owner` = role owner. For admin/owner levels the requester's own member may **not** vote (separation of duties; for agent requests this means the sponsor).
5. `two_person` means two **distinct** approvers. At least one of them satisfies `required_role`, and the other has role ≥ admin (or ≥ the level itself when the level is below admin). *Interpretation:* Acme has one owner, so "two owners" would be impossible. This is staging's `all_of: [owner, admin]`.
6. **Proposer co-sign.** If the requester is a human whose role satisfies `required_role` and the route is `two_person`, their approve vote is recorded at creation (`comment: "proposer co-sign"`). Only one distinct admin+ approver is then needed (staging's `sole_owner_fallback: requester_owner_plus_admin`).
7. Any eligible `deny` vote → `denied`. The requester's member, or an admin+, may `cancel`.

Every refusal returns a human `why_not` string. The dashboard shows it on the disabled button (F4).

### 2.5 Lifecycle and storage

- States (contract `ApprovalStatus`): `pending → approved | denied | expired | cancelled`.
  - **Auto-approval** is stored as `status=approved`, `required_role="auto"`, `decided_at=created_at`, `uses=max_uses` (consumed at once). There is no `auto_approved` status in the contract; the UI derives it from `required_role == "auto"`.
  - **Deny route** is stored as `status=denied`, `required_role="deny"`.
- `request(ctx, i, decision)` does the following, in order:
  1. Takes the draft, or synthesizes one from the interaction.
  2. Routes it.
  3. Computes the fingerprint: `fp_interaction` for `action`; for other kinds, `fp_draft` over `{kind, action_type, principal, payload.patch/changes}` so each BUD-01 scope or config proposal deduplicates.
  4. **Reuses** a pending request with the same fingerprint.
  5. Applies the deny cooldown: the same fingerprint denied less than `deny_cooldown_s` (60 s) ago returns that denied request (anti-retry loop).
  6. Applies flood caps: global `max_pending` (50) and per principal `max_pending_per_principal` (10). Over the cap → created as `denied` with `rule_id="defaults.max_pending"`.
  7. Creates the row with `expires_at = now + ttl_s`, the co-sign if any, and `payload.bound` (tool name plus **masked** args via `rt.redactor.mask_for_log`, ≤ 2 KB; never raw, ASI09 "render from bound params") and `payload.routing` (`rule_id`, `aliases`, `description`, matched facts, `eligible` member ids, `grant_ttl_s`).
  8. Writes the audit record and SSE event, then returns.
- `find_preapproved(ctx, i)` redeems **only `kind == "action"`**. Config, budget and MCP-pin approvals take effect through executors and must never authorize a different call.
  - The redeemable request is chosen by `ctx.approval_token` (`X-Aegis-Approval`) **and** a matching fingerprint, or by fingerprint alone. It must be `approved`, have `expires_at > now`, and either have `uses < max_uses` or have been redeemed less than `redeem_window_s` (30 s) ago. The window covers the hook and the MCP proxy seeing the same call. Window state is held in memory: `{apr_id: last_redeem_monotonic}`.
  - A token whose fingerprint differs is **rejected**. `ctx.state["apr.replay_of"]` is set so that the new request's `payload.replay_of` shows "grant apr_X rejected: params mismatch" (SCENARIOS #3).
- `wait(id, timeout)` uses one `asyncio.Event` per id. `vote`, `cancel` and `sweep` set it, so the held call resumes within milliseconds.
- `vote()` runs under an `asyncio.Lock`:
  1. Lazy expiry, then the not-pending check (→ `ValueError` → 409).
  2. `can_approve` (→ `PermissionError(why)` → 403), then append the vote and `tally`.
  3. On approval: `decided_at`; `expires_at = now + grant_ttl_s` (grant validity); run the executor for this kind, store `execution`, and set `uses=max_uses` for executor kinds; then publish, audit and update metrics.
- Expiry: a pending request past `expires_at` → `expired` (denied semantics), with audit `approval.expired` and SSE. This happens lazily on every read or redeem, and from a 1 s background sweep when not in test mode. An expired grant is simply non-redeemable; its status stays `approved`, and the UI shows "grant expired" from `expires_at`.
- SQLite: the `approvals` table and indexes **exactly as CONTRACTS §6.1**, created in `start()` via `rt.db()`. There is one connection plus a lock. Single-row ops run inline (sub-ms, WAL); list and count queries use `asyncio.to_thread`. Restart-safe: pending rows survive, and only in-memory waiters are lost.

### 2.6 Executors ("apply approved config changes")

- `register_executor(kind, fn)` follows the contract: the last registration wins.
- My **fallbacks** live in a separate dict and run only when nobody registered that kind. This makes registration order irrelevant: policy-engine can register in its own `start()` or `on_startup` and still win.
- Fallback for `config_change` and `budget_raise`:
  - `payload.patch` or `payload.proposal.patch` → `rt.policy.apply_patch(ops, actor=<last approver Identity>, source="approval", reason="approved apr_… (rule raise-team-small) by u_emily")`.
  - Otherwise `payload.proposal.yaml` → `apply_yaml(...)`, **only if** `proposal.base_version == rt.policy.snapshot().version`. Otherwise `execution={"status": "conflict"}` and the old YAML is not re-applied.
- The policy store then validates, self-tests, swaps atomically and publishes `policy.applied`. budgets-ledger reads the new `budgets.limits` and the gauges move.
- `execution = {"status", "policy_version", "previous_version", "message", "errors", "executor": "policy-engine"|"fallback"}`. Failures are audited (`approval.executed`, `data.ok=false`) and published as a `system` warning ("Approved change apr_… could not be applied: …"). The approval stays `approved`; nothing is applied silently.
- `mcp_pin` → registered by mcp-proxy (no fallback, so `execution={"status": "no_executor"}` plus a warning). `action` → no executor; the held or retried call passes via `find_preapproved`.

### 2.7 How the gateway holds or blocks pending actions (consumed by surface owners; listed so every surface behaves the same)

| Surface (owner) | Hold (`approvals.defaults.hold_s`) | Still pending after hold | Approved later |
|---|---|---|---|
| `/v1/hooks/claude-code` PreToolUse (claude-code-integration) | `hook: 60` (must stay < hook curl `--max-time` 110 < settings `timeout` 120, FINDINGS #3b) | `permissionDecision: "deny"` + "Approval apr_… pending (needs admin: Emily, Marek or Katarzyna) — approve at http://127.0.0.1:8787/ui/governance/approvals?id=apr_…, then retry" | Claude retries the same tool call; the fingerprint matches and it passes. `ask` is **not** recommended: it lets the terminal user bypass role routing and audit. It is acceptable only for `required_role == "self"` when the terminal user is the sponsor. |
| `/mcp/{server}` tools/call (mcp-proxy) | `mcp: 30` | JSON-RPC result `isError` with the same text | Same call again passes (fingerprint, 30 s redemption window de-duplicates hook+proxy) |
| `/egress` (metadata-egress) | `egress: 15` | **403** `approval_required` envelope (`approval_id`, `required_role`, `expires_at`) + `X-Aegis-Approval-Id` | Retry with `X-Aegis-Approval: apr_…` |
| `/v1/guard` (core-gateway) | `wait_s` from the body | 200 `{verdict, approval}` | SDK polls `GET /api/approvals/{id}/wait` and retries with `approval_id` |
| Model proxies (core-gateway; BUD-01 `budget_raise`) | 0 | 200 synthetic reply with approval id and link (or 403 per `block_response`) | Executor raises the limit; the next call passes BUD-01 |
| `rt.policy.propose()` (policy-engine, dashboard) | 0 | `ApplyResult(status="pending_approval", approval=…)` | Executor applies; `policy.applied` |

The contract has no `202 Accepted` path. The user's "202 + approval id + polling" is delivered as **403/200 + `approval_id` + long-poll `GET /api/approvals/{id}/wait`** (an extension in my namespace) + retry with `X-Aegis-Approval`. No contract change is needed.

### 2.8 GOV-05 — config-change governance (`controls/config/gov05_config.py`)

- `id="GOV-05"`, family `GOV`, kind `deterministic`, `applies_to = AppliesTo(kinds={"config_change"}, surfaces={"config.change"})`, `priority = 50`, `owasp = ["ASI03", "ASI09"]`.
- `evaluate`:
  - `changes = interaction.meta.get("changes")`. If missing, return `None`. This covers Claude Code `ConfigChange` hook events, which claude-code-integration handles.
  - Parse the changes into `PolicyChange`.
  - `route = rt.approvals.route(kind="config_change", action_type=<kind of the most restrictive change>, requester=ctx.identity, changes=changes)`.
- Decision rules:
  - `deny` → `block`.
  - `auto` → `allow`, reason "auto: rule protect-more".
  - Human proposer satisfies the level and the route is not `two_person` → `allow`, reason "authorized: admin ≥ admin (rule raise-team-small)" (contract §3.5).
  - Agent proposer → `params.agent_proposals` (default `require_approval`; `block` optional).
  - Otherwise → `require_approval` with `ApprovalDraft(kind="config_change", action_type=…, title="Piotr Zieliński wants to raise team:trading day usd 60 → 75 (+25%)", summary=<all change summaries>, labels={"scope": …, "change_kinds": …}, payload={"changes": [...], "proposal": interaction.meta["proposal"]})`.
- Findings: `category="governance"`, `detector="gov.config.<kind>"`, `meta={"rule_id", "required_role", "two_person"}`. Severity: owner/deny → high, admin → medium.
- Raising an exception → pipeline `fail_mode: closed` → block. GOV-05 never fails open.

### 2.9 Events, audit, metrics

- **SSE** (`rt.bus.publish`): `approval.created` (any creation, including auto and deny) and `approval.updated` (vote, decide, cancel, expire, execute, redeem, escalate).
  - Payload = `ApprovalRequest` JSON, **trimmed**: `payload.proposal.yaml` is replaced by `{yaml_sha256, yaml_bytes}`. The full payload is only returned by `GET /api/approvals/{id}`.
- **Audit** (`rt.audit.record`). Each event carries `actor`, `request_id`, `decision_id`, `action_type`, `amount_usd`, `resource`, `control_id` and `data={approval_id, status, rule_id, required_role, two_person, votes, sub}`.

  | When | `event_type` | `data.sub` |
  |---|---|---|
  | create | `approval.created` | — |
  | auto/deny at creation | `approval.created` + `approval.decided` | `auto` / `deny_rule` |
  | non-final vote | `approval.decided` | `vote`, `final=false` |
  | final | `approval.decided` | `approved` / `denied` / `cancelled` |
  | expiry | `approval.expired` | — |
  | executor | `approval.executed` | `execution` |
  | redemption | `approval.executed` | `redeemed` (with the redeeming `request_id`) |
  | replay mismatch | `system` | `approval.token_mismatch` (fingerprints only) |
  | escalation (could) | `system` | `approval.escalated` |

- **Metrics**: `rt.metrics.inc("aegis_approvals_total", {"kind": k, "outcome": approved|denied|expired|cancelled|auto|deny_rule})` and `rt.metrics.set_gauge("aegis_approvals_pending", n)` on every transition.

### 2.10 Endpoints (`src/aegis/api/routes/approvals.py`, `ORDER = 100`; static paths declared before `/{id}`)

| Method & path | Min role | Behaviour |
|---|---|---|
| `GET /api/approvals?status=pending\|approved\|denied\|expired\|cancelled\|all&kind=&mine=true&limit=` | member | `ApprovalsResponse {items (each + can_vote, why_not for the viewer), counts (all 5 statuses)}`. The default `status` is `all`, newest first. `mine` = the viewer is the requester or sponsor, **or** can vote |
| `GET /api/approvals/rules` | member | `ApprovalRulesResponse` (ordered; `when` human-readable, e.g. "action ∈ spend.* · amount > $200"; `ttl_s`; plus `two_person`) |
| `POST /api/approvals/simulate` | member | `ApprovalSimulateRequest` (+ optional extras: `labels`, `profile`, `scope_type`, `increase_pct`, `control_id`, `loosening`) → `ApprovalRoute`. The requester is built from the org cache; db/vendor labels are derived from resources, exactly as live |
| `POST /api/approvals` | member | `ApprovalDraft` → `create_manual(viewer, draft)` → `ApprovalRequest` (e.g. a member asks for a budget raise with `payload.patch`) |
| `GET /api/approvals/{id}` | member | `ApprovalRequest` + `can_vote`/`why_not`; 404 `not_found` |
| `GET /api/approvals/{id}/wait?timeout_s=25` (*extension*) | member | Long-poll until it is no longer pending or the timeout passes (≤ 60 s) → `ApprovalRequest`. Used by the SDK and agents |
| `POST /api/approvals/{id}/approve` · `/deny` | member (eligibility checked) | `{comment?}` → `ApprovalRequest`. Not eligible → **403 `forbidden`** with `why_not` as the message. Already decided → **409 `conflict`**. Unknown → 404 |
| `POST /api/approvals/{id}/cancel` | requester's member or admin+ | → `ApprovalRequest`; otherwise 403 |

Errors use `aegis.core.errors.api_error` (envelope §5.3). The viewer comes from `aegis.core.deps.viewer`.

### 2.11 Config keys read

`approvals.defaults.{ttl_s, on_timeout, max_pending, default_approver, default_config_approver, hold_s}`. Extras: `grant_ttl_s`, `max_pending_per_principal`, `redeem_window_s`, `deny_cooldown_s`, `sweep_interval_s`, `clock_multiplier` (could), `escalation` (could).
Also `approvals.rules[]`, `approvals.config_rules[]` (with the extras above), `approvals.tests[]`, `profile`, `controls[].severity`, `models.{allowed,routes}`, `providers[].destination`, the GOV-05 control `params`, and the settings `test_mode`, `org_seed`, `data_dir`.

---

## 3. Reuse map

### 3.1 Staging → owned paths

| Staging input | Goes to | How |
|---|---|---|
| `staging/seed/approvals.yaml` `rules:` (65) | `config/snippets/approvals-engine.yaml` `approvals.rules` / `config_rules` | Translated to `ApprovalRule`. Contract IDs are kept where §4.3/§8 name them (`spend-admin`, `raise-team-small`, `raise-large`, `budget-override`, `mcp-repin`, …). Staging IDs are kept in the `aliases:` extra. Mapping in §3.2 |
| `approvals.yaml` `routing_tests:` (34) | snippet `approvals.tests` + `tests/unit/approvals_engine/test_routing_seed.py` (reads the snippet) + `approvals/selftest.py` | Request types translated to contract `kind`/`action_type`/`labels`/`changes`. The expected rule is the contract ID. Approver sets are checked through `can_approve`/`tally`. Adaptations in §5 APR-V02 |
| `approvals.yaml` `principals`, `defaults` (TTLs, grant uses, `bind_to`, anti-flooding, display), `lifecycle` | `eligibility.py`, `service.py`, `fingerprint.py`, snippet defaults | Sponsor = `self`; agents never vote; distinct approvers; sole-owner fallback = proposer co-sign; `pending_ttl` → `ttl_s`; `grant_ttl` → `grant_ttl_s`; `grant_uses: 1` → `max_uses: 1`; dedupe window → reuse pending by fingerprint; `on_expiry: deny`; display from bound params → `payload.bound` (masked) |
| `staging/seed/org.seed.yaml` cast, sponsors, resources (DB sensitivity/env, vendors approved/plans) | `tests/unit/approvals_engine/conftest.py` FakeOrg; `facts.py` derivation logic | Read at runtime only through `rt.org.*` |
| `org.seed.yaml` `demo_state.approval_history` (3 items) | `approvals/seed.py` | Read from `settings.org_seed` if present; else an embedded copy. Inserted once when the table is empty and not in test mode. Staging rule IDs mapped to contract IDs |
| `staging/seed/SCENARIOS.md` #2–#12 | Test names, `why_not` texts, demo checks (APR-V09) | — |
| `staging/seed/policy.yaml` GOV-04 notes (bind to exact params, single-use, `max_pending_per_agent`, replay example) | `fingerprint.py`, `find_preapproved` token binding, test `replay-grant-for-other-params` | — |
| `staging/spikes/claude-code/FINDINGS.md` #3/#3b | §2.7 hold timing constraint (hold < curl timeout < settings timeout) | Documented for claude-code-integration |
| research 01 (ASI09, T10 anti-HITL-flooding, ACS `ask`) / 02 (hook `ask`/`deny`, MCP re-pin approvals) | Flood caps, deny cooldown, ACS mapping in docs (`require_approval` ≙ ACS `ask`) | — |

### 3.2 The 65 staging rules → contract rules (all accounted for)

| Staging rule(s) | Contract rule (order within family = most restrictive first) |
|---|---|
| APR-SPEND-TWO-PERSON · -OWNER · -STRICT-UNAPPROVED-VENDOR · -STRICT-RECURRING · -ADMIN · -SELF | `spend-owner-2p` · `spend-owner` · `spend-strict-vendor` · `spend-strict-recurring` · `spend-admin` · `spend-self` |
| APR-DATA-RESTRICTED · -PROD-DDL · -PROD-BULK-DELETE · -PROD-WRITE · -STAGING-WRITE · -CONFIDENTIAL-READ · -INTERNAL-READ · -PUBLIC-READ + -INTERNAL-READ-PERMISSIVE | `db-restricted` · `db-prod-ddl` · `db-prod-bulk-delete` (needs ACT-02 label `bulk`) · `db-prod-write` · `db-staging-write` · (`db-write` contract catch-all) · `db-pii-read` · `db-internal-read` · `db-read` (auto only for PUBLIC/INTERNAL; unknown sensitivity → default admin, **safer than the §4.3 example**) |
| APR-DATA-STRICT-SHORT-GRANTS | folded: a TTL-only rule cannot be expressed in first-match; strict grants rely on rule `grant_ttl_s` |
| APR-SEND-EXTERNAL-RESTRICTED · -CONFIDENTIAL · -TAINTED · -PEER-INITIATED · -BULK · -INTERNAL · -EXTERNAL-PUBLIC-PERMISSIVE · -EXTERNAL-PUBLIC | `send-restricted` · `send-confidential` · `send-tainted` · `send-peer` (inert until A2A) · `send-bulk` (needs label `bulk`) · `send-internal` · `external-send-permissive` · `external-send` |
| APR-EXEC-PKG-UNKNOWN · -STRICT · -REMOTE-SHELL · -UNSANDBOXED · -SANDBOXED · -PKG-KNOWN-PERMISSIVE · -PKG-KNOWN | `pkg-unknown` · `code-exec-strict` · `code-exec-remote-shell` · `code-exec-unsandboxed` · `code-exec-sandboxed` · `pkg-install-permissive` · `pkg-install` |
| APR-DEPLOY-PROD-STRICT · -PROD · -MAINLINE · -STAGING · -DEV | `deploy-prod-strict` · `deploy-prod` · `deploy-mainline` · `deploy-staging` · `deploy-dev` · (`deploy` contract catch-all → admin) |
| APR-BUDGET-ORG-OVER-2X · -ORG · -TEAM-OVER-2X · -TEAM-2X · -AGENT-LARGE · -AGENT-SMALL | `raise-org-2x` · `raise-org` · `raise-large` · `raise-team-small` (≤ +100 %; the §4.3 example said ≤ 50 %, and F5's +25 %/+150 % behave the same) · `raise-agent-large` · `raise-small` (self ≤ +50 %) |
| APR-CTRL-ENABLE · -STRICT · -BALANCED-CRITICAL · -PERMISSIVE · -BALANCED | `protect-more` (auto) · `disable-control-strict` (owner, two-person) · `disable-control-critical` (owner) · `disable-control-permissive` (self) · `disable-control` (admin). F5's "DLP-02 → owner" holds because DLP-02 is `critical` |
| APR-MODEL-NEW-PROVIDER · -LOCAL · -REMOTE | `model-new-provider` · `model-allow-local` · `model-allow` |
| APR-MODEL-ORG-WIDE | **not ported**: `models.allowed` is org-wide by construction, so this rule would make every allow owner-level. That contradicts the contract (`model.allow` → admin). Per-agent allowlists are org-rbac's `PATCH /api/agents` (admin) |
| APR-POLICY-PROFILE-DOWN · -TIGHTEN · -LOOSEN-STRICT · -LOOSEN · -NEUTRAL | `profile-down` · `profile-up` + `protect-more` · `policy-loosen-strict` · `policy-loosen` · `policy-neutral` |
| APR-FEED-OVERRIDE-CRITICAL · -OVERRIDE | `feed-override-critical` · `feed-override` |
| APR-KILL-RELEASE-GLOBAL · -RELEASE · -ENGAGE | `killswitch-release-global` · `loosen-threshold` (contract ID; admin) · `killswitch-own-agent` (auto for the sponsor's own agent) + `tighten` (killswitch.on otherwise → admin, contract §5.4 "kill on = tighten → admin") |
| APR-MCP-REAPPROVE-INTERNAL · -EXTERNAL · APR-MCP-REGISTER-STRICT · -REGISTER | `mcp-repin-internal` · `mcp-repin` (kind `mcp_pin`, contract ID) · `mcp-server-strict` · `mcp-server` |
| contract-only additions | `budget-override` (kind `budget_raise` → admin, F6), `approval-rules` (owner), `raise-other`, `budget-tighten`, `mode-tighten`, `provider-change` (owner), `control-params-loosen` |

---

## 4. Interfaces

### 4.1 Provided (exact contract shapes)

- **`rt.approvals`**: `aegis.approvals.service:create(rt)` returns an object implementing `ApprovalService` (§3.2, frozen) verbatim: `route(*, kind, action_type, requester, amount_usd=None, resource=None, labels=None, changes=None) -> ApprovalRoute`, `can_approve(voter, req) -> tuple[bool, str]`, `fingerprint(identity, interaction) -> str`, `async find_preapproved(ctx, interaction) -> ApprovalRequest | None`, `async request(ctx, interaction, decision) -> ApprovalRequest`, `async wait(approval_id, timeout_s) -> ApprovalRequest`, `async vote(approval_id, voter, decision, comment=None) -> ApprovalRequest` (raises `PermissionError`), `async cancel(approval_id, actor)`, `async get(approval_id)`, `async list_requests(*, status=None, kind=None, limit=200)`, `async create_manual(requester, draft)`, `register_executor(kind, fn)`. Lifecycle: `async start()`, `async stop()`.
- **Control** `GOV-05` via `CONTROLS` in `src/aegis/controls/config/gov05_config.py` (§2.1 discovery).
- **Routes** in §2.10: shapes `ApprovalsResponse`, `ApprovalRequest` (+ `can_vote`, `why_not`), `ApprovalRulesResponse`, `ApprovalRuleView`, `ApprovalSimulateRequest`, `ApprovalRoute` (§5.5).
- **SSE** `approval.created`, `approval.updated` (`SseEventMap`: `ApprovalRequest`).
- **Audit** event types `approval.created|decided|expired|executed` (+ `system`). **Metrics** `aegis_approvals_total{kind,outcome}`, `aegis_approvals_pending`.
- **SQLite**: table `approvals` + `ix_approvals_status`, `ix_approvals_fp` (verbatim §6.1).
- **Snippet** `config/snippets/approvals-engine.yaml` (§7).

### 4.2 Consumed

| From | What | If missing |
|---|---|---|
| scaffold (frozen) | `aegis.core.types` (`ApprovalRequest`, `ApprovalRoute`, `ApprovalDraft`, `ApprovalVote`, `Identity`, `Interaction`, `Decision`, `Finding`, `AuditEvent`, `APPROVER_RANK`, `ROLE_RANK`, `new_id`, `utcnow`), `aegis.core.protocols` (`BaseControl`, `ApprovalExecutor`), `aegis.core.policy_schema` (`ApprovalsSection`, `ApprovalRule`, `ApprovalWhen`, `PolicyChange`, `PatchOp`, `PolicySnapshot`, `PolicyDoc`) | — (required) |
| core-gateway | `aegis.core.crypto.hmac_hex`, `aegis.core.paths.glob_match`, `aegis.core.deps.{get_rt, viewer}`, `aegis.core.errors.api_error`, `aegis.core.runtime.get_runtime`, `aegis.settings.get_settings`, `rt.db()`; pipeline calls `find_preapproved` / `request` / `wait` | Guarded fallbacks: local HMAC (WARNING), `fnmatch.fnmatchcase`. The route module only works in the real app; unit tests use dependency overrides |
| policy-engine | `rt.policy.snapshot()`, `apply_patch`, `apply_yaml`, `on_change`; builds `config.change` interactions with `meta.changes`/`meta.proposal` and calls `rt.approvals.route` for `ValidationReport.required_role`; registers config executors | Fake store in tests; fallback executors |
| org-rbac | `rt.org.list_members()`, `list_agents()`, `resources()`; `resolve_viewer` (via `deps.viewer`) | Org cache empty → sponsor taken from `Identity.member_id`; labels not derived |
| action-guards / budgets-ledger / mcp-proxy | `ApprovalDraft`s on decisions (with labels: §4.3); mcp-proxy registers the `mcp_pin` executor | Routing falls to the fail-closed defaults |
| redaction-engine / threat-feed / audit-metrics / core bus | `rt.redactor.mask_for_log`, `rt.feed.signatures()`, `rt.audit.record`, `rt.metrics.inc/set_gauge`, `rt.bus.publish/subscribe` | Null fallbacks (contract §3.3) |

### 4.3 Contract gaps (proposed addenda; meanwhile the escape hatches noted are used — no frozen file is touched)

1. **No `auto_approved` status.** Represented as `status=approved` + `required_role="auto"`; the UI derives the label. *Addendum (optional):* document it in §3.5.
2. **First-match vs most-restrictive.** The contract wins (first match). Staging semantics are reproduced by ordering, the fail-closed catch-alls and 34 routing tests. *Addendum:* note in §3.5 that rule lists are authored most-restrictive-first.
3. **`ApprovalWhen` / `ApprovalRule` / `ApprovalDefaults` / `ApprovalsSection` extras** used by the snippet:
   - when: `profiles`, `labels_in`, `signals_any`;
   - rule: `aliases`, `grant_ttl_s`, `note`;
   - defaults: `grant_ttl_s`, `max_pending_per_principal`, `redeem_window_s`, `deny_cooldown_s`, `sweep_interval_s`, `clock_multiplier`, `escalation`;
   - section: `tests`.

   Request to **policy-engine**: list these as known extras (no validator warnings), document them in `docs/policy-reference` and keep `approvals.tests` when merging snippets.
4. **Two-person semantics with one owner.** Interpreted as "two distinct approvers: ≥ 1 satisfies `required_role`, the other ≥ admin", plus proposer co-sign. *Addendum:* add this sentence to §3.5.
5. **GOV-05 inline tests need a member identity and changes.** `PolicyTest` has no `member`/`changes`/`profile`. Request to **policy-engine**: the self-test runner should map the extra keys `member` → `Identity(member_id, role from rt.org)`, `changes` → `interaction.meta["changes"]` and `profile` → the candidate profile. Until then GOV-05's snippet tests are covered by my unit tests.
6. **`decision_id` is not available inside `request()`.** Request to **core-gateway**: set `decision.meta["decision_id"] = verdict.id` (or `ctx.state["aegis.decision_id"]`) before calling `rt.approvals.request`. Fallback: `decision_id=None`; the UI links via `request_id`.
7. **Audit types for votes, redemption, escalation and replay rejection are missing.** Mapped to `approval.decided` / `approval.executed` / `system` with `data.sub` (§2.9). *Addendum (optional):* `approval.voted`, `approval.redeemed`, `approval.escalated`.
8. **No 202 path.** Delivered as 403/200 + `approval_id` + long-poll `GET /api/approvals/{id}/wait` (my namespace). Request to **demo-mocks-docs**: `aegis.sdk` should handle `approval_required` by polling `/wait`, then retrying with `X-Aegis-Approval`, with an HTTP timeout greater than `hold_s`.
9. **Labels needed from draft producers.** I derive what I can from `rt.org.resources()`; everything else falls to fail-closed defaults.
   - **action-guards:**
     - ACT-01 `vendor_approved` (`"true"`/`"false"`) and `recurring`.
     - ACT-02 `sensitivity` and `env` (already in the contract), plus `bulk: "true"` for unbounded prod `DELETE`/`UPDATE`.
     - ACT-03 `data_class` (max class in the payload; a placeholder counts as its entity's class) and `bulk` (recipients > 10).
     - ACT-04 `env` (`prod|staging|mainline|dev`) and `pattern`.
     - EXE-03 `signals: lethal_trifecta`.
     - EXE-01/ACT-04 `sandboxed`.
   - **threat-feed** SIG-03: `signals: unknown_package`.
   - **mcp-proxy** `mcp_pin` drafts: `labels.dest` = the server's destination.
   - **budgets-ledger** `budget_raise` drafts: `payload.patch` + `labels.scope`/`scope_type`.
10. **The hook and the MCP proxy must resolve the same identity** (otherwise the fingerprints differ and duplicate cards appear). Request to **claude-code-integration**: `demo/claude/mcp.json` sends `X-Aegis-Agent: claude-code@platform` (or the agent key) on MCP requests. Use the deny text in §2.7.
11. **org-rbac:** put `owner_delegate: true` into `Member.meta` (only needed for the could-task escalation). `Identity.member_id` = sponsor for agent identities (already in §3.1's docstring).
12. **Metrics naming:** I pass full names (`aegis_approvals_total`). audit-metrics should accept names with or without the prefix.

---

## 5. Tasks

Order = degradation order. All tasks are implementer-sized; estimates are in minutes.

### APR-01 · Skeleton & public surfaces (interfaces first)
- [ ] Create every file in §2.1. `create(rt)` is cheap. Stub methods are safe: `route` → default level; `request` → pending row; `find_preapproved` → `None`.
- [ ] `CONTROLS = [ConfigChangeGovernance()]` stub returning `None`; `router` with all §2.10 paths returning the correct shapes.
- [ ] Guarded imports for core-gateway modules (crypto, paths); no import-time side effects.
- priority **must** · demo_critical **yes** · 8 min · deps: frozen files (scaffold)

### APR-02 · Routing engine + fact builders
- [ ] `routing.py`: compile `ApprovalsSection` (cached by `snap.version` in `snap.compiled["approvals-engine:rules"]`); `match()` covering all contract `ApprovalWhen` fields plus the extras `profiles`, `labels_in`, `signals_any`; fail-closed `None` numbers; unknown keys → not satisfied + one WARNING.
- [ ] `route_many()` for multi-change configs (max rank, OR two-person, min TTL); defaults when nothing matches.
- [ ] `facts.py`: `OrgCache` (members, agents → sponsor/team, resources) loaded in `start()`; `facts_for_action` (vendor/db derivation, `dest`, requester facts); `facts_for_change` (severity max(before, after), loosening, scope/scope_type, `increase_pct`, model_dest/provider_new, signature_severity, requester_is_sponsor).
- [ ] `describe_when(rule)` → human string for the rules page.
- priority **must** · demo_critical **yes** · 20 min · deps: APR-01

### APR-03 · Snippet: ported rules, defaults, routing tests, GOV-05 entry
- [ ] Write `config/snippets/approvals-engine.yaml` exactly as §7 (both rule lists in that order, defaults, `tests:` with the 34 adapted seed cases + flow cases, GOV-05 control entry).
- [ ] The file must load into `PolicyDoc` (merged with a minimal doc) without errors.
- priority **must** · demo_critical **yes** · 12 min · deps: APR-02 (vocabulary)

### APR-04 · Store + fingerprint
- [ ] `store.py`: DDL exactly as §6.1; JSON columns; mapping both ways (`requester_member_id`/`requester_agent_id` filled); `insert/update/get/list(status, kind, limit)/counts/pending_by_fp/redeemable_by_fp/due_for_expiry/recent_denied_by_fp`; one connection + lock; WAL via `rt.db()`.
- [ ] `fingerprint.py`:
  - canonical JSON (sorted keys, numbers normalized `50 == 50.0`);
  - `VOLATILE_KEYS = {request_id, idempotency_key, nonce, timestamp, ts, _meta, session_id, trace_id}`;
  - `fp_interaction` = `{org, principal, action_type or tool_name or kind:surface, args, resource, amount_usd(2dp)}`, plus `changes_digest` for `config_change`;
  - `fp_draft` for budget/config/pin;
  - all via `hmac_hex(purpose="approval")`.
- priority **must** · demo_critical **yes** · 12 min · deps: APR-01

### APR-05 · Lifecycle core (request · vote · two-person · cancel · get/list · wait · lazy expiry) + notifications
- [ ] `eligibility.py` per §2.4: `can_approve` with `why_not` texts; `tally`; co-sign; `eligible_members`.
- [ ] `request()` per §2.5: route; fingerprint reuse; deny cooldown; flood caps; auto/deny immediate; `payload.bound` (masked via `rt.redactor.mask_for_log`, ≤ 2 KB), `payload.routing`, `payload.replay_of`; `team_id` from the requester.
- [ ] `vote()` / `cancel()` / `get()` / `list_requests()` / `create_manual()` / `wait()` with `asyncio.Event`s; `asyncio.Lock` around transitions; lazy expiry on every read.
- [ ] `notify.py`: audit + SSE (trimmed) + metrics + waiter wake-up at a single choke point (§2.9).
- priority **must** · demo_critical **yes** · 25 min · deps: APR-02, APR-04

### APR-06 · `find_preapproved` (redemption, binding, replay protection)
- [ ] Action kind only; token + fingerprint must both match; `uses < max_uses` or within `redeem_window_s` of the last redemption (in-memory map); grant `expires_at` check.
- [ ] Consume a use; audit `approval.executed{sub: redeemed}` + SSE.
- [ ] Token mismatch → `ctx.state["apr.replay_of"]` + `system` audit; the next `request()` links `payload.replay_of`.
- priority **must** · demo_critical **yes** · 8 min · deps: APR-05

### APR-07 · Executors (apply approved config changes)
- [ ] Registry + separate fallback dict (§2.6); `run_executor` with a 10 s timeout and exception capture → `execution`; `uses=max_uses` after executor kinds.
- [ ] Fallback `config_change`/`budget_raise` → `apply_patch` / guarded `apply_yaml`; actor = last approver Identity; `system` warning on failure.
- priority **must** · demo_critical **yes** · 8 min · deps: APR-05

### APR-08 · GOV-05 control
- [ ] Per §2.8; params model with defaults (`allow_if_proposer_satisfies: true`, `agent_proposals: require_approval`, `title_template`); finding + meta; deterministic, no I/O besides `rt.approvals.route`.
- priority **must** · demo_critical **yes** · 12 min · deps: APR-02, APR-05

### APR-09 · Dashboard API routes
- [ ] All §2.10 endpoints: `can_vote`/`why_not` augmentation; counts for all 5 statuses; `mine`; static paths before `/{id}`; envelope errors 403/404/409/400.
- [ ] `/rules` (ordered views, defaults block), `/simulate` (requester from the org cache, derived labels, optional extras).
- priority **must** · demo_critical **yes** · 12 min · deps: APR-05

### APR-10 · Background sweeper + org cache refresh
- [ ] `expiry.py` loop every `sweep_interval_s` (1 s) when `settings.test_mode` is false: expire pending, publish. Org cache refreshes on bus `org.updated` and every 30 s.
- priority **should** · demo_critical **yes** (expiry visible on stage) · 10 min · deps: APR-05

### APR-11 · Routing self-test after each policy apply
- [ ] `selftest.py` runs `approvals.tests` against a snapshot (requesters resolved from the org cache; pairwise approver checks via `tally`).
- [ ] `rt.policy.on_change(cb)` → run it; on failures publish `system` level=warning "Approval routing self-test: 2/40 failing (spend-admin: got owner)"; log.
- priority **should** · demo_critical no · 10 min · deps: APR-03, APR-05

### APR-12 · Demo history seed
- [ ] `seed.py`: insert `demo_state.approval_history` (approved by u_agnieszka, denied by u_emily with comment, expired), relative timestamps, mapped rule IDs, `labels.seed="true"`; only when the table is empty and not in test mode.
- priority **should** · demo_critical no (the inbox is not empty at start) · 10 min · deps: APR-04

### APR-13 · Long-poll `/wait` endpoint
- [ ] `GET /api/approvals/{id}/wait?timeout_s=` (≤ 60) using `wait()`.
- priority **should** · demo_critical no · 5 min · deps: APR-05, APR-09

### APR-14 · Escalation, reminders, owner delegate, demo clock
- [ ] `defaults.escalation` + `clock_multiplier`. The sweeper sets `payload.escalation = {to, at}` and audits `system{sub: approval.escalated}`.
- [ ] `owner_delegate` members (`Member.meta`) may fill a single owner slot once escalated, never the owner half of a two-person rule.
- priority **could** · demo_critical no · 20 min · deps: APR-10

### APR-15 · Session-scoped data grants
- [ ] Rule extra `grant_scope: session`. `payload.bound.session_id`; `find_preapproved` also accepts same principal + action_type + resource + session within the grant TTL, with uses unbounded (SCENARIOS #5).
- priority **could** · demo_critical no · 15 min · deps: APR-06

### APR-16 · Temporary disable with auto-revert
- [ ] Rule extra `revert_after_s`. After an approved `control.disable`/`control.mode`, schedule a revert patch (applied by the sweeper via `rt.policy.apply_patch`, `source="approval"`) and audit it (SCENARIOS #8 "disabled until 14:05").
- priority **could** · demo_critical no · 20 min · deps: APR-07, APR-10

### APR-17 · Approval timeline endpoint
- [ ] `GET /api/approvals/{id}/timeline` → audit events whose `data.approval_id` matches (via `rt.audit.query`, filtered).
- priority **could** · demo_critical no · 10 min · deps: APR-05

### Verification tasks

| ID | Proves | How (commands / checks) | Expected |
|---|---|---|---|
| **APR-V01** | Imports and discovery are clean | `uv run --frozen python -c "import aegis.approvals.service, aegis.approvals.routing, aegis.controls.config.gov05_config, aegis.api.routes.approvals"` · `uv run --frozen ruff check src/aegis/approvals src/aegis/controls/config src/aegis/api/routes/approvals.py tests/unit/approvals_engine` | No output, exit 0 |
| **APR-V02** | **The 34 staging routing tests**, adapted | `uv run --frozen pytest tests/unit/approvals_engine/test_routing_seed.py -q` (parametrized over `approvals.tests` where `staging:` is set). Each case asserts `required_role`, `two_person`, `rule_id`, every `approvers_ok` (single → `can_approve` true; pair → two votes → `approved`) and every `approvers_not_ok` (→ false, with a reason) | **34 passed**. Documented adaptations: (a) staging `type` → contract `kind`/`action_type`/labels/`changes`; (b) staging rule IDs → contract IDs (aliases kept); (c) `org-budget-raise-by-sole-owner` → route `owner/raise-org` **and** GOV-05 = `allow` (contract §3.5; proposer satisfies); (d) `disable-control-balanced-admin` additionally asserts GOV-05 = `allow` for proposer u_marek (contract) while `approvers_not_ok: [u_marek]` still holds for votes; (e) `unmatched-type-fails-closed` → `default_config_approver` = **owner** (contract default; staging said admin); (f) `grant_uses: session` is asserted only when APR-15 is done |
| **APR-V03** | Contract headline flows route correctly | `pytest tests/unit/approvals_engine/test_routing_flows.py -q` | F4: $50 `spend-admin`; $12 `spend-self` (u_agnieszka ok, u_james not); $480 `spend-owner`; $1500 `spend-owner-2p`; customers `db-pii-read`; payment_cards `db-restricted`/deny; prod DELETE `db-prod-write`/owner. F5: 60→75 `raise-team-small`/admin; 60→150 `raise-large`/owner; DLP-02 disable `disable-control-critical`/owner. F6: `budget_raise` → `budget-override`/admin. F9: `mcp_pin` → `mcp-repin`/admin. Missing amount → `spend-owner-2p` |
| **APR-V04** | Lifecycle and safety properties | `pytest tests/unit/approvals_engine/test_lifecycle.py test_fingerprint.py -q` | All pass. Pending reused by fingerprint (2 `request()` calls → 1 row); auto → approved + consumed; deny → denied + no button; sponsor self-approve; SoD 403 reason; agent vote rejected; two-person 1/2 → 2/2; any eligible deny → denied; cancel by requester ok and by an unrelated member → `PermissionError`; lazy expiry → `expired` + audit `approval.expired`; `wait()` wakes < 100 ms after `vote()`; redemption: use 1 consumed, a second redeem within 30 s ok, after the window → `None`; token for other params → `None` + `replay_of`; config/budget approvals never redeemable; flood cap → denied `defaults.max_pending`; deny cooldown returns the same denied request; `50` vs `50.0` and volatile keys give the same fingerprint |
| **APR-V05** | Executors apply config changes | `pytest tests/unit/approvals_engine/test_executors.py -q` (FakePolicyStore records calls) | Approval of a `config_change` with `payload.patch` → `apply_patch` called once with `source="approval"`, actor u_emily; `execution.policy_version` set; a registered executor overrides the fallback regardless of registration order; executor exception → `execution.status="error"`, status stays approved, `system` warning published; stale `base_version` yaml → `conflict`, not applied |
| **APR-V06** | GOV-05 decisions | `pytest tests/unit/approvals_engine/test_gov05.py -q` | u_piotr budget raise → `require_approval` + draft (kind config_change, title contains "+25%"); u_emily same → `allow` "authorized: admin ≥ admin"; u_katarzyna org raise → `allow`; u_marek DLP-02 disable → `require_approval` (owner); agent proposer → `require_approval`; strict + owner proposer two-person → draft, and `request()` records the co-sign vote; `deny` rule → `block`; no `meta.changes` → `None` |
| **APR-V07** | API contract and RBAC over ASGI | `pytest tests/unit/approvals_engine/test_api.py -q` (FastAPI app with my router; `dependency_overrides` for `get_rt`/`viewer` if core is absent) | `GET /api/approvals?status=pending` items have `can_vote`/`why_not`; `counts` has 5 keys; approve as u_piotr → **403** `forbidden` with "Separation of duties…" or "Needs admin…"; as u_emily → 200 `approved`; again → **409**; unknown id → 404; `/rules` ordered with human `when`; `/simulate {kind: action, action_type: spend.subscription, amount_usd: 50, requester_agent_id: trading-copilot@trading}` → `{required_role: admin, rule_id: spend-admin, two_person: false, ttl_s: 900, max_uses: 1}`; `/wait` returns early after a vote |
| **APR-V08** | Privacy of payloads, SSE and audit | `pytest tests/unit/approvals_engine/test_privacy.py -q` | A request whose tool args contain a fake PESEL/PAN generated at runtime: `payload`, the SSE message and the audit `data` contain no raw digits (masked); SSE payload has `yaml_sha256` instead of the YAML |
| **APR-V09** | Real-runtime integration (F5 end to end) | `pytest tests/unit/approvals_engine/test_integration.py -q` (uses root fixtures `client`/`rt` when present, else skips) | View-as u_piotr `POST /api/budgets/raise {scope: team:trading, window: day, dimension: usd, new_limit: 75}` → `pending_approval` with approval; `POST /api/approvals/{id}/approve` as u_emily → `execution.policy_version == v+1`; `GET /api/policy` shows 75; audit has `approval.created → approval.decided → approval.executed → policy.applied` |
| **APR-V10** | Live demo check (manual, gateway running) | `curl -s -XPOST :8787/v1/guard -H 'content-type: application/json' -d '{"interaction":{"kind":"mcp","surface":"mcp.call","destination":{"name":"mcp:marketpulse","dest_class":"third_party"},"tool_name":"marketpulse.purchase_subscription","tool_args":{"vendor":"marketpulse","plan":"mp-pro-monthly","amount_usd":50}},"identity":{"agent_id":"trading-copilot@trading"}}'` → note `approval.id`; `curl -s -XPOST :8787/api/approvals/$ID/approve -H 'X-Aegis-View-As: u_piotr'` → 403; same with `u_emily` → approved; repeat the guard call → `verdict.action == "allow"`, reason "approved by u_emily". In parallel `curl -N ':8787/api/events?events=approval.created,approval.updated'` shows both events | As described; dashboard toast and inbox update live |
| **APR-V11** | Expiry and sweeper on a live stack | Set a short `ttl_s` in a rule in `config/policy.yaml` (hot reload); trigger the request; wait | Within ttl + 1 s: SSE `approval.updated` with `status: expired`, audit `approval.expired`, gauge `aegis_approvals_pending` decremented (`curl :8787/metrics \| grep approvals`) |
| **APR-V12** | Routing self-test after a live edit (APR-11) | Edit `spend-admin` to `approver: owner` in `config/policy.yaml` | Policy applies; `system` warning "Approval routing self-test: 1/… failing (saas-subscription-50-needs-admin)"; reverting clears it |

Whole workstream: `uv run --frozen pytest tests/unit/approvals_engine -q` runs in under 10 s with no network and no models.

### 5.1 The 34 seed routing cases → contract request and expected route (APR-V02 data)

Labels for `action` cases are written as `k=v`. `chg` = one `PolicyChange` (kind, scope, increase_pct, control_id, loosening). The profile is `balanced` unless noted.

| # | Staging name | Contract request | Expect (`role`/`2p`, rule) |
|---|---|---|---|
| 1 | saas-subscription-50-needs-admin | `spend.subscription` $50 by trading-copilot, vendor_approved=true, recurring=monthly | admin, `spend-admin` |
| 2 | spend-20-is-self | `spend.charge` $20.00 by research-agent | self, `spend-self` (ok u_agnieszka; not u_james, agent) |
| 3 | spend-20.01-is-admin | $20.01 research-agent | admin, `spend-admin` |
| 4 | spend-200-is-admin | $200 claude-code | admin, `spend-admin` |
| 5 | spend-480-needs-owner | $480 claude-code | owner, `spend-owner` (not u_marek/u_emily/u_tomasz) |
| 6 | spend-4800-two-person | $4800 trading-copilot | owner/2p, `spend-owner-2p` |
| 7 | strict-unapproved-vendor-small | strict; $15 vendor_approved=false recurring=monthly | admin, `spend-strict-vendor` |
| 8 | read-customers-pii-needs-admin | `db.read` db:customers sensitivity=CONFIDENTIAL env=prod, research-agent | admin, `db-pii-read` (not u_agnieszka) |
| 9 | prod-db-write-needs-owner | `db.write` CONFIDENTIAL prod, claude-code | owner, `db-prod-write` |
| 10 | read-card-table-denied | `db.read` db:payment_cards RESTRICTED | deny, `db-restricted` |
| 11 | prod-ddl-denied | `db.schema` db:trades CONFIDENTIAL prod, chaos-agent | deny, `db-prod-ddl` |
| 12 | staging-write-self | `db.write` INTERNAL staging, claude-code | self, `db-staging-write` (ok u_tomasz) |
| 13 | external-email-with-client-name-admin | `email.external` data_class=CONFIDENTIAL | admin, `send-confidential` |
| 14 | external-send-card-denied | `email.external` data_class=RESTRICTED | deny, `send-restricted` |
| 15 | internal-email-auto | `email.internal` data_class=CONFIDENTIAL | auto, `send-internal` |
| 16 | unknown-package-admin | `package.install` signals=unknown_package sandboxed=false | admin, `pkg-unknown` |
| 17 | prod-terraform-owner | `code.deploy` env=prod pattern=terraform_apply | owner, `deploy-prod` |
| 18 | prod-terraform-strict-two-person | strict; same | owner/2p, `deploy-prod-strict` |
| 19 | team-monthly-raise-under-2x-admin | chg budget.raise team:trading +66.67 %, u_piotr | admin, `raise-team-small`; GOV-05 require_approval |
| 20 | team-monthly-raise-exactly-2x-admin | chg budget.raise team:research +100 %, u_agnieszka | admin, `raise-team-small` |
| 21 | team-monthly-raise-over-2x-owner | chg budget.raise team:research +200 % | owner, `raise-large` (ok u_katarzyna; not u_emily) |
| 22 | org-budget-raise-owner | chg budget.raise org:acme-capital +33 %, u_marek | owner, `raise-org` (not u_marek) |
| 23 | org-budget-raise-by-sole-owner | chg budget.raise org +33 %, u_katarzyna | owner, `raise-org`; **GOV-05 allow** (adapted) |
| 24 | disable-control-strict-two-person | strict; chg control.disable INJ-02 (high), u_marek | owner/2p, `disable-control-strict` (pair u_katarzyna+u_emily; not u_marek) |
| 25 | disable-control-balanced-admin | chg control.disable INJ-03 (medium), u_marek | admin, `disable-control` (ok u_emily, u_katarzyna; not u_marek); **GOV-05 allow** for proposer (adapted) |
| 26 | disable-critical-balanced-owner | chg control.disable DLP-02 (critical), u_emily | owner, `disable-control-critical` |
| 27 | enable-control-auto | chg control.enable INJ-03, u_olivia | auto, `protect-more` |
| 28 | allow-known-provider-remote-model-admin | chg model.allow, model_dest=remote, provider_new=false (given as change facts) | admin, `model-allow` |
| 29 | allow-new-provider-owner | chg model.allow, provider_new=true | owner, `model-new-provider` |
| 30 | profile-down-owner | chg profile.change balanced→permissive, loosening | owner, `profile-down` |
| 31 | profile-up-auto | chg profile.change balanced→strict, not loosening | auto, `profile-up` |
| 32 | kill-release-sponsor-cannot-self-release | chg killswitch.off scope agent:chaos-agent@platform, u_tomasz | admin, `loosen-threshold` (ok u_marek, u_emily; not u_tomasz) |
| 33 | agent-can-never-approve | `spend.charge` $5 research-agent | self, `spend-self` (not research-agent, chaos-agent, claude-code) |
| 34 | unmatched-type-fails-closed | config_change `action_type: something.new`, no changes, u_james | owner (`default_config_approver`, adapted from staging's admin), rule `None` |

Test cases may pass precomputed change facts (`model_dest`, `provider_new`, `control_severity`) in a `facts:` key on the change. `facts_for_change` uses given facts first and derives the rest from the snapshot.

---

## 6. Demo cut

**Must really work live (never faked):**
- F4 end to end: $50 via the MCP proxy or Claude Code hook is held → card → disabled for Piotr with the reason → Emily approves → the held call passes.
- $12 self-approval by the sponsor; $480 owner-only; $1,500 two-person (1/2 → 2/2); `payment_cards` denied with no button; prod write owner-only.
- F5 config governance via GOV-05 + executor → policy v+1 → gauges; DLP-02 disable needs the owner; owner edits apply directly.
- F6 budget-raise approval resumes the agent. F9 re-pin via mcp-proxy's executor.
- SSE updates, audit trail and the 34+ routing tests.

**May be simplified or stubbed convincingly:**
- Escalation, reminders and the owner delegate: show expiry with a short TTL instead.
- Session-scoped grants: single-use grants are fine.
- Auto-revert of temporarily disabled controls: the banner text can be omitted.
- `provider_new` heuristic: provider changes are owner-gated anyway.
- Demo history: static seed.
- Timeline endpoint: the audit page filter covers it.

**Cut order if late:** APR-17 → APR-16 → APR-15 → APR-14 → APR-12 → APR-11 → APR-13 → APR-10 (lazy expiry still works without the sweeper).

---

## 7. Snippet — `config/snippets/approvals-engine.yaml` (policy-engine merges it verbatim)

```yaml
approvals:
  defaults:
    ttl_s: 900                     # pending TTL (expiry => denied semantics)
    on_timeout: deny
    max_pending: 50
    default_approver: admin        # action / budget_raise / mcp_pin requests matching no rule (fail closed)
    default_config_approver: owner # config changes matching no rule (fail closed)
    hold_s: {hook: 60, mcp: 30, egress: 15, guard: 0, proxy: 0, playground: 0, dashboard: 0}
    # approvals-engine extras
    grant_ttl_s: 900               # how long an approval can be redeemed after it is given
    max_pending_per_principal: 10  # anti human-in-the-loop flooding (T10 / ASI09)
    redeem_window_s: 30            # hook + MCP proxy redeeming the same call count as one use
    deny_cooldown_s: 60            # identical call just denied -> denied again without a new card
    sweep_interval_s: 1
    clock_multiplier: 1            # demo: 60 => minutes behave like seconds (could)
    escalation: {self: {after_s: 600, to: admin}, admin: {after_s: 1200, to: owner}, owner: {after_s: 1200, to: owner_delegate}}

  # Agent actions, budget overrides, MCP re-pins. FIRST MATCH WINS: each family is written
  # most-restrictive-first and ends with a fail-closed catch-all (port of staging approvals.yaml).
  rules:
    # spend - <= $20 self | <= $200 admin | > $200 owner | > $1000 owner + second admin
    - {id: spend-owner-2p,        aliases: [APR-SPEND-TWO-PERSON], when: {action: ["spend.*"], amount_usd_gt: 1000}, approver: owner, two_person: true, ttl_s: 7200}
    - {id: spend-owner,           aliases: [APR-SPEND-OWNER], when: {action: ["spend.*"], amount_usd_gt: 200}, approver: owner}
    - {id: spend-strict-vendor,   aliases: [APR-SPEND-STRICT-UNAPPROVED-VENDOR], when: {action: ["spend.*"], profiles: [strict], labels: {vendor_approved: "false"}}, approver: admin}
    - {id: spend-strict-recurring, aliases: [APR-SPEND-STRICT-RECURRING], when: {action: ["spend.*"], profiles: [strict], labels_in: {recurring: [monthly, yearly]}}, approver: admin}
    - {id: spend-admin,           aliases: [APR-SPEND-ADMIN], when: {action: ["spend.*"], amount_usd_gt: 20, amount_usd_lte: 200}, approver: admin}
    - {id: spend-self,            aliases: [APR-SPEND-SELF], when: {action: ["spend.*"], amount_usd_lte: 20}, approver: self, grant_ttl_s: 600}
    # data access - by table sensitivity (ACT-02 labels) and environment
    - {id: db-restricted,         aliases: [APR-DATA-RESTRICTED], when: {action: ["db.*"], labels_in: {sensitivity: [RESTRICTED, SECRET]}}, approver: deny, description: "PCI: no agent may read raw card data, whoever approves."}
    - {id: db-prod-ddl,           aliases: [APR-DATA-PROD-DDL], when: {action: ["db.schema"], labels: {env: prod}}, approver: deny}
    - {id: db-prod-bulk-delete,   aliases: [APR-DATA-PROD-BULK-DELETE], when: {action: ["db.write"], labels: {env: prod, bulk: "true"}}, approver: owner, two_person: true}
    - {id: db-prod-write,         aliases: [APR-DATA-PROD-WRITE], when: {action: ["db.write"], labels: {env: prod}}, approver: owner, grant_ttl_s: 600}
    - {id: db-staging-write,      aliases: [APR-DATA-STAGING-WRITE], when: {action: ["db.write"], labels: {env: staging}}, approver: self}
    - {id: db-write,              when: {action: ["db.write", "db.schema"]}, approver: admin}
    - {id: db-pii-read,           aliases: [APR-DATA-CONFIDENTIAL-READ], when: {action: ["db.read"], labels: {sensitivity: CONFIDENTIAL}}, approver: admin, grant_ttl_s: 3600}
    - {id: db-internal-read,      aliases: [APR-DATA-INTERNAL-READ], when: {action: ["db.read"], profiles: [strict, balanced], labels: {sensitivity: INTERNAL}}, approver: self, grant_ttl_s: 3600}
    - {id: db-read,               aliases: [APR-DATA-PUBLIC-READ, APR-DATA-INTERNAL-READ-PERMISSIVE], when: {action: ["db.read"], labels_in: {sensitivity: [PUBLIC, INTERNAL]}}, approver: auto}
    # external send - by data class in the payload (ACT-03 labels) and taint signals
    - {id: send-restricted,       aliases: [APR-SEND-EXTERNAL-RESTRICTED], when: {action: ["email.external", "egress.post"], labels_in: {data_class: [RESTRICTED, SECRET]}}, approver: deny}
    - {id: send-confidential,     aliases: [APR-SEND-EXTERNAL-CONFIDENTIAL], when: {action: ["email.external", "egress.post"], labels: {data_class: CONFIDENTIAL}}, approver: admin}
    - {id: send-tainted,          aliases: [APR-SEND-TAINTED], when: {action: ["email.*", "egress.post"], signals_any: [lethal_trifecta]}, approver: admin}
    - {id: send-peer,             aliases: [APR-SEND-PEER-INITIATED], when: {action: ["email.*", "egress.post"], signals_any: [peer_initiated]}, approver: admin}
    - {id: send-bulk,             aliases: [APR-SEND-BULK], when: {action: ["email.external"], labels: {bulk: "true"}}, approver: admin}
    - {id: send-internal,         aliases: [APR-SEND-INTERNAL], when: {action: ["email.internal"]}, approver: auto}
    - {id: external-send-permissive, aliases: [APR-SEND-EXTERNAL-PUBLIC-PERMISSIVE], when: {action: ["email.external", "egress.post"], profiles: [permissive]}, approver: auto}
    - {id: external-send,         aliases: [APR-SEND-EXTERNAL-PUBLIC], when: {action: ["email.external", "egress.post"]}, approver: self}
    # code execution & packages
    - {id: pkg-unknown,           aliases: [APR-EXEC-PKG-UNKNOWN], when: {action: ["package.install"], signals_any: [unknown_package]}, approver: admin}
    - {id: code-exec-strict,      aliases: [APR-EXEC-STRICT], when: {action: ["package.install", "code.exec"], profiles: [strict]}, approver: admin}
    - {id: code-exec-remote-shell, aliases: [APR-EXEC-REMOTE-SHELL], when: {action: ["code.exec"], labels: {pattern: remote_shell}}, approver: admin}
    - {id: code-exec-unsandboxed, aliases: [APR-EXEC-UNSANDBOXED], when: {action: ["code.exec"], labels: {sandboxed: "false"}}, approver: admin}
    - {id: code-exec-sandboxed,   aliases: [APR-EXEC-SANDBOXED], when: {action: ["code.exec"], labels: {sandboxed: "true"}}, approver: self}
    - {id: pkg-install-permissive, aliases: [APR-EXEC-PKG-KNOWN-PERMISSIVE], when: {action: ["package.install"], profiles: [permissive]}, approver: auto}
    - {id: pkg-install,           aliases: [APR-EXEC-PKG-KNOWN], when: {action: ["package.install"]}, approver: self}
    # deploy - by environment (ACT-04 label env)
    - {id: deploy-prod-strict,    aliases: [APR-DEPLOY-PROD-STRICT], when: {action: ["code.deploy"], profiles: [strict], labels: {env: prod}}, approver: owner, two_person: true}
    - {id: deploy-prod,           aliases: [APR-DEPLOY-PROD], when: {action: ["code.deploy"], labels: {env: prod}}, approver: owner, grant_ttl_s: 600}
    - {id: deploy-mainline,       aliases: [APR-DEPLOY-MAINLINE], when: {action: ["code.deploy"], labels: {env: mainline}}, approver: admin}
    - {id: deploy-staging,        aliases: [APR-DEPLOY-STAGING], when: {action: ["code.deploy"], labels: {env: staging}}, approver: self}
    - {id: deploy-dev,            aliases: [APR-DEPLOY-DEV], when: {action: ["code.deploy"], labels: {env: dev}}, approver: auto}
    - {id: deploy,                when: {action: ["code.deploy"]}, approver: admin}
    # budget overrides from BUD-01 (on_hard: require_approval) and MCP re-pins from MCP-03
    - {id: budget-override,       when: {kind: [budget_raise]}, approver: admin}
    - {id: mcp-repin-internal,    aliases: [APR-MCP-REAPPROVE-INTERNAL], when: {kind: [mcp_pin], labels: {dest: local}}, approver: self}
    - {id: mcp-repin,             aliases: [APR-MCP-REAPPROVE-EXTERNAL], when: {kind: [mcp_pin]}, approver: admin}

  # Config changes (GOV-05). `action` globs match PolicyChange.kind; labels are per-change facts
  # (control_severity, loosening, scope, model_dest, provider_new, signature_severity, requester_is_sponsor).
  # Multi-change proposals take the highest level. FIRST MATCH WINS.
  config_rules:
    - {id: approval-rules,        when: {action: ["approval.rule"]}, approver: owner}
    - {id: protect-more,          aliases: [APR-CTRL-ENABLE, APR-POLICY-TIGHTEN], when: {action: ["control.enable", "control.add", "control.action.tighten", "control.threshold.tighten", "model.disallow"]}, approver: auto}
    - {id: mode-tighten,          when: {action: ["control.mode"], labels: {loosening: "false"}}, approver: auto}
    - {id: disable-control-strict, aliases: [APR-CTRL-STRICT], when: {action: ["control.disable", "control.remove", "control.mode", "control.action.loosen"], profiles: [strict]}, approver: owner, two_person: true, ttl_s: 3600}
    - {id: disable-control-critical, aliases: [APR-CTRL-BALANCED-CRITICAL], when: {action: ["control.disable", "control.remove", "control.mode", "control.action.loosen"], labels: {control_severity: critical}}, approver: owner}
    - {id: disable-control-permissive, aliases: [APR-CTRL-PERMISSIVE], when: {action: ["control.disable", "control.remove", "control.mode", "control.action.loosen"], profiles: [permissive]}, approver: self}
    - {id: disable-control,       aliases: [APR-CTRL-BALANCED], when: {action: ["control.disable", "control.remove", "control.mode", "control.action.loosen"]}, approver: admin}
    - {id: raise-org-2x,          aliases: [APR-BUDGET-ORG-OVER-2X], when: {action: ["budget.raise"], scope_type: [org], increase_pct_gt: 100}, approver: owner, two_person: true}
    - {id: raise-org,             aliases: [APR-BUDGET-ORG], when: {action: ["budget.raise"], scope_type: [org]}, approver: owner}
    - {id: raise-large,           aliases: [APR-BUDGET-TEAM-OVER-2X], when: {action: ["budget.raise"], scope_type: [team], increase_pct_gt: 100}, approver: owner}
    - {id: raise-team-small,      aliases: [APR-BUDGET-TEAM-2X], when: {action: ["budget.raise"], scope_type: [team]}, approver: admin}
    - {id: raise-agent-large,     aliases: [APR-BUDGET-AGENT-LARGE], when: {action: ["budget.raise"], scope_type: [member, agent, session], increase_pct_gt: 50}, approver: admin}
    - {id: raise-small,           aliases: [APR-BUDGET-AGENT-SMALL], when: {action: ["budget.raise"], scope_type: [member, agent, session]}, approver: self}
    - {id: raise-other,           when: {action: ["budget.raise", "budget.remove"]}, approver: owner}
    - {id: budget-tighten,        when: {action: ["budget.lower", "budget.add"]}, approver: admin}
    - {id: profile-down,          aliases: [APR-POLICY-PROFILE-DOWN], when: {action: ["profile.change"], labels: {loosening: "true"}}, approver: owner}
    - {id: profile-up,            when: {action: ["profile.change"]}, approver: auto}
    - {id: killswitch-release-global, aliases: [APR-KILL-RELEASE-GLOBAL], when: {action: ["killswitch.off"], labels: {scope: global}}, approver: owner}
    - {id: loosen-threshold,      aliases: [APR-KILL-RELEASE], when: {action: ["control.threshold.loosen", "killswitch.off"]}, approver: admin}
    - {id: killswitch-own-agent,  aliases: [APR-KILL-ENGAGE], when: {action: ["killswitch.on"], labels: {requester_is_sponsor: "true"}}, approver: auto}
    - {id: tighten,               when: {action: ["killswitch.on"]}, approver: admin}
    - {id: provider-change,       when: {action: ["provider.change", "route.change"]}, approver: owner}
    - {id: model-new-provider,    aliases: [APR-MODEL-NEW-PROVIDER], when: {action: ["model.allow"], labels: {provider_new: "true"}}, approver: owner}
    - {id: model-allow-local,     aliases: [APR-MODEL-LOCAL], when: {action: ["model.allow"], labels: {model_dest: local}}, approver: self}
    - {id: model-allow,           aliases: [APR-MODEL-REMOTE], when: {action: ["model.allow"]}, approver: admin}
    - {id: feed-override-critical, aliases: [APR-FEED-OVERRIDE-CRITICAL], when: {action: ["feed.override"], labels: {signature_severity: critical}}, approver: owner}
    - {id: feed-override,         aliases: [APR-FEED-OVERRIDE], when: {action: ["feed.override"]}, approver: admin}
    - {id: mcp-server-strict,     aliases: [APR-MCP-REGISTER-STRICT], when: {action: ["mcp.server"], profiles: [strict]}, approver: owner}
    - {id: mcp-server,            aliases: [APR-MCP-REGISTER], when: {action: ["mcp.server"]}, approver: admin}
    - {id: control-params-loosen, when: {action: ["control.params"], labels: {loosening: "true"}}, approver: admin}
    - {id: policy-loosen-strict,  aliases: [APR-POLICY-LOOSEN-STRICT], when: {profiles: [strict], labels: {loosening: "true"}}, approver: owner}
    - {id: policy-loosen,         aliases: [APR-POLICY-LOOSEN], when: {labels: {loosening: "true"}}, approver: admin}
    - {id: policy-neutral,        aliases: [APR-POLICY-NEUTRAL], when: {action: ["control.params", "other"]}, approver: self}

  # Routing self-tests (port of staging routing_tests; run by unit tests and after every apply).
  # requester = member id or agent id from the org seed; expect.rule uses contract ids.
  tests:
    - {name: saas-subscription-50-needs-admin, staging: true, request: {kind: action, action_type: spend.subscription, requester: trading-copilot@trading, amount_usd: 50, resource: "vendor:marketpulse", labels: {vendor_approved: "true", recurring: monthly}},
       expect: {required_role: admin, rule: spend-admin, approvers_ok: [u_emily, u_marek, u_katarzyna], approvers_not_ok: [u_piotr, u_olivia, trading-copilot@trading]}}
    - {name: team-monthly-raise-under-2x-admin, staging: true, request: {kind: config_change, requester: u_piotr, changes: [{kind: budget.raise, path: "budgets.limits[scope=team:trading,window=month].usd", scope: "team:trading", dimension: usd, before: 1200, after: 2000, increase_pct: 66.67}]},
       expect: {required_role: admin, rule: raise-team-small, gov05: require_approval, approvers_ok: [u_emily, u_marek, u_katarzyna], approvers_not_ok: [u_piotr]}}
    - {name: disable-control-strict-two-person, staging: true, profile: strict, request: {kind: config_change, requester: u_marek, changes: [{kind: control.disable, path: "controls[id=INJ-02].enabled", control_id: INJ-02, before: true, after: false, loosening: true}]},
       expect: {required_role: owner, two_person: true, rule: disable-control-strict, approvers_ok: [[u_katarzyna, u_emily]], approvers_not_ok: [u_marek]}}
    # … the remaining 31 staging cases follow the same pattern (table §5.1), plus the F4/F5/F6/F9 flow cases of APR-V03

controls:
  - id: GOV-05
    name: Config-change governance (who may change what)
    action: require_approval
    severity: high
    fail_mode: closed
    timeout_ms: 50
    owasp: [ASI03, ASI09]
    params: {allow_if_proposer_satisfies: true, agent_proposals: require_approval, title_template: "{actor} wants to {summary}"}
    tests:   # need policy-engine runner support for `member` / `changes` (contract gap 5)
      - {name: member-raises-team-budget, kind: config_change, surface: config.change, destination: local, member: u_piotr, expect: require_approval, control: GOV-05,
         changes: [{kind: budget.raise, path: "budgets.limits[scope=team:trading,window=day].usd", scope: "team:trading", dimension: usd, before: 60, after: 75, increase_pct: 25}]}
      - {name: owner-raises-team-budget, kind: config_change, surface: config.change, destination: local, member: u_katarzyna, expect: allow,
         changes: [{kind: budget.raise, path: "budgets.limits[scope=team:trading,window=day].usd", scope: "team:trading", dimension: usd, before: 60, after: 150, increase_pct: 150}]}
      - {name: admin-disables-critical-control, kind: config_change, surface: config.change, destination: local, member: u_marek, expect: require_approval, control: GOV-05,
         changes: [{kind: control.disable, path: "controls[id=DLP-02].enabled", control_id: DLP-02, before: true, after: false, loosening: true}]}
```

The implementer writes out all 34 staging cases (+ ≈ 12 flow cases) in full. The `staging: true` marker lets `test_routing_seed.py` assert exactly 34.

---

## 8. Dependencies

- **No new packages.** Python stdlib (`sqlite3`, `asyncio`, `hmac`, `hashlib`, `json`, `fnmatch`, `time`) plus deps already in the manifest: `pydantic>=2.9`, `fastapi`, `pyyaml` (snippet in tests, seed file), `httpx`.
- Dev: `pytest`, `pytest-asyncio` (`asyncio_mode=auto`), `asgi-lifespan` (integration test only), `ruff`.
- Runtime collaborators: core-gateway (crypto, paths, deps, errors, runtime, pipeline), policy-engine (snapshot / apply / on_change / propose / executor registration), org-rbac (members, agents, resources, viewer), action-guards / budgets-ledger / mcp-proxy (drafts + labels), audit-metrics, bus.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| The hook and the MCP proxy resolve different identities, so fingerprints differ: duplicate cards, and the held call never passes | Contract gap 10 (send the same `X-Aegis-Agent`); 30 s redemption window; APR-V10 runs the exact call through both paths before the demo |
| Hold longer than the client timeout makes Claude Code **fail open** (FINDINGS #3b) | `hold_s.hook = 60` < hook curl 110 s < settings timeout 120 s (§2.7, told to claude-code-integration); SDK timeout > hold (gap 8) |
| First-match ordering surprises when judges edit rules live | Families ordered most-restrictive-first with fail-closed catch-alls; unknown condition keys never match; routing self-test warning after each apply (APR-11); `/simulate` and the rules page show order and reason |
| Executor ownership race (policy-engine vs fallback) | Separate fallback layer: registration order is irrelevant (APR-V05) |
| Stale YAML proposal re-applied over newer changes | Fallback prefers patches and refuses YAML whose `base_version` is stale (`execution.status=conflict`) |
| Approval replay for different parameters / config approvals redeemed for other calls | Token + fingerprint must both match; only `kind=action` is redeemable; executor kinds set `uses=max_uses` (APR-V04) |
| Raw PII in approval payloads, SSE or audit | Bound args masked via `rt.redactor.mask_for_log`, capped size; SSE trims YAML; privacy test APR-V08 |
| HITL flooding by a runaway agent | Reuse pending by fingerprint, per-principal and global caps, deny cooldown |
| Missing labels from producers (vendor, data class, env) | Derivation from `rt.org.resources()`; otherwise fail-closed defaults (admin/owner) — never `auto` |
| One owner makes two-person impossible under a literal reading | Interpretation (owner + distinct admin) + proposer co-sign, documented as gap 4 and tested |
| SQLite contention / blocking the event loop | One connection + lock, WAL, tiny indexed queries inline, lists via `asyncio.to_thread`; in-memory waiters |
| Time pressure | Must-tasks ≈ 117 min (APR-01…09), delivered in dependency order with the V-tests alongside; should ≈ 35 min, could ≈ 65 min; the cut order in §6 keeps every headline flow intact |
