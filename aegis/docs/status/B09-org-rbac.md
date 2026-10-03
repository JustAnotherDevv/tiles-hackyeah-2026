# B09-org-rbac — status

Bundle: Org & RBAC (Acme Capital seed, identity, view-as, permissions, GOV-01/02). Plan: `docs/plan/08-org-rbac.md`.
Built by two agent sessions (the first one was stopped mid-task; the second one verified its work, added integration and key tests, and wrote this file).

## Tasks

| ID | Priority | State | Notes |
|---|---|---|---|
| ORG-01 | must | done | `aegis.org.service:create`, `aegis.org.seed:main`, routes, CONTROLS lists |
| ORG-02 | must | done | `config/org.seed.yaml` = `docs/seed-fixes/org.seed.yaml` (Addendum A fixes); `models.py`, `seed.py` (load/map/validate with paths, `--check/--reset/--path`) |
| ORG-03 | must | done | `store.py` SQLite (contract tables + `org_meta`, `org_changes`), seeding once, HMAC canary + re-hash, cache-backed reads, `members_with_role`, `get_agent`, `resources()` |
| ORG-04 | must | done | `identity.py` O(1) HMAC key lookup, revoked/expired/unknown/mismatch, aliases, `X-Aegis-*` headers; `resolve_viewer` (header > `?view_as=` > cookie; role aliases; default `u_katarzyna`) |
| ORG-05 | must | done | `permissions.py` capability table, org-op table with hard floors, `authorize()`, whoami permissions/capabilities, policy-driven matrix |
| ORG-06 | must | done | `GET /api/org`, `/api/members`, `/api/members/{id}`, `/api/agents`, `/api/agents/{id}`, `/api/whoami` |
| ORG-07 | must | done | `changes.py`: request/apply/executor/reconcile; `POST /api/members`, `PATCH /api/members/{id}`, `PATCH /api/agents/{id}`; `org.changed` audit + `org.updated` SSE; executor registered on startup |
| ORG-08 | must | done | GOV-01 `controls/governance/gov01_identity.py` |
| ORG-09 | must | done | GOV-02 `controls/governance/gov02_models.py` (allowlists, tier ceiling block/reroute, model.admin) |
| ORG-10 | must | done | `config/snippets/org-rbac.yaml` |
| ORG-11 | should | done | `GET /api/org/permissions`, `GET /api/org/changes?status=` |
| ORG-12 | should | done | `GET/POST /api/agents/{id}/keys` (plaintext shown once, `Cache-Control: no-store`), `POST .../keys/{key_id}/revoke` |
| ORG-13 | could | done | GOV-02 `reroute_on_class`, GOV-01 `enforce_key_scopes` |
| ORG-14 | could | done | non-demo viewer needs an admin token (`compare_digest`); `POST /api/whoami` sets the `aegis_view_as` cookie |
| ORG-15 | could | not started | `POST /api/agents` (register agents from the dashboard) skipped |

## Verification

All commands were run with `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off`.

| ID | Command | Result |
|---|---|---|
| V01 | `uv run --frozen python -c 'import aegis.org.{service,seed,store,identity,permissions,changes,models,compat}, aegis.api.routes.org, aegis.controls.governance.gov0{1_identity,2_models}'` | PASS (`ok`) |
| V02 | `uv run --frozen python -m aegis.org.seed --check` | PASS: `org acme-capital: teams=3 members=8 (owners=1 admins=2) agents=5 (inactive=1) keys=6 (revoked=1 expired=1)`, exit 0. With the sponsor changed to `u_nobody` it exits 1 and reports `agents[0].sponsor: unknown member 'u_nobody'` |
| V03–V11 | `uv run --frozen pytest tests/unit/org_rbac -q` | PASS: 89 tests in about 9 s, including the perf test (10k `resolve_identity` calls under 1 s) |
| V12 | `ruff check` + `ruff format --check` on the owned src and test paths | PASS |
| V13 | `pytest tests/unit/org_rbac/test_integration.py` (real `create_app` + lifespan) | PASS: view-as `member` → `u_piotr`; revoked key → GOV-01 block with no key echoed; copilot `gpt-4.1-mini` → GOV-02 block; promotion goes through the real `/api/approvals/{id}/approve` and Piotr becomes admin |
| V14 | `uv run --frozen python -m aegis selftest` | GOV rows PASS (`disabled-agent-blocked`, `valid-agent`, `local-agent-local`, `local-agent-to-remote`). Gate failures 0. The other 20 FAILs are ACT/EXE/GOV-03/04/SIG-03 tests owned by other bundles |
| V15 | manual `make up` demo | not run (no long-lived servers on the shared machine). V13 covers the same promotion flow in-process |

## Files
- `src/aegis/org/{__init__,models,compat,seed,store,identity,permissions,changes,service}.py`
- `src/aegis/controls/governance/{_common,gov01_identity,gov02_models}.py`
- `src/aegis/api/routes/org.py`
- `config/org.seed.yaml`, `config/snippets/org-rbac.yaml`
- `tests/unit/org_rbac/` (conftest + 12 test modules; `test_integration.py` and `test_keys.py` added in this session)

## How to demo
- `python -m aegis.org.seed --check` prints the org summary.
- `curl -H 'X-Aegis-View-As: admin' :PORT/api/whoami` returns the viewer, permissions and capabilities.
- Promotion flow: `PATCH /api/members/u_piotr {"role":"admin"}` as `u_marek` returns `403 approval_required` with an `apr_…` id. Approving it as `u_katarzyna` via `/api/approvals/{id}/approve` applies the change, writes the `org.changed` audit event and publishes `org.updated` over SSE.
- Revoking a key: `POST /api/agents/{id}/keys/{key_id}/revoke`. GOV-01 then blocks that key on the next request.

## deps_needed
None.

## contract_deviations (all additive)
- Extra endpoints: `/api/agents/{id}`, `/api/org/permissions`, `/api/org/changes`, the key endpoints and `POST /api/whoami`.
- Extra tables: `org_meta` and `org_changes`.
- `WhoAmI.capabilities` and `view_as_options`.
- `meta.pending_changes` on members.

## integration_todos
- policy-engine: the GOV-01/GOV-02 params, tests and the `org.*` approvals rules from `config/snippets/org-rbac.yaml` must go at the TOP of `approvals.rules` in `config/policy.yaml`. The current selftest already passes the GOV rows.
- policy-engine self-test runner: honour a per-test `model` key so the commented GOV-02 model-allowlist tests in the snippet can be enabled (plan 08 gap G9).
- `src/aegis/org/compat.py:22` local HMAC fallback is only used when `aegis.core.crypto` is missing. It can be removed once that module is always present.
- Observed, not mine: during the `create_app` test the semantic manager logs `horizon-small pending->loading` even with `AEGIS_SEMANTIC=off`. B07 should check this, because loading a model inside tests is a risk on the 8 GB machine.
