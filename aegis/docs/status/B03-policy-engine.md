# B03-policy-engine — status

Two agents worked on this bundle. Agent 1 wrote POL-02 and most of the engine modules. Agent 2 (this report) added the routes, the snippet tool, the schema export and the tests, applied the orchestrator fixes, and ran the verification tasks.

## Tasks
| ID | State | Notes |
|---|---|---|
| POL-01 skeleton | done | `aegis.policy.store:create(rt)` provides `snapshot()`, `control_config()` and `on_change()`. |
| POL-02 catalog | done | `config/policy.yaml` is byte-identical to the golden file: 39 controls and 82 inline tests. `config/profiles/{permissive,balanced,strict,paranoid}.yaml` are in place. |
| POL-03 loader/validator | done | Errors carry line/col, typo suggestions, the RE2 check and the A-34 whitelist. `match_agents`, `redact_system`, `escalation` and `note` were added to the whitelist. |
| POL-04 profiles | done | See the V04 matrix below. |
| POL-05 store | done | Pipeline: parse → validate → profile merge → self-test gate → atomic swap. The last-known-good file is `data/policy/last_good.yaml`. Also covers `policy_versions` / `policy_proposals`, audit, bus, metrics, `on_change`, and the startup fallback chain file → last_good → golden → defaults. |
| POL-06 watcher + reload | done | `watchfiles` with a 200 ms debounce. The store ignores its own writes and does not watch in `AEGIS_TEST_MODE=1`. `POST /api/policy/reload` (admin) is the manual fallback. |
| POL-07 routes | done | `src/aegis/api/routes/policy.py` serves every §5.4 and A-31 endpoint, plus `/api/policy/status` and `/api/policy/effective?profile=`. Stale writes get 409 and invalid YAML gets 422. |
| POL-08 diff | done | |
| POL-09 patch | done | Fix: `_node_end_line` now goes down to the last leaf of block collections. Before, inserts and removes after a block-mapping item ran into the next sibling. |
| POL-10 governed propose + executors | done | Covers GOV-05, the fallback route and the `config_change` / `budget_raise` executors. F5 was tested end to end: an admin disables DLP-02, the request goes pending, the owner approves, and the change applies. |
| POL-11 self-test gate | done | A-29 semantics. A **governed profile switch** no longer fails the gate on cases that passed under the old profile; they become warnings. Without this, `profile: permissive` was always rejected. The `headers` test extra now reaches `Interaction.headers` and `ctx.headers` (A-30). |
| POL-12 controls/coverage | done | `DecisionStats` is started from `on_startup`. |
| POL-13 self-test extras | done | Run `python -m aegis selftest [--all-profiles] [--json]`. |
| POL-14 schema | done | `scripts/export_schema.py` writes `config/schema/policy.schema.json`. |
| POL-16 snippet check/merge | done | See "Integrator" below. The live policy has **not** been merged; that is left to the integrator. |
| POL-15, POL-17 (partial: whitelist), POL-18–22 | not started / partial | POL-20 `register_validator` and POL-19 `effective_controls(profile)` are available on the store. |

## Verification
- V01: import smoke `ok`; `ruff check` on all owned code: all checks passed.
- V02: validate gives 0 errors and 0 warnings. `cmp` against the golden file shows no difference, the empty-patch round-trip returns the text unchanged, and all 38 catalog ids (plus GOV-06) are present.
- V03/V05/V06: `uv run --frozen pytest tests/unit/policy_engine -q` gives **38 passed** in about 60 s. Most of that time is the in-process app startup in `test_routes.py`; `test_watcher.py` is marked slow.
- V04, INJ-02 / DLP-02 / ACT-01 cap / EXE-03 per profile:

  | Profile | INJ-02 | DLP-02 | ACT-01 cap | EXE-03 |
  |---|---|---|---|---|
  | permissive | 0.80 | redact | 10000 | log |
  | balanced | 0.80 | block | 5000 | require_approval |
  | strict | 0.75 | block | 1000 | block |
  | paranoid | 0.60 | block | 500 | block |

  INJ-02 is pinned at 0.80 per SF-22, not 0.90.
- V09: `python -m aegis selftest --all-profiles` exits 0. Balanced passes 82/82. The failures in the other profiles are expected profile deltas and never fail the gate.
- V10: `schema ok`.
- Live check (in-process app): an apply lands in about 70–300 ms with summary text for the toast. Broken YAML is rejected with `still on vN, line L col C`. A rollback creates a new version, and a stale `base_version` returns 409.

## Orchestrator fixes applied (live `config/policy.yaml` and golden, byte-identical)
1. F6 (B08): the chaos-agent day limit now has `on_soft: warn`. Validates 0/0, self-test 82/82, applies as owner. **`docs/seed-fixes/policy.yaml` is not owned by B03 and needs the same one-line change.**
2. B12: added `mcp.servers.poisoned-stdio`, copied from `config/snippets/mcp-proxy.yaml`. Validates 0/0, self-test 82/82.

## Integrator: one-command snippet merge (POL-16)
```
uv run --frozen python -m aegis.policy.snippets check      # what would change (nothing written)
uv run --frozen python -m aegis.policy.snippets merge      # merge, validate, write policy.yaml + policy.golden.yaml
uv run --frozen python -m aegis selftest                   # optional: inline tests
```
- Merge rules follow A-34. Keyed lists merge by id, name, (scope, window, match_agents) or from. New items go in after the previous snippet item, so rule order is preserved. Values tagged `[SF-..]` are kept from the policy. Comments and untouched lines stay byte-identical, and a second run makes no changes.
- Rehearsal at 00:00 on a copy of the live policy:
  - 16 snippets, 395 changes, 0 merge errors, 0 validation errors.
  - The merged policy passes the gate: **183/183 self-tests** and an owner apply succeeds.
- Known reported items:
  - `semantic-models.yaml` has a top-level `profiles:` section, which is skipped because it is not a policy section.
  - Two `description` conflicts on approval rules, where the later snippet wins: `org-owner-grants` (approvals-engine vs org-rbac) and `goal-drift` (approvals-engine vs injection-defense).
  - INJ-02 `threshold` is kept at 0.80 because of SF-22.
- Merging takes about 20 s. Merge while the gateway runs and the watcher hot-reloads it, or call `POST /api/policy/reload`.

## Files (created or changed by agent 2)
`src/aegis/api/routes/policy.py`, `src/aegis/policy/snippets.py`, `scripts/export_schema.py`, `config/schema/policy.schema.json`, `config/snippets/policy-engine.yaml`, `tests/unit/policy_engine/{conftest,test_loader_validate,test_profiles_diff_patch,test_store,test_routes,test_snippets,test_watcher}.py`. Edited: `src/aegis/policy/{patch,store,selftest,validate,watcher,views}.py`, `config/policy.yaml`, `config/policy.golden.yaml`.

## deps_needed
None.

## contract_deviations
- Additive endpoints: `/api/policy/status` and `/api/policy/effective`.
- `PolicyDiffResponse` has the extra fields `rule_id` and `two_person`.
- The profile-switch gate behaviour described under POL-11.

## integration_todos
- Run the snippet merge (above), then `make reset` / copy the golden file as usual.
- Apply the `docs/seed-fixes/policy.yaml` delta (chaos-agent `on_soft: warn`, `poisoned-stdio` server) if the seed fixes are kept in sync.
- **Not B03:** `src/aegis/injection/canary.py:55` `extract_urls` raises `IndexError: no such group` (`m.span(1)`). INJ-04 then logs an internal error and degrades to allow on `model.response`. Owner: injection-defense.
- **Not B03:** `get_settings()` is cached per process. Tests that build several apps must pass `create_app(Settings.from_env())`, otherwise a later app reuses an earlier test's temp policy and data dir.
