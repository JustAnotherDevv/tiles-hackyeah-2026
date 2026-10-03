# B25-docs-submission — status

Judge-facing docs and the HackTribe submission kit (plan 20: DEMO-08, 09, 14, 15, 16, 18). Written from
CONTRACTS + Addendum A, MASTER_PLAN §7 (name corrections applied), the live `config/policy.yaml` /
profiles / presets, and the staging drafts (read-only). No numbers invented: every number is a
`{{TBD: <key>}}` placeholder filled by `docs/submission/build.py` from `reports/*` (or a live API call).

## Tasks
| ID | Prio | State | Notes |
|---|---|---|---|
| DEMO-08 | must | done | `README.md` (judge front page: pitch, quick start with `make` + raw `uv` commands, 5-minute judge path, GS requirement → where table, Mermaid + SVG architecture, try-to-break-it, live-edit recipes, feed, Claude Code, cast, ports, layout, measured-results table (placeholders), limitations, credits) + `docs/JUDGES.md` (test suite commands, Playground, 12 one-click attacks with expected action/control, how to read a decision, live policy edits, approvals by role, feed publish/tamper, reporting, reset) |
| DEMO-09 | must | done | `docs/demo-script.md` (4:30 runbook, scene ↔ command map, contract names, fallbacks F1–F6, Q&A Q1–Q23); `docs/submission/{README.md (checklist, deadlines, final-pass commands), HACKTRIBE.md (title, 454-word description incl. 4 placeholder team lines, claims-to-verify table, 127-word checkpoint text, gallery captions, opening instructions), VIDEO_60S.md (shot ↔ capture command map, VO, captions, ffmpeg recipe)}` |
| DEMO-16 | must | partial (by design) | pipeline built and dry-run; the real pass needs final `make test`/`make eval`/`make bench` after integration (commands in `docs/submission/README.md`). A dry `collect` on the current partial reports worked (results.json had only 6 cases, bench.json partial), so `numbers.json` was deleted again to avoid shipping partial numbers |
| DEMO-14 | should | done | `docs/architecture.md` (component + sequence Mermaid, interception points, destination matrix, decision ↔ ACS/HTTP table, ports, build-status table with `{{TBD: status}}`), `docs/assets/architecture.svg` (hand-authored, rendered and visually checked) + `architecture.png` (1920 px, HackTribe image), `docs/policy-reference.md` (documented sample policy: sections, strictness profiles table from `config/profiles/*`, control catalog, budgets, approvals, destinations, MCP, feeds, hot reload/self-test, judge edits), `docs/samples/policy-{strict-bank,budgets,approvals,local-only}.yaml`, `docs/api.md` (curl + SDK cheat sheet) |
| DEMO-15 | should | done | `docs/submission/DECK.md` (10 slides, copy + notes + criteria map), `deck/deck.html` (10 print-ready 1920×1080 slides, design tokens, screenshot slots that load `docs/assets/screens/*.png` when present), `build.py collect|render|apply --pdf --check --strict --screens` |
| DEMO-18 | could | partial | `video/cards.html` (title / animated architecture / end card; screenshot-checked), `video/captions.srt`, ffmpeg recipe in VIDEO_60S.md, `build.py --screens` (headless Chrome of `/ui/...?view_as=`; not run: needs the live stack after warm-up) |

## Verification
| ID | Command | Result |
|---|---|---|
| DEMO-V14 | `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/docs_submission -q` | PASS 22 tests (~2 s): samples validate (PolicyDoc + `validate_text` 0 errors), all relative links in README/docs/submission resolve, title 4 words, description ≤ 500 incl. team headroom, checkpoint ≤ 160, deck 10/10 slides, staging names absent, renderer never invents numbers, collect parsers |
| DEMO-V14 | `uv run --frozen python docs/submission/build.py --check` | `check: OK` (warns: 4 `[NAME — EMAIL]` placeholders) |
| DEMO-V15 | `uv run --frozen python docs/submission/build.py render --pdf` + `mdls -raw -name kMDItemNumberOfPages docs/submission/out/Aegis_HackYeah2026_GS_AIControlLayer.pdf` | PASS: `10` pages, ~1.5 MB, ~7 s; every number visibly `[TBD: key]` (no numbers.json yet). Pages rasterized with pdftoppm and reviewed |
| extra | `AEGIS_POLICY=docs/samples/<sample> AEGIS_SEMANTIC=off AEGIS_TEST_MODE=1 AEGIS_FEED_URL=disabled AEGIS_DATA_DIR=$(mktemp -d) uv run --frozen python -m aegis selftest` | all 4 samples: gate failures 0 (approvals 1/1, budgets 0 tests, local-only 1/1, strict-bank 4/4) |
| extra | `uv run --frozen ruff check/format --check docs/submission/build.py tests/unit/docs_submission` | clean |
| not done | Mermaid render check | no `mmdc` installed (no new deps); blocks follow Mermaid v11 syntax from the render-checked staging diagrams. Paste into mermaid.live once, or rely on GitHub rendering |

## Files (all within owned paths)
- `README.md`, `docs/JUDGES.md`, `docs/architecture.md`, `docs/policy-reference.md`, `docs/api.md`, `docs/demo-script.md`
- `docs/assets/architecture.svg`, `docs/assets/architecture.png`
- `docs/samples/policy-strict-bank.yaml`, `policy-budgets.yaml`, `policy-approvals.yaml`, `policy-local-only.yaml`
- `docs/submission/README.md`, `HACKTRIBE.md`, `DECK.md`, `VIDEO_60S.md`, `build.py`, `deck/deck.html`, `video/cards.html`, `video/captions.srt`
- generated: `docs/submission/out/` (rendered copies + PDF with `[TBD]` chips; regenerate at the final pass)
- `tests/unit/docs_submission/test_docs.py`

## How to run / demo
- Final pass (DEMO-16, after `make test && make eval && make bench`, optional `make up`):
  `uv run --frozen python docs/submission/build.py collect --url http://127.0.0.1:8787` →
  `… render --pdf --check` → `… apply` (fills README/JUDGES/demo-script/architecture in place) →
  `… --check --strict` (fails until team names, repo URL and every number are filled).
- Screenshots: `make demo` (warm-up), then `uv run --frozen python docs/submission/build.py --screens --url http://127.0.0.1:8787`, re-run `render --pdf` (deck slots pick them up).
- Video cards: open `docs/submission/video/cards.html#title|#arch|#end` in Chrome full screen, keys 1/2/3.
- Try a sample policy: `AEGIS_POLICY=docs/samples/policy-strict-bank.yaml make gateway`.

## deps_needed
None. Uses stdlib + httpx (present) + the installed Google Chrome; optional `rsvg-convert`, `pdftoppm`,
`ffmpeg` (present) only for PNG export/preview/video.

## contract_deviations
- Docs tests live in `tests/unit/docs_submission/` (bundle ownership) instead of plan 20's
  `tests/unit/demo_mocks_docs/test_docs.py`.
- Placeholder syntax is `{{TBD: dotted.key}}` (plain `{{key}}` also accepted by the renderer).

## integration_todos
1. **DEMO-16 final pass** (integrator / B25 at Sun 06:00–09:00): commands above; tick the claims table in
   `docs/submission/HACKTRIBE.md` §2; fill `docs/architecture.md#build-status`; replace `[NAME — EMAIL]`
   (README footer, HACKTRIBE description + checkpoint, `deck/deck.html` slide 1) and `[PUBLIC REPO URL]`
   (HACKTRIBE, deck slides 1/10, `video/cards.html`).
2. **Borderline preset vs runbook** (`web/src/components/security/playground/presets.ts`, B17): preset
   "Borderline (0.62)" uses surface `tool.output` (untrusted → INJ-02 `params.untrusted_threshold`, balanced
   0.75, action quarantine/redact) and its hint says threshold 0.90, while the live policy pins
   `controls[id=INJ-02].threshold: 0.80`. The runbook/JUDGES tell presenters to lower `threshold` 0.80 → 0.50
   (and `untrusted_threshold` for tool output). Either switch the preset to `prompt.user` and fix the hint
   (0.80), or keep it and rehearse the two-field edit. Verify the 0.62 score at rehearsal.
3. **Referenced B23/B13 paths** to confirm at integration (docs fall back to Playground/curl if missing):
   `demo/scenarios/run.py s1…s8` (+ `--claude-fallback`), `demo/scenarios/tail.py`, `demo/scenarios/PROMPTS.md`,
   `demo/scenarios/payloads/pii.json`, `demo/agents/chaos_agent.py`, `demo/claude/replay.py`, `demo/claude/run.sh`.
4. HackTribe image: upload `docs/assets/architecture.png` (+ screenshots).
5. Verify OWASP 2026 IDs on deck slide 2 (LLM06:2026 Unbounded Consumption, LLM03:2026 Excessive Agency per
   research 01/staging) against the official list before export.
6. B08 note: the F6 runaway story in the docs assumes `on_soft: warn` on `agent:chaos-agent@platform`
   (HANDOFF B08 line); keep `config/policy.yaml` in sync or scene 3b stalls at 86 %.
