# FIX: fresh-clone reproducibility fixes (2026-10-04)

Source: judge-simulation REPRO (fresh clone of the public repo). Scope: docs, feed CLI, run_stack, report legend, tree hygiene.

## Changes

| # | Finding | Fix | Files |
|---|---|---|---|
| 1 | Busy ports undocumented; `make models` described as "verifies"; Node 20+ too loose | README + JUDGES: "Ports busy?" (`make up ARGS=--auto-ports`, `--port-offset N`, `serve --port N` / `AEGIS_PORT`), "models are optional", `make models` = ~2 GB download, `ARGS=--verify` = offline check, Node 20.19+/22.12+, setup download size, arm64 MiniLM note. fetch_models.sh header comment (models/ fully gitignored) | `README.md`, `docs/JUDGES.md`, `scripts/fetch_models.sh`, `Makefile` (help text) |
| 1b | **Bug found while verifying:** `--auto-ports` crashed with `KeyError: 'mcp'` on any real conflict | `pick_auto_offset` maps child names to port keys; regression test | `scripts/run_stack.py`, `tests/unit/demo_mocks_docs/test_run_stack.py` |
| 2 | `feed_service publish` always hit :8790 | new `aegis.feed.urls.resolve`: `--url` > `$AEGIS_FEED_SERVICE_URL` > `$AEGIS_FEED_URL` > live `data/run/feed.pid` > :8790; prints the target; an explicit/stack target that is down errors instead of silently writing local files. Same for `python -m aegis.feed.demo` (`--gateway`/`--feed`, `$AEGIS_URL`, `gateway.pid`). run_stack prints an `export AEGIS_URL=… AEGIS_FEED_URL=…` line on non-default ports | `src/aegis/feed/urls.py`, `feed_service/__main__.py`, `src/aegis/feed/demo.py`, `scripts/run_stack.py`, `tests/unit/threat_feed/test_fresh_clone.py` |
| 3 | api.md `jq` recipe printed `control: null` | `.verdict.primary.control_id` (verified in-process: `redact`/`DLP-01`); new "Playground" section for `POST /api/playground` with fields + example output from an in-process call | `docs/api.md`, `docs/JUDGES.md` (guard curl now uses the short jq filter) |
| 4 | PARTIAL unexplained | Status legend under the matrix in `matrix.md`, `selftest.html` and the console; new "Expected failures (xfail)" section listing each xfail case per control; JUDGES §1 explains PARTIAL | `tests/lib/report.py`, `docs/JUDGES.md`, `README.md` |
| 5a | First `make up` on a fresh clone rewrote `config/feeds/*` (3 tracked files) | `keygen --if-missing` without the committed key's private half now pins the new key + re-signed seed in gitignored `config/feeds/local/`; the gateway (`FeedManager._pubkey_path`) prefers it when present; `--repo` flag = maintainer re-key into committed files. Existing key (this machine, b147d42c) = no-op as before | `feed_service/build.py`, `feed_service/__main__.py`, `src/aegis/feed/manager.py`, `.gitignore` |
| 5b | `make test` rewrote tracked `reports/selftest.html` | gitignored (`/reports/selftest.html`); the gateway serves it at `/api/selftest/report`, so the file name stays. **Orchestrator: `git rm --cached aegis/reports/selftest.html`** | `.gitignore` |

## Validation

- Fresh-clone keygen simulated in a scratch copy: committed `config/feeds/*` sha1 unchanged, `config/feeds/local/` created, second run = "nothing to do".
- `make up ARGS='--auto-ports --port-offset 1200 --semantic off'` with :9987 occupied → auto offset +100 (gateway :8887, feed :8890), export hint printed; `/healthz` ok (feed ok, semantic off); `python -m feed_service publish` with no env → "publishing to feed service http://127.0.0.1:8890 (from data/run/feed.pid)", serial 20, gateway in sync; `python -m aegis.feed.demo check` 4/4 PASS via pidfiles. Stack stopped, ports free.
- `AEGIS_PORT=18787` → `Settings.port == 18787`.
- Tracked files after the run: `config/feeds/*` and `reports/selftest.html` unchanged.
- `pytest tests/unit/threat_feed tests/unit/demo_mocks_docs tests/unit/test_suite`: 127 passed. Under load average 25-50: `test_sig01::test_perf_8kb_prompt` (p95 bound 50 ms, measured 58-102 ms) and 1-2 `test_manager` tests flake when the whole directory runs. `test_manager.py` alone passes 3/3. ruff clean.

## Not done / for others

- `src/aegis/__main__.py` bind error hint (`use --port N or AEGIS_PORT=N`): not my path.
- Root `README.md` banner pointing GS judges to `aegis/`, plus the Pocket README items (P1-P9): outside `aegis/`.
- `make eval` / `make bench` still rewrite the tracked `reports/{eval,bench}.{json,html}` (committed evidence; CAL2).
- The committed `reports/selftest.html` snapshot has no legend. It is moot once untracked.
