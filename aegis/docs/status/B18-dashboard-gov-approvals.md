# B18-dashboard-gov-approvals — status

Dashboard Governance A: foundation (UIG-01), approvals inbox (UIG-02), org (UIG-06/10), approval rules + route simulator (UIG-06/07), mock store (UIG-11), persona/keyboard polish (UIG-13), API contract smoke test (UIG-16).

## Tasks

| ID | Priority | State | Notes |
|---|---|---|---|
| UIG-01 | must | done (prev. agent) | lib/{eligibility,line-diff,format-gov}, gov-api.ts, hooks.ts, shared components, mocks, page stubs |
| UIG-02 | must | done (prev. agent; verified this session) | Approvals inbox: tabs, kind filter, KPI chips, member banner, list/detail, PayloadView, WhyRole, RoutingSteps, DecideDialog, `?id=` deep link, SSE refresh, LockedAction |
| UIG-06 | must | done | Org page (hero KPIs; Teams / Members / Agents / Roles & permissions tabs, `?tab=`), Rules page (two first-match tables + defaults + note) |
| UIG-07 | should | done | RouteSimulator: live (debounced) `POST /api/approvals/simulate` with A-28 extras, 10 SCENARIOS presets, matched rule row highlighted in the tables, eligible approvers + viewer reason |
| UIG-10 | should | done (org part) | RoleChangeMenu (all options visible; locked ones show the reason), member active switch, agent Deactivate/Reactivate; gated on `whoami.permissions`/`capabilities`; 403 `approval_required` → "Sent for owner approval" toast with **Open** + pending chip from `meta.pending_changes` (A-37). KillSwitchControl is B19's. Invite member not built (endpoint is could; mock 501). |
| UIG-11 | should | done | `mocks/governance/store.ts`; this session added org.* routes (org-owner-grants / org-privileged / org-routine), send-tainted, code-exec-remote-shell, deploy-mainline, governed role changes (admin → owner approval, executor applies the patch on approval) and `pending_changes` in `mockMembersList` |
| UIG-13 | could | done (prev. agent) | PersonaSwitcher chips + select; inbox keys j/k/a/d; empty states |
| UIG-16 | could | done | `tests/unit/dashboard_governance/test_api_contract.py` (5 tests; each step skips on 404/405/501 or app start failure) |

## Verification

| ID | Command / check | Result |
|---|---|---|
| UIG-V01 | `cd web && npm run typecheck` (filtered to governance) + `npx eslint src/pages/governance/{approvals,org,rules}.page.tsx src/components/governance/{org,rules,approvals,lib} src/components/governance/*.ts src/mocks/governance` | PASS: no typecheck errors; eslint exit 0 (only warnings are in B19 files: GovernanceToaster.tsx, policy.page.tsx) |
| UIG-V02 | page-discovery node script (plan 17 §5) | PASS `OK 5/5` |
| UIG-V04 | short-lived `npx vite --port 5391` (stopped afterwards), `/ui/governance/approvals?mock=1` | PASS: as Piotr the $50 card's Approve/Deny are disabled + `data-locked`, reason "Needs an admin — you sponsor trading-copilot@trading (separation of duties)", member banner shown; as Emily Approve enabled → toast "Approved — grant valid until …, 1 use"; $4,800 two-person card 1/2 → "Approve (2 of 2)" → 2/2, approved; Deny dialog's confirm stays disabled until a reason is given. Org members tab and rules simulator rendered; mock-store org role change → 403 approval_required (rule org-privileged, owner), approved by Katarzyna → role applied; mock router presets give spend-admin / db-restricted(deny) / disable-control-critical / raise-large / spend-owner-2p. Visual review of org/rules is partial: another agent kept driving the shared browser pane. |
| UIG-V06 | live F4 (stack + demo agent) | NOT RUN (needs the full stack; integrator) |
| UIG-V07 | live F5 in the UI | NOT RUN in the UI; the server half is covered by V10 (raise → pending admin → Piotr 403 → Emily approves → policy version bumps) |
| UIG-V10 | `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/dashboard_governance -v` | PASS **5 passed** (0 skipped) against the real in-process app |

## Files (this bundle)

- Pages: `web/src/pages/governance/{approvals,org,rules}.page.tsx`
- Shared: `web/src/components/governance/{gov-api.ts,hooks.ts,ApproverBadge,LockedAction,TwoPersonProgress,ExpiryCountdown,RequesterLine,MemberAvatar,PersonaSwitcher}.tsx`, `lib/{eligibility,line-diff,format-gov}.ts`
- Approvals: `web/src/components/governance/approvals/*`
- Org (new): `web/src/components/governance/org/{TeamCards,MembersTable,AgentsTable,RolesMatrix,RoleChangeMenu}.tsx`, `org-actions.ts`
- Rules (new): `web/src/components/governance/rules/{RulesTable,RouteSimulator}.tsx`
- Mocks: `web/src/mocks/governance/{fixtures,approvals,org,rules,store}.ts`
- Tests: `tests/unit/dashboard_governance/test_api_contract.py`

## How to demo

`/ui/governance/approvals` (add `?mock=1` offline): view as Piotr → $50 MarketPulse card locked with reason; chip Emily → Approve; $4,800 card shows 1/2 → 2/2. `/ui/governance/org?tab=members` as Emily → promote Piotr to admin → "Sent for owner approval" toast + pending chip → approve as Katarzyna in the inbox. `/ui/governance/rules` → click presets; the matched row lights up.

## govStore API (consumed by B19) — unchanged

`subscribe`, `version`, `policyVersion`/`bumpPolicyVersion()`, `createApproval(draft)`, `registerExecutor(fn)`, `route(req)`, `ext`, `reset()`, `MockApiError`. Additive only: org.* routes in `route()`, `executeOrgChange` runs before registered executors for `org.*` action types.

## deps_needed

None.

## contract_deviations

- Org page meta: `icon: 'Building'` (the installed lucide has no `Building2`), `shortcut: 'g g'` (CONTRACTS A-55; plan 17 said `g o`, which is overview).
- `ApprovalSimulateRequestExt` (gov-api.ts) gained optional A-28 extras `control_id`, `loosening`, `profile` (page-local type; frozen types untouched).

## integration_todos

- Run UIG-V06/V07 on the live stack (F4 $50 card via the demo agent; F5 raise in the budgets UI) once gateway + mock_mcp + demo agent run together.
- Invite member (`POST /api/members`) has no UI; add it if org-rbac ships the endpoint (mock returns 501).
- The browser pane is shared by concurrent agents. For UI checks, open a dedicated tab (`tabs_create`); the fronted tab gets driven by other agents.
