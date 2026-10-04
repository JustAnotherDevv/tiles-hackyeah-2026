# B24-redteam-eval-perf — status

Red-team corpora, eval harness (Wilson CIs, heatmap, DLP leak leg) and load bench → `reports/`.
Everything runs against the **real** pipeline/gateway; no number is ever fabricated (failures write
`status: unavailable|partial|skipped` with the reason). Developed with `AEGIS_SEMANTIC=off`; **no ML
models were loaded** (semantic stages are implemented but left for the integrator's final run).

## Tasks
| ID | State | Notes |
|---|---|---|
| EVAL-01 | done | corpora ported byte-identical into `tests/corpora/` (1,194 rows, 684/510), licences, `MANIFEST.json` (sha256, counts, licence, `seen_by_tuning`, `pii_dropped`), `loader.py`, `obfuscate.py` (reproduces the 253-row matrix byte-identically), `tools/{build_public,port_pii,verify}.py`, runtime `secrets_gen.py`. PII port dropped 24 secret-shaped rows (adversarial 2, hard_negatives 4, holdout 18); `secrets_code.jsonl` not copied |
| EVAL-02 | done | `overlays/invocations.yaml` (43 rows: 22 tool.input, 8 mcp.call, 9 mcp.list, 4 model.response) + `tests/eval/adapter.py` (frozen types only; guard body uses A-12 string destination + `meta.raw_result`) |
| EVAL-03 | done | `overlay.py` (validated with frozen `PolicyDoc`; rate/loops/limits relaxed, kill switch off, mock providers → echo upstream, `mock-slow-*` route for the 800 ms share) + `harness.py` (temp policy/data dir, env, `lifespan_context`, `switch_profile` via `apply_yaml`, fresh-boot fallback when the self-test gate rejects a profile, semantic preflight ≥ 2 GB + model dir) |
| EVAL-04 | done | `runner.py` (in-process dry-run, semaphore, 10 s timeout, exceptions → `error`; HTTP guard dry-run), `scoring.py` (§2.6), `metrics.py` (Wilson, percentiles, all breakdowns, held-out vs tuning, masked misses/FPs, stratified sampling), `cli.py` |
| EVAL-05 | done | `heatmap.py` (`aegis.heatmap/1`, primary + variants, benign twins, row/col rates + CI), `report.py` (eval.json/heatmap.json/eval.md, rich console + ASCII heatmap, atomic merge into bench.json + headline keys) |
| EVAL-06 | done | `tests/bench/` upstream (port 0 thread), targets (Spawn/Inproc/Live), mix (80/15/5), loadgen, servertiming, profiles, report; `scripts/bench.py` |
| EVAL-07 | done | entry points + 44 unit tests in `tests/unit/redteam_eval_perf/` |
| EVAL-08 | done | `openai-det-c1` vs `direct-c1`, `openai-det-800ms-c1` (share source) + `-c16`; `overhead_share` |
| EVAL-09 | implemented, not run | `--semantic auto|on` (balanced+strict, stratified 200, 150 s budget, `semantic_status`, degraded label). Not executed: models must not be loaded now |
| EVAL-10 | done | `dlp.py` leak leg per profile (verbatim / normalized / ≥6-digit subsequence on post-redaction segments), per entity/lang/file, hard-negative over-block; embeds `reports/dlp-metrics.json` if present |
| EVAL-11 | done | `micro.py` (34 controls), `reload.py` (`apply_ms` in-process, `file_to_active_ms` on the spawned gateway with the watcher on) |
| EVAL-12 | done | `html.py` (dark, self-contained eval.html with inline-SVG heatmap, bench.html), `deck.py` → `deck_numbers.{json,md}`, `schemas/*.schema.json`, `--write-samples` → `tests/eval/samples/*.sample.json` (from a real run, `"sample": true`) |
| EVAL-13 | done | `--target http://127.0.0.1:8787` (guard dry-run, profile/policy_version from the live gateway) |
| EVAL-14 | partial | `--sizes` (0.5/2/8/32 KB) + model/streaming snapshots (labelled, provenance kept) merged; streaming TTFT profile not done |
| EVAL-15, EVAL-16 | not started | (could) `make redteam` prints the Makefile TODO |

## Verification
| ID | Command | Result |
|---|---|---|
| V01 | `uv run --frozen python -m tests.corpora.tools.verify` | PASS: 1194 (684/510), 506 PII rows / 783 gold entities, sha256 OK, 0 secret hits |
| V02 | `uv run --frozen pytest tests/unit/redteam_eval_perf -q -m "not slow"` | PASS 42 tests, ~3 s (+2 `slow` smoke tests PASS, ~4 s) |
| V03 | `python3 tests/corpora/obfuscate.py --out $TMP/x.jsonl && cmp …` | IDENTICAL |
| V04 | `time uv run --frozen python -m tests.eval --quick` | PASS 5.8 s wall (48 s while ~20 agents loaded the machine), 0 errors, schema-valid |
| V05 | `uv run --frozen python -m tests.eval --semantic off` | PASS 16 s, 4 deterministic runs, by_lang en/pl/de with CIs. Monotonic but flat: strict = paranoid = balanced 66.7 % ≥ permissive 64.4 % (see todos). Semantic stage not run (no models now) |
| V06 | `scripts/bench.py --quick --modes deterministic` / full `--modes deterministic` | PASS 14 s / 50 s; guard-det-*, by_control 34 rows, headline filled; semantic `skipped: not requested` |
| V07 | dashboard wiring | NOT RUN (needs the integrated stack); `reports/bench.json` = `aegis.bench/1`, `eval`/`heatmap`/`dlp` present |
| V08 | shasum policy.yaml/golden before/after eval + bench; `pgrep -f port-file` | PASS: hashes unchanged (5248f9ab…), no leftover spawned gateway |
| V09 | `test_runner_fake.py` (raising pipeline + AEGIS-CORE fail-closed) | PASS: errors counted, 0 detections, FPR unchanged |
| V10 | `cat reports/deck_numbers.md` | PASS: every row has source_file + json_path; unmeasured rows say "not measured" |
| V11 | live re-eval vs `:8787` | PARTIAL: live guard dry-run eval works (`--subsets generated`, 4.8 s); the policy-edit half not run (would edit the shared config/policy.yaml) |
| V12 | `/usr/bin/time -l` | quick bench peak RSS 239 MB, quick eval 177 MB; spawned det gateway RSS 183 MB |

## Measured so far (deterministic, loaded 8 GB M2, Sat→Sun night; integrator re-runs on the final build)
eval balanced: attack 66.7 % [63.2–70.0] (held-out 39.2 %, tuning 94.2 %), FPR 1.6 % [0.8–3.1]; obfuscation heatmap 226/226; DLP leak 11.2 % balanced / 8.5 % strict / 0.12 % paranoid.
bench (spawn): guard c1 overhead p50 2.7 / p95 5.3 ms, 200 rps at c16, proxy adds 9.6 ms of an 800 ms upstream (1.18 %), apply_yaml p95 197 ms, file→active p95 412 ms.

## Files
`tests/corpora/**` (data, LICENSES, README, MANIFEST.json, loader, obfuscate, secrets_gen, overlays/, tools/),
`tests/eval/{__init__,__main__,cli,common,adapter,overlay,harness,runner,scoring,metrics,heatmap,dlp,report,html,deck}.py`, `tests/eval/schemas/`, `tests/eval/samples/`,
`tests/bench/{__init__,cli,upstream,targets,mix,loadgen,servertiming,profiles,micro,reload,report}.py`, `tests/bench/data/*.snapshot.json`,
`scripts/bench.py`, `config/snippets/redteam-eval-perf.yaml` (comment only), `tests/unit/redteam_eval_perf/*`.
Generated (real runs): `reports/{eval.json,heatmap.json,eval.md,eval.html,bench.json,bench.md,bench.html,deck_numbers.json,deck_numbers.md}`.

## How to run / demo
- On stage: `make eval ARGS=--quick` (~6 s: profile table with CIs + ASCII heatmap).
- `make eval` = `uv run --frozen python -m tests.eval` (det × 4 profiles + DLP leg, then semantic auto on balanced+strict if ≥ 2 GB free and models present; ≤ 4 min).
- `make bench` = `uv run --frozen python scripts/bench.py` (spawned gateway on an ephemeral port; det then semantic; ~2–3 min). `--quick`, `--modes deterministic`, `--target inproc|URL`, `--sizes`.
- Live: `uv run --frozen python -m tests.eval --target http://127.0.0.1:8787 --quick --subsets generated`.
- Dashboard mocks: `tests/eval/samples/{bench,eval,heatmap}.sample.json`.

## deps_needed
none (pandas/pyarrow only ephemerally for `tools/build_public.py`).

## contract_deviations
- PII port also drops `AKIAIOSFODNN7EXAMPLE` and extra scanner shapes (sk-ant-, github_pat_, AIza, glpat-, npm_) — stricter than plan §2.3.
- MCP tool-description rows use the seeded `web` server (not `evalsrv`) so MCP-01 "unknown server" never decides.
- `--quick` also skips the DLP leg (`--dlp` re-enables) to stay ≤ 20 s.
- Overhead share uses the c=1 800 ms profile (c=16 kept as a separate profile).

## integration_todos
1. **Final runs (Sun ~06:00, quiet machine, models present):** `make eval && make bench` (Makefile lines already correct: `eval: $(PY) -m tests.eval $(ARGS)`, `bench: $(PY) scripts/bench.py $(ARGS)`). Then `uv run --frozen python -m tests.eval --write-samples` is optional. Check `reports/deck_numbers.md` before pasting into the deck.
2. **B06 injection-defense bug:** `src/aegis/injection/canary.py:53` `extract_urls` → `IndexError: no such group` (m.span(1)); INJ-04 logs "internal error (degraded allow)" on model.response rows.
3. **redaction-engine / metadata-egress:** in the DLP leg (balanced, model.request → remote) IP_ADDRESS 0/34 and MAC_ADDRESS 0/10 gold values left unredacted; PERSON 67/115 without NER (deterministic). See `reports/eval.json` → `dlp.runs[*].by_entity`.
4. **policy-engine:** deterministic attack detection is identical for balanced/strict/paranoid (profiles differ mainly in semantic knobs); permissive apply via `apply_yaml` was rejected by the self-test gate once (handled via fresh boot).
5. **injection-defense / semantic-models:** benign FPs: INJ-02 heuristic blocks PL security-meta prompts ("Napisz regułę, która wykrywa frazę …"), INJ-03 blocks JBB-BEN-064; ACT-01 requires approval for the benign $15 spend (AGT-SPEND-003).
6. **B17 dashboard-security (A-55):** render `bench.eval` (EvalPanel) and `bench.heatmap` (ObfuscationHeatmap) from `/api/perf.bench`; shapes in `tests/eval/samples/`.
7. **scaffold (A-54):** `.gitignore` exceptions for `reports/{eval,bench,heatmap}.json`, `reports/deck_numbers.md`, `reports/*.html`.
8. A gateway on 127.0.0.1:8787 (pid 76658, started 23:34, `python -m aegis serve`) is **not ours**; left untouched.
