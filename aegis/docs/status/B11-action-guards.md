# B11-action-guards — status

Controls GOV-03, GOV-04, ACT-01..04, EXE-01..03 are **all real** (no stubs). The headline flows F3 and F4 work end-to-end through the real in-process pipeline: `/v1/guard` runs the real approvals-engine, which routes $50 → `spend-admin`, `DELETE FROM trades` → `db-prod-write` (owner) and $12 → `spend-self`.

## Tasks
| ID | State | Notes |
|---|---|---|
| ACT-01 surfaces | done | `aegis.actions.classify` (exact §3.3 signature), `runtime`, `base`, `params`, 9 control modules with `CONTROLS` |
| ACT-02 classification | done | argpath (pseudo-paths + json/body fallback), rx (RE2→re fallback), money, `match_rule/classify/ensure_classified/refine/render_title`, `rules_builtin` |
| ACT-03 catalog/explain/drafts | done | `catalog.get_catalog` (5 s cache, `FALLBACK_RESOURCES`, `params.tables` overrides), `explain.Explain`, `drafts.build_draft/flood_check/preview_route` |
| ACT-04 ctl ACT-01 spend | done | fx, vendor/plan, catalog price check (understated $5 → $4,800), hard cap, unapproved vendor, auto-allow, labels `vendor_approved/recurring/amount_unknown`, sets `interaction.amount_usd` |
| ACT-05 SQL + ctl ACT-02 | done | sensitivity from table + `sensitive_columns`, aggregate cap, prod DDL block (also stacked), RESTRICTED block, standing grants, labels `sensitivity/env/operation/unbounded/bulk/grant` |
| ACT-06 shell + ctl EXE-01 | done | 11 structural detectors, decoded base64 ("decodes to `rm -rf ~`"), deny/approve/allow patterns, `unknown_command`; `cfg.action` lever (block → require_approval) |
| ACT-07 ctl EXE-02 | done | fs deny/exceptions/write-deny/allow, symlinks, cwd; SSRF canonicalization (decimal/octal/hex/short/IPv6-mapped/userinfo), allow_hosts with port ranges, `egress_allowlist` |
| ACT-08 snippet | done | `config/snippets/action-guards.yaml`: `actions:` identical to the live table, 9 controls with params and 43 inline tests, `x-profiles` |
| ACT-09 headline tests | done | `conftest.py` mini-pipeline harness plus `test_scenarios.py` |
| ACT-10 GOV-03 | done | global deny, agent allow/deny (`mcp__` and `name:qual` normalized), `action_types`, `arg_rules` |
| ACT-11 ACT-03 | done | per-recipient internal check, denylist, data class (placeholders, Luhn, `rt.redactor.detect`), RESTRICTED/SECRET external → block |
| ACT-12 ACT-04 | done | terraform/kubectl/helm/git push (protected or force)/vercel/fly/sls/gcloud/docker push; pkg install; code.exec; env extraction; `category_actions` |
| ACT-13 EXE-03 | done | `actions/taint.py`; `on_complete` marks private/untrusted; adds `signals=lethal_trifecta` (A-27); TTL by turns/seconds |
| ACT-14 GOV-04 + flood | done | `approve_tools` → `tool:<name>`; flood check in `base.soft()` |
| ACT-15 adversarial | done | `test_analyzers.py` (shell obfuscation + benign twins, SQL, FS incl. symlink, SSRF encodings, classify) |
| ACT-16 /v1/guard integration | done | `test_guard_integration.py` (root `client` fixture; skips if the app can't boot) |
| ACT-17 explain extras | partial | `agent_note` done; `drafts.preview_route` exists but is not yet used in reasons; no `budget_impact` |
| ACT-18 SSRF hardening | partial | realpath symlinks on; no DNS re-check / nip.io |
| ACT-19 free-text amount | done | `params.amount_from_text` (off by default) |
| ACT-20 LIMIT clamp | not started | `params.clamp_rows` placeholder only |
| ACT-21 perf bench | not started | |

**Orchestrator request from B12, done:** EXE-02 no longer treats the MCP upstream as an SSRF target.
- On `mcp.call` and `mcp.init`, EXE-02 reads URLs only from the tool arguments. It ignores `interaction.url`, which is the registered upstream; MCP-01 governs the registry.
- Any URL whose (host, port) matches a configured `mcp.servers[*].url` is exempt.
- Test: `test_scenarios.py::test_mcp_upstream_not_ssrf`. It also confirms that an agent-chosen URL argument to a loopback port is still blocked.

## Verification
| ID | Command | Result |
|---|---|---|
| V01 | import + discovery one-liner from plan | PASS (9 ids, annotations ok) |
| V02 | `uv run --frozen pytest tests/unit/action_guards -q` | PASS 165 passed, 1 skipped (AGT-EXF-006 is DLP-04's). Wall time 13.5 s, of which about 2 s is booting the app for ACT-16 on a loaded machine. Without the integration test the suite runs in under 8 s. |
| V03 | `ruff check` + `ruff format --check` on owned paths | PASS |
| V04 | `pytest tests/unit/action_guards/test_corpus_agentic.py -rA` | PASS (29 mapped rows; 1 override AGT-SPEND-003 with reason) |
| V05 | `pytest tests/unit/action_guards/test_snippet.py` | PASS (sections validate, params have no unknown keys, all 43 inline cases, actions == live table) |
| V06 | `pytest tests/unit/action_guards/test_guard_integration.py` | PASS (real app: $50 → admin/spend-admin, $5000.01 block, customers → approval, payment_cards block, base64 → sh block, .env block) |
| V07 | live curl on :8787 | not run (no servers left running); equivalent covered in-process by V06 |
| V08/V09 | manual Claude Code / MCP demo | not run (user/integrator) |
| V10 | judge lever hot reload | covered in-process (`test_judge_levers_spend`: hard cap 40 → block, auto-allow 60 → allow); live reload not run |
| V11 | `uv run --frozen python -m aegis selftest` | PASS, 82/82, including every ACT/EXE/GOV-03/04 case in the live `config/policy.yaml` |

## Files
- **New:** `src/aegis/actions/{commands,taint}.py`, `config/snippets/action-guards.yaml`, `tests/unit/action_guards/{__init__,conftest,test_scenarios,test_snippet,test_corpus_agentic,test_analyzers,test_guard_integration}.py`, `tests/unit/action_guards/data/agentic_tools.jsonl`.
- **Rewritten from stubs:** `src/aegis/controls/actions/*.py` (all 9).
- **Ruff-formatted only:** the other `src/aegis/actions/*` helpers. `runtime.py` now uses PEP 695 generics.

## Demo
- `/v1/guard` with `tool.input` Bash `curl … | sh` → `Blocked: pipe-to-shell — curl output piped into sh executes a remote script. Do not retry or work around this.`
- `marketpulse.purchase_subscription {vendor: marketpulse, plan: mp-pro-monthly, amount_usd: 50}` as trading-copilot → `Needs approval: spending $50.00 on MarketPulse Pro (mp-pro-monthly, monthly)` (admin).
- The draft payload carries `facts`, `checks` and `agent_note`; `Decision.meta.explain` carries summary, facts, checks and levers.

## deps_needed
none (stdlib, pydantic, pyyaml; google-re2 is optional, with an `re` fallback).

## contract_deviations
- EXE-03 sets label `signals` (A-27), not `taint`.
- ACT-02 sets `bulk=true` (A-27) for unbounded prod writes, plus an extra `unbounded=true`.
- The snippet carries no `approvals.rules`; the canonical rules are already in `docs/seed-fixes/approvals.yaml` / `config/policy.yaml`.
- `capability` uses the A-27 vocabulary. The file/network distinction is in `classify.tool_kind()`, not in a label.

## integration_todos
- **policy-engine:** merge the snippet's extra controls `params`/`tests` into `config/policy.yaml`. The live entries are a subset and already pass; the new tests are understated-plan-price, pln-converted, delete-trades, drop/stacked DDL, research-grant-read, force-push, feature-push, base64, cat-ssh, hex-loopback, env-example, public-api, GOV-04 weather, and EXE-03 untainted. Also port `x-profiles` into `config/profiles/*.yaml`.
- The live `EXE-03` entry has no `action`, so the schema default is `block`. Set `action: require_approval` for balanced, unless the profile merge already does.
- **mcp-proxy (B12):** the `mocks/mock_mcp/e2e.py` workaround (adding its port to the temp policy) is no longer needed for EXE-02.
- **dashboard (G9):** render `payload.facts`, `payload.checks`, `payload.agent_note` ("agent-supplied, untrusted") and `Decision.meta.explain.levers`.
