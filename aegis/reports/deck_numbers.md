# Deck numbers (measured; paste-ready)

Generated 2026-10-03T22:04:31+00:00. Every value is read from a report file at the given JSON path. `not measured` means the run has not happened - never fill in a guess.

| slide | number | value | source | json path | measured at | note |
|---|---|---|---|---|---|---|
| 4 | leak rate (balanced, deterministic) | **11.18 %** | `reports/eval.json` | `dlp.runs.0.leak_rate` | 2026-10-03T22:03:32+00:00 | 92/823 gold PII/secret values left toward a remote model |
| 4 | leak rate (permissive, deterministic) | **21.14 %** | `reports/eval.json` | `dlp.runs.1.leak_rate` | 2026-10-03T22:03:32+00:00 | 174/823 gold PII/secret values left toward a remote model |
| 4 | leak rate (strict, deterministic) | **8.51 %** | `reports/eval.json` | `dlp.runs.2.leak_rate` | 2026-10-03T22:03:32+00:00 | 70/823 gold PII/secret values left toward a remote model |
| 4 | leak rate (paranoid, deterministic) | **0.12 %** | `reports/eval.json` | `dlp.runs.3.leak_rate` | 2026-10-03T22:03:32+00:00 | 1/823 gold PII/secret values left toward a remote model |
| 4 | detector precision (redaction-engine) | **1.0** | `reports/dlp-metrics.json` | `overall.precision` | 2026-10-03T21:30:01+00:00 | redaction-engine detector P/R (if present) |
| 4 | detector recall (redaction-engine) | **1.0** | `reports/dlp-metrics.json` | `overall.recall` | 2026-10-03T21:30:01+00:00 |  |
| 7 | policy edit -> active p95 | **412.0 ms** | `reports/bench.json` | `reload.file_to_active_ms.p95` | 2026-10-03T22:03:42+00:00 | file write -> /healthz policy_version (spawned gateway) |
| 7 | policy apply p95 (in-process) | **197.0 ms** | `reports/bench.json` | `reload.apply_ms.p95` | 2026-10-03T22:03:42+00:00 | rt.policy.apply_yaml incl. self-test gate |
| 7 | feed signature activation | **not measured** | `reports/results.json` | `perf.feed_activation_ms` |  |  |
| 9 | gateway overhead p50 (deterministic) | **2.73 ms** | `reports/bench.json` | `headline.det_overhead_p50_ms` | 2026-10-03T22:03:42+00:00 |  |
| 9 | gateway overhead p95 (deterministic) | **5.27 ms** | `reports/bench.json` | `headline.det_overhead_p95_ms` | 2026-10-03T22:03:42+00:00 |  |
| 9 | throughput (deterministic, co-located load generator) | **200.0 rps** | `reports/bench.json` | `headline.rps_det` | 2026-10-03T22:03:42+00:00 | lower bound |
| 9 | share of an 800 ms upstream | **1.18 %** | `reports/bench.json` | `headline.overhead_share_pct` | 2026-10-03T22:03:42+00:00 | simulated upstream |
| 9 | semantic overhead p50 | **not measured** | `reports/bench.json` | `headline.sem_overhead_p50_ms` |  |  |
| 9 | semantic overhead p95 | **not measured** | `reports/bench.json` | `headline.sem_overhead_p95_ms` |  |  |
| 9 | redaction (DLP-01) p95 | **0.24 ms** | `reports/bench.json` | `by_control.11.p95_ms` | 2026-10-03T22:03:42+00:00 |  |
| 9 | attack detection (balanced, deterministic) | **66.7 %** | `reports/eval.json` | `runs.0.overall.attack.rate` | 2026-10-03T22:03:32+00:00 |  |
| 9 | attack detection 95% CI (balanced, deterministic) | **63.2–70.0 %** | `reports/eval.json` | `runs.0.overall.attack.ci95` | 2026-10-03T22:03:32+00:00 |  |
| 9 | false-positive rate (balanced, deterministic) | **1.6 %** | `reports/eval.json` | `runs.0.overall.benign.fpr` | 2026-10-03T22:03:32+00:00 |  |
| 9 | held-out detection (balanced, deterministic) | **39.2 %** | `reports/eval.json` | `runs.0.by_split.held_out.attack.rate` | 2026-10-03T22:03:32+00:00 | public sets not used for tuning |
| 9 | attack detection (strict, deterministic) | **66.7 %** | `reports/eval.json` | `runs.2.overall.attack.rate` | 2026-10-03T22:03:32+00:00 |  |
| 9 | attack detection 95% CI (strict, deterministic) | **63.2–70.0 %** | `reports/eval.json` | `runs.2.overall.attack.ci95` | 2026-10-03T22:03:32+00:00 |  |
| 9 | false-positive rate (strict, deterministic) | **1.6 %** | `reports/eval.json` | `runs.2.overall.benign.fpr` | 2026-10-03T22:03:32+00:00 |  |
| 9 | held-out detection (strict, deterministic) | **39.2 %** | `reports/eval.json` | `runs.2.by_split.held_out.attack.rate` | 2026-10-03T22:03:32+00:00 | public sets not used for tuning |
| 9 | obfuscation coverage (seed x transform) | **100.0 %** | `reports/bench.json` | `headline.obfuscation_coverage` | 2026-10-03T22:03:42+00:00 |  |
| claims | "policy edits apply within a second" (reload p95) | **412.0 ms** | `reports/bench.json` | `headline.reload_p95_ms` | 2026-10-03T22:03:42+00:00 |  |
