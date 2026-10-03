# B13-claude-code — status

Claude Code integration (plan `docs/plan/12-claude-code-integration.md`, Addendum A-06/A-07/A-13/A-17/A-19/A-23/A-40/A-47/A-48 applied).

## Tasks
| ID | State | Notes |
|---|---|---|
| CC-01 skeleton | done | route `POST /v1/hooks/claude-code` (+ `GET …/status`), package `aegis.integrations.claude_code` |
| CC-02 hook client | done | `scripts/aegis-hook` bash+curl, fail-closed matrix, key via header file; fail text now `[Aegis] FAIL-CLOSED: …` |
| CC-03 mapping | done | + A-13: `meta.client="claude-code"`, `meta.cwd`, `meta.claude_code.session_id`; `map_config_change` (config.change for GOV-06) |
| CC-04 respond | done | A-06 prefix: every deny reason starts `[Aegis] <CONTROL-ID>: `; A-23 pending text `Approval apr_… pending (needs owner: u_katarzyna) — approve at <link>, then retry`; never `ask` |
| CC-05 handler | done | pending TTL **600 s → complete(Outcome 200)** (A-13); `Outcome.error="tool_error"` for errored tool results / PostToolUseFailure; response headers `X-Aegis-Decision-Id`, `x-should-retry`, `retry-after`, `x-aegis-approval-id` (A-06) via `handle_hook_ex` |
| CC-06 SessionStart | done | banner explains `[Aegis] <ID>:` rule + placeholders; warnings |
| CC-07 profile + run.sh | done | `profile.py` (demo/failclosed/hardened, mcp.json with all 9 servers, `X-Aegis-Agent-Key` in `ANTHROPIC_CUSTOM_HEADERS`), `demo/claude/run.sh` |
| CC-08 workspace | done | `demo/claude/project/` (README, CLAUDE.md w/ internal host, docs/SETUP.md curl\|sh + HTML-comment injection, docs/roadmap.md deal code name, src/payments/refunds.py, data/customers_sample.csv FAKE checksum-valid), `reset.sh` (runtime .env + Unicode-tag line; `--clean` strips them) |
| CC-09 replay | done | `demo/claude/replay.py` (stdlib; `--hold`, `--bench`, `--via-hook`, `--list`) + 11 fixtures |
| CC-10 live demo + docs | done (live run unverified) | `demo.sh` scenes pipe-to-shell/dotenv/injection/gpu-480/failclosed/rehydrate, `PROMPTS.md`, `README.md` (claude update note, stop-code table) |
| CC-11 budget semantics | done | budget pre-check → GOV-06 decision (402 budget_exceeded / 429 killed + `x-should-retry: false`) |
| CC-12 ConfigChange guard | done | guarded-key diff (baseline = generated profile for profile copies), Stop/SessionEnd sweep |
| CC-13 DLP-08 rehydration | done | prefers `rt.redactor.rehydrate_obj` (A-40), falls back per string; verified on the real stack |
| CC-14 snippet | done | `config/snippets/claude-code-integration.yaml` (hold_s, local_tools, EXE-02 fs_deny, GOV-06 entry + knobs + tests, 6 top-level `cc-*` tests); validates against `PolicyDoc` |
| CC-15 status + check.sh | done | `GET /v1/hooks/claude-code/status`, `demo/claude/check.sh` |
| CC-16 ask surface | not done (by contract) | A-23: hook PreToolUse is **never** `ask` |
| CC-17 GOV-06 real control | done | `src/aegis/integrations/claude_code/gov06.py` (`CONTROLS=[HarnessIntegrity()]`, prio 20, discovered via A-15); handler uses the pipeline when GOV-06 is registered+enabled, else `guards.py` fallback (audit + bus only) |
| CC-18 hardened variant | done | `settings.hardened.json` |

## Verification
| ID | Command | Result |
|---|---|---|
| CC-V01 | `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/claude_code_integration` | **89 passed** (≈13 s; the in-process real-app test boots the gateway) |
| CC-V02 | `uv run --frozen ruff check src/aegis/integrations/claude_code src/aegis/api/routes/hooks_claude_code.py tests/unit/claude_code_integration demo/claude/replay.py`; `bash -n scripts/aegis-hook demo/claude/*.sh` | clean |
| CC-V03 | import smoke | `/v1/hooks/claude-code` |
| CC-V04 | hook fail-closed matrix (`test_hook_script.py`) + `check.sh` | pass (down→exit 2, PostToolUse→0, PermissionRequest deny JSON, SessionStart msg, timeout/500/non-JSON→2, missing script guarded→2) |
| CC-V05 | `test_integration.py` (create_app + lifespan, in-process) | pass: curl\|sh→EXE-01 deny, .env→EXE-02 deny, README→`{}`, WebFetch→GOV-03, SETUP.md PostToolUse→INJ-01 `updatedToolOutput`, PII prompt→note, Edit settings.json→GOV-06, ConfigChange drop hooks→GOV-06 block, malformed→deny; DLP-08 rehydration round trip restores 3 placeholders |
| CC-V06 | `uv run --frozen python -m aegis.integrations.claude_code.profile --gateway-url http://127.0.0.1:8787 --check` | `profile OK`; nothing written under `~/.claude` / managed paths |
| CC-V11 | real gateway on an ephemeral port, `gpu_480` held, approve via API | u_tomasz → 403; u_katarzyna → 200 and the held hook call flips to `allow` "approved by u_katarzyna (apr_…)" |
| CC-V14 | `replay.py read-readme --bench 50` (real gateway, ephemeral port) | HTTP p50 22 ms / p95 89 ms ✔; via bash+curl hook p50 201 ms / p95 372 ms ✘ on the shared, heavily loaded 8 GB machine (≈20 agents) — re-measure on a quiet machine |
| replay e2e | `replay.py all --hold 2` and `--via-hook` against the real gateway | **11/11 scenes matched** both ways |
| CC-V07/V08/V09/V10/V12/V13 | live `claude -p` | **not run** (orchestrator: no real Claude sessions). Integrator: `make up`, `demo/claude/check.sh`, then `demo.sh pipe-to-shell`, `dotenv`, `injection`, `failclosed`; check `/api/decisions` session ids match (V09) |

## How to run / demo
`make up` → `demo/claude/check.sh` → `demo/claude/run.sh` (= `make claude`) with `demo/claude/PROMPTS.md`, or `demo/claude/demo.sh <scene>`; offline fallback `python3 demo/claude/replay.py all` (`--hold 20` for the approval scene; approve as u_katarzyna). Run `demo/claude/reset.sh` before the demo, `reset.sh --clean` before committing.

## Files
`src/aegis/integrations/claude_code/{__init__,schema,mapping,respond,handler,pending,guards,selfcheck,profile,gov06}.py`, `src/aegis/api/routes/hooks_claude_code.py`, `scripts/aegis-hook`, `config/snippets/claude-code-integration.yaml`, `demo/claude/{settings.json,settings.failclosed.json,settings.hardened.json,mcp.json,.agent_key,run.sh,demo.sh,check.sh,reset.sh,replay.py,README.md,PROMPTS.md,fixtures/*.json,project/**}`, `tests/unit/claude_code_integration/{conftest,test_mapping,test_respond,test_handler,test_hook_script,test_profile,test_gov06,test_integration}.py`.

## deps_needed
none (uvicorn/httpx/asgi-lifespan already present).

## contract_deviations
- PostToolUseFailure completes with `Outcome(200, error="tool_error")` (A-13 wording) instead of plan's 500.
- Hook client fail-closed stderr also uses the `[Aegis] FAIL-CLOSED:` prefix (not a control id; there is no deciding control).
- `meta.cwd` carries the raw hook cwd as A-13 requires (plan said hash only); `meta.claude_code.cwd_hash` kept too.

## integration_todos
- policy-engine: `config/policy.yaml` already has GOV-06 (the real-app test sees it decide); merge `config/snippets/claude-code-integration.yaml` tests (`cc-*`, GOV-06 `bash-disable-hook-blocked`, `edit-source-file-allowed`) and `destinations.local_tools` additions (`BashOutput`, `KillShell`, `Task`, `Skill`).
- dashboard: GOV-06 rows use `control_id="GOV-06"`, owner `claude-code-integration`; bus `system` toasts use `component: "claude-code"`.
- Human before the event: `claude update` (2.1.271 on PATH), then `demo/claude/demo.sh pipe-to-shell` + `python3 demo/claude/replay.py all` (CC-V07/V09/V12).
- Commit hygiene: run `demo/claude/reset.sh --clean` before committing (keeps the generated `.env` and the Unicode-tag line out of git).
