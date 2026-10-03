# B07-semantic-models: status

Two agents worked on this bundle. Agent 1 built the runtime (SEM-01, SEM-02 and SEM-06 to SEM-12 code). Agent 2 finished the remaining work, fixed the memory issue, and wrote the tests and this report.

## Tasks

| ID | State | Notes |
|---|---|---|
| SEM-01 | done | `aegis.semantic.engine:create`, CONTROLS INJ-03 / CUS-01, `GET /api/semantic/status`. No import-time ORT or tokenizers. |
| SEM-02 | done | `heuristic.py` (EN+PL injection, moderation, 384-d hashed embed, judge), `shared.py` (`FALLBACK_REASONS`, `degraded_disposition`, `fallback_code`), `config.py`. |
| SEM-03 | done | CUS-01 keyword leg: 1:1 diacritic, case and homoglyph folding; whole-word; offsets into the original text; block / redact / log / require_approval; legacy `deny_terms`. |
| SEM-04 | done | INJ-03: safety and adherence legs run concurrently; latest user turn only; response mode; per-profile params; `degraded_disposition`; meta, findings and timings. |
| SEM-05 | done | `config/snippets/semantic-models.yaml`. Inline tests pass under the heuristic. Live policy aliases (`params.purpose`, `off_topic_action`) are supported. |
| SEM-06 | done | Breaker, LatencyWindow, TTLCache, SingleFlight. |
| SEM-07 | done | ONNX Horizon / MiniLM / NER with one shared XLM-R vocab and an id-equality self-check. |
| SEM-08 | done | Async Ollama client, Qwen3Guard raw prompt (byte-equal golden), A-44 scores 1.0 / 0.5 / 0.0. |
| SEM-09 | done | Engine: cache, single-flight, breaker gate, fallback codes, metrics, bus and audit events. |
| SEM-10 | done | Warm-up task, RAM plan, `status()`, `warmup()`, `stop()`. |
| SEM-11 | done | Judge: yes/no logprob, calibration 0.08 → 0.70, RAM gate. CUS-01 NL leg runs only for rules with `text` and **no** keywords. |
| SEM-12 | done (code) | Monitor loop: ps, keep-alive, half-open probe, shedding. Not exercised live. |
| SEM-13 | done | `scripts/fetch_models.sh` (`--verify` / `--onnx-only` / `--force`). Also added `src/aegis/semantic/data/{Modelfile.guard,Modelfile.judge,MODEL_LICENSES.md}`. |
| SEM-14 | done | sha256 against `models/MANIFEST.sha256` before load; a mismatch sets `integrity_error`. `models/.gitignore` now keeps `MANIFEST.sha256`. |
| SEM-15 | done | Guard escalation of the 0.50–0.80 band; PG2 vote when enabled. |
| SEM-16 | done | `POST /api/semantic/score` and `POST /api/semantic/warmup`. |
| SEM-17 | partial | Logprob `p_unsafe` parsing exists. The engine uses the discrete scores; `continuous` is off. |

## Orchestrator fix: memory safety (B09 report)

**Problem.** Tests build `Settings(...)` directly, which does not read the environment. As a result the engine ran in `auto` mode under `AEGIS_SEMANTIC=off` and started warming up models in the background inside `create_app`.

**Fix** (`SemanticConfig.from_settings`):
- The env vars `AEGIS_SEMANTIC=off` and `AEGIS_TEST_MODE=1` always win.
- Any **pytest** process defaults to `test_mode` unless `AEGIS_SEMANTIC=on|auto` is set explicitly.

In test mode or off mode no model ever loads. Calls get the heuristic with `fallback:off` or `fallback:warming`. Models load only through an explicit `warmup()`.

**Verified:** `create_app` + lifespan under both modes leaves `onnxruntime` and `tokenizers` out of `sys.modules`.

## Verification

| ID | Command | Result |
|---|---|---|
| V01 | import smoke (plan command) | PASS: `['INJ-03', 'CUS-01'] /api/semantic/status`, no ORT. |
| V02 | `AEGIS_SEMANTIC=off AEGIS_TEST_MODE=1 uv run --frozen pytest tests/unit/semantic_models -q -m "not semantic"` + `ruff check` | PASS: 119 tests, ~3 s; ruff clean. |
| V03 | `uv run --frozen pytest tests/unit/semantic_models -q -m semantic` (run one test at a time) | PASS: Horizon ≥ 0.99 (EN), PL ≥ 0.9, hard negative < 0.9; MiniLM EN↔PL > 0.8; NER `Jan Kowalski` exact offsets, vocab shared; guard bomb EN/PL Unsafe, kill-process Safe; guard unloaded afterwards. |
| V04/V05 | per-model scratch run, 1 model at a time (machine swapping, ~1.6 GB free) | MiniLM p50 7 ms; NER p50 111 ms; guard p50 491 ms / p95 860 ms (ollama 751 MB); Horizon timed out under swap (load 12.5 s). Agent 1 measured on an idle machine: horizon 13 / minilm 1.4 / ner 5.7 / guard 227 ms. **Not representative under the current 20-agent load.** |
| V06 | degraded drill (`AEGIS_OLLAMA_URL=127.0.0.1:9`) | PASS: calls 1–3 `fallback:error`, call 4 `fallback:breaker_open` (0.1 ms); exactly 1 system warning + 1 audit `breaker_open`; INJ-03 blocks the bomb prompt under `deterministic_only` (degraded) and under `closed` ("fail-closed: breaker_open"). |
| V07 | off mode | PASS: unit test plus a subprocess check (no ORT / tokenizers; every result is `fallback:off`; health `off`). |
| V08 | policy self-test with the snippet merged | NOT RUN: needs policy-engine to merge the snippet. Inline cases are verified in `test_snippet.py` (heuristic). |
| V09 | heuristic spot check | Finance + xstest (92 rows): injection FP 0, moderation FP 0. Deepset attacks TPR@0.8 = 3/50 (expected; Horizon covers these). JBB moderation 1/30. |
| V10 | in-process `create_app` (off mode) `/v1/guard` | PASS: bomb → block INJ-03 (degraded); Project Falcon → block CUS-01; kill-process → allow; `/api/semantic/status` 200; `/healthz` components semantic/ollama present. Auto mode with all models was not run (RAM). |
| V11 | `bash scripts/fetch_models.sh --verify` | PASS: MANIFEST OK (22 files), aegis-guard ✓, aegis-judge ✓, exit 0, 3 s, no downloads. |
| V12 | judge NL rule live | NOT RUN: the judge needs 1.3 GB and less than 1.9 GB was free. Covered by mocked tests. |

## Files (this round)

- **New:** `config/snippets/semantic-models.yaml`, `scripts/fetch_models.sh`, `src/aegis/semantic/data/{Modelfile.guard,Modelfile.judge,MODEL_LICENSES.md}`.
- **Tests:** `tests/unit/semantic_models/{conftest.py,semtest_helpers.py,test_*.py}`.
- **Edited:**
  - `src/aegis/semantic/config.py`: env and pytest override.
  - `src/aegis/semantic/engine.py`: a breaker change emits one toast, not two.
  - `src/aegis/controls/semantic/inj03_content_safety.py`: the org-wide fallback purpose `*` is not flagged by the heuristic, to cut log noise.
  - `models/.gitignore`.

## Demo / run

- **Status:** `curl -s localhost:8787/api/semantic/status | jq`.
- **Degraded drill:** stop Ollama (or set `AEGIS_OLLAMA_URL=http://127.0.0.1:9`). A breaker toast appears and INJ-03 still blocks with the `degraded` flag.
- **Live keyword edit:** add a term to `controls[id=CUS-01].params.rules[0].keywords`.
- **Lite profile:** `AEGIS_SEMANTIC_MODELS=horizon-small,aegis-guard` lowers RAM.

## deps_needed

None.

## contract_deviations

- **CUS-01 NL leg.** A rule with both `text` and `keywords` uses the keyword leg only, and its `text` acts as a description. This avoids loading the judge on every request with the seed policy.
- **INJ-03 org-wide purpose.** The fallback `params.purpose` (purpose_agent `*`) only flags low adherence when a real embedding model scored it.

## integration_todos

1. **policy-engine:** merge `controls:` from `config/snippets/semantic-models.yaml`. The `profiles:` block is a hint for `config/profiles/*.yaml` only; do not merge it into the PolicyDoc. The seed's INJ-03 `timeout_ms: 600` vs the snippet's 900: 900 is recommended (guard p95 under load is about 860 ms).
2. **redaction-engine (A-38):** call `getattr(rt.semantic, "ner", None)` and never load eu-pii-ner itself.
3. **core-gateway:** check that `/healthz` maps `components.semantic = status()["health"]`. It currently reports `off` in off mode, which is correct.
4. **Ollama:** `aegis-judge` (1.3 GB) was loaded in Ollama at 23:3x by another agent, not by B07 (my judge tests are mocked). I left it alone; it expires through keep_alive.
