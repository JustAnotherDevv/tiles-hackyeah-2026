# B23-demo-agents — status

Bundle: scripted demo agents and scene scripts on top of `aegis.sdk` (plan 20, DEMO-06/10/11/12/13/17).
Verified live against a **private** stack (real gateway + mock_llm/mock_mcp/exfil_sink/mock_saas +
a copied feed_service state, scratch `AEGIS_DATA_DIR` and scratch policy copy, `AEGIS_SEMANTIC=off`),
started only for the smoke tests and stopped afterwards. No Ollama model was kept loaded.

## Tasks

| ID | Status | Notes |
|---|---|---|
| DEMO-06 (must) | **done** | `_common.py`, `trading_copilot.py` (pii-draft, subscribe, replay-grant, read-customers, email-client, all), `runaway.py` (loop ladder → budget wall → budget_raise approval → waits for the executor → continues → 429 killed) |
| DEMO-10 | **done** | `catalog.py` (42 steps, 10 families incl. benign, all 4 approval kinds, every control family) + `chaos_agent.py` (✓/≈/✗/· grading, `/api/controls` not-implemented skip, `--family/--only/--fast/--no-config/--approve/--keep-pending/--kill/--json/--list`, exfil-sink delta, cleanup of created cards) |
| DEMO-11 | **done** | `demo/scenarios/warmup.py` (`--fast`, `--rounds`, `--ollama auto|on|off`) + `demo/agents/ambient.py` (rate, duration, pidfile `data/run/ambient.pid`, `--stop`, auto-cancel of its approval cards, session rotation) |
| DEMO-12 | **done** | `run.py` (s1…s8, runaway, warmup, all; `--assert`, `--approve-as/--approve-after`, `--claude-fallback`, `--via-file`, `--tamper`, `--feed-reset`, `--no-cleanup`, `--with-runaway`), `s1…s8`, `tail.py` (SSE, filters, replay, reconnect), `PROMPTS.md`, `payloads/{pii,aws_key,setup_md,ti022,curl_sh}.json` + `payloads/render.py` |
| DEMO-13 | **done (scripted path verified)** | `research_agent.py` — `/ollama/api/chat` aegis-judge → qwen3:0.6b fallback, `--no-llm` scripted; live Ollama path **not run** (no model loading allowed in this session) |
| DEMO-17 (could) | not started | planner lives in `mocks/mock_llm/planner.py` (B20-owned path) — cut |

## Verification (all on the private stack)

| ID | Command | Result |
|---|---|---|
| DEMO-V08 | `python demo/agents/trading_copilot.py pii-draft` | **PASS** — `redact DLP-01`, 7 redactions; mock received `[PERSON_1] [PESEL_1] [EMAIL_1] [IBAN_1] [PAN_1] [CARD_EXPIRY_1] [REDACTED:CVV]`; `/_mock/scan` 0 raw values; reply rehydrated locally, CVV stays dropped |
| DEMO-V09 | `… trading_copilot.py subscribe --approve-as u_emily` | **PASS** — `require_approval ACT-01 · rule spend-admin · eligible u_katarzyna, u_emily, u_marek` → `approved by u_emily (admin)` → grant redeemed → `subscription active sub_…` |
| DEMO-V10 | `… runaway.py --approve-as u_emily --kill-after 2` | **PASS with policy fix** (see integration_todos #1): EXE-04 tool_error → block; BUD-01 `budget_raise` card (rule budget-override, admin) → u_emily → executor policy v+1 ($0.50 → $1.00) → continues → kill switch → `429 killed` clean stop |
| DEMO-V11 | `… chaos_agent.py --json` | **PASS** 41/41 graded as expected (37 ✓, 4 ≈, 0 ✗, 1 skipped: INJ-03 needs semantic models), attacker received 0, 0 pending left |
| DEMO-V12 | `… warmup.py --fast` + `/api/stats` + `/api/approvals?status=all` | **PASS** — 59 interactions in ~2–5 s, all 5 decision colours, MCP inventory 9 servers, approvals $12 (u_agnieszka) / $50 (u_emily, redeemed) / $480 denied (u_katarzyna) [+ team raise, see #3], pending 0, usage on trading/research/platform |
| DEMO-V13 | `… run.py all --assert --approve-as u_emily --approve-after 3 --with-runaway` | 8/9 **PASS** (s1 s2 s3 s4 s5(+tamper) s6 s7 runaway); **s8 FAIL** caused by integration bug #3 (first budget raise routes owner instead of admin). An earlier run (after the policy had been re-serialized once) passed s8 |
| unit | `AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/demo_agents -q` | **22 passed** (catalog invariants, grading, YAML helpers on the real policy, hook parsing, payloads/no secret literals, scene wiring, in-process gateway guard + hook steps) |
| lint | `uv run --frozen ruff check demo/agents demo/scenarios tests/unit/demo_agents` | clean |

## Files created

- `demo/agents/{__init__,_common,catalog,trading_copilot,runaway,chaos_agent,ambient,research_agent}.py`
- `demo/scenarios/{__init__,run,s1_redaction,s2_injection,s3_approvals,s4_policy,s5_feed,s6_proof,s7_mcp,s8_config_gov,warmup,tail}.py`, `demo/scenarios/PROMPTS.md`
- `demo/scenarios/payloads/{pii,aws_key,setup_md,ti022,curl_sh}.json`, `demo/scenarios/payloads/render.py`
- `tests/unit/demo_agents/{__init__,conftest,test_catalog,test_scenes}.py`
- (runtime output, gitignored data dir) `data/demo/chaos.json`, `data/run/ambient.pid`

## How to run / demo

```bash
make up                                                     # stack (B20 run_stack)
uv run --frozen python demo/scenarios/warmup.py --fast      # dashboard history, 0 pending
uv run --frozen python demo/agents/trading_copilot.py pii-draft   # F1
uv run --frozen python demo/agents/trading_copilot.py subscribe   # F4 (approve as u_emily in the UI)
uv run --frozen python demo/agents/runaway.py               # F6 (approve raise, then kill switch)
uv run --frozen python demo/agents/chaos_agent.py --fast    # red-team sweep
uv run --frozen python demo/scenarios/run.py all --assert --approve-as u_emily --approve-after 3
uv run --frozen python demo/scenarios/tail.py               # CLI live feed fallback
```
All scripts: `--url` (default `$AEGIS_URL`/:8787), exit 0 ok · 1 mismatch (`--assert`) · 2 gateway down.
Mock ports follow `AEGIS_MOCK_*_PORT`; feed `AEGIS_FEED_URL`.

## deps_needed

None (httpx, rich, pyyaml, fastapi TestClient already in the venv).

## contract_deviations

- `warmup.py`: research-team usage comes from real Ollama calls only when `aegis-judge` is already warm
  (`--ollama auto`); otherwise it uses the audited `POST /api/budgets/usage` fast-forward
  (`compute_s +240`, reason "warm-up fast-forward (Ollama not warm)") so the team gauge moves.
- `research_agent.py --no-llm` uses **dry-run** `/v1/guard` for the local model hops (a non-dry local
  guard leaks BUD-02's concurrency slot, see #4).
- `payloads/aws_key.json` is a template (`__AWS_KEY__`), rendered by `payloads/render.py` — no
  secret-shaped literal is committed (GitHub push protection).
- Benign copilot chats accept `redact` because every OpenAI-wire SDK call gets `redact DLP-03` (#5).

## integration_todos

1. **F6 needs `on_soft: warn` on the chaos limit** — `config/policy.yaml` line 170 (owner B03, also
   `config/policy.golden.yaml` + `docs/seed-fixes/policy.yaml`):
   `- {scope: "agent:chaos-agent@platform", window: day, usd: 0.50, tokens: 100000, on_soft: warn, on_hard: require_approval}   # F6`.
   Without it the defaults (`on_soft: downgrade`) reroute the runaway's `mock-echo` calls to
   `aegis-judge` (local, $0 USD) at 80 %: the $0.50 wall is never reached and Ollama gets loaded
   (observed: 75 s timeouts on a loaded machine).
2. **Makefile aliases** (scaffold; `demo-scene` already exists):
   ```make
   warmup: ## dashboard history + approvals, 0 pending (demo-mocks-docs)
   	@$(PY) demo/scenarios/warmup.py $(ARGS)
   chaos: ## red-team sweep over every control family (demo-mocks-docs)
   	@$(PY) demo/agents/chaos_agent.py $(ARGS)
   demo-copilot: ## F1/F4 trading copilot: make demo-copilot S=pii-draft|subscribe
   	@$(PY) demo/agents/trading_copilot.py $(or $(S),subscribe) $(ARGS)
   demo-runaway: ## F6 runaway agent
   	@$(PY) demo/agents/runaway.py $(ARGS)
   demo-tail: ## CLI live decision feed
   	@$(PY) demo/scenarios/tail.py $(ARGS)
   ambient: ## background traffic until Ctrl-C
   	@$(PY) demo/agents/ambient.py $(ARGS)
   ```
   B20 `scripts/run_stack.py --demo` should call `demo/scenarios/warmup.py --fast`; `--ambient` →
   `demo/agents/ambient.py --rate 0.5`; `reset.py --stop-ambient` → `demo/agents/ambient.py --stop`
   (or kill the pid in `data/run/ambient.pid`).
3. **Budget raise routing bug (B03 diff / B08 raise → GOV-05)**: on the pristine policy file,
   `POST /api/budgets/raise {team:trading, day, usd, 75}` as u_piotr yields an approval whose change
   set is `session:* session usd limit removed` → rule `raise-other` → **owner**, while
   `/api/budgets/raise/preview` correctly says `raise-team-small` → admin. After the policy has been
   re-serialized once by `apply_patch` the same call routes admin. Breaks F5 ("60 → 75 → admin") and
   `run.py s8 --assert`. Look at how GOV-05 / `policy.diff` keys `budgets.limits` entries
   (`session:*` with `window: session`).
4. **BUD-02 local-concurrency leak (B08)**: a non-dry `/v1/guard` model_call to a local model holds the
   `local_concurrency: 1` slot until `/v1/guard/complete`; callers that never complete (and the 404
   "no pending guard decision" for that id) leave every later local call blocked with
   `BUD-02 local model busy` until reset. Expire guard reservations or skip concurrency on guard.
5. **OpenAI-wire SDK calls always `redact DLP-03` "metadata stripped: 1 headers"** (B05 egress
   header plan vs. B20 SDK headers): every copilot chat shows as cyan redact in the feed. Either do not
   count the user-agent replacement / inbound-only `x-aegis-*` headers as a strip, or have the SDK not
   send that header on the OpenAI wire.
6. ≈ findings for owners (not blocking): `mailer.send_email` to an external address with a generic
   body routes **admin** (send-confidential) instead of **self** (ACT-03 data_class seems to count the
   recipient email; SF-04 says recipient args are exempt) — B11. Model-proxy redact decisions carry no
   `control_id` in `X-Aegis-*` headers (pii-remote / md-exfil graded ≈) — B02. Approval titles show
   `[PERSON] wants to …` (audit scrubber masks member display names) — B15/B10.
7. `INJ-04` logs `IndexError: no such group` in `aegis/injection/canary.py:53 extract_urls` on long
   `[[LONG:n]]` responses (degraded allow) — B06.
8. DEMO-17 planner mode is B20's `mocks/mock_llm/planner.py`; `trading_copilot.py` has no `loop` scene.
