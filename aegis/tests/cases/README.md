# Aegis self-test cases — add a line, see it in the matrix

Every YAML item in this folder is one black-box test. `make test` boots a **hermetic** gateway
(temp data dir, a copy of `config/policy.golden.yaml`, fake LLM / exfil sink / signed feed on
ephemeral ports — no models, no fixed ports, no running stack), runs every case, and prints a
**pass/fail matrix per control**. Evidence files land in `reports/`:
`junit.xml`, `results.json` (schema `aegis.selftest/1`, shown in the dashboard), `matrix.md` and an
offline, self-contained `selftest.html`.

| Command | What it runs |
|---|---|
| `make test` | all unit tests + hermetic e2e + coverage gate + reports |
| `make test-e2e` | hermetic e2e + coverage only (fast loop) |
| `make test-live` | the **same cases** against the running gateway (`make up`) and its **current** policy; guard cases are dry-run (no approvals, no audit noise); mutating suites only with `AEGIS_LIVE_MUTATE=1` |
| `uv run --frozen pytest tests/e2e/test_cases.py -k DLP01` | just the DLP-01 cases |

## Add a case (judge walkthrough)

Append one line to the family file (`dlp.yaml`, `inj.yaml`, `exe.yaml`, …):

```yaml
  - {id: JUDGE-001, control: DLP-01, polarity: attack, expect: redact, input: "IBAN PL61 1090 1014 0000 0712 1981 2874", dest: remote}
```

Run `make test-e2e` — `JUDGE-001` appears under DLP-01 in the console matrix and in
`reports/selftest.html`. A typo (`expct:`) fails `tests/test_cases_schema.py` with
`tests/cases/dlp.yaml:<line>: JUDGE-001: extra field 'expct'`.

Edit the policy instead and re-run against the live gateway (`make test-live`): a control you
disabled shows **DISABLED**, never a cryptic FAIL. Rules and feed signatures carry their own
`tests:` — those are collected automatically (`tests/e2e/test_inline_tests.py`).

## Schema

A file is a list of cases, or `{defaults: {...}, cases: [...]}` (defaults merged into each case).
Files starting with `_` are not case files (`_harness.yaml` holds tunables).

| Key | Meaning |
|---|---|
| `id` | unique, `[A-Z0-9-]+` |
| `control` | expected deciding control (attribution); a list = any of; omit = any |
| `polarity` | `attack` \| `benign` \| `error` (must agree with `expect`) |
| `expect` | `allow` \| `log` \| `redact` \| `require_approval` \| `block` \| `error:<http or jsonrpc code>` |
| `via` | `guard` (default, `POST /v1/guard`) \| `anthropic` \| `openai` \| `ollama` \| `hook` \| `mcp` \| `egress` \| `playground` \| `simulate` \| `api` |
| `surface`, `kind` | contract Surface / Kind (kind derived from surface) |
| `dest` | `local` \| `remote` \| `third_party` |
| `as` | agent id (`trading-copilot@trading`, uses its seed key), member id (`u_piotr`), `key:revoked`, `none` |
| `input` / `segments` | text, or `[{text, role, trusted}]` |
| `tool`, `args`, `url`, `method`, `model`, `stream`, `amount_usd`, `labels`, `meta` | interaction fields (MCP tools as `server.tool`) |
| `hook_event` | `PreToolUse` \| `PostToolUse` \| `UserPromptSubmit` \| `ConfigChange` (via: hook; templates in `tests/fixtures/hooks/`) |
| `path`, `json`, `view_as` | via: api |
| `action_type`, `resource`, `changes` | via: simulate (who approves what) |
| `expect_entities` | entities that must be redacted (`PESEL`, `IBAN`, `PAN`, …) |
| `expect_route` / `expect_rule` | approval level `auto\|self\|admin\|owner\|deny` (`owner+2p` = two-person) / rule id |
| `expect_status` | HTTP status (proxies, egress, api) |
| `expect_monitor` | `{control, action}` a monitor-mode control "would have" decided |
| `assert` | `upstream_must_contain`, `upstream_must_not_contain`, `response_must_contain`, `response_must_not_contain`, `audit_must_not_contain`, `sink_hits`, `tool_listed`, `tool_not_listed` |
| `steps`, `repeat` | multi-step in one session (expect applies to the last step) / replay N times |
| `mode` | `deterministic` \| `semantic` (skipped unless `make test-sem`) \| `both` |
| `tier` | `core` (gating) \| `stretch` (reported as xfail when it fails, never hidden) |
| `profiles` | run only when the loaded policy profile matches |
| `tags`, `source`, `note` | `owasp:LLM01:2025`, `scenario:S1`, provenance, free text for the report |
| `hermetic_only` | mutating case; skipped in live mode unless `AEGIS_LIVE_MUTATE=1` |

## Outcomes and statuses

- **pass** — right action and right control; **pass_other** (yellow) — right action, another control decided;
  **fail**; **xfail** — a stretch case failed or the control is not implemented; **disabled** — the expected
  control is switched off in the loaded policy; **skip** — e.g. semantic mode off, endpoint missing.
- Matrix status per control, first match wins: `DISABLED` · `NOT_IMPLEMENTED` · `UNTESTED` (no must-block
  or no must-allow test anywhere) · `FAIL` · `PARTIAL` (only stretch failures) · `SKIPPED` · `PASS`.
- `tests/test_coverage.py` fails on UNTESTED MVP controls (`AEGIS_ALLOW_UNTESTED=1` to downgrade).

## Test data rules

Only fake values (research-05 fixture table: PESEL `44051401359` valid vs `44051401358` invalid, IBAN
`…2874` vs `…2875`, card `4111 1111 1111 1111` vs `…1112`). Never commit secret-shaped strings — use
macros, expanded at run time and registered in the privacy scanner:

`{{gen:aws_access_key_id|aws_secret|github_pat|slack_token|stripe_key|jwt|openssh_private_key|anthropic_key}}`,
encoders `{{b64:T}}` `{{b64url:T}}` `{{hex:T}}` `{{tags:T}}` `{{zw:T}}` `{{repeat:N:T}}` (nestable).
`tests/test_no_committed_secrets.py` enforces this. Attack strings are harmless stand-ins
(`http://evil.test/i.sh`, `exfil.test`), never working exploits.

## Environment knobs

`AEGIS_LIVE_URL`, `AEGIS_LIVE_MUTATE`, `AEGIS_LIVE_MOCK_LLM|MCP|SINK|FEED`, `AEGIS_TEST_MOCKS=real`
(use `mocks.*` apps instead of the built-in fakes), `AEGIS_TEST_GATEWAY=subprocess` (black-box gateway
process), `AEGIS_TEST_OVERRIDES=<yaml>` ("what if" policy deltas, same shape as
`tests/fixtures/policy_overrides.yaml`), `AEGIS_ALLOW_UNTESTED`, `AEGIS_REPORTS_DIR`.

Seeding: `uv run --frozen python -m tests.lib.seed_import --write --out <dir>` translates the staging
policy examples and approval routing tests into this schema (provenance in each case's `source:`).
