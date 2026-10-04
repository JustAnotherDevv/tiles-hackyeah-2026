# 14 · audit-metrics: audit log, metrics and live stats

> **Workstream:** `audit-metrics` · **Task prefix:** `AUD` · **Research:** 04 §4 (with 07 §9 for redaction spans)
> **Owned paths (CONTRACTS §1.2):** `src/aegis/audit/**`, `src/aegis/metrics/**`, routes `src/aegis/api/routes/{audit,decisions,stats,metrics}.py`, `tests/unit/audit_metrics/**`, `config/snippets/audit-metrics.yaml`, this file.
> **Binding inputs:** CONTRACTS §3.1 (`AuditEvent`, `AuditVerifyResult`, `DecisionSummary`, `DecisionDetail`), §3.2 (`AuditSink`, `MetricsSink`), §3.3 (factories), §3.5 step 11, §5.4/§5.5 (`StatsResponse`, `StatsTick`, `PerfResponse`, `Page<T>`, `AuditEvent`), §6.1 (tables), §6.2 (chain formula), §6.3 (`stats` event), §6.4 (metric names).

### Scope reconciliation (prompt vs CONTRACTS; CONTRACTS wins)

| Prompt says | CONTRACTS says | Plan |
|---|---|---|
| Prometheus `aicl_*` metrics | prefix **`aegis_`** (§6.4) | Use the §6.4 `aegis_*` names exactly. The research `aicl_*` names map 1:1 (table in §2.6). No duplicate `aicl_*` series. |
| "in-process event bus feeding SSE `/api/events`" | `aegis.core.bus` and route `events.py` belong to **core-gateway** | We don't build the bus. We **publish** `stats` (StatsTick every 2 s) and `system` events through `rt.bus`. We verify the SSE path end to end (AUD-V08). |
| Audit schema `aicl.audit/1` (research 04 §4.3) | `AuditEvent` with `schema="aegis.audit/1"` (frozen) | Research-only fields (OTel attributes, redaction spans with fingerprints, privacy markers) go under `AuditEvent.data`, the escape hatch. |
| "posture score" | not in `StatsResponse` (frozen) | New additive endpoint `GET /api/stats/posture` (Contract gap G2) |
| `platform.audit` / `platform.metrics` in `staging/seed/policy.yaml` | `PolicyDoc` rejects unknown top-level keys | These become code constants (excerpt 120 chars, overhead buckets, checkpoint every 100 records). The only policy key we read is `defaults.audit_content`. |

---

## 1. Goal and demo value

**What judges see**
- **Security reporting (20%).** Every decision is in a **hash-chained, redacted JSONL audit log**. `python -m aegis verify-audit` and the Audit page both print **"chain OK (N records)"**. A **tamper demo** flips one byte in a *copy* of the log, and verify then reports `broken_at_seq`. Exports come as **JSONL, CSV and OCSF** (Detection Finding 2004 / API Activity 6003), the export itself is audited, and only admins can run it.
- **Management view.** The Overview shows KPI tiles (requests, blocked, redacted, spend today against the org budget, **cost avoided**, active agents, p50/p95 overhead) and a stacked decision timeseries (1h/24h/7d), with top controls, entities, destinations and agents. There is also a **posture score** ("92 / A−") made of controls enforcing, self-tests passing, feed freshness and audit chain status.
- **Performance telemetry (architecture & performance 20%).** `/api/perf` reports real per-control p50/p95 latency, gateway overhead p50/p95/p99, upstream latency by provider and RPS. `/metrics` is a Prometheus exposition with the §6.4 names and sub-millisecond buckets.
- **Live.** An SSE `stats` tick every 2 s drives the KPI tiles and sparklines, and the decision drawer shows `audit_seq` / `audit_hash`.
- **Charts are never empty.** On a fresh `data/`, a **flagged synthetic 7-day history** is backfilled. It is clearly labelled: `synthetic=1`, a `[demo]` preview prefix, and it is kept out of the audit chain. A **dry-run primer** warms the per-control latency reservoirs with *real* measurements from the policy's inline tests.

**Headline flows served:** F10 (Proof: audit export + verify, perf, `/metrics`), and every other flow through the decisions feed and the audit trail (F1 drawer, F4/F5 "every step in the audit log").

---

## 2. Design

### 2.1 Files (all inside owned paths)

```
src/aegis/audit/
  __init__.py        docstring only (no import-time side effects)
  log.py             create(rt) -> AuditService  (implements AuditSink + start/stop + intra-workstream extras)
  chain.py           GENESIS, canonical_json(), chain_hash(), ChainWriter (daily files, HEAD.json, resume, flock)
  privacy.py         scrub_event() never-raw guard, redaction_spans() (+fp lift), audit_content handling
  index.py           SQLite DDL + writers (audit_index, decisions projection) + read queries (decisions/audit, cursors)
  verify.py          verify_dir() pure function, main(argv) CLI (`python -m aegis verify-audit`), --tamper-demo
  export.py          async streaming exporters: jsonl (raw lines), csv (flattened), ocsf; filters
  ocsf.py            to_ocsf(record: dict) -> dict (2004 / 6003 mapping, security_control profile)
src/aegis/metrics/
  __init__.py        docstring only
  prom.py            create(rt) -> MetricsService (implements MetricsSink); registry; label guard; derived counters; refresh_gauges()
  perf.py            Reservoir, PerfTracker (overhead/control/upstream/rps), build_perf_response()
  stats.py           SQL aggregation -> StatsResponse, build_stats_tick(), posture(), control_rollup() (public helper, gap G9)
  cost.py            estimate_avoided() + fallback price table
  otel.py            genai_attributes() — OTel GenAI semconv v1.41 names; SEMCONV_VERSION
  timing.py          iso_z(), parse_since(), bucket math (UTC, ms precision, 'Z')
  warmup.py          backfill() synthetic history, prime() dry-run primer, main(argv) CLI
src/aegis/api/routes/
  audit.py           GET /api/audit · GET /api/audit/export (admin) · GET /api/audit/verify
  decisions.py       GET /api/decisions · GET /api/decisions/{id}
  stats.py           GET /api/stats · GET /api/perf · (G2/G3) GET /api/stats/posture · GET|POST|DELETE /api/stats/warmup
                     on_startup(rt): stats ticker, auto warm-up, primer, startup verify · on_shutdown(rt): cancel tasks
  metrics.py         GET /metrics (refresh scrape-time gauges, then rt.metrics.render())
tests/unit/audit_metrics/
  conftest.py  test_chain.py  test_privacy.py  test_index_api.py  test_metrics_perf.py  test_stats_warmup.py  test_export.py
config/snippets/audit-metrics.yaml   (no controls; documents defaults.audit_content and the metric/audit contract for others)
```

### 2.2 Write path (one record per decision)

```
pipeline step 11 ──► rt.audit.record(AuditEvent(event_type="decision", data={"summary", "detail"}))
                         │ 1. dump  model_dump(mode="json", by_alias=True)          (to_thread)
                         │ 2. enrich data.redaction_spans (+fp/preview lifted from findings.meta),
                         │           data.otel (GenAI attrs), data.privacy
                         │ 3. scrub  never-raw guard over free-text leaves (rt.redactor.detect, no NER)
                         │ 4. chain  async Lock: seq=n+1, prev_hash=head, hash=sha256(prev+canonical(d-"hash"))
                         │ 5. persist (to_thread, single writer conn): append line → HEAD.json → audit_index row
                         │           → if decision: UPSERT decisions row (summary/detail + audit_seq/hash)
                         │ 6. derive counters for non-decision events (approvals/policy/feed reloads)
                         └─ never raises: log.exception + aegis_audit_errors_total; returns event with seq/hash
pipeline ──► rt.metrics.observe_verdict(ctx, interaction, verdict)
                         counters + histograms + PerfTracker + cost avoided → annotate decisions row (same writer)
pipeline.complete ──► (R1) rt.audit.record(event_type="decision", data.phase="outcome", usage)
                         → chain append + UPDATE decisions SET cost_usd,tokens,upstream_ms + aegis_cost_usd_total
```

**Chain format (§6.2, exact).** `canonical_json(o) = json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)`. The hash is `sha256((prev_hash + canonical_json(d_without_"hash")).encode("utf-8")).hexdigest()`, where `d` already has `seq` and `prev_hash` set. Genesis `prev_hash = "0"*64` and the first `seq = 1`. The line written is `canonical_json(d_with_hash) + "\n"`, and verify re-parses that line, so whatever is written is exactly what is hashed. Use stdlib `json`, not orjson, so third parties can reproduce the hash from the contract formula.

**Files.** `data/audit/audit-YYYYMMDD.jsonl` is chosen by the UTC date at write time. The chain continues across files. `data/audit/HEAD.json` holds `{"seq","hash","file"}` and is rewritten atomically (temp + `os.replace`) after each append. A `data/audit/.lock` (`fcntl.flock`) means only one process writes. If the lock is busy, the service runs in **degraded log-only** mode with an ERROR log and a `system` bus event. **CLI tools never append to the chain.**

**Resume on start.** Read HEAD.json and the last line of the newest file. A partial trailing line (crash mid-write) is truncated back to the last newline, with a WARNING and a `system` audit event after start. If HEAD is *ahead of* the file, the log was truncated: keep appending from the file's last record and cache a broken verify result for posture and UI. If `audit_index` is empty while files exist (DB wiped), rebuild the index in the background.

**Concurrency and performance.** One `asyncio.Lock` guards seq/hash/persist. All I/O runs through `asyncio.to_thread` on a dedicated writer connection (`rt.db()`, `PRAGMA busy_timeout=5000`). There is no per-record fsync; `stop()` does flush + fsync. Target: `record()` p95 under 1.5 ms (AUD-V12). AUD-20 adds batching if needed.

### 2.3 Privacy guard (redaction spans + HMAC fingerprints, never raw values)

- **Spans.** `AuditEvent.redactions` (frozen `Redaction`: segment_index, path, start/end in *original* coordinates, entity, data_class, placeholder, control_id, reversible) is always present. The sink adds `data.redaction_spans[]` in the research-07 §9 shape: `{segment_index, path, entity, data_class, control_id, op ("tokenize"|"drop"|"mask"), placeholder, start, end, r_start, r_end, orig_len, detector?, score?, preview?, fp?}`. `r_start`/`r_end` are offsets **in the redacted text**, computed from the placeholder lengths in segment order. `detector`/`score`/`preview`/`fp` come from the matching `Finding` (same segment_index, overlapping span) in `data.detail.decisions[].findings[]`: `preview` = `Finding.excerpt` (already masked) and `fp` = `Finding.meta["fp"]` (request R4).
- **Fingerprints.** The sink **never computes** a fingerprint because it never sees raw values. It only lifts `meta.fp` (`"hmac:<16 hex>"`, produced by redaction-engine with `aegis.core.crypto.hmac_hex(value, purpose="audit")`). For `CVV`/`TRACK_DATA` it **drops** `fp` and `preview` even if they were provided (PCI SAD: never fingerprinted).
- **Scrubber (defence in depth).** Walk string leaves of `data` plus `reason` (skip keys `hash, prev_hash, fp, fingerprint, sha256, placeholder, ts, *_id, id`, and strings under 8 or over 4096 chars; at most 200 leaves per event). Run `rt.redactor.detect(s, use_ner=False)` and replace spans right-to-left with `[REDACTED:<ENTITY>]`. If `rt.redactor` is the Null fallback, a built-in mini-set takes over (`AKIA[0-9A-Z]{16}`, PEM private key header, PESEL via `aegis.redaction.validators.pesel_ok`, 13–19 digit Luhn runs via `card_ok`, all guarded imports). Drop keys `authorization, cookie, x-api-key, api_key, password, raw, wire, original, response_raw, response_local`, plus `segments`/`content` unless `defaults.audit_content` is true. Record `data.privacy = {"scrubbed": n, "audit_content": bool}`. If `n > 0`, an upstream owner leaked something: log a WARNING (without the value).

### 2.4 SQLite (own tables, §6.1 DDL verbatim, plus additive columns, gap G4)

- `audit_index` (§6.1) **+ `offset INTEGER, length INTEGER`** for byte-offset random access to the JSONL line. `GET /api/audit` reads rows from the index and the record via seek.
- `decisions` (§6.1) **+ `cost_avoided_usd REAL NOT NULL DEFAULT 0`, `avoided_reason TEXT`, `categories_json TEXT NOT NULL DEFAULT '[]'`, `synthetic INTEGER NOT NULL DEFAULT 0`**, plus `CREATE INDEX ix_decisions_synth ON decisions(synthetic, ts)`.
- `ts` is always written as `YYYY-MM-DDTHH:MM:SS.mmmZ` (UTC), so string range comparisons work and `strftime('%s', ts)` buckets (verified to work on SQLite 3.50 / Python 3.13).
- The projection upserts `INSERT … ON CONFLICT(id) DO UPDATE` so annotate columns survive. `detail_json` = DecisionDetail-without-wire plus `audit_seq`/`audit_hash`. `categories_json` = the unique `findings[].category` values. If the pipeline sends no `summary`, a summary is built from the AuditEvent top-level fields.
- An in-memory LRU of the last 500 details (decision id to detail dict) means `GET /api/decisions/{id}` never misses a just-written row.

### 2.5 Verification (tamper evidence)

`verify_dir(audit_dir) -> AuditVerifyResult` reads files in name order and checks each line: it parses (fail means broken), checks `seq == expected`, checks `prev_hash == running`, and recomputes the hash. After the walk it checks that **HEAD.json** seq/hash equal the last record (this catches tail truncation). The service version also cross-checks `audit_index` (row count, last hash) and records index drift in `message`. The result is cached as `last_verify`. It runs in the background at startup (unless test mode), on `GET /api/audit/verify`, before export (if the cached result is more than 60 s old), and every 5 min.
CLI `python -m aegis verify-audit [--data-dir D] [--json] [--tamper-demo]` dispatches to `aegis.audit.verify:main(argv) -> int`. Its output is `chain OK (N records, F files, head 41d9…c07e)` with exit 0, or `chain BROKEN at seq K (audit-20261003.jsonl:118): hash mismatch` with exit 1. `--tamper-demo` copies the audit dir to a temp dir, flips one byte in record ⌊N/2⌋, verifies the **copy**, prints both results and exits 0. The real log is untouched.

### 2.6 Metrics (`aegis.metrics.prom`, exact §6.4 names; private `CollectorRegistry` per service)

| Metric (`aicl_*` research name) | Type · labels | Fed by |
|---|---|---|
| `aegis_requests_total` (`aicl_requests_total`) | counter · surface, source, action | observe_verdict |
| `aegis_decisions_total` (`aicl_decisions_total`) | counter · control_id, action, mode | observe_verdict (each `verdict.decisions[]`) |
| `aegis_control_duration_seconds` | histogram · control_id, kind | `ctx.timings["ctl.<ID>"]` (R2), else `decision.latency_ms`; primer samples |
| `aegis_gateway_overhead_seconds` | histogram · phase; buckets `[.0002,.0005,.001,.0025,.005,.01,.025,.05,.1,.25,.5,1]` | observe_overhead(phase) from core-gateway, plus `phase="pipeline"` from `verdict.latency_ms` (separate label value, so nothing is double counted) |
| `aegis_upstream_duration_seconds` | histogram · provider | observe_upstream |
| `aegis_tokens_total` | counter · provider, model, type(input/output/cache_read/cache_write) | observe_upstream |
| `aegis_cost_usd_total` | counter · team, agent, provider | outcome audit events (R1). Until the first one is seen: observe_upstream with team/agent=`unknown` |
| `aegis_cost_avoided_usd_total` | counter · reason (policy_block, budget, loop, downgrade, spend_blocked) | observe_verdict → cost.py |
| `aegis_redactions_total` | counter · entity, dest_class | `verdict.redactions` |
| `aegis_signature_hits_total` | counter · signature_id | findings `category=="signature"` (`meta.signature_id`, else detector) |
| `aegis_loop_detections_total` | counter · detector | findings `category=="loop"` |
| `aegis_approvals_total` | counter · kind, outcome | derived from `approval.*` audit events |
| `aegis_policy_reloads_total` / `aegis_feed_reloads_total` | counter · result | derived from `policy.*` / `feed.*` audit events |
| `aegis_approvals_pending`, `aegis_policy_version`, `aegis_feed_serial`, `aegis_semantic_degraded`, `aegis_killswitch_active` (number of active kill-switch scopes), `aegis_budget_utilization_ratio{scope_type,scope,dimension}` (org/team/member/agent only; max over windows) | gauges | `refresh_gauges(rt)` at scrape time in `GET /metrics` (each call try/except, 250 ms timeout) |
| extra: `aegis_audit_records_total{event_type}`, `aegis_audit_errors_total`, `aegis_audit_chain_ok` | counter / counter / gauge | audit service |

- **Label guard.** Values matching `^(req|dec|int|apr|evt|res|ses)_`, or longer than 80 chars, become `other`. Each metric is capped at 500 label sets, then `other`.
- **Generic `inc()`/`set_gauge()`.** Names are accepted with or without the `aegis_` prefix and `_total` suffix. Unknown names get a lazily created `aegis_<name>` (label names fixed on first use). Calls to the **derived** counters (approvals, policy/feed reloads) are ignored at DEBUG level to avoid double counting; owners only need to write their audit events.
- `render()` returns `generate_latest(registry), CONTENT_TYPE_LATEST`.

### 2.7 Perf tracker (`aegis.metrics.perf`)
Ring-buffer `Reservoir`s: overhead per phase (2048), per control (1024), per (provider, model) upstream (512), plus a 120 s deque of `(monotonic, action)` for `rps` and `decisions_1m`. Percentiles are exact over the buffer (sorted copy of 2048 floats, about 0.1 ms). `build_perf_response(rt)` returns `PerfResponse`: overhead from phases `request`+`response` when present, else `pipeline`; `by_control` uses `kind` from `rt.controls.get(id)`, sorted by p95 descending; `semantic` = `rt.semantic.status()`; `bench` = `reports/bench.json`, cached by mtime, `null` if missing or invalid. Memory stays under 2 MB.

### 2.8 Stats (`aegis.metrics.stats`) → `StatsResponse` (frozen shape)
- **Windows.** `1h` = 60 × 1 min, `24h` = 96 × 15 min, `7d` = 56 × 3 h. Buckets align to epoch multiples and are zero-filled.
- **Timeseries.** `SELECT CAST(strftime('%s',ts) AS INT)/? b, action, count(*), sum(cost_usd), sum(tokens) … GROUP BY b, action`.
- **KPIs (window).**
  - `requests` = all evaluations; `allowed`/`logged`/`redacted`/`blocked` by final action.
  - `approvals_pending` = `len(await rt.approvals.list_requests(status="pending"))`; `approvals_decided` = items with `decided_at` in the window.
  - `spend_usd` = Σ`cost_usd`; `tokens` = Σ`tokens`; `cost_avoided_usd` = Σ`cost_avoided_usd`; `active_agents` = distinct `agent_id`.
  - `spend_today_usd`, `org_budget_used_pct` and `local_compute_s` come from `rt.ledger.status("org:<id>")` (day window; **ledger-authoritative**), falling back to Σ since UTC midnight or 0.
  - `p50/p95_overhead_ms` from the PerfTracker.
  - `degraded` = semantic degraded OR a degraded decision in the last 5 min OR feed status not in {ok, seed} OR last verify not OK.
- **`by_control`.** From `json_each(summary_json,'$.controls')`: hits, blocks (enforce + block), redacts. `family` = id prefix. Top 15.
- **Other breakdowns.** `by_category` (`json_each(categories_json)`), `by_destination` (all 3 dest classes, zero-filled, with Σ`redaction_count`), `by_entity` (`json_each(entities_json)`, top 15), `top_agents` (requests, blocks, Σ`cost_usd`, top 8).
- **Synthetic filter and caching.** `?synthetic=0|1` (gap G10; default 1 in demo mode) adds `AND (? OR synthetic=0)`. Results are cached per (window, synthetic) for 2 s and computed in `to_thread`.
- **Ticker.** `stats_loop` publishes `rt.bus.publish("stats", StatsTick)` every 2 s. Values come from memory only, with no SQL per tick: ledger spend is refreshed every 10 s, the pending-approvals count every 5 s.
- **Public helper (G9).** `async control_rollup(rt, window_s=86400) -> dict[str, {"hits","blocks","p95_ms"}]` for policy-engine's `ControlView.hits_24h/blocks_24h/p95_ms`.

### 2.9 Cost avoided (`aegis.metrics.cost.estimate_avoided(rt, interaction, verdict) -> (usd, reason|None)`)
- **Block** of an outbound `model_call`: `rt.ledger.price(model, Usage(input_tokens=est_in, output_tokens=min(max_out or 1024, 4096)))`, where `est_in = interaction.est_input_tokens` or `aegis.budgets.tokens.estimate_tokens(text)` (guarded) or 1000. `reason` = `budget` (BUD-01/02), `loop` (EXE-04), else `policy_block`.
- **Block** of `spend.*` with `amount_usd`: `usd = amount_usd`, `reason = spend_blocked` (for example the $5,000.01 hard block).
- **Route mutation** (downgrade): `price(original) − price(new)` on the same estimate, `reason = downgrade`.
- If `rt.ledger.price` returns 0 (Null ledger), a fallback table from §4.6 is used. The result is stored with `annotate(decision_id, cost_avoided_usd, avoided_reason)` and counted in Prometheus. All values are labelled estimates.

### 2.10 OTel GenAI attributes (`aegis.metrics.otel`, semconv **v1.41** names, research 04 §4.2)
`genai_attributes(summary: dict, usage: dict | None, outcome: dict | None) -> dict` builds `data.otel` in decision and outcome records, and is reused by OCSF `unmapped.otel` and the OTLP export.

| Attribute | Source |
|---|---|
| `gen_ai.operation.name` | `model_call`→`chat`; `tool_call`/`mcp` (call/result)→`execute_tool`; `a2a`→`invoke_agent`; others omitted |
| `gen_ai.provider.name` | `destination.provider` or `destination.name` (`anthropic`, `openai`, custom `ollama`, `mock`) |
| `gen_ai.request.model` / `gen_ai.response.model` | `model` / outcome `model_used` |
| `gen_ai.usage.input_tokens`, `.output_tokens`, `.cache_read.input_tokens`, `.cache_creation.input_tokens` | `Usage` |
| `gen_ai.conversation.id` | `session_id` |
| `gen_ai.agent.id` / `gen_ai.agent.name` | `identity.agent_id` / `identity.display_name` |
| `gen_ai.tool.name` / `gen_ai.tool.type` | `tool_name` / `extension` (MCP) or `function` |
| `mcp.method.name` | `mcp.init`→`initialize`, `mcp.list`→`tools/list`, `mcp.call`/`mcp.result`→`tools/call` |
| `error.type` | primary `error_type` |
| `aegis.decision.action`, `aegis.control.id`, `aegis.surface`, `aegis.dest_class`, `aegis.policy.version`, `aegis.feed.serial`, `aegis.redaction.count`, `aegis.semconv.version="1.41.0"` | summary |

Content attributes (`gen_ai.input.messages` etc.) are **never** emitted, following OTel's privacy-first default.

### 2.11 Exports (`aegis.audit.export`, `aegis.audit.ocsf`)
- **Filters.** `from`, `to` (ISO; files preselected by date in the name), `action`, `control_id` (primary or any `data.summary.controls[]`), `agent_id` (`actor.agent_id`), optional `event_type`. Output streams in chunks of about 64 KB, read in `to_thread`.
- **`jsonl`.** Raw lines, byte-identical, so every record re-verifies on its own (`sha256(prev_hash + canonical(rec−hash))`) and contiguous exports verify as a chain. Media type `application/x-ndjson`.
- **`csv`.** Columns: `seq, ts, event_type, event_id, request_id, decision_id, session_id, principal, org_id, team_id, member_id, agent_id, kind, surface, direction, dest_name, dest_class, model, tool_name, action_type, amount_usd, resource, action, control_id, controls ("DLP-01:redact;INJ-02:block"), reason, score, threshold, redaction_count, entities, latency_ms, input_tokens, output_tokens, cost_usd, policy_version, feed_serial, prev_hash, hash`. CSV-injection guard: cells starting with `= + - @ \t \r` get a `'` prefix.
- **`ocsf`.** One OCSF 1.9.0 event per line:
  - Non-allow decisions, plus `feed.rejected`, `policy.rejected` and `mcp.tool_changed` → **Detection Finding** `class_uid 2004`, `category_uid 2`, `activity_id 1`, `type_uid 200401`. Fields: `finding_info{uid=decision_id|event_id, title="<control_id>: <reason>", analytic{uid=control_id, type_id 1 "Rule"}, types=[categories]}`, `evidences[{data:{surface, tool_name, entities, redaction_spans (no values)}}]`, `resources[{type: "ai_model"|"tool", name}]`, `risk_score = round(score*100)`, `is_alert` (block/require_approval).
  - Everything else → **API Activity** `class_uid 6003`, `category_uid 6`, `activity_id` 1 Create (`approval.created`), 3 Update (`policy.applied`, `feed.updated`, `killswitch.toggled`, `org.changed`), 99 Other, `type_uid = 600300 + activity_id`. Fields: `api{operation: gen_ai.operation.name or event_type, service{name: provider or "aegis"}}`, `src_endpoint{name: agent_id or member_id or "aegis"}`, `duration = latency_ms`.
  - Common fields: `time` (epoch ms); `severity_id` (info 1, low 2, medium 3, high 4, critical 5); `metadata{version "1.9.0", product{name "Aegis AI Control Layer", vendor_name "Aegis", version}, uid=event_id, correlation_uid=request_id, log_name "aegis.audit", profiles ["security_control"]}`; `actor{user{uid=member_id}, app_name=agent_id}`; `ai_model{name, ai_provider}`; `ai_agent{uid, name}`; `policy{uid=str(policy_version), name "aegis-policy"}`.
  - Security-control profile mapping: allow → action_id 1 / disposition_id 1 Allowed; log → 3 Observed / 17 Logged; redact → 4 Modified / 11 Corrected; require_approval → 2 Denied / 14 Delayed; block → 2 Denied / 2 Blocked.
  - `unmapped{aegis:{seq, hash, prev_hash, surface, controls}, otel:{…}}`.
  - Implementer: if network is available, check the enum ids against schema.ocsf.io. If not, keep these and use the caption strings.
- **Route.** `GET /api/audit/export` (admin) returns a `StreamingResponse` with `Content-Disposition: attachment; filename="aegis-audit-<date>.{jsonl|csv|ocsf.jsonl}"` and headers `X-Aegis-Audit-Head: <hash>`, `X-Aegis-Audit-Records: <seq>`, `X-Aegis-Audit-Verified: ok|broken`. The export is itself audited: `system` event `{kind:"audit.export", format, filters, by: viewer}`.

### 2.12 Posture score (`GET /api/stats/posture`, gap G2)

| Component (weight) | Score 0..1 | Source |
|---|---|---|
| `controls` Controls enabled & enforcing (35) | enforce = 1, monitor = 0.5, off/disabled/not implemented = 0, averaged over `snapshot.controls` | `rt.policy.snapshot()`, `rt.controls.get()` |
| `selftests` Inline policy tests passing (20) | passed / total from the last primer run (AUD-15); component excluded if unknown | primer cache |
| `feed` Threat feed freshness (15) | ok 1 · seed 0.7 · rejected (on last-good) 0.6 · unreachable 0.5 · stale 0.4 · disabled 0 | `rt.feed.status()` |
| `audit` Audit chain integrity (15) | last verify ok 1 / else 0 | `last_verify` |
| `models` Detection models healthy (10) | not degraded 1 / degraded 0.5 | `rt.semantic.status()` |
| `governance` Approvals and budgets configured (5) | `approvals.rules` and `budgets.limits` both non-empty = 1, one = 0.5 | snapshot |

`score = round(100·Σw·s/Σw)`. Grade: ≥95 A, ≥90 A−, ≥85 B+, ≥80 B, ≥70 C, else D. `findings[]` lists, for example, "DLP-02 disabled (policy v14)" (high), "feed stale" (medium) and "audit chain broken at seq 118" (critical), each with a `link` (`/ui/governance/policy`, `/ui/security/threats`, `/ui/security/audit`).

### 2.13 Demo warm-up (`aegis.metrics.warmup`)
- **`backfill(rt, days=7, per_day=900, seed=20261003, clear=False) -> int`.** Builds synthetic `decisions` rows for `[now−days, now−2 min]`.
  - Cast comes from `rt.org.list_agents()`/`list_members()`, falling back to the §4.5 ids.
  - Traffic follows a diurnal Europe/Warsaw curve (×3 from 08:00 to 19:00, ×0.3 at weekends) with seeded RNG.
  - Scenario mix (weights): allow 74%, DLP-01 redact (PESEL/IBAN/EMAIL/PAN/PHONE/PERSON) 10%, DLP-03 redact 4%, INJ-03 log 2%, DLP-06 redact on `model.response` 1.5%, DLP-02 block 1.5%, INJ-01/02 block 1.5%, EXE-01 block 0.8%, ACT-01/ACT-02 require_approval 1%, EXE-02 block 0.5%, SIG-01 block 0.5%, EXE-04 block 0.4%, BUD-01 block 0.3%, GOV-02 block 0.3%, MCP-02 redact 0.3%. Kind, surface, destination, model and tool are consistent per scenario.
  - Tokens are lognormal; `cost_usd` via `rt.ledger.price` (fallback table); `cost_avoided_usd` via cost.py; latency is lognormal by control kind.
  - Ids are time-sortable and backdated (`dec_` + hex ms + random), `request_id req_demo…`, `session_id ses_demo_<agent>_<yyyymmdd>`, preview `"[demo] …"` (masked templates), `synthetic=1`.
  - Every summary is validated through `DecisionSummary`, then all rows go in with one `executemany` transaction.
  - **These rows are never written to the audit chain.** The API/auto path records one `system` audit event: `{kind:"demo.backfill", rows, window_days, note:"synthetic history for charts; flagged synthetic=1; not part of the decision chain"}`.
- **Auto trigger** (stats route `on_startup`): `settings.demo_mode and not settings.test_mode and warmup != "off"` and there are no synthetic rows. With `warmup == "force"`, clear and refill on every start.
- **CLI.** `python -m aegis.metrics.warmup [--days 7] [--per-day 900] [--clear] [--data-dir data]` writes SQLite only and never touches the chain.
- **`prime(rt, passes=2)`** (AUD-15). Runs the policy's inline tests (`snapshot.doc.tests` + every `ControlConfig.tests`, mapped like the self-test gate: text→`TextSegment(path="text")`, tool_name/args, amount, agent identity) through `rt.pipeline.evaluate(…, dry_run=True)` with `source="selftest"`. Dry runs reserve no budgets, create no approvals and leave no audit or SSE trace. The primer feeds the **real** per-control timings into the PerfTracker and the control-duration histogram, and caches pass/fail (expect vs got action, attribution if `control` is set) for posture. It runs once after start, then once after each `policy.applied` bus event (debounced 2 s). Concurrency is 1.

### 2.14 Endpoints served

| Method & path | Viewer | Response |
|---|---|---|
| `GET /api/decisions?action=&control_id=&kind=&surface=&agent_id=&team_id=&member_id=&since=&q=&limit=&cursor=&synthetic=` | member | `Page<DecisionSummary>` newest first. `q` = LIKE over id/preview/reason/tool/model/agent. Cursor = b64(`ts|id`) |
| `GET /api/decisions/{id}` | member | `DecisionDetail` (+`wire` from `rt.pipeline.wire(id)`, `audit_seq`/`audit_hash`); 404 envelope `not_found` |
| `GET /api/audit?event_type=&since=&decision_id=&limit=&cursor=` | member | `Page<AuditEvent>` newest first (`event_type` supports a trailing `*`, e.g. `approval.*`) |
| `GET /api/audit/export?format=jsonl\|csv\|ocsf&from=&to=&action=&control_id=&agent_id=` | **admin** | file stream (§2.11) |
| `GET /api/audit/verify` | member | `AuditVerifyResult` |
| `GET /api/stats?window=1h\|24h\|7d&synthetic=` | member | `StatsResponse`; bad window → 400 `invalid_request` |
| `GET /api/perf` | member | `PerfResponse` |
| `GET /api/stats/posture` (G2) | member | `PostureResponse` (§4.3) |
| `GET /api/stats/warmup` / `POST` `{days?, per_day?, clear?}` / `DELETE` (G3) | member / **admin** / **admin** | `WarmupStatus` |
| `GET /metrics` | none (Prometheus) | text exposition |

Errors use `aegis.core.errors.api_error`. RBAC uses `aegis.core.deps.require_role("admin")`.

### 2.15 Events emitted / config read
- **SSE (via `rt.bus`):** `stats` (StatsTick, every 2 s, not in test mode); `system` with `{level, message, component:"audit"|"metrics"}` for: audit chain broken, audit write failures (rate-limited to 1 per 10 s), lock busy (log-only mode), and warm-up done (info).
- **Audit events written by us:** `system` (`audit.started`/`audit.resumed`, `audit.repaired`, `demo.backfill`, `audit.export`).
- **Config read:**
  - Settings `data_dir`, `demo_mode`, `test_mode`, `warmup` (G3, read via `getattr(settings, "warmup", "auto")`).
  - Policy `defaults.audit_content`, `controls`, `tests`, `budgets.kill_switch`, `budgets.limits`, `approvals.rules`.
  - File `reports/bench.json`.

---

## 3. Reuse map (staging → owned paths; port, never import)

| Staging input | What we take | Into |
|---|---|---|
| `staging/pii/placeholders.py` (`spans.append({...})`, `mask_preview`, `SAD_TYPES`) | span schema `type/detector/score/op/ph/start/end/orig_len/preview/fp`; SAD rule "never fingerprinted, never previewed" (code stays with redaction-engine) | `audit/privacy.py` `redaction_spans()` field names; CVV/TRACK fp-drop rule |
| research 07 §9 (span example, rules) | `r_start/r_end` in redacted coordinates; "HMAC keys not exportable"; ingress body never logged | `audit/privacy.py` |
| research 04 §4.2–4.5 | OTel v1.41 attribute names, OCSF 2004/6003 + security_control mapping, overhead buckets, cardinality rule, CSV flattening, reporting tests list | `metrics/otel.py`, `audit/ocsf.py`, `metrics/prom.py`, tests |
| `staging/seed/policy.yaml` `platform.audit` / `platform.metrics` (lines 549–561) | `excerpt_chars: 120`, `checkpoint.every_records: 100`, overhead buckets, `export_formats`, `capture_content: false` | constants in `audit/chain.py` / `metrics/prom.py` (no policy section; `PolicyDoc` forbids it) |
| `staging/design/prototype/assets/data.js` (`A.kpi`, `A.topControls`, `A.controlLatency`, `A.heat`) and `view-overview.js` (posture list: controls enabled, self-tests, feed freshness, audit chain; ring 92) | scenario weights and entity mix for the synthetic backfill; posture components and labels | `metrics/warmup.py` scenario table; `metrics/stats.py` posture |
| `staging/spikes/mcp/aegis_mcp/events.py` | confirms MCP decisions should land in the hash-chained sink; nothing to port (mcp-proxy goes through the pipeline → `rt.audit`) | n/a |
| `staging/submission/DEMO_RUNBOOK.md` Scene 6, `VIDEO_60S.md` row 8, `PITCH_DECK.md` slide 8 | acceptance strings "chain OK ([N] records)", "Export (OCSF)", perf p50/p95 | CLI/API messages, V-tasks |
| `staging/seed/SCENARIOS.md` "Audit" rows | card only as `411111******1111` + `fp:<hmac>`, CVV never stored; `source=file` policy edits audited | privacy tests (`test_privacy.py`) |

---

## 4. Interfaces

### 4.1 Consumed (exact names from CONTRACTS)
- Frozen types: `AuditEvent`, `AuditVerifyResult`, `DecisionSummary`, `DecisionDetail`, `ControlHit`, `Redaction`, `Verdict`, `Interaction`, `RequestContext`, `Usage`, `Identity`, `TextSegment`, `BusMessage`, `utcnow`, `new_id`; protocols `AuditSink`, `MetricsSink`, `RuntimeProto`; `PolicySnapshot`, `ControlConfig`, `PolicyTest`.
- `aegis.core.deps`: `get_rt`, `viewer`, `require_role`. `aegis.core.errors.api_error`. `aegis.core.runtime.get_runtime` (CLI not needed).
- Guarded public surfaces: `aegis.redaction.validators` (`pesel_ok`, `card_ok`) for the scrubber fallback; `aegis.budgets.tokens.estimate_tokens` for cost estimates.
- Runtime services:
  - `rt.settings`, `rt.db()`, `rt.bus.publish/subscribe`
  - `rt.policy.snapshot()/on_change()`
  - `rt.redactor.detect(text, use_ner=False)`, `rt.ledger.price()/status()`, `rt.approvals.list_requests()`
  - `rt.semantic.status()`, `rt.feed.status()/serial`, `rt.controls.all()/get()`
  - `rt.pipeline.wire()/new_context()/evaluate(dry_run=True)`, `rt.org.org()/list_agents()/list_members()`
- **Degradation.** Every one of these is wrapped. A Null service (ledger, redactor, approvals, feed, semantic) yields fallbacks such as the price table, the mini scrubber, or 0 pending. A missing `aegis.core.deps` means the routes fail to import and are reported by discovery, but services still work.

### 4.2 Provided
- `aegis.audit.log:create(rt) -> AuditService`, which implements `AuditSink` exactly: `record`, `verify`, `query(event_type, since, limit, cursor)`, `export(fmt, **filters)`, plus `start()`/`stop()`. Intra-workstream extras: `head()`, `last_verify`, `annotate(decision_id, **cols)`, `recent_detail(id)`.
- `aegis.metrics.prom:create(rt) -> MetricsService`, which implements `MetricsSink` exactly: `observe_verdict`, `observe_upstream`, `observe_overhead`, `inc`, `set_gauge`, `render`, plus `start()`/`stop()`, `perf` (PerfTracker).
- `aegis.audit.verify:main(argv: list[str] | None = None) -> int` (target of `python -m aegis verify-audit`).
- `aegis.metrics.warmup:main(argv) -> int`.
- Routes per §1.3 plus the G2/G3 additions; SSE `stats`; `/metrics`.
- `aegis.metrics.stats.control_rollup(rt, window_s=86400)` (G9).

### 4.3 Contract gaps (proposed addenda; additive only, nothing frozen changes)

| # | Gap | Proposal | Interim behaviour |
|---|---|---|---|
| G1 | prompt asks for `aicl_*` metric names | none; §6.4 `aegis_*` is binding (mapping in §2.6) | n/a |
| G2 | posture score has no endpoint or type | `GET /api/stats/posture` (stats.py) → `PostureResponse { generated_at: ISODate; score: number; grade: string; policy_version: number; feed_serial: number \| null; components: { id: string; label: string; weight: number; score: number; value: string; status: 'ok'\|'warn'\|'error'\|'off' }[]; findings: { severity: Severity; message: string; control_id: string \| null; link: string \| null }[] }` | dashboard-shell uses it as a page-local type on `overview.page.tsx` with a mock fallback |
| G3 | warm-up control | `GET /api/stats/warmup` → `WarmupStatus { synthetic_rows: number; oldest_ts: ISODate\|null; newest_ts: ISODate\|null; primer: { state: 'idle'\|'running'\|'done'\|'skipped'; samples: number; tests_passed: number; tests_total: number } }`; `POST` (admin) `{days?, per_day?, clear?}`; `DELETE` (admin) removes synthetic rows. Env **`AEGIS_WARMUP=auto\|off\|force`** (default `auto`) → `Settings.warmup` | `getattr(settings, "warmup", "auto")` |
| G4 | own tables need extra columns | `decisions` + `cost_avoided_usd, avoided_reason, categories_json, synthetic` (+ `ix_decisions_synth`); `audit_index` + `offset, length`. Owner-internal; no other workstream reads these tables (rule 7.1-5) | implemented in our DDL |
| G5 | usage/cost/upstream time is not linked to decisions (`observe_upstream` has no decision id or identity) | **R1 → core-gateway:** in `pipeline.complete()`, call `rt.audit.record(AuditEvent(event_type="decision", decision_id=verdict.id, request_id, session_id, actor=ctx.identity, model=outcome.model_used, usage=<priced Usage>, data={"phase":"outcome","status_code","upstream_ms","provider","model_used","error"}))`. The sink appends it to the chain and updates the decisions row | spend timeseries per bucket stays 0 for live traffic; KPI spend comes from the ledger; Prometheus cost uses observe_upstream with `team/agent=unknown` |
| G6 | per-control latency for controls that returned `None` | **R2 → core-gateway:** put the measured ms for every evaluated control in `ctx.timings["ctl.<ID>"]` (plus `ctx.timings["pipeline"]`), and call `rt.metrics.observe_overhead("request"\|"response", s)` | fall back to `verdict.decisions[].latency_ms` and the `pipeline` phase |
| G7 | HMAC fingerprints for redaction spans | **R4 → redaction-engine:** DLP-01/02/07 findings carry `meta.fp = "hmac:" + hmac_hex(canonical_value, purpose="audit")[:16]` (never for CVV/TRACK_DATA) and `excerpt` = type-aware masked preview (`mask_preview` from staging) | spans are logged without `fp` |
| G8 | audit record for the drawer | additive query param `GET /api/audit?decision_id=` | n/a |
| G9 | `ControlView.hits_24h/blocks_24h/p95_ms` (policy-engine) needs our data | add public import surface `aegis.metrics.stats.control_rollup(rt, window_s=86400) -> dict[str, dict]` to §3.3 | policy-engine may leave the fields at 0/null |
| G10 | show or hide demo history | additive `?synthetic=0\|1` on `/api/stats` and `/api/decisions` (default 1 when `demo_mode`) | n/a |
| G11 | runbook says `make audit-verify` | scaffold: Makefile alias `audit-verify` → `uv run --frozen python -m aegis verify-audit` | the command works directly |

**Requests to other owners (for their reports and integration):**
- core-gateway: R1, R2, `Settings.warmup`; step 11 passes `data={"summary": DecisionSummary, "detail": DecisionDetail-without-wire}` exactly (models or dicts both accepted); dispatch `verify-audit` to `aegis.audit.verify:main(argv)`; `/healthz` may show `components.audit` from `getattr(rt.audit, "last_verify", None)`.
- redaction-engine: R4.
- policy-engine: optional use of `control_rollup`.
- dashboard-shell: posture tile (G2); cost-avoided tooltip "blocks · downgrades · loop kills · blocked spend"; optional "demo history" toggle (G10).
- dashboard-security: Audit page uses `/api/audit`, `/api/audit/verify`, and `/api/audit/export?format=` (admin; uses `api.download`); the drawer uses `GET /api/audit?decision_id=` to show `prev_hash`/`hash`.
- demo-mocks-docs: preflight checks `/api/audit/verify` `ok` and `/api/stats/warmup` `synthetic_rows > 0`; README notes that history before startup is flagged synthetic.
- scaffold: CONTRACTS addenda G2, G3, G4, G8, G9, G10, G11.

### 4.4 Snippet `config/snippets/audit-metrics.yaml`
```yaml
# audit-metrics has no controls. It reads only:
defaults:
  audit_content: false   # true = keep data.content in audit records (never recommended); raw values are still scrubbed
# Owners: write audit events (rt.audit.record) for approvals/policy/feed changes; the matching
# aegis_approvals_total / aegis_policy_reloads_total / aegis_feed_reloads_total counters are derived from them.
```

---

## 5. Tasks

Ordered so the work degrades gracefully. Must ≈ 120 min, should ≈ 50 min, could ≈ 35 min. Develop with `AEGIS_SEMANTIC=off AEGIS_TEST_MODE=1`. Never bind fixed ports in tests.

### AUD-01 · Interfaces-first skeleton — must · demo_critical: yes · 7 min · deps: CONTRACTS §3.2/§3.3/§1.3
- [ ] `audit/log.py:create(rt)` returning `AuditService` with exact protocol signatures; `record()` returns the event unchanged at first; `verify()` returns `ok=False, message="not initialised"`.
- [ ] `metrics/prom.py:create(rt)` returning `MetricsService` with every `MetricsSink` method as a no-op; `render()` returns an empty exposition.
- [ ] Route modules `audit.py`, `decisions.py`, `stats.py`, `metrics.py` with a module-level `router: APIRouter` (absolute paths) returning correctly shaped empty payloads (`Page` `{items: [], next_cursor: null}`, a zero-filled `StatsResponse`, etc.).
- [ ] `audit/verify.py:main(argv) -> int`; `metrics/warmup.py:main(argv) -> int`; `config/snippets/audit-metrics.yaml`.
- [ ] No import-time side effects (no I/O, no threads, no registry creation at import).

### AUD-02 · Hash-chained JSONL writer — must · yes · 15 min · deps: AUD-01, §6.2
- [ ] `chain.py`: `GENESIS`, `canonical_json`, `chain_hash(prev, d)`, `ChainWriter(audit_dir)` with UTC-daily file selection, append, atomic HEAD.json, `flock` on `.lock`, resume (HEAD + tail; partial-line repair; HEAD-ahead detection).
- [ ] `AuditService.start()`: dirs, lock, resume, writer connection, DDL (AUD-04); `stop()`: flush + fsync, release lock.
- [ ] `record()`: dump → (AUD-03 enrich/scrub) → lock → seq/prev/hash → `to_thread(persist)` → update head → return `event.model_copy(update={seq, prev_hash, hash})`. **Never raises.** Increments `aegis_audit_records_total{event_type}` and `aegis_audit_errors_total`.
- [ ] Non-test mode: after start, record a `system` event (`audit.started` or `audit.resumed`, with seq).
- Acceptance: 100 records produce contiguous seq 1..100 and each hash re-derives from the line; after a restart the chain continues seamlessly.

### AUD-03 · Privacy guard at write time — must · yes · 7 min · deps: AUD-02, §7.1-8
- [ ] `privacy.scrub_event(d, redactor) -> int` (rules in §2.3, Null-redactor fallback set, key drops, `audit_content` handling), with `data.privacy` stamped.
- [ ] Runs inside the `to_thread` prepare step, before hashing.
- Acceptance: a deliberately leaky event (raw PESEL in `data.summary.preview`, an AWS key in `reason`) is stored with `[REDACTED:PESEL]`/`[REDACTED:AWS_KEY]`, and `data.privacy.scrubbed == 2`.

### AUD-04 · SQLite index and decisions projection — must · yes · 12 min · deps: AUD-02, §6.1, G4
- [ ] `index.py` DDL (§6.1 verbatim + G4 columns, `CREATE … IF NOT EXISTS`).
- [ ] `insert_audit_index(conn, d, file, line, offset, length)`; `upsert_decision(conn, summary, detail, seq, hash, categories)` with summary-from-event fallback; `annotate(conn, id, **cols)`; outcome-phase update (R1 shape: cost_usd/tokens/upstream_ms, and `json_set` on summary_json).
- [ ] In-memory LRU (500) of details.
- [ ] Background index rebuild when `audit_index` is empty but files exist.
- Acceptance: one decision event produces one `audit_index` row and one `decisions` row whose `detail_json.audit_seq/audit_hash` match the line.

### AUD-05 · Tamper verification: function, CLI, API — must · yes · 8 min · deps: AUD-02
- [ ] `verify_dir()` (seq, prev_hash, hash, parse, HEAD check), `AuditService.verify()` (+ index drift, cached `last_verify`, `aegis_audit_chain_ok` gauge).
- [ ] `main(argv)`: `--data-dir`, `--json`; human output `chain OK (N records, F files, head xxxx…xxxx)` or `chain BROKEN at seq K (file:line): reason`, exit 0/1.
- [ ] `GET /api/audit/verify`.
- Acceptance: AUD-V03 passes (byte flip, deleted line, reordered lines and tail truncation are each detected with the right `broken_at_seq` or a HEAD message).

### AUD-06 · Audit and decisions read APIs — must · yes · 12 min · deps: AUD-04
- [ ] `GET /api/decisions` (all §5.4 filters + `q`, `synthetic`, limit ≤ 1000, b64 cursor `ts|id`, `control_id` via `primary OR EXISTS json_each(summary_json,'$.controls')`).
- [ ] `GET /api/decisions/{id}`: detail_json or LRU, `wire = rt.pipeline.wire(id)` (try/except → null), 404 `api_error(404, "not_found", …)`.
- [ ] `AuditService.query()` + `GET /api/audit` (`event_type` with trailing `*`, `since` ISO or `15m/1h/24h/7d`, `decision_id`, seq cursor; records read by offset; `AuditEvent.model_validate` then `model_dump(mode="json", by_alias=True)`).
- Acceptance: AUD-V04 shape checks; paging returns no duplicates or gaps.

### AUD-07 · Prometheus metrics, perf tracker, `/metrics`, `/api/perf` — must · yes · 16 min · deps: AUD-01, §6.4, G6
- [ ] Private `CollectorRegistry`; all §2.6 families with exact names, labels and buckets; label guard; generic `inc`/`set_gauge` (derived-name suppression).
- [ ] `observe_verdict`: requests, decisions, control durations (`ctx.timings["ctl.*"]` else decision latency), redactions, signature hits, loop detections, `phase="pipeline"` overhead, PerfTracker feed.
- [ ] `observe_upstream`: duration, tokens, cost fallback. `observe_overhead`: histogram + reservoir.
- [ ] Audit-event-derived counters (approval.*, policy.*, feed.*) hooked from `AuditService.record` after a successful persist.
- [ ] `refresh_gauges(rt)` + `GET /metrics` (`Response(content, media_type=content_type)`).
- [ ] `perf.py` Reservoir/PerfTracker + `build_perf_response(rt)` + `GET /api/perf` (bench.json mtime cache).
- Acceptance: AUD-V05/V07.

### AUD-08 · Stats aggregation, `/api/stats` and the SSE `stats` ticker — must · yes · 18 min · deps: AUD-04, AUD-07
- [ ] `stats.py` window/bucket math, SQL aggregations (§2.8), KPI assembly with ledger/approvals pulls (each wrapped, 300 ms timeout), 2 s cache, `synthetic` filter, `control_rollup()`.
- [ ] `GET /api/stats` (400 on a bad window).
- [ ] `build_stats_tick()` from memory + stats route `on_startup` ticker task (skipped when `test_mode`), cancelled in `on_shutdown`.
- Acceptance: AUD-V06 (bucket counts 60/96/56, exact key set) and AUD-V08 (`event: stats` within 3 s).

### AUD-09 · Demo warm-up: synthetic history backfill — must · yes · 12 min · deps: AUD-04, AUD-08, G3, G10
- [ ] `warmup.backfill()` (scenario table §2.13, seeded RNG, diurnal curve, backdated ids, `DecisionSummary`-validated rows, single transaction in `to_thread`).
- [ ] Auto trigger in stats `on_startup` (demo mode, not test mode, `warmup != off`, no synthetic rows; `force` → clear + refill); `system` audit event + bus `system` info.
- [ ] `GET/POST/DELETE /api/stats/warmup` (POST/DELETE admin). CLI `main()` (SQLite only, cast/pricing fallbacks, `--clear`).
- Acceptance: AUD-V10 (a fresh `data/` gives ≥ 80% non-empty 24h buckets; `?synthetic=0` shows only real rows; the chain doesn't contain synthetic ids).

### AUD-10 · Exports JSONL / CSV / OCSF — must · yes · 13 min · deps: AUD-02, AUD-05
- [ ] `export.py` streaming generators + filters (`from` via `Query(alias="from")`).
- [ ] `ocsf.py` mapping (§2.11).
- [ ] `GET /api/audit/export` with `require_role("admin")`, `StreamingResponse`, Content-Disposition and the `X-Aegis-Audit-*` headers.
- Acceptance: AUD-V09 (jsonl lines re-verify individually; csv parses with the expected header and an injection guard; ocsf line 1 has `class_uid` 2004 for a block and 6003 for an allow; a member gets 403).

### AUD-11 · Redaction spans with HMAC fingerprints — should · yes · 8 min · deps: AUD-03, G7
- [ ] `privacy.redaction_spans(redactions, findings)` (r_start/r_end math, op from placeholder `[REDACTED:` → drop/irreversible, fp/preview lift, CVV/TRACK fp+preview removal) into `data.redaction_spans`.
- Acceptance: a PESEL + PAN + CVV decision has span entries with `fp` like `hmac:[0-9a-f]{16}` on PESEL/PAN, none on CVV, and no raw digits anywhere in the line (AUD-V04b).

### AUD-12 · Cost-avoided estimator — should · yes · 8 min · deps: AUD-07
- [ ] `cost.estimate_avoided()` (§2.9) with the fallback price table; called in `observe_verdict` → `aegis_cost_avoided_usd_total{reason}` + `rt.audit.annotate(...)`; reused by the backfill.
- Acceptance: a blocked `claude-sonnet-*` request with 2000 est. input tokens and max_tokens 1024 gives about $0.0214 avoided (3·2000/1e6 + 15·1024/1e6); a `$5000.01` spend block gives `spend_blocked` 5000.01.

### AUD-13 · OTel GenAI attributes — should · no · 6 min · deps: AUD-02
- [ ] `otel.genai_attributes()` (§2.10) into `data.otel` for decision and outcome records; reused by OCSF `unmapped.otel`.
- Acceptance: a model_call record has `gen_ai.operation.name=chat`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.conversation.id`; there are no `gen_ai.input.messages`.

### AUD-14 · Posture score endpoint — should · yes · 8 min · deps: AUD-05, AUD-08, G2
- [ ] `stats.posture(rt)` (§2.12) + `GET /api/stats/posture`.
- Acceptance: with the golden policy, all components are present and `score` is in 0–100; disabling DLP-02 (patch the snapshot in tests) lowers the score and adds a high finding naming DLP-02.

### AUD-15 · Live primer (real per-control latency + self-test pass rate) — should · yes · 10 min · deps: AUD-07, AUD-14
- [ ] `warmup.prime(rt, passes=2)` (§2.13): dry-run evaluations of the inline tests, timings into PerfTracker + histogram, pass/fail cache, `WarmupStatus.primer`.
- [ ] Scheduled from stats `on_startup` (3 s after start, not in test mode, `warmup != off`), and re-run on `policy.applied` bus events (debounced 2 s).
- Acceptance: right after start, `/api/perf` `by_control` has ≥ 10 controls with `count > 0` before any live traffic; `/api/stats/posture` `selftests` shows `passed/total`.

### AUD-16 · Operational polish: tamper demo, audited export, startup verify, system events — should · yes · 10 min · deps: AUD-05, AUD-10
- [ ] `--tamper-demo` CLI flag (temp copy, flip one byte, verify the copy, print both).
- [ ] Startup background verify + 5-min re-verify (not in test mode); `system` bus event on broken/lock-busy/write-error (rate-limited).
- [ ] Export audited (`system`, `kind: audit.export`); `X-Aegis-Audit-Verified` header.
- Acceptance: AUD-V03b; the Audit page badge flips to "broken" after manual tampering of the real file (manual test on a scratch `AEGIS_DATA_DIR` only).

### AUD-17 · Signed checkpoints — could · no · 12 min · deps: AUD-02, AUD-05
- [ ] Every 100 records and on `stop()`, append `{seq, hash, ts, key_id, sig}` to `data/audit/checkpoints.jsonl`, where `sig` = ed25519 (PyNaCl) over `"<seq>:<hash>"` and the key is at `data/keys/audit-ed25519.key` (generated once). `verify` checks the latest checkpoint signature and that its hash matches the chain at that seq (this detects a full re-hash rewrite without the key).
- Acceptance: re-hashing the whole chain after an edit still fails verify with "checkpoint mismatch at seq 100".

### AUD-18 · OTLP/JSON trace export — could · no · 10 min · deps: AUD-13
- [ ] `GET /api/audit/export?format=otlp` (route-level extension; protocol `export()` untouched): a single OTLP JSON `resourceSpans` document, one CLIENT span per decision named `{gen_ai.operation.name} {gen_ai.request.model}` (or `execute_tool {tool}`), with attributes from `data.otel`, `traceId` from `trace_id` or `sha256(request_id)[:32]`, and status ERROR on block.
- Acceptance: valid JSON whose `resourceSpans[0].scopeSpans[0].spans` length equals the decision records in range.

### AUD-19 · OTel-standard metric names in Prometheus — could · no · 5 min · deps: AUD-07
- [ ] `gen_ai_client_token_usage` histogram {gen_ai_operation_name, gen_ai_provider_name, gen_ai_token_type, gen_ai_request_model} and `gen_ai_client_operation_duration_seconds` {…, error_type} fed from `observe_upstream`. These are additive to the §6.4 metrics.

### AUD-20 · Writer batching / hot-path hardening — could · no · 8 min · deps: AUD-02 · only if AUD-V12 fails
- [ ] Assign seq/hash in-loop under the lock, push lines into a queue drained every 25 ms or 100 items by one `to_thread` batch (file write + `executemany`); `record()` returns immediately; `stop()` drains. Test mode stays synchronous.

### Verification tasks

| ID | Proves | How (commands from repo root) | Expected |
|---|---|---|---|
| **AUD-V01** | imports, lint | `uv run --frozen python -c "import aegis.audit.log, aegis.audit.verify, aegis.audit.export, aegis.metrics.prom, aegis.metrics.stats, aegis.metrics.warmup, aegis.api.routes.audit, aegis.api.routes.decisions, aegis.api.routes.stats, aegis.api.routes.metrics"` · `uv run --frozen ruff check src/aegis/audit src/aegis/metrics src/aegis/api/routes/{audit,decisions,stats,metrics}.py tests/unit/audit_metrics` · `uv run --frozen ruff format --check <same>` | exit 0, no output from import |
| **AUD-V02** | unit suite | `AEGIS_SEMANTIC=off AEGIS_TEST_MODE=1 uv run --frozen pytest tests/unit/audit_metrics -q` | all pass, < 10 s. `conftest.py` provides a `FakeRT` (tmp `data_dir`, real `AuditService`/`MetricsService`, stub redactor/ledger/approvals/feed/semantic/policy/pipeline) and uses root fixtures `rt`/`client` when present |
| **AUD-V03** | tamper evidence (`test_chain.py`) | record 50 events; flip one byte in line 20 → `broken_at_seq == 20`; delete line 30 → 30; swap lines 10/11 → 10; truncate the last 5 → `ok=False`, "HEAD ahead"; injected clock across UTC midnight → 2 files, ok; restart a new service on the same dir → seq continues, ok | as stated |
| **AUD-V03b** | CLI demo | `uv run --frozen python -m aegis verify-audit` then `uv run --frozen python -m aegis.audit.verify --tamper-demo` | `chain OK (N records, …)`; then `tampered copy: chain BROKEN at seq K …` and `original: chain OK`, exit 0 |
| **AUD-V04** | API shapes and privacy (`test_index_api.py`, `test_privacy.py`) | in-process ASGI: write a decision with PESEL `44051401359`, AWS-shaped key (generated at runtime), PAN `4111111111111111`, CVV; `GET /api/decisions`, `/api/decisions/{id}`, `/api/audit?decision_id=` | shapes match §5.5 key sets; `audit_seq`/`audit_hash` set; **raw values absent from `data/audit/*.jsonl` bytes and from every SQLite text column** (scan `decisions`, `audit_index`) |
| **AUD-V04b** | fingerprints (AUD-11) | same test with findings carrying `meta.fp` | `fp` present on PESEL/PAN spans, absent on CVV; `r_start/r_end` index the placeholder in the redacted text |
| **AUD-V05** | `/metrics` | unit: render after 3 verdicts; live: `curl -s 127.0.0.1:8787/metrics \| grep -E '^aegis_(requests_total\|decisions_total\|gateway_overhead_seconds_bucket\|policy_version)'` | series present; overhead histogram has `le="0.0002"`; no label value starts with `ses_`/`req_` |
| **AUD-V06** | `/api/stats` | unit with backfilled rows: windows `1h/24h/7d` | `len(timeseries)` = 60/96/56; key set equals `StatsResponse`/`StatsKpis`/`StatsBucket`; `by_destination` has 3 entries; bad window → 400 envelope |
| **AUD-V07** | `/api/perf` | unit after 20 verdicts + `observe_upstream`; live after primer | `overhead_ms.count > 0`, `by_control` sorted by p95 desc, `semantic.mode` present, `bench` null or object |
| **AUD-V08** | SSE ticks through core-gateway's bus | live: `curl -sN --max-time 5 'http://127.0.0.1:8787/api/events?events=stats'` | ≥ 2 `event: stats` frames whose `data` has `decisions_1m` with all 5 actions |
| **AUD-V09** | exports (`test_export.py`) | jsonl: each line `chain_hash(prev_hash, rec−hash) == hash`; csv: `csv.DictReader` header and a guarded `=cmd` cell; ocsf: block → 2004 with `finding_info.analytic.uid`, allow → 6003; live: `curl -s -H 'X-Aegis-View-As: u_katarzyna' '127.0.0.1:8787/api/audit/export?format=ocsf' \| head -1 \| python -m json.tool` and as `u_piotr` → 403 `forbidden` | as stated |
| **AUD-V10** | warm-up | fresh `AEGIS_DATA_DIR`, start gateway (demo mode) → `GET /api/stats/warmup`, `/api/stats?window=24h`, `/api/stats?window=24h&synthetic=0`; then `grep -c req_demo data/audit/*.jsonl` | `synthetic_rows > 0`; ≥ 80% of 24h buckets non-empty; synthetic=0 counts only live rows; grep = 0 |
| **AUD-V11** | dashboard integration (manual, after dashboard build) | open `/ui/`: Overview KPIs and charts populated, posture tile; Security → Audit: "chain OK (N records)", Export (OCSF) downloads; Live drawer shows `audit_seq`/hash | as stated |
| **AUD-V12** | hot-path cost | unit micro-bench (marked `bench`, skipped by default): 1000 `record()` calls of a realistic decision event on tmp dir | p95 < 1.5 ms (else do AUD-20) |
| **AUD-V13** | derived counters | record `approval.created`, `approval.decided` (approved), `policy.applied`, `feed.rejected` events | `aegis_approvals_total{outcome="requested"}` = 1, `{outcome="approved"}` = 1, `aegis_policy_reloads_total{result="ok"}` = 1, `aegis_feed_reloads_total{result=…}` = 1 |

---

## 6. Demo cut

**Must really work live (never faked):**
- Hash chain over real decisions; `verify` OK via CLI and `/api/audit/verify`; `--tamper-demo` detection.
- Decisions list and detail with `audit_seq`/`audit_hash`; `/api/audit` paging.
- JSONL/CSV/OCSF export download (admin-gated), with records redacted at write time.
- `/metrics` with real counters/histograms; `/api/perf` overhead and per-control p50/p95 from **real measurements** (live traffic and dry-run primer of the policy's own tests).
- `/api/stats` KPIs and timeseries including live traffic; SSE `stats` ticks.

**May be simulated or stubbed, as long as it's labelled:**
- History before the gateway started: the synthetic backfill. It is flagged `synthetic=1`, uses a `[demo]` preview prefix, is excluded from the chain and announced by a `system` audit event. Toggle with `?synthetic=0`.
- Spend per bucket for live traffic if R1 is missing (KPI spend still real from the ledger).
- `fp` on spans if R4 is missing (spans are still logged).
- Posture "self-tests" component if the primer is off (component excluded).
- OTLP export, signed checkpoints, OTel-named metrics (could-tier).

**Cut order if behind:** AUD-19 → AUD-18 → AUD-17 → AUD-20 → AUD-13 → AUD-16 (keep `--tamper-demo`) → AUD-14 → AUD-15. **Never cut:** AUD-02/03/05 (chain, privacy, verify), AUD-09 (charts not empty), AUD-10 OCSF.

---

## 7. Dependencies (no new packages; all in CONTRACTS §7.6)

| Package | Use | Notes |
|---|---|---|
| `fastapi` (+ starlette `StreamingResponse`) | routes | — |
| `pydantic>=2.9` | frozen models, `model_dump(mode="json", by_alias=True)` | — |
| `prometheus-client` | `CollectorRegistry`, `Counter`, `Gauge`, `Histogram`, `generate_latest`, `CONTENT_TYPE_LATEST` | private registry per service |
| `pynacl` | AUD-17 checkpoint signing (could) | guarded import |
| stdlib | `sqlite3` (JSON1 `json_each`/`json_set`, checked on 3.13.11 / SQLite 3.50.4), `hashlib`, `json`, `csv`, `fcntl`, `base64`, `statistics`, `random` | `json`, not orjson, for hashing (contract formula) |
| dev: `pytest`, `pytest-asyncio`, `httpx` (`ASGITransport`), `asgi-lifespan`, `ruff` | tests | — |

**Deps requested:** none.

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Audit write adds latency to every request (pipeline awaits `record`) | Small events; thread hop and single writer connection; no per-record fsync; AUD-V12 budget 1.5 ms p95; AUD-20 batching as a fallback |
| **Chain fork** from two writers (second gateway, CLI) | `flock` on `data/audit/.lock` (log-only degraded mode if busy); CLIs never append; warm-up CLI writes SQLite only |
| Hash non-reproducible (key order, floats, non-JSON types) | Hash exactly the dict that is serialized; verify re-parses the line; stdlib `json` canonical form per §6.2; round-trip unit test; `default=str` only after `mode="json"` |
| Raw PII/secrets reach the audit log through other owners' `data`/`reason` | Write-time scrubber with Null-redactor fallback; key drops; `data.privacy.scrubbed` counter + WARNING; AUD-V04 byte scan of JSONL and SQLite; R4 so fingerprints are produced upstream; the sink never hashes raw values |
| Synthetic history misleads judges | Flagged everywhere (`synthetic` column, `[demo]` preview, `ses_demo_*`, `req_demo*`), never in the audit chain, `system` audit event, `?synthetic=0`, `WarmupStatus`; perf numbers come only from real measurements |
| Partial dependence on core-gateway (R1/R2) and redaction-engine (R4) | Every feature has a fallback (§4.3 interim column); verified independently with `FakeRT` |
| SQLite contention (WAL, many owners) | `busy_timeout=5000`; reads use separate `rt.db()` connections in `to_thread`; 2 s stats cache; indexes on `ts`, `action`, `control_id`, `agent_id`, `synthetic` |
| Prometheus duplicate registration across app instances in tests | Per-service `CollectorRegistry`, never the global default |
| Label cardinality explosion | Label guard (id-prefix and length rules, 500 label-set cap → `other`); budget gauge limited to org/team/member/agent scopes |
| Timezone or bucket drift between SQL and Python | Single `iso_z()` formatter (UTC, ms, `Z`); buckets computed from epoch seconds on both sides; tests pin `now` |
| OCSF enum ids wrong (offline venue) | Mapping isolated in `ocsf.py`; caption strings included; structural tests; check against schema.ocsf.io when online |
| Memory (8 GB machine) | Reservoirs bounded (< 2 MB); LRU of 500 details; backfill about 6k rows (about 10 MB SQLite); streaming exports, no full-file reads |
| Startup work slows the demo boot | Backfill and primer run as background tasks after `on_startup`; primer concurrency 1; skipped when `AEGIS_TEST_MODE=1` or `AEGIS_WARMUP=off` |
