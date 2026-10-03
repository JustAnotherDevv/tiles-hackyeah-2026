# B04-redaction-engine — status

Headline F1 works end-to-end in-process: PESEL/IBAN/PAN/expiry/email → `[PESEL_1]`, `[IBAN_1]`, `[PAN_1]`, `[CARD_EXPIRY_1]`, `[EMAIL_1]`. CVV becomes `[REDACTED:CVV]`: it is never vaulted and never fingerprinted. The vault rehydrates the values for the local user, and only for this session. Track data is blocked everywhere. A PAN sent to WebFetch is blocked. An AWS key in a prompt is blocked; inside a tool_result it is tokenized.

## Tasks
| ID | State | Notes |
|---|---|---|
| RED-01 | done | Package, `engine.create(rt)`, entity catalog, `CONTROLS` lists, route |
| RED-02 | done | `validators.py` and `normalize.py` (public surfaces) |
| RED-03 | done | `scan.py` (Tier-D port + §2.4 fixes), `detectors/*` (9 families, 32 plug-ins via core discovery) |
| RED-04 | done | `placeholders.py`: `PLACEHOLDER_RE`, `Vault`/`VaultStore` (TTL, cap), `rehydrate_text`/`rehydrate_json_value`, `StreamRehydrator` |
| RED-05 | done | Engine: scanner per snapshot, LRU cache, apply/rehydrate/mask_for_log, extras (A-39). **Fixed this session:** placeholders are now numbered by first appearance (they used to be numbered right-to-left). |
| RED-06 | done | `policy.py`: matrix, neutral actions, score ladder, forced rules, findings/decision builders, ratio and max-entity rules |
| RED-07 | done | DLP-01 (incl. `routing_args` SF-04, `matrix_overrides`, known-value rescan), DLP-02, DLP-05, DLP-08 (**+`mcp.call` surface per A-40**) |
| RED-08 | done | DLP-07 plus `ner_fallback` heuristics (`degraded=True`) |
| RED-09 | done | `config/snippets/redaction-engine.yaml`: 5 controls, 15 inline tests. No `destinations` section, because the seed owns the matrix. |
| RED-10 | done | `tests/unit/redaction_engine/`: 105 tests |
| RED-11 | done | `evaluate.py` CLI and `GET /api/redaction/metrics`. `reports/dlp-metrics.{json,md}` written. |
| RED-12 | done (A-38) | NER is borrowed via `rt.semantic.ner`. **The redaction engine's own ONNX session is disabled** (only `AEGIS_REDACTION_OWN_NER=1` turns it on). Timeout or no backend → heuristics. |
| RED-13 | done | Cache counters in `Decision.meta.cache_hits`; `to_thread` above 4 KB |
| RED-14 | done | `GET`/`DELETE /api/redaction/sessions/{id}` (DELETE requires admin), `forget_session` |
| RED-15–18 | done | Fragments, opaque tokens, shell-egress guard, `python -m aegis.redaction.preview fp ENTITY value` |

Fixes this session from Addendum A:
- A-42: `Finding.meta.fp` = `hmac:` + `hmac_hex(canonical, purpose="audit")[:16]`.
- A-38: the engine never loads its own NER session.
- A-40: DLP-08 also covers `mcp.call`.

## Verification
| ID | Command | Result |
|---|---|---|
| V01 | import check (plan cmd) | pass, 0.6 s, no model loaded |
| V02 | `pytest test_validators.py test_normalize.py` | pass |
| V03 | `AEGIS_SEMANTIC=off uv run --frozen python -m aegis.redaction.evaluate --check --write` | P=R=F1=1.000, leak 0%, hardneg FP 0%, finance-benign FP 0/42 |
| V04 | `test_re2_portability.py` | pass |
| V05/V06 | `test_vault_rehydrate.py`, `test_stream_rehydrator.py` (2000 chunkings), `test_engine_apply.py` | pass |
| V07/V08 | `test_controls.py` | pass |
| V09 | `test_snippet.py` (default + strict matrix; strict skips 1 third_party-redact case) + contract tests | pass |
| V10 | `test_privacy.py` | pass |
| V11 | `AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/redaction_engine -q` + ruff check/format | 104 passed, 1 skipped, 5.8 s; ruff clean |
| V12 | real model | **not run** (no model loading allowed). Covered with a fake `rt.semantic.ner` in `test_extras.py` (label map, timeout → fallback). |
| V13 | `--bench` | cache hit 90.5% (≥90 ✓). Tier D p95 @16 KB prose = 33.8 ms (target 15) and mask_for_log 2 KB = 2.0 ms (target 1). Both were measured on the loaded machine, using the densest PII corpus. |
| V14 | `test_route.py` | pass (entities, sessions, 403/200 wipe, metrics shape) |
| V15/V16 | integration and live edit | not run; needs core-gateway + playground |

## Run / demo
- `AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/redaction_engine -q`
- `uv run --frozen python -m aegis.redaction.evaluate --check --write [--bench]`
- `uv run --frozen python -m aegis.redaction.preview fp PESEL 44051401359`

## deps_needed
`phonenumbers>=9` (A-58). It is already in the venv; the import is guarded.

## contract_deviations
- The perf targets in V13 are not met under load (see above).
- The `/api/redaction/status` endpoint is extra.

## integration_todos
- core-gateway: call `rt.redactor.apply` on the final redact. Rehydrate only the `meta.roles` (assistant) text when DLP-08 returns `meta.rehydrate`, and never `tool_use` inputs (A-40).
- claude-code-integration: DLP-08 `meta.rehydrate` on `tool.input` → `updatedInput = rt.redactor.rehydrate_obj(ctx, tool_input)`. DLP-08 sets the entity filter in `ctx.state["redaction.rehydrate_entities"]`, so use the same `ctx`. On `SessionEnd` → `rt.redactor.forget_session(session_id)`.
- mcp-proxy: DLP-08 on `mcp.call` to local servers → write the rehydrated args back via `rehydrate_obj`.
- policy-engine: merge `config/snippets/redaction-engine.yaml`. Its controls carry `fail_mode`, `timeout_ms: 2000` for DLP-01/02/05, and the full params.
- semantic-models: `rt.semantic.ner(text, labels=, min_scores=, timeout_s=)` (A-38) is consumed by `aegis/redaction/ner.py:ner_spans`.
