# B06-injection-defense — status

Owner paths: `src/aegis/injection/`, `src/aegis/controls/injection/`, `config/snippets/injection-defense.yaml`, `tests/unit/injection_defense/`.
Two agents worked on this bundle. Agent 1 wrote normalize/views/signatures plus the catalog. Agent 2 wrote everything else.

## Tasks
| Task | State | Notes |
|---|---|---|
| INJ-01 skeleton / public `aegis.injection.normalize` | done | public API unchanged (`normalize`, `Normalized`, `Layer`, `HiddenRun`) |
| INJ-02 normalizer | done | NFKC, zero-width/bidi, tag chars, VS smuggling, mixed-script homoglyphs, carriers, base64/hex/url/html/\u/rot13 to depth 2, truncation |
| INJ-03 RE2 catalog + scanner | done | 64 signatures, 22 families, EN/PL/DE/UK/RU, inline tests self-validated (0 disabled), `scan_text` public |
| INJ-04 control INJ-01 | done | latest-turn blocking, harness `<system-reminder>` strip, quarantine findings with verbatim `replacement` |
| INJ-05 control INJ-02 | done | cascade + guard review band + review_fallback, heuristic when degraded (`max(engine heuristic, signature score)`, `degraded=True`), score+threshold always set |
| INJ-06 control INJ-04 deterministic legs | done | extraction (prompt.user/model.request), canary plain/squashed/decoded/URL |
| INJ-07 snippet | done | `config/snippets/injection-defense.yaml`, INJ-02 threshold 0.80 / 700 ms (SF-22), profile table C.2 included as a comment |
| INJ-08 evasion views | done | fuzzy/typoglycemia, collapsed, deleet, camel, payload split, reversed |
| INJ-09 exemplars | done | `injection/exemplars.py` + `data/exemplars.yaml` (~60). Built lazily in the background; skipped when `embed()` returns `[]`. Lifts INJ-02 into the review band; INJ-04 has a paraphrase leg |
| INJ-10 overlap + URL exfil | done | shingles recorded on model.request (`ctx.state` + session; no session write on dry_run) |
| INJ-11 corpus + FP wall | done | matrix 226/226, PL 44/46 (excludes `harmful`/`agentic`), indirect 41/45, finance 0 FP, benign tool results 0 FP. Added signature `third_party_request.en.please_data_action` |
| INJ-12 INJ-05 goal drift | done (monitor) | embed, then similarity, then lexical fallback; verb-family halving; `ApprovalDraft(action_type="agent.goal_drift")` |
| INJ-13 crescendo | not started | `conversation` params are parsed but ignored |
| INJ-14 canary planting | not started | needs core mutation support; canary is planted by config (A-45) |
| INJ-15 dev CLI | done | `uv run python -m aegis.injection "text" [--untrusted] [--json]` |

## Verification
- INJ-V01, discovery and no import-time I/O: `tests/unit/injection_defense/test_discovery.py` PASS.
- INJ-V02 normalizer: `test_normalize.py` PASS.
- INJ-V03 catalog: `test_signatures.py` PASS. RE2 is in use.
- INJ-V04 corpora: `test_corpus.py` PASS (under 3 s).
- INJ-V05 INJ-01: `test_inj01.py` PASS. Covers the Claude Code harness fixture, a sticky-history attack, SETUP.md quarantine and degraded-allow on an internal error.
- INJ-V06 INJ-02: `test_inj02.py` PASS. Covers the threshold flip without a cache flush, base64 candidates, sentence-level localization, degraded heuristic and exemplar lift.
- INJ-V07 INJ-04: `test_inj04.py` PASS.
- INJ-V08 perf: `test_perf.py` PASS with load-tolerant bounds. Measured on a box with load avg ~17: 2 KB prompt p50 ≈ 2.7–3.7 ms (target 1 ms), 100 KB tool output ≈ 110 ms (target 40 ms). This needs to be re-measured on a quiet machine.
- INJ-V09 snippet: the `ok 4` check passes. `test_snippet.py` runs every inline test through a fake pipeline with an AEGIS_SEMANTIC=off-like engine: PASS. Real `python -m aegis selftest --policy config/policy.yaml`: 82 passed, 0 failed, all INJ tests included.
- INJ-V10 e2e: `test_e2e_guard.py` (real `create_app`, `/v1/guard`) PASS. INJ-01 block works; SETUP.md is quarantined through the real redactor (replacement applied verbatim, no tag chars left); the canary response is blocked.
- INJ-V11 live demo (manual) and INJ-V12 real models: not run. No models were loaded, per the instructions.
- INJ-V13 lint: `ruff check` and `ruff format --check` are clean on all owned paths.
- Full suite: `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/injection_defense -q` gives 112 passed. Consumer suites (mcp_proxy, semantic_models, action_guards) are green.

## Demo notes
- Scene 2: `tests/unit/injection_defense/fixtures/setup_md.txt` is a harmless stand-in for SETUP.md (HTML comment plus tag chars, `example.test` hosts). On `tool.output` it produces 2 quarantined spans.
- Scene 4: the borderline prompt is in `fixtures/demo_borderline.txt`. With AEGIS_SEMANTIC=off, INJ-02 scores it 0.70 (degraded). That falls in the review band; the guard is unavailable, so the result is allow. Lowering `INJ-02.threshold` to 0.65 makes it block. INJ-01 does not block it (0.70 < 0.75). Re-record the score with real models (INJ-V12).

## deps_needed
None. Uses google-re2, rapidfuzz (guarded), numpy, pyyaml and pydantic.

## contract_deviations
- INJ-04 response side scans every non-system segment. `/v1/guard` sends `model.response` text as role `tool_result`, not `assistant`.
- Emoji subdivision-flag tag sequences (decoded payload is 2–7 lowercase alphanumerics) are not treated as smuggling.
- INJ-01 returns an `allow` decision carrying score and threshold when 0 < score < threshold, and returns None when the score is 0.

## integration_todos
- policy-engine: merge `config/snippets/injection-defense.yaml`, including the `goal-drift` approval rule and the profile table in its header. `config/policy.yaml` already contains equivalent INJ entries, and its selftest passes.
- dashboard-security: render `decision.meta.inj` (Appendix B: `signals[*].stage`, `normalization.flags`, `score`/`threshold`) in the drawer and the playground waterfall.
- claude-code-integration / demo-mocks-docs: `demo/claude/project/docs/SETUP.md` can reuse the fixture's shape. Keep the canary out of files the agent reads (DLP-05).
- INJ-12 drift needs INJ-01 to have seen the user prompt in the same session: `remember_intent` writes `rt.sessions.get(session_id).data["injection"]["intent"]`.
