# OWASP coverage assessment

This document measures Aegis against three OWASP Top 10 lists:

- **OWASP Top 10 for LLM Applications 2025** (LLM01–LLM10)
- **OWASP Top 10 for Agentic Applications 2026** (ASI01–ASI10)
- **OWASP MCP Top 10 2025** (MCP01–MCP10). This list is still in **beta** (Phase 3, pilot testing).

It is deliberately strict. A control counts as coverage only if it is **implemented, enabled, and enforcing in the default `balanced` profile**, and an existing test or report shows that it works. If a control exists only in docs, or runs in `monitor`/`log` mode by default, it counts as at most Partial. Paths are relative to `aegis/`. Assessed on 2026-10-04; see [Methodology](#methodology).

## Executive summary

| List | Covered | Partial | Not covered | Out of scope | Total |
|---|--:|--:|--:|--:|--:|
| OWASP LLM Top 10 (2025) | 6 | 2 | 2 | 0 | 10 |
| OWASP Agentic Top 10 (2026) | 10 | 0 | 0 | 0 | 10 |
| OWASP MCP Top 10 (2025, beta) | 3 | 7 | 0 | 0 | 10 |
| **All lists** | **19** | **9** | **2** | **0** | **30** |

The Agentic row was **re-verified** at 09:30 CEST on 2026-10-04, after the ASI01–ASI10 hardening. Every item has an enabled, enforcing control in `balanced`. Black-box attack and benign probes pass through the real surfaces, and so do the targeted tests (`scratchpad` report VERIFY.md, probe script `verify_probes.py`). The full `make test` was then run once, with these results:
- **pytest:** 2611 passed and 13 failed. All 13 failures are in `tests/unit/asi07` and come from a single open ROG-01 state-isolation bug.
- **Case matrix:** 1172 cases with 0 failures. The LLM and MCP rows were **not** re-assessed; they still reflect the earlier run, so some of their caveats below (identity, MCP-03 collision, A2A) are now out of date.

**What is strong**
- **Data protection.** DLP-01 to DLP-08 tokenize, block or redact PII, PCI data, Polish IDs and secrets on both the request side and the response side. In the curated fixture set, 626 cases show 0% leaks.
- **Excessive agency and tool misuse.** Per-agent tool RBAC, guards on spend, data, send and deploy, and approvals bound to their exact arguments.
- **Supply chain at runtime.** A signed threat feed, a model-artifact gate, a package guard, and an MCP server registry with tool pinning against rug pulls.
- **Consumption limits.** Budgets, loop and rate breakers, and a kill switch.
- **Audit.** A hash-chained, tamper-evident audit log, redacted at write time.

All of these are enforced by default. In the last self-test run, all 1059 cases passed (0 failed, 19 known gaps marked xfail).

**What holds back a stricter verdict**
1. **Authentication is optional for model calls** (`require_auth: false`). *Fixed for agents:* a bare `X-Aegis-Agent` claim of a registered agent without its key now gets 401 (GOV-01). Anonymous callers now get a read-only tool allowlist, and sessions are bound to the credential that opened them. Key scopes are still not enforced, and `X-Aegis-Member` is still header-asserted.
2. Some controls still ship in **monitor or log mode** in `balanced`: MCP-04 auth hygiene, and SIG-03 for unknown packages at MCP launch. INJ-05 goal drift and MCP-03 shadowing collisions now enforce.
3. **Detection quality without the optional local models.** Aegis ships with no models by default. On the held-out sets it then detects **38.9%** of injections; with the models installed, **89.6%**. In the same deterministic run, the MCP tool-poisoning corpus is caught 1/7 times in the red-team eval and 3/7 times in the self-test.
4. **Inter-agent (A2A) security** is now implemented. A2A-01 and A2A-02 are enforced at the gateway (`POST /a2a/{peer}`), using shared-secret HMAC signatures, not JWS or mTLS. The peers in the demo are simulated.
5. **There are no RAG or vector controls**, and **no factuality or grounding controls**.

## Coverage matrix

**Column notes**
- **Default mode** is the `balanced` profile (`config/policy.yaml` overlaid with `config/profiles/balanced.yaml`).
- **Evidence** cites existing tests and reports. All of them passed in the last recorded run; none were re-run today. Items marked "(static)" come from reading the code only.
- **LLM IDs.** The repo tags controls with LLM *2026* IDs (`src/aegis/policy/data/frameworks.yaml`). The matrix uses the official 2025 IDs and gives the code ID in parentheses.

| List | ID | Risk | Aegis controls | Default mode | Evidence | Verdict |
|---|---|---|---|---|---|---|
| LLM | LLM01 (code LLM01:2026) | Prompt Injection | INJ-01 signatures, INJ-02 classifier, MCP-02, SIG-01, EXE-03 taint breaker | INJ-01/02 enforce. INJ-02 is heuristic-only without models. EXE-03 asks for approval. | `tests/cases/inj.yaml` (INJ01-CLASSIC-EN/PL, -BASE64-WRAPPED, -UNICODE-TAG-SMUGGLING, -INDIRECT-IN-TOOL-RESULT, INJ02-DAN-PERSONA). Matrix INJ-01: 13/13 attack, 10/10 benign. `reports/eval.md` balanced: 66.6% detected deterministic (38.9% held-out); 92.4% semantic (89.6% held-out, FPR 5.1%). | **Covered.** Every mitigation a gateway can apply is on. Without the models, held-out detection is weak. |
| LLM | LLM02 (LLM02:2026) | Sensitive Information Disclosure | DLP-01 to DLP-08, ACT-02, ACT-03, CUS-01; buffered streaming | All enforce | `tests/cases/dlp.yaml` (50+ cases, e.g. DLP01-PESEL-TO-THIRD-PARTY, DLP02-PROXY-SECRET-NEVER-UPSTREAM, DLP04-DNS-LABEL-EXFIL). `reports/dlp-metrics.md`: 626 cases, P=R=1.000 on a curated set. Eval secrets 40/40. e2e audit/privacy 6/6, streaming/egress 6/6. | **Covered.** DLP-07 NER is heuristic-only without models. |
| LLM | LLM03 (LLM04:2026) | Supply Chain | SIG-01 signed feed, SIG-02 model artifacts, SIG-03 packages, MCP-01, MCP-03, GOV-02 | Enforce. Unknown packages need approval. | SIG02-PICKLE-OS-SYSTEM, SIG02-GGUF-SSTI-TEMPLATE, SIG03-LITELLM-BACKDOOR, SIG03-HALLUCINATED-NAME. Matrix: SIG-02 9/9 attack, 5/5 benign; SIG-03 4/4, 4/4; SIG-01 57/58 (xfail SIG01-LANGCHAIN-LC-SECRET). | **Covered** for the slice a runtime gateway can intercept. SBOM and vendor review are out of scope for a gateway. |
| LLM | LLM04 (LLM05:2026) | Data and Model Poisoning | SIG-02 (artifacts); INJ-01/02 and MCP-02 at inference time | Enforce | SIG02-* cases; MCP02-POISONED-ADD, -HIDDEN-UNICODE-DESCRIPTION | **Partial.** Malicious artifacts are covered. Training data is out of scope. Writes to memory or RAG are not scanned for injection (static). |
| LLM | LLM05 (LLM10:2026) | Improper Output Handling | DLP-06 exfil channels, EXE-01, EXE-02, ACT-02 (SQL), ACT-04 | Enforce | DLP06-ECHOLEAK-IMAGE, DLP06-ANSI-OSC8-LINK, EXE01-CURL-PIPE-SH, ACT02-DROP-PROD. Matrix PASS. | **Partial.** Shell, SQL, terminal and exfil-URL sinks are handled. No XSS sanitization: inline `<script>`, `onerror=` and `javascript:` pass through (static, `src/aegis/egress/channels.py:141-167`). |
| LLM | LLM06 (LLM03:2026) | Excessive Agency | GOV-03 RBAC, GOV-04 approval gate, GOV-06, ACT-01 to ACT-04, EXE-02, EXE-03, approvals engine | Enforce. INJ-05 is monitor. | GOV03-RESEARCH-CANNOT-EMAIL, GOV03-COPILOT-CANNOT-EXECUTE-TRADES, ACT01-OVER-HARD-CAP, ACT04-TERRAFORM-PROD-OWNER. Approvals & RBAC 69/69; hooks 44/44. | **Covered.** Caveat: an identity asserted by header alone gets that agent's RBAC. |
| LLM | LLM07 (LLM08:2026) | System Prompt Leakage | INJ-04 (extraction attempts, canary, n-gram overlap), DLP-02, DLP-05 | Enforce | INJ04-REPEAT-ABOVE, INJ04-CANARY-ECHO; `test_inj04.py::test_overlap_leak_blocks`; `test_streaming_egress.py::test_j3_canary_never_echoed`. Eval 4/4 (small n). | **Covered.** The canary must be planted manually (`plant_canary` is unused). INJ-04 fails open on internal errors. |
| LLM | LLM08 (LLM09:2026) | Vector and Embedding Weaknesses | None dedicated. Retrieved text is scanned incidentally as untrusted tool output. | – | None | **Not covered** |
| LLM | LLM09 (LLM07:2026) | Misinformation | SIG-03 hallucinated-package check only. INJ-03 is tagged but checks harm and topic, not facts. | SIG-03 enforce | SIG03-HALLUCINATED-NAME | **Not covered.** Only the hallucinated-package slice is covered, and the dashboard overclaims through the INJ-03 tag. |
| LLM | LLM10 (LLM06:2026) | Unbounded Consumption | BUD-01 token/cost budgets, BUD-02 local compute, EXE-04 loops/rate/kill switch, GOV-04 flood cap, `max_body_bytes` | Enforce | `tests/cases/bud.yaml`; `test_budgets_loops.py::test_b3_hard_limit_402_preflight`, `b5`, `b6_loop_breaker`, `b7_rate_limit_429`, `b8_kill_switch`, `b10_runaway_chain`. Suite 12/12. | **Covered.** Session caps can be reset by rotating headers; the org cap still binds. |
| ASI | ASI01 | Agent Goal Hijack | INJ-05 goal drift (enforce, approval; rule `send-internal-drift`), INJ-01, INJ-02, A2A-02 on peer replies, DLP-04, DLP-06, ACT-03, EXE-03 | Enforce in balanced. INJ-05 asks for approval. | Probes: an ungrounded internal `send_email` after an unrelated question → require_approval **INJ-05**; the grounded twin → allow. `/v1/messages` and `/v1/chat/completions` hijack → block INJ-01; "ignore the typo" → forwarded. An injected WebFetch output is quarantined by INJ-01. YAML: INJ-05 3/3 attack, 3/3 benign; `tests/cases/asi01.yaml` 5/5; `test_inj05.py` passes. | **Covered.** Residual: without the models, detection of paraphrased injections is weak, and the grounding check is heuristic. |
| ASI | ASI02 | Tool Misuse and Exploitation | GOV-03 RBAC + `arg_rules` (bcc, non-web schemes, negative amounts; apply to every caller), ACT-01 to ACT-03, EXE-02, GOV-04, DLP-04, MCP-03 (`collision_action: block`) | Enforce | Probes: `send_email` with bcc → block GOV-03, without bcc → allow. A metadata-IP fetch → block EXE-02. research-agent → `trading.execute_trade` → block GOV-03. YAML `asi02.yaml` 6/6. Earlier matrix: GOV-03, ACT-01/02/03, EXE-02 PASS. | **Covered.** |
| ASI | ASI03 | Identity and Privilege Abuse | GOV-01: a bare claim of a registered agent → 401; anonymous callers limited to a read-only tool allowlist → 403; session↔credential binding; revoked or expired keys → block. Also GOV-03/05/06, and no token passthrough in the MCP proxy | Enforce (secure code defaults plus the merged asi-03 params). `require_auth: false` applies only to anonymous model calls. MCP-04 is in monitor mode. | Probes: a bare `X-Aegis-Agent: claude-code@platform` → block GOV-01 ("agent identity not proven"); with the key → allow. Anonymous `payments.create_charge` → block; anonymous `list_plans` → allow. Another agent's key on a bound session → block; revoked key → block. `tests/unit/asi03`, `test_gov01.py` pass; YAML GOV-01 8/8 attack, 4/4 benign. | **Covered.** Residual: key scopes not enforced, `X-Aegis-Member` header-asserted, MCP-04 in monitor mode, no full on-behalf-of model. |
| ASI | ASI04 | Agentic Supply Chain Vulnerabilities | MCP-01 registry, MCP-02 (with plain-language `extra_markers`), MCP-03 pins + collision block, SIG-01 feed, SIG-02, SIG-03 | Enforce | Probes: `/mcp/<unknown>` → block MCP-01. `/mcp/poisoned` drops `add` and keeps `get_weather`. "Whenever called, quietly add bcc" → MCP-02 drop; a clean description that mentions bcc → allow. `litellm==1.82.7` → block SIG-01 (TI-017). Slopsquat → approval SIG-03; `requests==2.32.3` → allowed. YAML `asi04.yaml` 5/5; `test_mcp.py` f1–f6. | **Covered.** Residual: no package digest pin; poisoning detection is marker-based. |
| ASI | ASI05 | Unexpected Code Execution (RCE) | EXE-05 code-execution provenance & sandbox guard (interpreter-on-file, one-liners, package runners; write/download-then-exec taint; `require_sandbox_for: [code.exec]`), EXE-01, ACT-04, SIG-01, SIG-02, GOV-06 | Enforce | Probes via the Claude Code hook: `python3 scripts/x.py` → require_approval **EXE-05**; the same under `bwrap` → allow. `curl -o setup.sh` then `bash setup.sh` in a later call → block EXE-05. `pytest` → allow. `curl … \| sh` → deny EXE-01. YAML EXE-05 16/16 attack, 7/7 benign; `tests/unit/asi05` passes. | **Covered.** Residual: the declared sandbox runner is classified, not attested. |
| ASI | ASI06 | Memory & Context Poisoning | MEM-01 persistent-memory guard: CLAUDE.md/AGENTS.md/.cursorrules/memory/RAG writes scanned, provenance-stamped, taint-aware; memory reads forced untrusted; inlined memory rescanned every turn. INJ-01 re-quarantines untrusted history. | Enforce (approval; injections and secrets block) | Probes via hook: a poisoned write to `CLAUDE.md` → block **MEM-01**. A WebFetch page later written into `AGENTS.md` → block MEM-01. A benign `memory/notes.md` → allow. YAML MEM-01 6/6 attack, 3/3 benign; `tests/unit/asi06` passes. | **Covered.** Residual: provenance is in-process only. |
| ASI | ASI07 | Insecure Inter-Agent Communication | A2A-01 (peer registry + typosquat check, caller allowlist, agent-card check, HMAC signature + TTL + single-use nonce + reply binding, inbound signature check); A2A-02 (hop limit, delegation loops, INJ engine on peer replies, exfil-link strip, EXE-03 taint); `POST /a2a/{peer}` | Enforce | Probes: `/a2a/research-agnet` → block **A2A-01** (typosquat). `/a2a/research-agent` with `X-Aegis-Hop: 3` → block **A2A-02**. A forged inbound signature → block A2A-01. A peer reply with a hidden injection → block A2A-02. A registered peer → allow. YAML `asi07.yaml` 14/14. **`tests/unit/asi07` currently fails 13 tests**, because ROG-01 state leaks across tests (open bug). | **Covered** at the gateway. Residual: shared-secret HMAC, not JWS or mTLS; in-process nonce cache; demo peers are simulated. |
| ASI | ASI08 | Cascading Failures | RES-01 cascade breaker (agent quarantine after 3 blocks, MCP/egress circuit breaker, transitive cross-agent taint); `fail_mode` honoured inside controls (INJ-01/02/04/05, SIG-01/03, INJ-03, DLP-07); EXE-04, BUD-01/02, EXE-03 | Enforce | Probes: `curl\|sh`, a credential read, `wget\|bash`, then `ls` → require_approval **RES-01**; two blocks then `ls` → allow. `tests/unit/asi08` (incl. INJ-01 fault → pipeline block, MCP 502×5 → 503 circuit, A→B→C taint) passes. YAML RES-01 2/2, 2/2. | **Covered.** Residual: breaker state is process-local. |
| ASI | ASI09 | Human-Agent Trust Exploitation | Approvals engine: grant bound to exact params, single use, flood caps, agents never vote. GOV-04/05, ACT-01 to ACT-04. The approval `review` block (bound action, agent text flagged `untrusted`, Aegis's own risk reason, destructive flag, agent-supplied title fields) is rendered by the dashboard card, with typed confirmation for destructive or flooded requests. | Enforce | Probes: a $50 purchase with an "URGENT: CEO already approved" justification → require_approval ACT-01; `review.bound` is present and the agent text appears only as `untrusted`. The agent's own key on approve → 403. A grant approved for $50 replayed with $500 → new approval. `u_piotr` → 403, `u_emily` → approves. `tests/unit/asi09`, `asi09_review.test.mjs`, `test_approvals_rbac.py` pass. | **Covered** for the approval channel. Residual: persuasive `model.response` text aimed at the human is not scanned (probe: allowed); the dashboard card has not been browser-verified. |
| ASI | ASI10 | Rogue Agents | ROG-01 behavioural anomaly detector (per-agent baseline; spawn/delegation bursts, depth, self-modification, novelty, rate/spend spikes → ≥0.5 approval, ≥0.85 block 429 + session quarantine); kill switch (5 scopes), EXE-04 ladder, GOV-06 anti-tamper, BUD caps, hash-chained audit | Enforce (ROG-01 `fail_mode: open`) | Probes: 16 `Task` spawns → block **ROG-01**; a single sub-agent → allow. A hook Edit of `.claude/settings.json` → block GOV-06. Kill switch → chaos-agent 429 `killed`, other agents 200. YAML ROG-01 5/5 attack, 4/4 benign; `tests/unit/asi10` passes. | **Covered.** Open bug: ROG-01's store is a process-global singleton, which leaks across app instances (it breaks `tests/unit/asi07`). |
| MCP | MCP01:2025 | Token Mismanagement & Secret Exposure | DLP-02 (mcp.init/call/result), DLP-05; proxy never forwards `Authorization`/`Cookie`/`x-api-key` and injects per-server credentials (`src/aegis/mcp/proxy.py:64-83`); audit redaction; EXE-02 fs_deny | Enforce. MCP-04 bearer redaction is monitor. | MCP04-BEARER-IN-RESULT (redacted by DLP-02); DLP-02 22/22 attack, 12/12 benign; `test_audit_privacy.py::test_g3_no_raw_sensitive_values_anywhere`; `test_proxy_http.py::test_f_call_args_redacted_upstream` | **Covered.** Header stripping has no test. |
| MCP | MCP02:2025 | Privilege Escalation via Scope Creep | GOV-03, MCP-01 `allowed_tools`, MCP-04 forbidden scopes, GOV-04 | GOV-03 enforce. **MCP-04 monitor.** Every server has `allowed_tools: ["*"]`. | GOV03-MCP-RESEARCH-CANNOT-EMAIL; `test_controls.py::test_mcp04_scope_and_smuggling` | **Partial.** Anonymous or header-asserted callers bypass per-agent RBAC. The scope check only logs. |
| MCP | MCP03:2025 | Tool Poisoning | MCP-02 drops poisoned tools, MCP-03 sha256 pins and rug-pull block, INJ-01/02 on `mcp.list`, SIG-01 TI-012 | Enforce. **Shadowing collision is log only.** | `test_mcp.py::test_f2_poisoned_tool_hidden`, `::test_f3_rug_pull` (admin re-pin), `::test_f6_tool_shadowing` (only with block overridden). Corpus AGT-MCP-001..007: 3/7 in self-test (4 xfail); eval 1/7. | **Partial.** Rug pulls and marker-style poisoning are blocked. Plain-language poisoning is mostly missed. |
| MCP | MCP04:2025 | Software Supply Chain Attacks & Dependency Tampering | MCP-01 exact launch command and transport, MCP-03 pins, SIG-03, SIG-01 | Enforce. SIG-03 unknown package at `mcp.init` is log only. | MCP01-LAUNCH-CMD-EXFIL and MCP01-KNOWN-BAD-PACKAGE pass, but MCP-01 decided both as an unregistered server; the package check was not exercised. `test_controls.py::test_mcp01_stdio_launch` | **Partial.** No sha256 or digest integrity (`McpServerConfig.package` is `name@version` only). HTTP servers are trusted by URL. |
| MCP | MCP05:2025 | Command Injection & Execution | EXE-01 on `mcp.call`/`mcp.init`, EXE-02 SSRF, SIG-01 TI-010/011 (CVE-2025-6514, CVE-2025-49596), transport rejects header smuggling | Enforce. The MCP-04 OAuth-URL check is monitor. | Matrix EXE-01 15/15, 8/8; EXE-02 15/15, 7/7 (metadata IP, hex loopback); `test_proxy_http.py::test_e_modern_header_smuggling`. The MCP04-*-OAUTH cases were decided by MCP-01, so the OAuth validator is untested. | **Covered** for traffic through the gateway. Injection bugs inside server code are the server's job. |
| MCP | MCP06:2025 | Prompt Injection via Contextual Payloads | INJ-01 on `mcp.result`/`mcp.list` (quarantine), INJ-02, MCP-02, EXE-03, DLP-05 | Enforce. INJ-02 heuristic without models. EXE-03 asks for approval. | `test_proxy_http.py::test_g_result_writeback_content_and_structured`; eval indirect injection 91.7% (tuning set); held-out 38.9% det / 89.6% sem | **Partial.** Weak without models. Taint flows go to approval rather than being blocked. |
| MCP | MCP07:2025 | Insufficient Authentication & Authorization | GOV-01 keys, revocation, spoof check; Origin allowlist; loopback bind; RBAC on re-pin and approvals | **`require_auth: false`, `anonymous_action: allow`** | GOV-01 5/5 attack, 4/4 benign; `test_f3_rug_pull` (member re-pin gets 403); approvals RBAC 69/69 | **Partial.** Authorization is solid, but authentication is off by default. |
| MCP | MCP08:2025 | Lack of Audit and Telemetry | Hash-chained append-only audit log, redacted at write time, OCSF/CSV/JSONL export; every verdict recorded; tool changes audited; decision headers | Always on | `test_audit_privacy.py::test_g1_chain_verifies`, `::test_g4_chain_break_detected`; `test_chain.py::test_tamper_byte_flip_delete_swap_truncate` | **Covered** |
| MCP | MCP09:2025 | Shadow MCP Servers | MCP-01 `unknown_server_action: block`; MCP inventory; gateway-only client config (`--strict-mcp-config`); GOV-06, EXE-02 and SIG-01 TI-015 protect MCP configs | Enforce | `test_mcp.py::test_f1_unknown_server`; MCP01-SHADOW-SERVER; ERR-MCP-UNKNOWN-SERVER | **Partial.** Blocks only servers reached through Aegis. Nothing discovers servers outside that path. `~/.cursor/mcp.json` is missing from fs_deny. |
| MCP | MCP10:2025 | Context Injection & Over-Sharing | DLP-01 and DLP-04 on `mcp.call` args, DLP-08 per-session vault (no rehydration to third parties), DLP-05/07 on results, EXE-03 | Enforce. EXE-03 asks for approval. | `test_mcp.py::test_f5_args_exfil_blocked`; `test_proxy_http.py::test_f_call_args_redacted_upstream` (PESEL sent upstream as `[PESEL_1]`) | **Partial.** Over-sharing to servers is minimized. Context isolation between tasks or agents is not addressed. |

## Top gaps and cheapest fixes

None of these fixes are implemented. They are ranked by how many items each one would move and how little it costs.

> **Update (ASI re-verification, 2026-10-04).** The following have since been implemented and verified:
> - **#1** for agents: header claims are refused, anonymous callers get least privilege, and sessions are bound to credentials.
> - **#2** for INJ-05 and MCP-03.
> - **#3**: `fail_mode` is now honoured inside controls.
> - **#4**: MCP-02 markers.
> - **#5**: A2A-01/02.
> - **#7** for memory (MEM-01) and code execution (EXE-05).
> - **#8**: the ASI tags were cleaned up, and `/api/coverage` is now evidence-based.
>
> The rest of this list is unchanged.

1. **Authentication off by default** (ASI03, ASI10, MCP02, MCP07, LLM06, LLM10).
   - **Fix:** in `config/policy.yaml:107`, set `defaults.require_auth: true`, and in the GOV-01 params (`:585`) set `anonymous_action: block` for the `mcp`, `hook` and `egress` sources. The Claude Code hook and the MCP configs already send per-agent keys (`src/aegis/mcp/claude_config.py:78`), so mostly the header-only `curl` examples in the README and JUDGES need updating.
   - **Smaller alternative:** keep header identity but mark it `authenticated=False` in `src/aegis/org/identity.py:252-253`, and treat it as an unknown agent in GOV-03.
2. **Monitor- or log-only defaults on controls that already work** (ASI01, ASI02, ASI04, MCP02, MCP03, MCP04). Each is a one-line change:
   - `config/profiles/balanced.yaml:37` `MCP-04` → `enforce`
   - `balanced.yaml:35` `INJ-05` → `enforce`. Its only action is `require_approval`.
   - `policy.yaml:1496` `MCP-03 collision_action: block`. `test_f6` already proves this path.
   - `policy.yaml:1579` `SIG-03 unknown_action_mcp_init: require_approval`
3. **Controls fail open on internal exceptions despite `fail_mode: closed`** (ASI08, LLM07; nine controls including INJ-01 and INJ-04).
   - **Fix:** re-raise in each control's `except` branch, e.g. `src/aegis/controls/injection/inj01_signatures.py:168-175` and `inj04_hidden_context.py:71-78`, so the pipeline (`src/aegis/core/pipeline.py`) applies the configured `fail_mode`.
   - Update `test_inj01.py::test_internal_error_degraded_allow`, which currently locks the fail-open behaviour in.
4. **Plain-language MCP tool poisoning** (MCP03, ASI04).
   - **Fix:** add behavioural markers such as "whenever <tool> is called", `bcc`, "always also send" and `fetch <url>?d=` to `MCP-02 params.extra_markers` (`policy.yaml:1484`) or to `src/aegis/mcp/detect.py`.
   - Then promote corpus rows AGT-MCP-002, -004 and -006 into `tests/cases/mcp.yaml`.
5. **Inter-agent traffic** (ASI07).
   - **Fix:** add `a2a.result` to the `applies_to` of INJ-01 and INJ-02 (`inj01_signatures.py:137`, `inj02_classifier.py:44`). Each is a one-line change.
   - Drop the ASI07 tag from GOV-01 until A2A-01 exists.
6. **XSS in model output** (LLM05).
   - **Fix:** add an active-content detector to `find_channels` in `src/aegis/egress/channels.py` covering `<script>` without `src`, `on*=` attributes, and `javascript:`/`vbscript:`/`data:text/html` URLs.
   - Add DLP06-XSS-* cases to `tests/cases/dlp.yaml`.
7. **Memory, RAG and code execution** (ASI06, LLM04, LLM08, ASI05).
   - Add `**/CLAUDE.md`, `**/AGENTS.md` and `**/.claude/**/memory/**` to GOV-06 `protected_paths` (`policy.yaml:683`).
   - Add a `rag.read` action rule so ACT-02 applies collection sensitivity (`policy.yaml`, around line 215).
   - Extend the `code.exec` classifier to cover an interpreter run on a file (`policy.yaml:232-233`).
8. **Honest labelling on the dashboard.** `src/aegis/policy/views.py:190-211` marks an item "covered" if *any* mapped control is enforced, so the Coverage page shows more green than this document.
   - Remove the `LLM07:2026` (Misinformation) tag from INJ-03 and the `ASI07` tag from GOV-01.
   - Rename MCP06 to "Prompt Injection via Contextual Payloads" in `frameworks.yaml:38`.
   - Relabel `web/src/mocks/security/coverage.ts`. It mixes the 2025 order with `:2026` suffixes and uses a stale MCP06 title.
   - Add a 2025↔2026 LLM ID crosswalk.
9. **Test gaps (cheap, no product change).**
   - Give MCP04-JS-OAUTH-ENDPOINT, MCP04-CMD-INJECTION-ENDPOINT and MCP01-KNOWN-BAD-PACKAGE a *registered* server in `tests/cases/mcp.yaml`, so that MCP-04 and the package feed are what decide them, not MCP-01.
   - Add a proxy test asserting that an inbound `Authorization` header never reaches the upstream.
   - Add a test for the EXE-04 burn-rate path.

## Methodology

- **Sources for the lists**, all checked on 2026-10-04:
  - LLM Top 10 2025 titles from genai.owasp.org/llm-top-10.
  - Agentic Top 10 2026 titles from the genai.owasp.org announcement of 9 Dec 2025.
  - MCP Top 10 from owasp.org/www-project-mcp-top-10. This list is in beta, Phase 3 pilot testing, and IDs carry the `:2025` suffix.
- **Title drift.** The internal research summary (`research/goldman/01-threat-model-controls.md`) and `src/aegis/policy/data/frameworks.yaml` use an older MCP06 title ("Intent Flow Subversion"). They also use LLM *2026* IDs and names, which that research doc itself marks as unverified. This assessment uses the official titles and the 2025 LLM IDs, with the code ID in parentheses.
- **Evidence** is code and config plus *existing* test definitions and generated reports:
  - `reports/matrix.md` and `reports/results.json`: self-test generated 2026-10-04T04:05Z at git `873d493`, hermetic mode, profile `balanced`, **semantic models off**, feed serial 1 (seed). 1059 cases: 1024 pass, 16 pass by another control, 19 xfail, 0 fail.
  - `reports/eval.md` and `reports/eval.json`: red-team corpus of 1234 rows, generated 2026-10-03T23:41Z, deterministic and semantic runs.
  - `reports/dlp-metrics.md`.
- **No tests were re-run for this assessment.** The working tree may differ from the commit the reports were generated at.
- Findings marked "(static)" come from reading the code and were not exercised by a test or probe.
- **Verdicts** apply to the default `balanced` profile:
  - **Covered:** controls are enabled and enforcing by default, and a passing test or report shows they work. Known residual gaps are listed in the cell.
  - **Partial:** a material part of the risk is unmitigated by default, or the mitigation is monitor-only, disabled, or untested.
  - **Not covered:** no effective default control.
  - **Out of scope:** the risk lies outside what a gateway can see. No whole item was rated out of scope. Sub-risks that are out of scope, such as training-data poisoning, vendor due diligence, and bugs inside MCP server code, are noted in the cells.
- **Calibration note.** Four reviewers worked in parallel, one per slice, and one reviewer merged and checked the results. Two pairs of verdicts rest on overlapping evidence and are judged at different scopes:
  - **LLM01 (Covered) and MCP06 (Partial).** Same weakness in detection without models. LLM01 is judged on whether the full set of gateway mitigations is present; OWASP itself says injection cannot be fully prevented. MCP06 is judged on the MCP tool-result and tool-description path, where the measured poisoning corpus is weak.
  - **ASI04 (Covered) and MCP04 (Partial).** ASI04 covers the broader agent supply chain: packages, model artifacts and MCP. MCP04 is judged on server integrity alone, where digest pinning is missing.
- **Re-checking a verdict.** Run `make test` to regenerate `reports/matrix.md`, and `python -m tests.eval` to regenerate `reports/eval.md`. Then compare the cited case IDs.
