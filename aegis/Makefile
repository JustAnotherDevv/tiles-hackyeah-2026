# Aegis - root Makefile (owner: scaffold; CONTRACTS section 7.7).
# Targets call the entrypoints their owners fill in. A missing entrypoint prints
# "TODO: <owner>" and exits 0, so every target is safe to run at any time.
# Compatible with macOS GNU make 3.81 (no .ONESHELL / .RECIPEPREFIX).

SHELL := /bin/bash
UV    ?= uv
PY    := $(UV) run --frozen python
PYTEST := $(UV) run --frozen pytest
# pytest exit code 5 = "no tests collected" (normal while workstreams are still landing)
OK5   := ; rc=$$?; if [ $$rc -eq 5 ]; then echo "(no tests collected yet)"; exit 0; fi; exit $$rc

# $(call todo_or,<path>,<owner>) -> shell test prefix; usage: $(call todo_or,x,y) <command>
todo_or = if [ ! -e "$(1)" ]; then echo "TODO: $(2) ($(1) not implemented yet)"; exit 0; fi;

.DEFAULT_GOAL := help
.PHONY: help setup gateway run dev web web-dev typecheck lint feed feed-keys feed-reseed mocks up demo \
        demo-scene demo-preflight demo-reset stack-check warmup chaos demo-copilot demo-runaway \
        demo-tail ambient test test-unit test-e2e test-sem test-live selftest eval bench redteam \
        verify-audit audit-verify fetch-models models reset claude

help: ## list targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup & build
setup: ## uv sync + npm ci (python 3.13 venv + web deps)
	@$(UV) sync --frozen
	@cd web && npm ci --no-audit --no-fund

web: ## build the dashboard into web/dist (served at /ui)
	@cd web && npm run build

web-dev: ## Vite dev server on :5173 (proxies /api /v1 /mcp /healthz /metrics -> :8787)
	@cd web && npm run dev

typecheck: ## web typecheck
	@cd web && npm run typecheck

lint: ## ruff (python) + eslint (web)
	@$(UV) run --frozen ruff check src tests feed_service mocks scripts demo
	@cd web && npm run lint

# ---------------------------------------------------------------- run
gateway: ## run the gateway on 127.0.0.1:8787
	@$(PY) -m aegis serve

run: gateway ## alias of gateway (CONTRACTS)

dev: ## gateway --reload + Vite dev server (Ctrl-C stops both)
	@trap 'kill 0' INT TERM; $(PY) -m aegis serve --reload & (cd web && npm run dev) & wait

feed: ## threat-intel feed service on :8790 (threat-feed)
	@$(PY) -m feed_service

feed-keys: ## generate feed signing keys + config/feeds/feed_pubkey.b64 (threat-feed)
	@$(PY) -m feed_service keygen --if-missing

feed-reseed: ## re-sign config/feeds/seed_bundle.json after editing feed_service/signatures (same key)
	@$(PY) -m feed_service reseed

mocks: ## run all mock upstreams (:8791-8794) in the foreground
	@pids=""; \
	for m in mock_llm:demo-mocks-docs mock_mcp:mcp-proxy exfil_sink:demo-mocks-docs mock_saas:demo-mocks-docs; do \
	  name=$${m%%:*}; owner=$${m##*:}; \
	  if [ -f mocks/$$name/__main__.py ]; then $(PY) -m mocks.$$name & pids="$$pids $$!"; \
	  else echo "TODO: $$owner (mocks/$$name/__main__.py not implemented yet)"; fi; \
	done; \
	if [ -n "$$pids" ]; then trap "kill $$pids" INT TERM; wait; fi

up: ## whole demo stack: feed + mocks + gateway (scripts/run_stack.py --lean; ARGS=--auto-ports ...)
	@$(PY) scripts/run_stack.py --lean $(ARGS)

demo: ## stack + warm-up + preflight (demo mode)
	@$(PY) scripts/run_stack.py --demo $(ARGS)

stack-check: ## port/identity/health check without starting anything
	@$(PY) scripts/run_stack.py --check $(ARGS)

demo-scene: ## run one demo scene: make demo-scene S=<scene>
	@$(call todo_or,demo/scenarios/run.py,demo-mocks-docs) $(PY) demo/scenarios/run.py $(S)

demo-preflight: ## READY / DEGRADED / NOT READY (ARGS=--reset|--quick|--json)
	@$(PY) demo/preflight.py $(ARGS)

demo-reset: ## reset demo state between judges (ARGS=--stop-ambient|--policy-golden)
	@$(PY) demo/scenarios/reset.py $(ARGS)

warmup: ## dashboard history + approvals, 0 pending (needs the stack)
	@$(PY) demo/scenarios/warmup.py $(ARGS)

chaos: ## red-team sweep over every control family (needs the stack)
	@$(PY) demo/agents/chaos_agent.py $(ARGS)

demo-copilot: ## F1/F4 trading copilot: make demo-copilot S=pii-draft|subscribe
	@$(PY) demo/agents/trading_copilot.py $(or $(S),subscribe) $(ARGS)

demo-runaway: ## F6 runaway agent (budget raise approval, then kill switch)
	@$(PY) demo/agents/runaway.py $(ARGS)

demo-tail: ## CLI live decision feed (fallback for the dashboard)
	@$(PY) demo/scenarios/tail.py $(ARGS)

ambient: ## background demo traffic until Ctrl-C
	@$(PY) demo/agents/ambient.py $(ARGS)

claude: ## Claude Code through Aegis (demo settings profile, never machine-wide)
	@if [ -x demo/claude/run.sh ] || [ -f demo/claude/run.sh ]; then bash demo/claude/run.sh $(ARGS); \
	elif [ -f demo/claude/settings.json ]; then cd demo/claude/project && claude --settings ../settings.json --mcp-config ../mcp.json --strict-mcp-config --setting-sources project; \
	else echo "TODO: claude-code-integration (demo/claude/run.sh not implemented yet)"; fi

# ---------------------------------------------------------------- tests (recipes from docs/plan/18 section 2.10)
test: ## unit + hermetic deterministic e2e + matrix/report
	@AEGIS_SEMANTIC=off $(PYTEST) tests --ignore=tests/eval --ignore=tests/bench --ignore=tests/redteam -m "not semantic and not live and not slow and not bench" $(OK5)

test-unit: ## unit tests of every workstream
	@AEGIS_SEMANTIC=off $(PYTEST) tests/unit $(ARGS) $(OK5)

test-e2e: ## hermetic e2e + coverage (test-suite)
	@$(call todo_or,tests/test_coverage.py,test-suite) AEGIS_SEMANTIC=off $(PYTEST) tests/e2e tests/test_coverage.py tests/test_cases_schema.py -m "not semantic and not live and not slow" $(OK5)

test-sem: ## semantic cases (skips with reason when models/Ollama absent)
	@$(call todo_or,tests/e2e,test-suite) AEGIS_SEMANTIC=on $(PYTEST) tests/e2e -m semantic $(OK5)

test-live: ## same cases against the running gateway + current policy
	@$(call todo_or,tests/test_coverage.py,test-suite) AEGIS_LIVE_URL=$${AEGIS_LIVE_URL:-http://127.0.0.1:8787} $(PYTEST) tests/e2e tests/test_coverage.py -m "not slow" $(OK5)

selftest: ## policy self-test (policy-engine)
	@$(PY) -m aegis selftest

eval: ## red-team eval -> reports/eval.json (redteam-eval-perf)
	@$(call todo_or,tests/eval/__main__.py,redteam-eval-perf) $(PY) -m tests.eval $(ARGS)

bench: ## overhead / rps benchmark -> reports/bench.json (redteam-eval-perf)
	@$(call todo_or,scripts/bench.py,redteam-eval-perf) $(PY) scripts/bench.py $(ARGS)

redteam: ## red-team runner (redteam-eval-perf)
	@$(call todo_or,tests/redteam/__main__.py,redteam-eval-perf) $(PY) -m tests.redteam $(ARGS)

# ---------------------------------------------------------------- ops
verify-audit: ## verify the hash-chained audit log (audit-metrics)
	@$(PY) -m aegis verify-audit

audit-verify: verify-audit ## alias

fetch-models: ## fetch/verify ONNX + Ollama models (semantic-models)
	@$(call todo_or,scripts/fetch_models.sh,semantic-models) bash scripts/fetch_models.sh $(ARGS)

models: fetch-models ## alias (CONTRACTS)

reset: ## wipe data/, copy golden policy, reseed org (core-gateway)
	@$(PY) -m aegis reset
