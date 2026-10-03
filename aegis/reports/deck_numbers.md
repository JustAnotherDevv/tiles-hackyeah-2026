# Deck numbers (measured; paste-ready)

Generated 2026-10-03T23:45:33+00:00. Every value is read from a report file at the given JSON path. `not measured` means the run has not happened - never fill in a guess.

| slide | number | value | source | json path | measured at | note |
|---|---|---|---|---|---|---|
| 4 | leak rate (balanced, deterministic) | **9.96 %** | `reports/eval.json` | `dlp.runs.0.leak_rate` | 2026-10-03T23:41:05+00:00 | 82/823 gold PII/secret values left toward a remote model |
| 4 | leak rate (permissive, deterministic) | **21.14 %** | `reports/eval.json` | `dlp.runs.1.leak_rate` | 2026-10-03T23:41:05+00:00 | 174/823 gold PII/secret values left toward a remote model |
| 4 | leak rate (strict, deterministic) | **4.37 %** | `reports/eval.json` | `dlp.runs.2.leak_rate` | 2026-10-03T23:41:05+00:00 | 36/823 gold PII/secret values left toward a remote model |
| 4 | leak rate (paranoid, deterministic) | **0.0 %** | `reports/eval.json` | `dlp.runs.3.leak_rate` | 2026-10-03T23:41:05+00:00 | 0/823 gold PII/secret values left toward a remote model |
| 4 | detector precision (redaction-engine) | **1.0** | `reports/dlp-metrics.json` | `overall.precision` | 2026-10-03T21:30:01+00:00 | redaction-engine detector P/R (if present) |
| 4 | detector recall (redaction-engine) | **1.0** | `reports/dlp-metrics.json` | `overall.recall` | 2026-10-03T21:30:01+00:00 |  |
| 7 | policy edit -> active p95 | **642.0 ms** | `reports/bench.json` | `reload.file_to_active_ms.p95` | 2026-10-03T23:43:31+00:00 | file write -> /healthz policy_version (spawned gateway) |
| 7 | policy apply p95 (in-process) | **382.0 ms** | `reports/bench.json` | `reload.apply_ms.p95` | 2026-10-03T23:43:31+00:00 | rt.policy.apply_yaml incl. self-test gate |
| 7 | feed signature activation | **22.0 ms** | `reports/results.json` | `perf.feed_activation_ms` | 2026-10-03T23:11:56.465053Z |  |
| 9 | gateway overhead p50 (deterministic) | **2.4 ms** | `reports/bench.json` | `headline.det_overhead_p50_ms` | 2026-10-03T23:43:31+00:00 |  |
| 9 | gateway overhead p95 (deterministic) | **3.82 ms** | `reports/bench.json` | `headline.det_overhead_p95_ms` | 2026-10-03T23:43:31+00:00 |  |
| 9 | throughput (deterministic, co-located load generator) | **321.0 rps** | `reports/bench.json` | `headline.rps_det` | 2026-10-03T23:43:31+00:00 | lower bound |
| 9 | share of an 800 ms upstream | **1.99 %** | `reports/bench.json` | `headline.overhead_share_pct` | 2026-10-03T23:43:31+00:00 | simulated upstream |
| 9 | semantic overhead p50 | **13.6 ms** | `reports/bench.json` | `headline.sem_overhead_p50_ms` | 2026-10-03T23:43:31+00:00 |  |
| 9 | semantic overhead p95 | **45.1 ms** | `reports/bench.json` | `headline.sem_overhead_p95_ms` | 2026-10-03T23:43:31+00:00 |  |
| 9 | redaction (DLP-01) p95 | **0.21 ms** | `reports/bench.json` | `by_control.10.p95_ms` | 2026-10-03T23:43:31+00:00 |  |
| 9 | attack detection (balanced, semantic) | **92.4 %** | `reports/eval.json` | `runs.4.overall.attack.rate` | 2026-10-03T23:41:05+00:00 |  |
| 9 | attack detection 95% CI (balanced, semantic) | **90.2–94.1 %** | `reports/eval.json` | `runs.4.overall.attack.ci95` | 2026-10-03T23:41:05+00:00 |  |
| 9 | false-positive rate (balanced, semantic) | **5.1 %** | `reports/eval.json` | `runs.4.overall.benign.fpr` | 2026-10-03T23:41:05+00:00 |  |
| 9 | held-out detection (balanced, semantic) | **89.6 %** | `reports/eval.json` | `runs.4.by_split.held_out.attack.rate` | 2026-10-03T23:41:05+00:00 | public sets not used for tuning |
| 9 | attack detection (strict, semantic) | **98.3 %** | `reports/eval.json` | `runs.5.overall.attack.rate` | 2026-10-03T23:41:05+00:00 |  |
| 9 | attack detection 95% CI (strict, semantic) | **97.1–99.0 %** | `reports/eval.json` | `runs.5.overall.attack.ci95` | 2026-10-03T23:41:05+00:00 |  |
| 9 | false-positive rate (strict, semantic) | **84.5 %** | `reports/eval.json` | `runs.5.overall.benign.fpr` | 2026-10-03T23:41:05+00:00 |  |
| 9 | held-out detection (strict, semantic) | **99.5 %** | `reports/eval.json` | `runs.5.by_split.held_out.attack.rate` | 2026-10-03T23:41:05+00:00 | public sets not used for tuning |
| 9 | obfuscation coverage (seed x transform) | **100.0 %** | `reports/bench.json` | `headline.obfuscation_coverage` | 2026-10-03T23:43:31+00:00 |  |
| claims | "policy edits apply within a second" (reload p95) | **642.0 ms** | `reports/bench.json` | `headline.reload_p95_ms` | 2026-10-03T23:43:31+00:00 |  |
