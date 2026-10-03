# 07 · budgets-ledger — Budgets, cost ledger & runaway protection

Workstream `budgets-ledger` · task prefix **BUD** · research ref `04-budgets-feeds-reporting.md` §1 (+ §4.6 dashboard ideas).
Owned paths (CONTRACTS §1.2): `src/aegis/budgets/**`, `src/aegis/controls/budget/**`, `config/pricing.yaml`, route `src/aegis/api/routes/budgets.py`, plus `config/snippets/budgets-ledger.yaml`, `tests/unit/budgets_ledger/**`, this file.
Controls owned (CONTRACTS §4.4): **BUD-01** (token & cost budgets), **BUD-02** (local compute & concurrency), **EXE-04** (loop / rate / circuit breaker / kill switch, priority 10).

---

## 1. Goal & demo value

**What the judges see**
- **Budgets page** (dashboard-governance renders our `/api/budgets`): org → team → member/agent → session tree with live bullet bars for USD, tokens and **local compute-seconds** (Ollama shadow-priced, so local spend shows in USD too). Pre-seeded with the Acme Capital demo state (team:trading at 64 % of daily USD, …) so nothing is empty at T0.
- **F6 runaway agent** (CONTRACTS §8): `chaos-agent@platform` loops `web.fetch_url` → EXE-04 ladder **tool_error → block (cooldown) → kill**; its model calls burn its $0.50/day → BUD-01 `on_hard: require_approval` → a `budget_raise` approval appears in the inbox → admin approves → limit is patched to $1.00 (policy v+1) → the agent continues. Gauges move live over SSE.
- **Soft limit downgrade**: at ≥ 80 % a request for `mock-echo` / `claude-sonnet-*` is rerouted to a cheaper/local model (`aegis-judge`), visible in the live feed as an amber "downgraded" decision with `X-Aegis-Downgraded-From`.
- **F5 config governance**: "Request raise" on the Budgets page (u_piotr: team:trading day USD 60 → 75) → `rt.policy.propose` → GOV-05 → admin approval → bars rescale live. A preview shows "requires admin/owner" before submitting.
- **Kill switch**: one click (or a judge editing `budgets.kill_switch.agents` in `policy.yaml`) stops the agent in < 1 s; Claude Code stops after exactly **one** attempt with a readable message (verified stop semantics from `staging/spikes/claude-code/FINDINGS.md`).

**Judging criteria served**
| Criterion | How |
|---|---|
| Guardrail robustness 30 % | denial-of-wallet / runaway loops (OWASP LLM06:2026 Unbounded Consumption, ASI08/ASI10); AND-semantics at every level; non-retryable stops that don't cause retry storms |
| Architecture & performance 20 % | atomic check-and-reserve in-process (< 0.2 ms), reserve → settle on provider usage, write-behind SQLite; scale path = Redis/Lua multi-key reserve (research 04 §1.5) |
| Security reporting 20 % | live gauges, `budget.threshold` / `budget.exceeded` / `killswitch.toggled` audit events, Prometheus gauges, enforcement counters (loops, downgrades, 402s) |
| Self-testing 15 % | unit suite (pricing, AND semantics, 200-way concurrency, ladder, loops), inline policy self-tests, examples ported from staging for test-suite |
| Implementability 15 % | standard semantics (402 / 429 + Retry-After / x-should-retry), one YAML for limits, pricing file hot-reload, works for remote **and** local models |

---

## 2. Design

### 2.1 Concepts (binding vocabulary for this workstream)

- **Scope chain** (AND semantics): `org:<org_id>` → `team:<team_id>` → `member:<id>` *(only when the principal is a human)* / `agent:<agent_id>` → `session:<session_id>`, plus per-interaction `model:<model>` and `tool:<tool_name>`. A request must fit **every** level; a denial names the scope that tripped.
- **Dimensions** (`BudgetDimension`, frozen): `usd` (AI cost), `tokens` (in + out), `compute_s` (local model seconds), `requests` (model calls = **steps**), `tool_calls`, `spend_usd` (real money moved by agent purchases). Staged `steps` → `requests` on a session scope; staged `local_compute_s` → `compute_s`.
- **Windows** (`BudgetWindow`): calendar `hour|day|week|month` in `budgets.timezone` (extra key, default `Europe/Warsaw`, fallback UTC), `session` (life of the session), `total`. Rate limits use sliding 60 s windows (EXE-04).
- **Limit resolution**: entries in `budgets.limits` match concrete scopes by glob. Per (concrete scope, window, dimension) the **most specific** entry wins (exact > glob with longest literal prefix > `*`; an entry with `match_agents` beats one without). AND applies across *levels*, not across duplicate entries for the same level — so raising `member:u_piotr` above `member:*` actually works.
- **Counters**: identity scopes (`org/team/member/agent`) track `hour, day, week, month, total`; session scopes track `session`; wildcard entries over identities (`member:*`, `session:*`) give **per-instance** counters; `model:<glob>` / `tool:<glob>` entries give one **aggregated** counter keyed by the entry's scope string (e.g. all Opus models together). Usage is tracked even without a limit, so a limit added live applies to usage already accrued.
- **State**: `ok` < soft (`soft_pct`, default 80) ≤ `soft` < 100 % ≤ `hard`; `killed` when the kill switch matches. `pct = (used + reserved) / limit * 100`; `limit <= 0` ⇒ `pct = 100`, `hard`.

### 2.2 Escalation ladder (one concept, several knobs)

| Step | Trigger | Mechanics | Config knob | Owner control |
|---|---|---|---|---|
| warn | crossing 50 % (and any level in `params.warn_pct`) | `budget.threshold` SSE + audit; `X-Aegis-Budget-Remaining` header; Decision `log` | `BUD-01.params.warn_pct` | BUD-01 |
| throttle | rpm / tool-calls-per-min exceeded; burn-rate spike (EWMA $/min > 5× baseline) | **429 `rate_limited` + `Retry-After: n`** (retrying is correct here) | `budgets.rate`, `EXE-04.params.burn_rate` | EXE-04 |
| downgrade | soft threshold with `on_soft: downgrade` (or `on_hard: downgrade` when the tripped dimension is `usd`) | `Mutation(target="route", path="model", value=<to>)` from `models.downgrade`; action `redact` (= modify per translation table); never to a less trusted destination; never push > `local_downgrade_max_input_tokens` to a local model | `budgets.defaults.on_soft`, `BudgetLimit.on_soft/on_hard`, `models.downgrade` | BUD-01 |
| require approval | `on_soft`/`on_hard: require_approval` | `Decision(require_approval, approval=ApprovalDraft(kind="budget_raise", payload={"patch": …}))` → pipeline → `rt.approvals.request` → rule `budget-override` → executor applies patch | `BudgetLimit.on_hard`, `BUD-01.params.raise_factor` | BUD-01 |
| block | hard limit (`on_hard: block`), session step cap | **402 `budget_exceeded`**, non-retryable, `x-should-retry: false`, body tells the model to stop and summarise | `budgets.defaults.on_hard`, `budgets.loops.max_steps_per_session` | BUD-01 / EXE-04 |
| kill switch | manual (API/file) or loop ladder step 3 | 403 `killed` (Claude Code: 429 + Retry-After 3600 + x-should-retry:false, see §2.3) | `budgets.kill_switch`, `budgets.loops.ladder` | EXE-04 |

Loop ladder (`budgets.loops.ladder`, default `[tool_error, block, kill]`, per session; a "trip" = a detector firing on an executed-call history):
1. **tool_error** — block *this* call with a reason the agent can read: `Aegis loop detected (LOOP-001 exact_repeat): web.fetch_url repeated 3x in the last 20 calls. Change approach or finish.` (MCP → `isError` tool result; hook → deny reason; model path → synthetic 200 reply via `block_response: message`).
2. **block** — block the session's **tool calls** (tool.input / mcp.call / egress.request) for `cooldown_s` (default 30): 429 + `Retry-After` + `x-should-retry: false`. Model calls keep flowing so F6 can reach the budget wall.
3. **kill** — session killed: in-memory immediately, then persisted via `rt.policy.apply_patch` (appends to `budgets.kill_switch.sessions`, `source="budgets-ledger"`), so release is a governed `killswitch.off` change (admin).

Detectors (EXE-04): **LOOP-001 exact repeat** (same fingerprint ≥ `loops.repeat` in last `loops.window`), **LOOP-002 short cycle** (period p ∈ 2..4 repeated `cycle_k` times), **LOOP-004 error streak** (`loops.error_streak` consecutive failed/blocked hops, excluding EXE-04's own blocks), **LOOP-005-lite model repeat** (same prompt hash to the same model ≥ `params.model_repeat`, default 5), **LOOP-006 burn-rate spike** (should). LOOP-003 (no progress) and LOOP-007 (context growth) are *could* (need result content). Fingerprint = `hmac_hex(canonical_json({tool|model, args minus volatile keys}), purpose="loop")` — in memory only. Blocked hops are **not** added to history (so our own 429s + client retries can never escalate a loop); hook + MCP-proxy double sightings of the same call within `dedupe_s` count once.

### 2.3 Stop semantics (Claude Code-friendly; from `staging/spikes/claude-code/FINDINGS.md`)

| Situation | Decision fields we set | Headers (via `Decision.meta["response_headers"]`, see gap G1) | Claude Code behaviour (verified) |
|---|---|---|---|
| Budget exhausted | `http_status=402`, `error_type="budget_exceeded"` | `x-should-retry: false` | 1 attempt, exit 1, `API Error: 402 <msg>` |
| Session step cap (`max_steps_per_session`) | 402 `budget_exceeded` | `x-should-retry: false` | 1 attempt |
| Rate limit / burn-rate throttle | 429 `rate_limited`, `retry_after_s=n` | (core emits `Retry-After`) | retries with backoff — intended |
| Loop ladder step 2 (tool block) | 429 `rate_limited`, `retry_after_s=cooldown` | `x-should-retry: false` | hooks: deny reason; model path: 1 attempt |
| Kill switch / loop kill, generic client | 403 `killed` | `x-should-retry: false` | — |
| Kill switch / loop kill, **Claude Code client** | 429, `retry_after_s=3600`, `error_type="killed"` | `x-should-retry: false` | 1 attempt, clean exit (403 renders as "Failed to authenticate" — avoid) |
| Policy-style loop message (ladder step 1) | `block`, no `http_status` | — | model path: synthetic 200 assistant message (`defaults.block_response`) |

Claude Code client detection: `identity.agent_id` matches `EXE-04.params.claude_code_agents` (default `["claude-code@*"]`) **or** inbound header `x-claude-code-session-id` **or** `user-agent` starts with `claude-cli`. Messages are written for the model to read: `Aegis: agent:chaos-agent@platform day usd budget exhausted (0.50/0.50). Stop and summarise progress.`

### 2.4 Data flow

```
model.request / tool.input / mcp.call / egress.request (direction out)
   │  pipeline enrich (ACT-* set action_type/amount_usd) ─────────────────────────────┐
   ▼                                                                                   │
EXE-04 (prio 10, stateful)  kill switch (policy ∪ runtime) → session kill → tool cooldown
   │                        → rate (sliding 60 s / principal) → burn-rate → step cap
   │                        → loop detectors on fingerprint → ladder; record "pending" fp
   ▼
BUD-02 (prio 85, local only) concurrency slot (≤ queue_wait_s) · num_predict/num_ctx clamp · model size (model.admin)
   ▼
BUD-01 (prio 90)  estimate Usage (tokens.py + pricing.py) → clamp max_tokens (Mutation)
                  → rt.ledger.reserve(ctx, est, chain+model/tool scopes)  [atomic, AND]
                  → Reservation(meta.soft, meta.remaining)  → warn / downgrade (re-reserve at target)
                  → BudgetDenial → block 402 | require_approval(budget_raise draft) | downgrade
                  ctx.state["bud.reservation"] = res
   ▼  … upstream executes …
pipeline.complete → on_complete
   BUD-01: price actual usage (fills outcome.usage.cost_usd if 0; local compute_s fallback = measured wall time)
           → rt.ledger.settle(res, actual) | commit(usage) when allowed without reservation (pre-approved) | release(res) when blocked
   EXE-04: confirm/remove pending fingerprint, error-streak update
   BUD-02: release slot
ledger.settle → counters (memory) → thresholds 50/80/100 (SSE budget.threshold + audit)
             → budget.updated (coalesced ≤ 2/s) → gauges → write-behind flush (SQLite, 1 s) → samples (≤ 1/5 s)
rt.policy.on_change → limits recompiled → budget.updated for all · kill_switch diff → SSE killswitch + audit killswitch.toggled
```

Special contexts:
- `ctx.dry_run` ⇒ BUD-01 uses `ledger.check()` (no reservation), EXE-04 checks without recording, BUD-02 takes no slot.
- `ctx.source == "selftest"` ⇒ BUD-01 checks the estimate against **zero usage**; EXE-04 skips kill switch / rate / loop state; BUD-02 skips slots. Otherwise a global kill switch or an exhausted org budget would make every must-allow self-test fail, and the self-test gate would reject every policy edit, including the budget raise that fixes it (see gap G9).
- Leaked reservations (no `complete` call) expire after `reservation_ttl_s` (default 600) and are settled **at estimate** (conservative).

### 2.5 Files and key symbols (all inside owned paths)

`src/aegis/budgets/`
| File | Contents |
|---|---|
| `__init__.py` | docstring only (no side effects) |
| `tokens.py` | **PUBLIC** `estimate_tokens(text: str, model: str | None = None) -> int` (chars/4; `claude*` chars/3.5; ceil, min 1 for non-empty). Helpers `estimate_request_usage(interaction, params, pricing) -> Usage` |
| `pricing.py` | `ModelPrice{in_, out, cache_read, cache_write, compute_s}`, `PricingTable{version, currency, unit, models: list[(glob, ModelPrice)], tools: list[(glob, float)]}`; `load_pricing(path) -> PricingTable`; `PricingTable.price(model, usage) -> float` = `(uncached_in·p_in + cache_read·p_cr + cache_write·p_cw + out·p_out)/1e6 + compute_s·p_cs` with `uncached_in = max(0, input − cache_read − cache_write)`, defaults `cache_read = 0.1·in`, `cache_write = 1.25·in`; first glob match wins; `tool_price(tool_name)`; provider prefixes (`anthropic/`, `ollama/`) stripped before matching |
| `windows.py` | patchable clock `now()`, `monotonic()`; `zone(snapshot)`; `window_start(window, at, tz) -> str` (UTC ISO of the local period start; `"session"`, `"total"`); `resets_at(window, at, tz) -> datetime | None` |
| `limits.py` | `scope_type(scope)`, `LimitEntry` (normalized `BudgetLimit` + `match_agents`, specificity), `LimitIndex.compile(snapshot)` cached in `snapshot.compiled["budgets-ledger:limits"]`, `LimitIndex.resolve(concrete_scope, identity) -> dict[(window, dim), LimitEntry]`, `counter_key(entry, concrete_scope)` |
| `ledger.py` | `class Ledger` implements `BudgetLedger` (+ extras below); `create(rt) -> Ledger` (cheap); `start()`/`stop()` |
| `store.py` | DDL for `budget_usage`, `budget_samples` (CONTRACTS §6.1 verbatim); `load_current(conn, keys)`, `flush(conn, rows)` (upsert), `insert_samples`, `query_samples(scope, dim, window, since)`, `wipe(scope=None)` — all called via `asyncio.to_thread` |
| `events.py` | `ThresholdTracker` (levels 50/80/100 + `warn_pct`, once per window instance), `UpdateCoalescer` (≤ 2 publishes/s; immediate in test mode), `audit_event(...)`, `gauges(...)` |
| `ladder.py` | `BudgetAction` decision logic (soft/hard → warn/downgrade/require_approval/block), `downgrade_target(snapshot, model, current_dest, wire)`, `build_raise_patch(snapshot, entry, concrete_scope, dim, new_limit) -> list[PatchOp]`, `approval_draft(...)`, `format_message(...)` |
| `stop.py` | `is_claude_code(ctx, params)`, `hard_stop(kind, ctx, params) -> StopFields(http_status, error_type, retry_after_s, headers)` (table §2.3) |
| `loops.py` | `fingerprint(interaction, volatile_keys)`, `LoopState` (deque history, pending, trips, blocked_until, error_streak), `LoopRegistry` (LRU ≤ 2000 sessions, `reset()`), detectors `exact_repeat`, `short_cycle`, `model_repeat`, `error_streak`; `BurnRate` (EWMA 1-min fast / 15-min baseline per principal) |
| `ratelimit.py` | `SlidingCounter` per (principal, kind) → `(allowed, retry_after_s)`; `LocalSlots` (BUD-02 concurrency, lease expiry) |
| `killswitch.py` | `match(ks: KillSwitch, identity, session_id) -> str | None` (returns matched scope, e.g. `agent:chaos-agent@platform`); `RuntimeKills` (sessions killed by the ladder, TTL until the policy swap shows them); `toggle_patch(snapshot, scope, active) -> list[PatchOp] | None` (always `set` the whole list; `global` → `set budgets.kill_switch.global`); `diff(old, new) -> list[(scope, active)]` |
| `demo_seed.py` | read `demo_state.budget_usage` from `settings.org_seed` (pyyaml, read-only) → counters (`usd_today`→day/usd, `usd_mtd`→month/usd, `tokens_today`→day/tokens, `local_compute_s_today`→day/compute_s; `team/x`→`team:x`, `agent/x`→`agent:x`, `org`→`org:<org.id>`); synthetic history samples (deterministic business-hours ramp, 15 min steps) — only when `budget_usage` is empty and `settings.demo_mode` |
| `enforcement.py` | in-memory 24 h event ring (≤ 5000): loop trips by detector, downgrades, hard blocks, approvals requested, throttles, step caps, kills, cost avoided |
| `schemas.py` | params models with defaults: `Bud01Params`, `Bud02Params`, `Exe04Params` (unknown keys → warning, never crash); route bodies `RaiseRequest{scope, window, dimension, new_limit, reason?}`, `ResetRequest{scope?, reseed?}`, `KillSwitchRequest{scope, active, reason?}`, `UsageImportRequest{scope, window?, dimension, amount, reason}` |

`Ledger` public extras (used only by our controls/routes; everything degrades if `rt.ledger` is the Null fallback):
`check(ctx, estimate, scopes) -> Reservation | BudgetDenial` (no commit) · `commit(ctx, usage, scopes) -> list[BudgetStatus]` (post usage without reservation) · `pricing: PricingTable` · `tree() -> BudgetsResponse dict` · `history(scope, dimension, range) -> dict` · `session_usage(session_id) -> dict[dim, float]` · `burn` (`BurnRate`) · `loops` (`LoopRegistry`) · `kills` (`RuntimeKills`) · `enforcement` · `import_usage(...)`.

`src/aegis/controls/budget/`
| File | Control |
|---|---|
| `__init__.py` | empty |
| `bud01_budgets.py` | `BudgetsControl` — `id="BUD-01"`, family `BUD`, kind `deterministic`, priority 90, `applies_to = AppliesTo(surfaces={"model.request","tool.input","mcp.call","egress.request"}, directions={"out"})`, owasp `["LLM06:2026","ASI08","ASI10"]`; `evaluate` + `on_complete`; `CONTROLS = [BudgetsControl()]` |
| `bud02_local.py` | `LocalComputeControl` — `BUD-02`, deterministic, priority 85, surfaces `{"model.request","model.admin"}`, destinations `{"local"}`, owasp `["LLM06:2026","ASI08"]` |
| `exe04_loops.py` | `LoopBreakerControl` — `EXE-04`, family `EXE`, kind `stateful`, **priority 10**, surfaces `{"prompt.user","model.request","model.admin","tool.input","mcp.init","mcp.call","egress.request","a2a.message"}`, directions `{"out"}`, owasp `["ASI08","ASI10","LLM06:2026"]` |

`src/aegis/api/routes/budgets.py` — `router` (absolute paths), `ORDER = 100`; endpoints in §4.2.
`config/pricing.yaml` — CONTRACTS §4.6 verbatim + comments + `tools: {"web.fetch": 0.002, "web.fetch_url": 0.002}`.
`config/snippets/budgets-ledger.yaml` — §4.4.

### 2.6 BUD-01 evaluate (precise)

1. Skip when `interaction.direction != "out"`. Read params (`Bud01Params`), snapshot `ctx.policy or rt.policy.snapshot()`.
2. **Estimate.** Model call: `in = interaction.est_input_tokens or estimate_tokens(interaction.text(), model)`; `out = min(max_output_tokens or params.default_output_tokens (1024), params.reserve_max_output_tokens (8192))`; local destination → `compute_s = in/params.local_prompt_tokens_per_s + out/params.local_tokens_per_s`; `requests=1`. Tool/MCP/egress: `tool_calls=1`, `cost_usd = tool_price(tool_name)`, `spend_usd = amount_usd if action_type startswith "spend." else 0`, `requests=0`. `cost_usd = pricing.price(model, est)`.
3. **Clamp** (model calls): if `max_output_tokens > budgets.defaults.max_output_tokens` → `Mutation(target="body", op="set", path=<wire path>, value=clamp, reason="max_tokens clamped 32000→4096")`; wire path from `interaction.meta["wire"]` (gap G3) else inferred from `interaction.raw` keys (`max_completion_tokens` | `options.num_predict` | `max_tokens`). Skip when `raw.thinking.budget_tokens` exists and `params.clamp_skip_when_thinking` (Anthropic requires `max_tokens > budget_tokens`; Claude Code sends 32000/31999).
4. **Scopes** = `rt.ledger.scopes_for(identity, session_id)` + `model:<model>` (model calls) + `tool:<tool_name>` (tool hops).
5. **Reserve** (`check` when dry-run/selftest). Denial → hard path: `on_hard = entry.on_hard or defaults.on_hard`:
   - `block` → `Decision(block, http_status=402, error_type="budget_exceeded", reason=format_message(...), findings=[Finding(category="budget", detector=f"budget.{dim}.{window}", severity="high", meta={scope, used, limit, requested})], meta={scope, dimension, window, limit, used, requested, resets_at, response_headers: {"x-should-retry": "false"}})`.
   - `require_approval` → `ApprovalDraft(kind="budget_raise", action_type="budget.override", title=f"{principal} hit {scope} {window} {dim} limit ({used:.2f}/{limit:.2f}) — raise to {new:.2f}?", amount_usd=(new−limit if dim in {usd, spend_usd}), resource=f"budget:{scope}", labels={"scope_type", "dimension", "window"}, payload={"patch": [...], "scope", "window", "dimension", "before", "after", "increase_pct", "tripped_by"})`; `new = max(limit × raise_factor, used + reserved + requested)` rounded up to 2 decimals. Patch: key selector `budgets.limits[scope=<entry.scope>,window=<window>].<dim>` for exact entries; for glob entries (`member:*`, `session:*`) an `append` of a concrete entry for the tripped scope (most-specific rule makes it win); index selector only if the scope string contains `.`.
   - `downgrade` → only if the tripped dimension is `usd`; re-reserve at the downgrade target; else block.
6. **Soft** (from `Reservation.meta["soft"]`, the most severe `on_soft` among soft entries): `warn` → Decision `log`; `downgrade` → release + re-reserve at target, `Mutation(target="route", op="set", path="model", value=target)`, action `redact`, reason `downgraded mock-echo → aegis-judge (team:trading 84% of day usd)`; target must be allowed by `models.allowed/denied`, must not be a less trusted destination (resolve via `models.routes` → `providers[p].destination`), must change the model, and local targets need `est_input_tokens ≤ params.local_downgrade_max_input_tokens` (6000) — else fall back to `warn`. `require_approval` → as hard path.
7. Always attach `meta.response_headers["X-Aegis-Budget-Remaining"] = "usd=0.42;scope=team:research"` (tightest USD headroom among day windows; tokens if no USD limit) and `meta.pricing_version`. Return `allow` + clamp mutation when nothing else applies.
8. `ctx.state["bud.reservation"] = res`, `ctx.state["bud.t0"] = monotonic()`.

**on_complete:** price actual (`outcome.usage`; local + `compute_s == 0` → `(outcome.upstream_ms or elapsed)/1000`), write `outcome.usage.cost_usd` in place if 0; executed (`status_code < 400`, verdict action ∈ allow/log/redact) → `settle(res, actual)` or `commit(...)` if no reservation (pre-approved path); blocked/failed → `release(res)` (spend not counted; tokens counted if the upstream returned usage). Record enforcement events (downgrade, block, cost avoided).

### 2.7 EXE-04 evaluate (precise)

Order (first hit returns): selftest → `None` · kill switch (`policy.budgets.kill_switch` ∪ `RuntimeKills`; globs over team/member/agent/session; `global`) → hard stop `killed` · session killed by ladder → `killed` · tool cooldown (tool surfaces) → 429 + `x-should-retry:false` · rate (`requests_per_min` on model.request, `tool_calls_per_min` on tool surfaces, per principal) → 429 + `Retry-After` · burn-rate spike (should) → 429 `Retry-After: throttle_s` · `max_steps_per_session` (session `requests` counter) → 402 · loop detectors on the current fingerprint (+ executed history) → ladder step `ladder[min(trips, len−1)]` · record pending fingerprint (not in dry-run). Exempt tools (`params.repeat_exempt_tools`, default `[Read, Glob, Grep, LS, TodoWrite]`) and per-agent overrides (`params.agent_overrides: {"claude-code@*": {repeat: 6}}`) protect normal Claude Code work (`npm test` re-runs). Findings: `Finding(category="loop", detector="loop.exact_repeat", meta={count, window, trip, step})`; metrics `aegis_loop_detections_total{detector}`.
**on_complete:** executed → confirm fingerprint into history, reset error streak; blocked/failed (not by EXE-04 itself) → drop pending fp, `error_streak += 1`; tool error (`outcome.error`) → executed + `error_streak += 1`.

### 2.8 BUD-02 (should)
Local model requests: acquire a `LocalSlots` slot (`params.max_concurrency` else `budgets.defaults.local_concurrency`); wait ≤ `queue_wait_s` (10, below `timeout_ms` 15000) else 429 `rate_limited` `Retry-After: 2`; slot lease expires after `slot_lease_s` (180) as a leak guard; released in `on_complete`. Ollama native bodies: clamp `options.num_predict` (set when missing/−1, cap 1024) and `options.num_ctx` (cap 8192) via mutations. `model.admin` pull/create: estimate size from the tag (`70b` → 70 × `gb_per_billion_params` 0.65 ≈ 45 GB) > `max_model_gb` (3) → block "model too big for this machine"; unknown size → `unknown_size_action` (log).

### 2.9 Config keys read

`budgets.defaults.{soft_pct,on_soft,on_hard,local_concurrency,max_output_tokens}`, `budgets.limits[]` (+ extra `match_agents`), `budgets.loops.{repeat,window,cycle_k,error_streak,max_steps_per_session,ladder}`, `budgets.rate.{requests_per_min,tool_calls_per_min}`, `budgets.kill_switch.*`, extra `budgets.timezone`; `models.{allowed,denied,routes,downgrade}`, `providers[*].{wire,destination}`; control params of BUD-01/BUD-02/EXE-04; `config/pricing.yaml` (`AEGIS_PRICING`); settings `pricing`, `org_seed`, `data_dir`, `test_mode`, `demo_mode`.

### 2.10 Events, audit, metrics emitted

- SSE: `budget.updated {statuses}` (coalesced ≤ 2/s; full set after each policy swap so F5 gauges rescale), `budget.threshold {scope, dimension, window, pct, state}` (50/80/100 + `warn_pct`, once per window instance), `killswitch {scope, active, actor}` (policy swap diff and ladder kills), `system` (pricing reload ok/failed, kill persistence failed).
- Audit (`rt.audit.record`): `budget.threshold`, `budget.exceeded` (every hard denial, data = denial), `killswitch.toggled` (data `{scope, active, source, policy_version}`).
- Metrics: `aegis_budget_utilization_ratio{scope_type,scope,dimension}` (max over windows; never session scopes), `aegis_loop_detections_total{detector}`, `aegis_killswitch_active` (0/1: any kill active), `aegis_cost_avoided_usd_total{reason=downgrade|budget_block|loop_block}` (should).

### 2.11 Lifecycle & performance
`create(rt)`: no I/O. `start()`: DDL + load current windows (`to_thread`), demo seed if empty, load pricing, compile limits, `rt.policy.on_change(self._on_policy)`; unless `AEGIS_TEST_MODE=1`: flush task (1 s), reservation sweeper (5 s), pricing watcher (`watchfiles.awatch`, debounce 200 ms, keep last good). In test mode flushes run inline after settle. `stop()`: cancel tasks, final flush. Hot path is pure dict arithmetic with no `await` between check and commit (atomic on the event loop; an `asyncio.Lock` guards anyway). Target ≤ 0.2 ms p95 for reserve + settle; pydantic objects only at the edges.

---

## 3. Reuse map (staging → owned paths)

| Staging input | Becomes | Adaptation |
|---|---|---|
| `staging/seed/org.seed.yaml` `budgets:` (org/team/agent daily+monthly usd/tokens/local_compute_s, agent `session:` caps, `member_defaults`) | `config/snippets/budgets-ledger.yaml` → `budgets.limits` (policy-engine merges; amounts live **only** in policy, no SQLite amounts, no `limit_overrides`) | `team/x`→`team:x`; `daily/monthly`→`window: day/month`; `local_compute_s`→`compute_s`; session `steps`→`requests`; per-agent session caps → `session:*` + `match_agents`; chaos-agent session USD cap **dropped** so F6 reaches the $0.50/day wall; `max_parallel`/`max_concurrent_local` → BUD-02 params; `wall_s` → could |
| `staging/seed/org.seed.yaml` `demo_state.budget_usage` | `src/aegis/budgets/demo_seed.py` (reads `config/org.seed.yaml` at runtime, read-only) | key mapping §2.5; synthetic samples for history charts |
| `staging/seed/policy.yaml` `budgets:` (ladder, error message, clamp, downgrade_map, cost_table, kill_switch) | `budgets.defaults` + BUD-01 params (`message`, `warn_pct`) + `models.downgrade` snippet; `cost_table` → `config/pricing.yaml` | **contract prices (§4.6) win** over staged prices (e.g. Sonnet $3/$15, mock $3/$15); `ollama/*` → `aegis-*`, `qwen*`, `hf.co/*`; `mock/*` → `mock-*`; `unknown_model_policy: block` → pessimistic `"*"` row |
| `staging/seed/policy.yaml` EXE-04 entry (LOOP-001…007, ladder, `tool_error_message`, `per_tool_rates`, profiles strict 2 / permissive 5) | `budgets.loops` + EXE-04 params; `loops.py` detectors | `block_session/kill_session` → `block/kill`; `tool.call`→`tool.input`/`mcp.call`; profile overrides → `config/profiles/*` request to policy-engine (`EXE-04.params` only) |
| `staging/seed/policy.yaml` BUD-01 / BUD-02 / EXE-04 `examples` (runaway-search-loop, three-distinct-calls, session-usd-exhausted, clamp-max-tokens, small-request, model-too-big, session-compute-exhausted, short-local-inference) | unit tests in `tests/unit/budgets_ledger/` + inline `tests:` where state-independent; listed for test-suite `tests/cases/` | `mock/echo-llm`→`mock-echo`; `llm.request`→`model.request`; `admin.api`→`model.admin`; `expect: modify`→`allow`+mutation assert |
| `staging/seed/SCENARIOS.md` #7 (budget raises) and #10 (runaway chaos agent) | acceptance checks BUD-V10 | `config_change.budget_increase` → `propose` + ChangeKind `budget.raise`; `kill_switch_engage/release` → `killswitch.on/off` |
| `staging/spikes/claude-code/FINDINGS.md` + `proxy.py` `BUDGET_MODES` | `src/aegis/budgets/stop.py` + §2.3 table | `429_noretry` headers (`retry-after: 3600`, `x-should-retry: false`) for Claude Code hard stops; 402 for budgets; avoid 403 for Claude Code |
| research 04 §1.3–1.7 | `pricing.py` (normalisation, cost formula), `ledger.py` (reserve/settle, AND, overshoot), `loops.py` (LOOP-00x), `ladder.py` (error body text) | Redis/Lua kept as documented scale path only |
| `staging/design/prototype/assets/view-budgets.js` ("Runaway & enforcement · 24h" panel: ladder chips, loop detections, downgrades, hard blocks, step cap, kill switch; forecast) | `/api/budgets/enforcement` shape + `forecast` in history | page-local TS types for dashboard-governance |

---

## 4. Interfaces

### 4.1 Provided (exactly as CONTRACTS)

```python
# aegis.budgets.ledger:create(rt) -> BudgetLedger      (CONTRACTS §3.2 / §3.3)
class BudgetLedger(Protocol):
    def scopes_for(self, identity: Identity, session_id: str) -> list[str]: ...
    async def reserve(self, ctx: RequestContext, estimate: Usage, scopes: list[str] | None = None
                      ) -> Reservation | BudgetDenial: ...
    async def settle(self, reservation: Reservation, actual: Usage) -> list[BudgetStatus]: ...
    async def release(self, reservation: Reservation) -> None: ...
    async def status(self, scope: str | None = None) -> list[BudgetStatus]: ...
    async def reset(self, scope: str | None = None) -> None: ...
    def price(self, model: str | None, usage: Usage) -> float: ...

# aegis.budgets.tokens (public import surface, CONTRACTS §3.3)
def estimate_tokens(text: str, model: str | None = None) -> int: ...   # chars/4, Claude chars/3.5

# aegis.controls.budget.*  ->  CONTROLS = [BudgetsControl()], [LocalComputeControl()], [LoopBreakerControl()]
```
`scopes_for` example: `Identity(org_id="acme-capital", team_id="trading", agent_id="trading-copilot@trading", member_id="u_piotr")`, session `ses_1` → `["org:acme-capital", "team:trading", "agent:trading-copilot@trading", "session:ses_1"]`; human `u_piotr` → `[..., "member:u_piotr", "session:ses_1"]`.

### 4.2 HTTP (route file `budgets.py`; shapes = §5.5 TS types)

| Method & path | Role | Request → Response | Notes |
|---|---|---|---|
| `GET /api/budgets` | member | → `BudgetsResponse` | tree: org → teams → (members, agents) → recent sessions (≤ 20, active in last 1 h) → `model:`/`tool:` scopes under org. `name` from `rt.org`; `parent` scope string; `state` = killed / worst limit; `kill_switch` = policy ∪ runtime sessions; `pricing_version` |
| `GET /api/budgets/history` | member | `?scope=&dimension=usd&window=1h|24h|7d|30d` → `BudgetHistoryResponse` (+ additive `forecast: {at, used, limit} | null`) | samples from `budget_samples` (budget window `day` for ≤ 24h, `month` otherwise); falls back to `[start→0, now→used]`; forecast = linear month-end projection |
| `POST /api/budgets/raise` | member (propose decides) | `{scope, window, dimension, new_limit, reason}` → `ApplyResult` | builds `PatchOp`s (§2.6 step 5 rules; `append` when no entry) → `rt.policy.propose(viewer, patch=…, reason=…, source="dashboard")`; 200 for applied/pending_approval/noop/rejected (ApplyResult carries status), 400 `invalid_request` for bad input |
| `POST /api/budgets/reset` | **admin** | `{scope?: string}` → `{ok: true}` | zero counters (memory + rows), clear thresholds; no scope ⇒ also clear loop/runtime-kill state and re-seed demo state when demo mode (additive optional `reseed: bool`) |
| `POST /api/killswitch` | member (propose decides) | `{scope: "global"|"team:x"|"member:x"|"agent:x"|"session:x", active, reason}` → `ApplyResult` | `killswitch.toggle_patch` → `rt.policy.propose`; `noop` if already in that state; on `applied` the runtime set updates immediately (no wait for the watcher) |
| *extra, same prefix (page-local TS types):* | | | |
| `POST /api/budgets/raise/preview` | member | same body → `{change: PolicyChange, route: ApprovalRoute, viewer_can_apply: bool}` | uses `rt.approvals.route(kind="config_change", action_type="budget.raise", requester=viewer, changes=[…])` → "requires owner" before submitting |
| `GET /api/budgets/enforcement` | member | `?window=24h` → `{window, loop_detections, by_detector: {…}, downgrades, hard_blocks, throttles, step_caps, approvals_requested, kills, cost_avoided_usd, recent: [{ts, kind, scope, detector?, control_id, reason}]}` | feeds the "Runaway & enforcement" panel |
| `GET /api/budgets/pricing` | member | → `{version, currency, unit, models: [{match, in, out, cache_read, cache_write, compute_s}], tools: [{match, usd}]}` | approval cards' "budget impact" |
| `POST /api/budgets/usage` | **admin** | `{scope, window?, dimension, amount, reason}` → `{ok, statuses}` | manual usage import (vendor invoice); also the demo "fast-forward" lever; audited `budget.threshold` if a level is crossed |

Errors use `aegis.core.errors.api_error` (§5.3 envelope). Viewer via `aegis.core.deps.viewer`, admin gates via `require_role("admin")`.

Example `GET /api/budgets` (trimmed):
```json
{"generated_at":"2026-10-03T19:12:00Z","currency":"USD","pricing_version":"2026-10-03.1",
 "scopes":[
  {"scope":"org:acme-capital","scope_type":"org","name":"Acme Capital","parent":null,"state":"ok",
   "limits":[{"scope":"org:acme-capital","scope_type":"org","dimension":"usd","window":"day","limit":150,"used":62.3,
              "reserved":0.06,"pct":41.57,"state":"ok","resets_at":"2026-10-03T22:00:00Z","label":null}]},
  {"scope":"team:trading","scope_type":"team","name":"Trading","parent":"org:acme-capital","state":"ok","limits":[…]},
  {"scope":"agent:chaos-agent@platform","scope_type":"agent","name":"Chaos Agent (red team)","parent":"team:platform",
   "state":"hard","limits":[{"dimension":"usd","window":"day","limit":0.5,"used":0.51,"pct":102.0,"state":"hard", …}]}],
 "kill_switch":{"global":false,"teams":[],"members":[],"agents":[],"sessions":[]}}
```

### 4.3 Storage (CONTRACTS §6.1, verbatim; reservations in memory only)
```sql
CREATE TABLE IF NOT EXISTS budget_usage (scope TEXT NOT NULL, window TEXT NOT NULL, window_start TEXT NOT NULL, dimension TEXT NOT NULL,
  used REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, PRIMARY KEY (scope, window, window_start, dimension));
CREATE TABLE IF NOT EXISTS budget_samples (ts TEXT NOT NULL, scope TEXT NOT NULL, dimension TEXT NOT NULL, window TEXT NOT NULL,
  used REAL NOT NULL, limit_value REAL);
```
`window_start` = UTC ISO of the local period start, or `"session"` / `"total"`. Samples ≤ 1 per 5 s per (scope, dimension, window), dimensions `usd|tokens|compute_s`, windows `day|month|session`.

### 4.4 Snippet `config/snippets/budgets-ledger.yaml` (implementer writes exactly this, with comments)

```yaml
models:
  downgrade:                                  # consumed by BUD-01; first match wins
    - {from: "claude-opus-*",   to: "claude-sonnet-4-5"}
    - {from: "claude-sonnet-*", to: "claude-haiku-4-5"}
    - {from: "*",               to: "aegis-judge"}     # incl. mock-*, gpt-*; guarded by local_downgrade_max_input_tokens
budgets:
  timezone: Europe/Warsaw                     # extra key: calendar windows (daily reset 00:00 local)
  defaults: {soft_pct: 80, on_soft: downgrade, on_hard: block, local_concurrency: 1, max_output_tokens: 4096}
  limits:
    - {scope: "org:acme-capital", window: day,   usd: 150,  tokens: 12000000,  compute_s: 14400}
    - {scope: "org:acme-capital", window: month, usd: 3000, tokens: 240000000, compute_s: 300000, spend_usd: 10000}
    - {scope: "team:trading",  window: day,   usd: 60,   tokens: 4000000, compute_s: 1800}
    - {scope: "team:trading",  window: month, usd: 1200, tokens: 80000000, spend_usd: 2000}
    - {scope: "team:research", window: day,   usd: 15,   tokens: 1500000, compute_s: 7200}
    - {scope: "team:research", window: month, usd: 300}
    - {scope: "team:platform", window: day,   usd: 50,   tokens: 6000000, compute_s: 3600}
    - {scope: "team:platform", window: month, usd: 1000}
    - {scope: "member:*",      window: day,   usd: 5, tokens: 500000}          # each human (playground, CLI)
    - {scope: "agent:claude-code@platform",    window: day, usd: 30, tokens: 5000000}
    - {scope: "agent:trading-copilot@trading", window: day, usd: 20, tokens: 1500000}
    - {scope: "agent:research-agent@research", window: day, usd: 2,  compute_s: 5400}
    - {scope: "agent:chaos-agent@platform",    window: day, usd: 0.50, tokens: 100000, compute_s: 120,
       on_hard: require_approval, label: "red-team agent: tiny on purpose"}
    - {scope: "session:*", window: session, usd: 5.0, tokens: 3000000, requests: 300, tool_calls: 400}
    - {scope: "session:*", match_agents: ["trading-copilot@trading"], window: session, usd: 1.0, tokens: 200000, requests: 30, tool_calls: 20}
    - {scope: "session:*", match_agents: ["research-agent@research"], window: session, compute_s: 600, requests: 40, tool_calls: 30}
    - {scope: "model:claude-opus-*", window: day, usd: 20, label: "Opus org-wide daily cap"}
    - {scope: "agent:selftest-zero", window: day, usd: 0, label: "self-test fixture: proves hard limits block (BUD-01)"}
  loops: {repeat: 3, window: 20, cycle_k: 3, error_streak: 5, max_steps_per_session: 200, ladder: [tool_error, block, kill]}
  rate: {requests_per_min: 120, tool_calls_per_min: 60}
  kill_switch: {global: false, teams: [], members: [], agents: [], sessions: []}
controls:
  - id: BUD-01
    name: Token & cost budgets (remote + local, spend)
    action: block
    severity: medium
    fail_mode: closed            # ledger unavailable -> deny (cost safety)
    timeout_ms: 50
    owasp: [LLM06:2026, ASI08, ASI10]
    params:
      warn_pct: [50]
      reserve_max_output_tokens: 8192
      default_output_tokens: 1024
      clamp_skip_when_thinking: true
      raise_factor: 2.0
      local_downgrade_max_input_tokens: 6000
      local_tokens_per_s: 25
      local_prompt_tokens_per_s: 400
      reservation_ttl_s: 600
      message: "Aegis: {scope} {window} {dimension} budget exhausted ({used}/{limit}). Stop and summarise progress."
    tests:
      - {name: zero-budget-agent-blocked, agent: selftest-zero, text: "Summarise today's bond market.", expect: block, control: BUD-01}
      - {name: small-request-allowed, text: "One-line summary of PKO today.", expect: allow}
  - id: BUD-02
    name: Local compute & concurrency
    action: block
    severity: medium
    fail_mode: closed
    timeout_ms: 15000            # covers queue_wait_s
    owasp: [LLM06:2026, ASI08]
    params: {max_concurrency: 1, queue_wait_s: 10, slot_lease_s: 180, max_model_gb: 3, gb_per_billion_params: 0.65,
             unknown_size_action: log, num_predict_max: 1024, num_ctx_max: 8192}
    tests:
      - {name: short-local-inference, destination: local, text: "Summarise in one sentence: banks rallied.", expect: allow}
  - id: EXE-04
    name: Loop / rate / circuit breaker / kill switch
    action: block
    severity: high
    fail_mode: closed
    timeout_ms: 50
    owasp: [ASI08, ASI10, LLM06:2026]
    params:
      cooldown_s: 30
      model_repeat: 5
      repeat_exempt_tools: [Read, Glob, Grep, LS, TodoWrite]
      agent_overrides: {"claude-code@*": {repeat: 6}}
      volatile_keys: [timestamp, ts, nonce, request_id, cursor, page_token]
      dedupe_s: 5
      burn_rate: {factor: 5.0, floor_usd_per_min: 0.05, throttle_s: 60}
      claude_code_stop: true
      claude_code_agents: ["claude-code@*"]
      tool_error_message: "Aegis loop detected ({detector}): {tool} repeated {count}x in the last {window} calls. Change approach or finish."
    tests:
      - {name: distinct-call-allowed, kind: tool_call, surface: tool.input, destination: third_party,
         tool_name: web.fetch_url, tool_args: {url: "https://example.com/a"}, expect: allow}
# Proposed for approvals (approvals-engine / policy-engine own these sections):
# approvals.config_rules: insert BEFORE `tighten`:
#   - {id: killswitch-engage, when: {action: ["killswitch.on"]}, approver: self}   # brakes must be instant
# approvals.rules keeps: {id: budget-override, when: {kind: [budget_raise]}, approver: admin}
# config/profiles/strict.yaml: EXE-04 params {model_repeat: 3}; budgets soft 70 is a policy edit, not a profile
```

### 4.5 Consumed

| From | What | Degrade if missing |
|---|---|---|
| scaffold (frozen) | `aegis.core.types` (Usage, BudgetStatus, Reservation, BudgetDenial, Decision, Finding, Mutation, ApprovalDraft, Identity, …), `aegis.core.protocols.BaseControl`, `aegis.core.policy_schema` (PolicySnapshot, BudgetLimit, KillSwitch, PatchOp, PolicyChange, ApplyResult, ControlConfig) | — (hard requirement) |
| core-gateway | `aegis.core.runtime.get_runtime`, `aegis.core.deps.{get_rt, viewer, require_role}`, `aegis.core.errors.api_error`, `aegis.core.crypto.hmac_hex`, `aegis.core.paths.glob_match`, `aegis.settings.get_settings`; pipeline semantics §3.5 (`ctx.state`, `on_complete`, `dry_run`, mutations incl. `route`); `Decision.http_status/retry_after_s`; `rt.db()` | local fallbacks: `fnmatch.fnmatchcase`, keyed `blake2b` with a per-process key, plain `JSONResponse` envelope |
| policy-engine | `rt.policy.snapshot()`, `on_change(cb)`, `propose(actor, patch=…)`, `apply_patch(patch, actor=None, source=…)`; budget_raise executor applying `payload["patch"]`; self-test runner using `source="selftest"` | Null store: limits from the parsed doc, raise/kill endpoints return its `rejected` ApplyResult |
| org-rbac | `rt.org.org()`, `list_teams()`, `list_members()`, `list_agents()` (names/parents in the tree); `config/org.seed.yaml` `demo_state` (read-only file) | tree built from counters + limits with ids as names; no demo seed |
| approvals-engine | `rt.approvals.route(...)` (raise preview); `request()` via the pipeline for BUD-01 drafts | preview returns `route: null` |
| audit-metrics | `rt.audit.record`, `rt.metrics.inc/set_gauge` | no-op |
| core bus | `rt.bus.publish` | — |

### 4.6 Contract gaps (proposed addenda — need scaffold sign-off)

- **G1 Control-requested response headers.** Core-gateway merges `Decision.meta["response_headers"]: dict[str, str]` of all enforce-mode decisions into the data-plane response (allowed **and** blocked), and always emits `Retry-After: <retry_after_s>` when the primary decision sets it. Needed for `X-Aegis-Budget-Remaining` (§5.2 already lists it, but nothing says who computes it) and `x-should-retry: false`.
- **G2 Claude Code hard stops.** §5.3 maps the kill switch to 403 `killed`; FINDINGS shows Claude Code renders 403 as "Failed to authenticate". Proposal: for Claude Code clients (detection §2.3) EXE-04 sets `http_status=429`, `retry_after_s=3600`, `error_type="killed"`, header `x-should-retry: false` (one attempt, clean exit). Core-gateway must honour `Decision.http_status` over its per-`error_type` default. Budgets stay 402 (+ `x-should-retry: false`), which Claude Code already handles. Switch: `EXE-04.params.claude_code_stop`.
- **G3 Wire hint.** Core-gateway sets `Interaction.meta["wire"] ∈ {anthropic, openai, ollama}` on `model.request` so clamp mutations hit the right path. Fallback: infer from `interaction.raw`.
- **G4 Usage normalisation.** `Usage.input_tokens` = total input **including cache reads and cache writes** (Anthropic: `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`; OpenAI `prompt_tokens`). Pricing subtracts both cache counts. Local `compute_s` from Ollama native durations (`(load + prompt_eval + eval)/1e9`); BUD-01 falls back to measured wall time.
- **G5 Cost stamping.** BUD-01.`on_complete` fills `outcome.usage.cost_usd` in place when it is 0 (on_complete runs before usage metrics/audit per §3.5). Core-gateway should also call `rt.ledger.price(model_used, usage)` when `cost_usd == 0`, for hops where BUD-01 is disabled. The pricing version is stamped in BUD-01 `Decision.meta["pricing_version"]`, because `Usage` has no field for it.
- **G6 Completion of tool hops.** claude-code-integration and mcp-proxy call `rt.pipeline.complete` for every request-direction hop: PreToolUse on PostToolUse, or immediately with `Outcome(status_code=200)`. They set `Outcome.error="tool_error"` when the tool result is an error. Without this, reservations expire via TTL (settled at estimate) and error-streak only sees Aegis blocks.
- **G7 Extra policy keys.** `BudgetLimit.match_agents: list[str]` (agent-id globs; for `session:*`, `model:`, `tool:` entries) and `budgets.timezone` (IANA). policy-engine: whitelist (no warnings), preserve in ruamel round-trips, and carry `match_agents` in `diff_docs` budget changes.
- **G8 `budget_raise` payload.** `{"patch": [PatchOp dict…], "scope", "window", "dimension", "before", "after", "increase_pct", "tripped_by"}`. policy-engine's `budget_raise` executor applies `payload["patch"]` with `apply_patch(actor=None, source="approval", reason=request.title)`. budgets-ledger does **not** register executors, to avoid last-registration-wins conflicts.
- **G9 Self-test isolation.** policy-engine's self-test gate evaluates with `ctx.source="selftest"`. BUD-01/BUD-02/EXE-04 then ignore live counters, kill switches and loop state. Without this, a global kill switch or an exhausted org budget fails every must-allow test and locks the policy, which is a deadlock.
- **G10 Instant brakes.** `approvals.config_rules` gets `{id: killswitch-engage, when: {action: ["killswitch.on"]}, approver: self}` before `tighten` (SCENARIOS #10 `APR-KILL-ENGAGE = auto`). Release stays admin (`loosen-threshold`).
- **G11 Auto-kill persistence.** The EXE-04 ladder `kill` calls `rt.policy.apply_patch([...kill_switch.sessions...], actor=None, source="budgets-ledger", reason=…)`. `PolicyVersionInfo.source` must accept that string. Self-test cost per kill is acceptable (rare).
- **G12 Demo state.** budgets-ledger reads `demo_state.budget_usage` from `config/org.seed.yaml` (read-only YAML, not org-rbac's loader). org-rbac keeps the block's shape.

### 4.7 Requests to other owners (non-contract)
- **demo-mocks-docs** (`demo/agents/runaway.py`, preflight): fixed `X-Aegis-Session` per run. Vary model prompts with a step index so `model_repeat` doesn't pre-empt BUD-01. Use `mock-echo` with `max_tokens: 4096` and `[[LONG:20000]]` (≈ $0.075/call at mock pricing, so the $0.50 wall arrives in ~7 calls). Treat a 200 "approval pending apr_…" reply as "poll every 2 s and retry". Preflight calls `POST /api/budgets/reset {}` (re-seeds demo state).
- **dashboard-governance**: Budgets page consumes `/api/budgets`, `/history`, `/raise` (+ `/raise/preview`), `/enforcement`, `/pricing`, `/api/killswitch`; SSE `budget.updated`, `budget.threshold`, `killswitch`. Page-local TS types for the extra endpoints (shapes in §4.2).
- **org-rbac**: `/api/agents` `spend_today_usd` = `rt.ledger.status("agent:<id>")` row (`usd`, `day`). Optional: lower `demo_state` `agent/research-agent@research.local_compute_s_today` 4950 → ~2400 so research-agent doesn't start at 92 % (soft).
- **test-suite**: add `tests/cases/budgets.yaml` from the staged examples in §3 (must-block: zero-budget agent 402, runaway loop ladder, killed agent; must-allow: small request, three distinct calls).
- **core-gateway** (stretch): cancel in-flight upstream streams of a killed principal on the bus `killswitch` event.

---

## 5. Tasks

Ordered for graceful degradation. Estimates include writing the unit tests named in the matching verification task.

### BUD-01 · Skeleton & public surfaces first — must · demo_critical: yes · 8 min
Deps: frozen files (scaffold). Rule §7.1-4 (interfaces first).
- [ ] `src/aegis/budgets/__init__.py`, `tokens.py` with the real `estimate_tokens` (trivial), `ledger.py` with `Ledger` stub (reserve always returns a `Reservation`, `status() → []`) and `create(rt)`
- [ ] `src/aegis/controls/budget/{__init__,bud01_budgets,bud02_local,exe04_loops}.py` with ClassVars + `CONTROLS`, `evaluate` returning `None`
- [ ] `src/aegis/api/routes/budgets.py` with all §4.2 contract routes returning valid empty shapes (`BudgetsResponse` with `scopes: []`)
- [ ] `schemas.py` params models with defaults (unknown params → `log.warning`)

### BUD-02 · Pricing, tokens, windows — must · demo_critical: yes · 10 min
Deps: BUD-01.
- [ ] `config/pricing.yaml` (CONTRACTS §4.6 + comments + `web.fetch_url` tool price)
- [ ] `pricing.py`: loader, first-match globs, prefix stripping, cache defaults, `price()`, `tool_price()`, version
- [ ] `windows.py`: clock, `zone()` (Europe/Warsaw → fallback UTC), `window_start`, `resets_at` (hour/day/week Monday/month/session/total)

### BUD-03 · Limit index & scope chain — must · demo_critical: yes · 8 min
Deps: BUD-01, `policy_schema.BudgetLimit`.
- [ ] `limits.py`: `LimitEntry` (dims present, `on_soft/on_hard`, `match_agents`, specificity), `LimitIndex.compile` memoised in `snapshot.compiled["budgets-ledger:limits"]`
- [ ] most-specific resolution per (concrete scope, window, dimension); per-instance vs aggregated counter keys
- [ ] `Ledger.scopes_for` (member scope only for humans)

### BUD-04 · Ledger core — must · demo_critical: yes · 18 min
Deps: BUD-02, BUD-03.
- [ ] counters `{(scope_key, window, window_start, dim): used}` + reservations map; `reserve` (AND across levels, denial names the highest-pct tripped scope, `meta.soft`, `meta.remaining`, `meta.keys`), `check`, `settle` (overshoot log), `release`, `commit`, `status`, `reset`, `price`
- [ ] reservation TTL sweeper (settle at estimate), session last-seen tracking, memory pruning (> 24 h idle sessions)
- [ ] `events.py`: thresholds 50/80/100 + `warn_pct` once per window instance → SSE `budget.threshold` + audit; `budget.exceeded` audit on denials; `UpdateCoalescer` → `budget.updated`; gauge `aegis_budget_utilization_ratio`
- [ ] `on_change` handler: recompile limits, publish full `budget.updated`

### BUD-05 · Persistence + demo state — must · demo_critical: yes · 11 min
Deps: BUD-04.
- [ ] `store.py` DDL (§4.3), `load_current` on start, write-behind flush (1 s task; inline in test mode), final flush on stop
- [ ] `demo_seed.py`: counters from `demo_state.budget_usage` when `budget_usage` is empty and demo mode (samples → BUD-11)

### BUD-06 · BUD-01 control — must · demo_critical: yes · 18 min
Deps: BUD-04; pipeline §3.5; gaps G1, G3, G5, G8, G9.
- [ ] estimate (model / tool / spend), clamp mutation (wire path, thinking skip), scope list incl. `model:`/`tool:`
- [ ] hard path: 402 block / `budget_raise` ApprovalDraft with patch (`ladder.py`) / usd-only downgrade
- [ ] soft path: warn (`log`) / downgrade (`route` mutation, trust + allowlist + size guards, re-reserve) / require_approval
- [ ] `X-Aegis-Budget-Remaining` + `pricing_version` in `meta`; dry-run → `check`; selftest → zero usage
- [ ] `on_complete`: price actual, local compute fallback, fill `outcome.usage.cost_usd`, settle / commit / release; enforcement events

### BUD-07 · Kill switch — must · demo_critical: yes · 8 min
Deps: BUD-04, policy-engine `on_change`.
- [ ] `killswitch.py`: `match`, `RuntimeKills`, `toggle_patch`, `diff`
- [ ] policy swap diff → SSE `killswitch` (actor from `snapshot.applied_by` → `rt.org.get_member`), audit `killswitch.toggled`, gauge `aegis_killswitch_active`; a runtime entry is dropped once the policy contains it

### BUD-08 · EXE-04 control — must · demo_critical: yes · 18 min
Deps: BUD-07; gaps G2, G6, G11.
- [ ] `stop.py` (Claude Code detection, §2.3 table)
- [ ] `ratelimit.py` sliding counters; `loops.py` fingerprint (hmac_hex), `LoopState`/`LoopRegistry`, detectors exact_repeat / short_cycle / model_repeat / error_streak, exemptions, agent overrides, cross-source dedupe
- [ ] evaluate order §2.7; ladder tool_error → block (cooldown, tool surfaces only) → kill (runtime + background `apply_patch`, `system` warning on failure); `max_steps_per_session` → 402
- [ ] `on_complete`: confirm/drop pending fingerprint, error streak; metrics `aegis_loop_detections_total`

### BUD-09 · Dashboard API core — must · demo_critical: yes · 12 min
Deps: BUD-04, BUD-05, BUD-07.
- [ ] `GET /api/budgets` tree (names/parents from `rt.org`, recent sessions, model/tool scopes, killed state, `kill_switch` = policy ∪ runtime)
- [ ] `POST /api/budgets/raise` (validate, patch rules, `propose`), `POST /api/killswitch` (`toggle_patch` → `propose`, noop detection), `POST /api/budgets/reset` (admin)
- [ ] error envelopes; 400 on bad scope / dimension / window / non-positive `new_limit`

### BUD-10 · Snippet & inline self-tests — must · demo_critical: yes · 5 min
Deps: BUD-06, BUD-08.
- [ ] write `config/snippets/budgets-ledger.yaml` exactly as §4.4 with comments; check the YAML parses with `PolicyDoc.model_validate` (snippet merged onto an empty doc)

### BUD-11 · History, samples & forecast — should · demo_critical: yes (charts) · 10 min
Deps: BUD-05.
- [ ] samples ≤ 1/5 s in flush; synthetic demo ramp samples in `demo_seed.py`
- [ ] `GET /api/budgets/history` + additive `forecast`

### BUD-12 · BUD-02 local compute control — should · demo_critical: no · 12 min
Deps: BUD-04.
- [ ] `LocalSlots` with queue wait + lease; 429 when saturated; `num_predict`/`num_ctx` mutations; model-size check on `model.admin`

### BUD-13 · Extra dashboard endpoints — should · demo_critical: yes (F5 preview, enforcement panel) · 10 min
Deps: BUD-09.
- [ ] `POST /api/budgets/raise/preview` via `rt.approvals.route`
- [ ] `GET /api/budgets/enforcement` from `enforcement.py`
- [ ] `GET /api/budgets/pricing`; `POST /api/budgets/usage` (admin, audited)

### BUD-14 · Burn-rate spike (LOOP-006) — should · demo_critical: no · 8 min
Deps: BUD-04, BUD-08.
- [ ] `BurnRate` EWMA per principal updated on settle; EXE-04 throttle 429 `Retry-After: throttle_s` when > factor × baseline and > floor

### BUD-15 · Pricing hot reload — should · demo_critical: no · 6 min
Deps: BUD-02.
- [ ] `watchfiles.awatch(config/pricing.yaml)` (not in test mode) → reload → last good kept on error → SSE `system` info/warning + audit `system`

### BUD-16 · Cost avoided & polish — could · 8 min
- [ ] `aegis_cost_avoided_usd_total{reason}` (downgrade delta, blocked estimate); `max_request_usd` single-request cap; per-scope ladder hint in `BudgetStatus.label` ("soft 80% → downgrade · hard → approval")

### BUD-17 · More detectors — could · 10 min
- [ ] LOOP-003 no-progress (needs a result hash; add `tool.output`/`mcp.result` to EXE-04 `applies_to` with `directions={"in"}` used only for hashing), LOOP-007 context growth (`est_input_tokens` > 3× the session's first), session `wall_s` caps from seed

### BUD-18 · Sessions & kill UX — could · 8 min
- [ ] `GET /api/budgets/sessions?agent_id=` (usage + loop state per session); bus hint for core-gateway in-flight stream cancellation (G-request)

### Verification tasks

| ID | Verifies | Command / check | Expected |
|---|---|---|---|
| **BUD-V01** | BUD-01 | `uv run --frozen python -c "import aegis.budgets.ledger, aegis.api.routes.budgets as r; from aegis.budgets.tokens import estimate_tokens as e; from aegis.controls.budget import bud01_budgets, bud02_local, exe04_loops as x; print(e('x'*400), e('x'*350,'claude-sonnet-4-5'), [c.id for c in x.CONTROLS])"` | `100 100 ['EXE-04']`, no import-time I/O |
| **BUD-V02** | BUD-02 | `uv run --frozen pytest tests/unit/budgets_ledger/test_tokens_pricing.py -q` | Sonnet 1000 in / 500 out = **$0.0105**; Haiku 10 000 in incl. 8 000 cache_read + 100 out = $0.0033 (0.002 + 0.0008 + 0.0005); `aegis-judge` compute_s 10 = $0.002; `anthropic/claude-opus-4-1` matches `claude-opus-*`; unknown model → `"*"`; `web.fetch_url` = $0.002 |
| **BUD-V03** | BUD-02/03 | `uv run --frozen pytest tests/unit/budgets_ledger/test_windows_limits.py -q` | Warsaw day start = previous 22:00Z in CEST; month start; DST day (2026-10-25) has no crash; `member:u_piotr` entry beats `member:*`; `match_agents` entry beats the generic `session:*`; human chain includes `member:`, agent chain doesn't |
| **BUD-V04** | BUD-04 | `uv run --frozen pytest tests/unit/budgets_ledger/test_ledger.py -q` | AND: team limit trips while agent is fine → `BudgetDenial.scope == "team:research"`; release restores headroom; settle overshoot logged; TTL expiry settles at estimate; thresholds 50/80/100 emitted once each; `budget.updated` coalesced |
| **BUD-V05** | BUD-04 | `uv run --frozen pytest tests/unit/budgets_ledger/test_ledger.py -k concurrency -q` | 200 concurrent `reserve($0.01)` against a $0.10 session limit → exactly **10** reservations; after settling, used ≤ limit + one reservation |
| **BUD-V06** | BUD-05/11 | `uv run --frozen pytest tests/unit/budgets_ledger/test_store.py -q` (temp `AEGIS_DATA_DIR`) | restart restores `used`; demo seed gives `team:trading` day usd **38.40** and `org:acme-capital` month usd 1088.40; history returns ≥ 2 points; samples ≤ 1 per 5 s |
| **BUD-V07** | BUD-06 | `uv run --frozen pytest tests/unit/budgets_ledger/test_bud01.py -q` | clamp mutation path per wire (`max_tokens`, `max_completion_tokens`, `options.num_predict`) and skipped with thinking; at 85 % `mock-echo` → `route` mutation to `aegis-judge`, action `redact`; no downgrade local→remote; 20k-token prompt not downgraded to local; hard → 402 `budget_exceeded`, `meta.response_headers["x-should-retry"] == "false"`, reason names the scope; chaos agent → `require_approval` with `payload.patch[0].path == "budgets.limits[scope=agent:chaos-agent@platform,window=day].usd"` and value 1.0; dry-run reserves nothing; selftest ignores live usage; `on_complete` fills `cost_usd` and settles; local `compute_s` fallback from wall time |
| **BUD-V08** | BUD-07/08 | `uv run --frozen pytest tests/unit/budgets_ledger/test_exe04.py tests/unit/budgets_ledger/test_killswitch.py -q` | 3rd identical `web.fetch_url` → block with "repeated 3x"; 4th → 429 + `retry_after_s=30` + x-should-retry false; after cooldown (patched clock) next repeat → `killed` 403, and 429/3600 for `claude-code@platform`; distinct calls allowed; A,B,A,B,A,B → short_cycle; 5 failed hops → error_streak; EXE-04-blocked hops not counted; hook+mcp duplicate counted once; rpm overflow → 429 with `Retry-After`; `kill_switch.agents: ["chaos-*"]` blocks `chaos-agent@platform`; selftest bypass; policy swap diff → `killswitch` event + audit |
| **BUD-V09** | BUD-09/13 | `uv run --frozen pytest tests/unit/budgets_ledger/test_api.py -q` (in-process ASGI app with our router + fake runtime; uses `create_app()` when importable) | `GET /api/budgets` keys match `BudgetsResponse`; raise team:trading 60→75 sends `[PatchOp(set, budgets.limits[scope=team:trading,window=day].usd, 75)]` to `propose`; raise `member:u_piotr` → `append`; reset as member → 403 `forbidden`, as admin → `{ok: true}`; killswitch builds a set-list patch and returns noop when unchanged; bad dimension → 400 `invalid_request`; preview returns `route.required_role` |
| **BUD-V10** | F5/F6 live (lead, after `make up`) | see script below | 200s, then 200 "approval pending" (budget_raise apr_…); after u_emily approves, next call 200 and policy version +1; kill → next call 403 `killed`; SSE shows `budget.updated`, `budget.threshold`, `killswitch` |
| **BUD-V11** | all | `uv run --frozen ruff check src/aegis/budgets src/aegis/controls/budget src/aegis/api/routes/budgets.py tests/unit/budgets_ledger && uv run --frozen ruff format --check <same paths>` and `uv run --frozen pytest tests/unit/budgets_ledger -q` | clean; whole unit suite < 10 s |
| **BUD-V12** | perf | `uv run --frozen pytest tests/unit/budgets_ledger/test_ledger.py -k perf -q` | 10 000 reserve+settle cycles on a 5-scope chain: p95 < 1 ms (target ~0.1 ms) |
| **BUD-V13** | Claude Code stop (manual, optional) | `make claude` with `budgets.kill_switch.agents: [claude-code@platform]` edited into `config/policy.yaml`, then type "hi" | one request in gateway logs, Claude Code shows the Aegis message and does not retry |

BUD-V10 script (lead runs; gateway on 8787):
```bash
KEY=aegis_demo_chaos_agent_0000000000000004_NOT_A_SECRET
for i in $(seq 1 10); do
  curl -s localhost:8787/v1/chat/completions -H "Authorization: Bearer $KEY" -H 'X-Aegis-Session: ses_runaway_v10' \
    -H 'content-type: application/json' -o /dev/null -w '%{http_code} ' \
    -d "{\"model\":\"mock-echo\",\"max_tokens\":4096,\"messages\":[{\"role\":\"user\",\"content\":\"step $i [[LONG:20000]]\"}]}"
done; echo
curl -s 'localhost:8787/api/approvals?status=pending&kind=budget_raise' -H 'X-Aegis-View-As: u_emily' | jq '.items[0] | {id, title, required_role}'
curl -s -X POST localhost:8787/api/approvals/<apr_id>/approve -H 'X-Aegis-View-As: u_emily' -H content-type:application/json -d '{}' | jq .status
curl -s localhost:8787/api/budgets | jq '.scopes[] | select(.scope=="agent:chaos-agent@platform") | .limits'
curl -s -X POST localhost:8787/api/killswitch -H 'X-Aegis-View-As: u_marek' -H content-type:application/json \
  -d '{"scope":"agent:chaos-agent@platform","active":true,"reason":"demo"}' | jq .status        # "applied"
```

---

## 6. Demo cut

**Must really work live:** reserve/settle on real (mock or provider) usage with contract prices; AND hierarchy with the denial naming the scope; 402 `budget_exceeded` for the chaos agent and its `budget_raise` approval that applies a patch when approved; F5 raise via `/api/budgets/raise` → GOV-05 approval → limits and gauges update over SSE; kill switch via API and via a file edit (< 1 s, audited, SSE); EXE-04 ladder tool_error → block → kill on `web.fetch_url` loops; soft-threshold downgrade to `aegis-judge`; `/api/budgets` tree with seeded demo state; Claude Code stops after one attempt.

**May be simplified or stubbed convincingly:** history charts drawn from seeded synthetic samples plus live samples, with a linear forecast; burn-rate spike (unit-tested, rarely visible live); BUD-02 model size estimated from the tag name; LOOP-003/007 and session `wall_s` (could); cutting in-flight streams on kill (buffered streaming makes it moot); pricing hot reload (a restart works too).

**Cut order if late:** BUD-18 → BUD-17 → BUD-16 → BUD-15 → BUD-14 → BUD-12 → BUD-13 (keep `raise/preview` if possible) → BUD-11. Never cut BUD-06/08/09.

---

## 7. Dependencies

No new packages. Everything is in CONTRACTS §7.6:
- Runtime: `pydantic>=2.9`, `fastapi`, `pyyaml` (pricing + demo seed), `watchfiles` (pricing reload), stdlib `sqlite3`, `zoneinfo` (macOS system tz database; falls back to UTC if `Europe/Warsaw` is missing, so `tzdata` is not needed), `hashlib`/`hmac`, `asyncio`, `collections.deque`.
- Dev: `pytest`, `pytest-asyncio` (`asyncio_mode=auto`), `httpx` (`ASGITransport`), `asgi-lifespan`.
- Not used: `tiktoken` / `anthropic` count_tokens (chars heuristic, then reconcile on settle), `redis` (documented scale path only).

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Self-test gate deadlock (global kill switch or exhausted org budget fails every must-allow test, so no policy edit, not even the fix, can apply) | `source == "selftest"` ⇒ zero-usage checks, no kill/loop state (G9); unit test covers it |
| Loop detector false positives on normal Claude Code work (`npm test` ×3, re-reading files) | exempt read-only tools, `agent_overrides` (claude-code repeat 6), only executed calls enter history, blocked retries never count, ladder starts with a readable tool error |
| Our own 429s trigger client retries that escalate loops | history only holds executed calls; EXE-04's own blocks are excluded from the error streak; hard stops send `x-should-retry: false` |
| Clamping `max_tokens` breaks Anthropic extended thinking (`max_tokens` must exceed `budget_tokens`) | skip the clamp when `thinking.budget_tokens` is present; reservation output capped at 8192 instead |
| Downgrade sends a huge Claude Code prompt to a 0.8B local model on an 8 GB machine | `local_downgrade_max_input_tokens` guard (warn instead); haiku/sonnet chain stays on Anthropic |
| Leaked reservations when a surface never calls `complete` (hooks) | TTL sweeper settles at estimate; request G6 |
| Mid-demo restart loses state | write-behind flush every 1 s; restart reloads current windows; at most ~1 s of usage lost |
| Midnight rollover during the night/demo resets daily counters | windows in Europe/Warsaw; preflight re-seeds demo state; month windows keep MTD |
| Kill-switch persistence via `apply_patch` is slow or rejected | in-memory kill is immediate; failure → SSE `system` warning; runtime entry TTL 15 min |
| hook + MCP proxy evaluate the same MCP call (double count) | cross-source dedupe within `dedupe_s` by (principal, fingerprint); tool_calls reservation is cheap |
| Contract gaps G1/G2 not implemented by core-gateway (no `x-should-retry` header) | 402 alone already stops Claude Code after one attempt; 403 kill still blocks (wording only); messages remain in error bodies |
| Policy validator warns on extra keys (`match_agents`, `timezone`) | they are valid (`extra="allow"`); request whitelisting (G7); the per-agent session caps aren't demo-critical |
| Price inaccuracies | prices live in `config/pricing.yaml` (owned, hot-reloaded, versioned on decisions); mock priced like Sonnet so demo budgets move |
| F6 timing: runaway takes too long to reach $0.50 | `[[LONG:20000]]` ≈ $0.075/call means ~7 calls; `POST /api/budgets/usage` fast-forward lever; judges can also lower the limit live |
