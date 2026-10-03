# B10-approvals-engine — status

## Tasks
| ID | State | Notes |
|---|---|---|
| APR-01 | done | `aegis.approvals.service:create(rt)` → `ApprovalsService` (route/request/vote/cancel/get/list/wait/find_preapproved/register_executor/create_manual + route_info/simulate/rules_view/sweep) |
| APR-02 | done | `routing.py` (first match, `rules` + `config_rules`, multi-change → highest level), `facts.py` (amount, action_type, sensitivity/env from org resources, vendor labels, profile, scope_type, increase_pct) |
| APR-03 | done | `config/snippets/approvals-engine.yaml` = seed-fixes approvals block + routing tests + GOV-05 entry |
| APR-04 | done | `store.py` (SQLite via `rt.db()`, in-memory fallback), `fingerprint.py` (HMAC, canonical JSON minus volatile keys) |
| APR-05 | done | lifecycle, SoD, agents never vote, two-person per SF-01 (proposer co-sign), lazy expiry, notify (SSE/audit/metrics) |
| APR-06 | done | `find_preapproved` parameter-bound, single use, redeem window, replay_of |
| APR-07 | done | `executors.py` registry + fallback layer (config_change/budget_raise → `rt.policy.apply_patch/apply_yaml`, `no_executor`) |
| APR-08 | done | `controls/config/gov05_config.py` (`CONTROLS=[ConfigChangeGovernance()]`) |
| APR-09 | done | `api/routes/approvals.py` (list/rules/simulate/create/get/approve/deny/cancel, can_vote/why_not, 403/404/409/400 envelopes) |
| APR-10 | done | `expiry.py` sweeper loop (not started in test mode) + org cache refresh on `org.updated`/30 s |
| APR-11 | done | `selftest.py`; `policy.on_change` → `system` warning "Approval routing self-test: n/N failing (…)" |
| APR-12 | done | `seed.py` (org seed `demo_state.approval_history`, embedded fallback; only when table empty, not in test mode) |
| APR-13 | done | `GET /api/approvals/{id}/wait?timeout_s=` (≤60) |
| APR-14 | not started (could) | only `clock_multiplier` default exists |
| APR-15 | not started (could) | |
| APR-16 | not started (could) | |
| APR-17 | done (could) | `GET /api/approvals/{id}/timeline` |

## Verification (`AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off`)
- APR-V01 imports + `ruff check` owned paths → PASS
- APR-V02 `test_routing_seed.py` → PASS (56 cases incl. the 34 staging ones + runner)
- APR-V03 `test_routing_flows.py` → PASS
- APR-V04 `test_lifecycle.py test_fingerprint.py` → PASS
- APR-V05 `test_executors.py` → PASS
- APR-V06 `test_gov05.py` → PASS (14)
- APR-V07 `test_api.py` → PASS (10, in-process ASGI)
- APR-V08 `test_privacy.py` → PASS (3; runtime-generated PAN/PESEL, Null-redactor fallback, SSE yaml_sha256)
- APR-V09 `test_integration.py` → PASS on real `create_app` (F5: piotr raise 60→75 pending → emily approve → policy v+1; audit created→decided→executed) + F4 guard hold → piotr 403 → emily approve → retry `allow`
- APR-V10/V11 live-gateway manual checks → not run (no servers per orchestrator); V10 flow covered in-process by test_integration; V11 covered by `test_background.py` (sweep → expired SSE/audit/gauge)
- APR-V12 → covered by `test_background.py::test_policy_change_runs_selftest_and_warns`
- Whole suite: `uv run --frozen pytest tests/unit/approvals_engine -q` → 141 passed (~20 s incl. real-app integration)

## Files
src/aegis/approvals/{__init__,service,routing,facts,eligibility,fingerprint,store,expiry,executors,notify,views,seed,selftest,compat}.py ·
src/aegis/controls/config/{__init__,gov05_config}.py · src/aegis/api/routes/approvals.py ·
config/snippets/approvals-engine.yaml · tests/unit/approvals_engine/{conftest,test_routing_seed,test_routing_flows,test_lifecycle,test_fingerprint,test_executors,test_gov05,test_api,test_privacy,test_integration,test_background}.py

## Demo
Inbox: `GET /api/approvals?status=pending` (View-As header). Approve: `POST /api/approvals/{id}/approve` with `X-Aegis-View-As: u_emily`. "Who would approve?": `POST /api/approvals/simulate`. Shapes for the HarmonyOS companion (GET list, approve/deny, SSE `approval.created|updated`) follow CONTRACTS.

## deps_needed
none (tests use httpx + asgi_lifespan already in the env)

## contract_deviations (additive only)
- List/get items carry extra `can_deny`, `can_cancel`; list accepts `actionable=true`.
- Extension endpoints: `/api/approvals/{id}/wait`, `/api/approvals/{id}/timeline`.
- `/simulate` response adds `description` + `explain{eligible, eligible_names, requester, proposer_authorized}`; `/rules` adds `order`, `aliases`, `policy_version`, `selftest`.
- `POST /api/approvals` rejects `config_change`/`mcp_pin`/`org.*` drafts (must go through policy/mcp/org routes that compute changes server-side); `budget_raise` may only patch `budgets.limits`.

## integration_todos
- None blocking: real-runtime F4/F5 flows pass in-process. Integrator should run APR-V10/V11 on a live gateway (:8787) once, and confirm the policy engine merges `config/snippets/approvals-engine.yaml` (approvals block + GOV-05 entry).
