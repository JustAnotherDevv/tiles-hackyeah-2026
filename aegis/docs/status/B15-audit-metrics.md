# B15-audit-metrics — status

Owner paths: `src/aegis/audit/`, `src/aegis/metrics/`, `src/aegis/api/routes/{audit,decisions,stats,metrics}.py`,
`config/snippets/audit-metrics.yaml`, `tests/unit/audit_metrics/`. Plan: `docs/plan/14-audit-metrics.md`.

## Tasks

| ID | State | Notes |
|---|---|---|
| AUD-01 skeleton | done | `aegis.audit.log:create`, `aegis.metrics.prom:create`, 4 routers, `aegis.audit.verify:main`, `aegis.metrics.warmup:main`, snippet |
| AUD-02 hash-chained JSONL | done | §6.2 formula exactly (stdlib `json`), daily UTC files, HEAD.json, flock (second writer → log-only), resume, torn-line repair, HEAD-ahead detection |
| AUD-03 privacy guard | done | scrubber (engine detectors + built-in AWS/PEM/tokens/PESEL/Luhn), key drops, `data.privacy`, `defaults.audit_content` |
| AUD-04 SQLite index + projection | done | §6.1 DDL + A-54 columns, upsert, outcome update (A-08), 500-entry detail LRU, index rebuild when DB wiped |
| AUD-05 verify | done | `verify_dir`, `AuditService.verify` (cached `last_verify`, `aegis_audit_chain_ok`), CLI, `GET /api/audit/verify` |
| AUD-06 read APIs | done | `/api/decisions` (all filters, `q`, `synthetic`, b64 cursor), `/api/decisions/{id}` (+wire, audit_seq/hash), `/api/audit` (+`decision_id`, **`seq_from`** A-54, `event_type` with `*`) |
| AUD-07 Prometheus + perf | done | all §6.4 + A-50 names, private registry, label guard + 500 cap, auto-registration, derived counters from audit events, `/metrics`, `/api/perf` (bench from `AEGIS_REPORTS_DIR`) |
| AUD-08 stats + SSE | done | `/api/stats` (frozen shape, 60/96/56 buckets, `kpis.cost_avoided_usd` populated), 2 s cache, SSE `stats` ticker every 2 s (not in test mode), `control_rollup()` |
| AUD-09 warm-up | done | flagged synthetic history (SQLite only, never in chain), auto/force/off, top-up on restart, `GET/POST/DELETE /api/stats/warmup`, CLI |
| AUD-10 exports | done | jsonl (byte-identical, re-verifiable), csv (injection guard), OCSF 1.9.0 (2004/6003), admin-only, export itself audited and included, `X-Aegis-Audit-*` headers |
| AUD-11 spans + fp | done | `data.redaction_spans` with r_start/r_end, lifted `meta.fp`/excerpt, CVV/TRACK never fp/preview |
| AUD-12 cost avoided | done | block / spend_blocked / downgrade / budget / loop; fallback price table; annotates decision row |
| AUD-13 OTel attrs | done | `data.otel` (semconv 1.41 names, no content attributes) |
| AUD-14 posture | done | `GET /api/stats/posture` (A-51), prefers `rt.policy.last_selftest()`, else primer |
| AUD-15 primer | done | dry-run of inline policy tests → real per-control latencies + pass rate; re-run on `policy.applied` |
| AUD-16 polish | done | `--tamper-demo`, startup + 5-min verify, audited export, rate-limited `system` bus events |
| A-53 `/api/selftest*` | done (this session) | `GET /api/selftest`, `GET /api/selftest/report`, `POST /api/selftest/run` (admin, single-flight, 202, bus `system` on finish) |
| A-10 elision | done (this session) | `Mutation.value` > 512 chars → `{"$elided", sha256, len}` in persisted detail |
| AUD-20 batching | done (lite, this session) | chain append inline, SQLite projection batched every 20 ms in a worker thread (sync in test mode), HEAD.json deferred ≤ 250 ms / 100 records (always flushed on verify/stop) |
| AUD-17 signed checkpoints | not started | could |
| AUD-18 OTLP export | not started | could |
| AUD-19 `gen_ai_*` metrics | skipped | could; conflicts with A-50 ("prefix is always `aegis_`") |

## Verification

| ID | Command | Result |
|---|---|---|
| V01 | `uv run --frozen python -c "import aegis.audit.log, …routes.metrics"`; `ruff check` + `ruff format --check` on owned paths | pass |
| V02 | `AEGIS_SEMANTIC=off AEGIS_TEST_MODE=1 uv run --frozen pytest tests/unit/audit_metrics -q` | **39 passed, 1 skipped (bench)**, ~2 s |
| V03 | `test_chain.py` (byte flip→20, delete→30, swap→10, truncate→HEAD ahead, UTC midnight 2 files, restart, torn line, 2nd writer log-only) | pass |
| V03b | `uv run --frozen python -m aegis verify-audit` → `chain OK (93 records, 1 files, head c7d7…0b5a)`; `python -m aegis.audit.verify --tamper-demo` → `tampered copy: chain BROKEN at seq 47 …` / `original: chain OK` | pass (exit 0) |
| V04/V04b | `test_privacy.py`, `test_index_api.py` (byte scan of JSONL + every SQLite text column; fp on PESEL/PAN, none on CVV; r_start/r_end; key sets = frozen types) | pass |
| V05/V07/V13 | `test_metrics_perf.py` | pass |
| V06/V10 | `test_stats_warmup.py` (60/96/56 buckets, ≥80% non-empty 24h, `synthetic=0`, no `req_demo` in chain) | pass |
| V08 | in-process ticker test (`test_sse_stats_ticker_publishes`); live curl not run (no servers per orchestrator) | partial |
| V09 | `test_export.py` (jsonl re-verify, csv guard, OCSF 2004/6003, member 403) | pass |
| V11 | dashboard manual check | not run (needs UI build + live stack) |
| V12 | `pytest tests/unit/audit_metrics -m bench -s` | p50 0.27–0.40 ms (was 1.55 ms); p95 1.4–3.3 ms, depending on load from the ~20 agents running at the same time. Target 1.5 ms is met only when the machine is quiet. |
| smoke | in-process `create_app()` + LifespanManager: all routes 200, real pipeline PESEL → `redact DLP-01`, decision row `audit_seq=2`, `/api/perf` 14 controls, verify OK, member export 403, no raw PESEL in JSONL | pass |

## How to run / demo
- `uv run --frozen python -m aegis verify-audit` (or `make audit-verify`) → `chain OK (N records …)`; add `--tamper-demo` for the tamper scene (works on a temp copy).
- `uv run --frozen python -m aegis.metrics.warmup --days 7 [--clear] [--data-dir D]` (SQLite only).
- API: `/api/stats?window=1h|24h|7d[&synthetic=0]`, `/api/perf`, `/api/stats/posture`, `/api/stats/warmup`, `/api/decisions[/{id}]`, `/api/audit[?decision_id=|seq_from=]`, `/api/audit/verify`, `/api/audit/export?format=jsonl|csv|ocsf` (admin), `/metrics`, `/api/selftest[/report|/run]`.
- `/api/stats` is safe for the HarmonyOS widget: no viewer needed, frozen `StatsResponse` shape, `kpis.cost_avoided_usd` always a number (synthetic history + live blocks/downgrades).

## deps_needed
none.

## contract_deviations
- HEAD.json is written lazily (at most 250 ms / 100 records behind, always flushed before verify and on stop) for hot-path latency. A lagging HEAD never fails verify; only a HEAD *ahead* of the log does (tail truncation). Truncating records written in the last ≤250 ms before a crash is therefore not detectable via HEAD.
- SQLite projection (`decisions`/`audit_index`) lags the chain by ≤ ~20 ms in production (sync in test mode). `GET /api/decisions/{id}` uses the in-memory LRU, so a just-written decision is never missing.
- Warm-up curve: weekend factor 0.6 and night weight 0.6 (plan said ×0.3 / 0.35). The demo runs on a weekend and the last-24h chart would otherwise be about 40% empty. Rows are still flagged synthetic.
- `seq_from` on `/api/audit` = page starts at that seq, newest first (`seq <= seq_from`).
- `GET /api/stats/warmup` adds an extra `mode` field; POST adds `inserted`, DELETE adds `removed` (additive).

## integration_todos
- dashboard-security: Audit page can deep-link with `/api/audit?seq_from=N`; export headers `X-Aegis-Audit-Head/Records/Verified`. The export now includes its own `audit.export` record as the last line.
- dashboard-shell: posture tile from `/api/stats/posture`; "includes demo history" badge when `/api/stats/warmup` `synthetic_rows > 0`.
- policy-engine (optional): `aegis.metrics.stats.control_rollup(rt)` for `ControlView.hits_24h/blocks_24h/p95_ms`.
- integrator: live checks V05/V08/V10/V11 against a running gateway (`curl -s 127.0.0.1:8787/metrics | grep aegis_gateway_overhead_seconds_bucket`; `curl -sN --max-time 5 '127.0.0.1:8787/api/events?events=stats'`).
- redaction-engine: R4 `Finding.meta.fp` (A-42) so spans carry fingerprints. Spans are logged without `fp` until then.
