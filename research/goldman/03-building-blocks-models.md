# 03 — Building blocks: OSS guardrails, gateways, small local models

Track: Goldman Sachs "AI Control Layer" (HackYeah 2026, Kraków, 3–4 Oct 2026)
Compiled: 2026-10-03
Target machine: Apple **M2** (4P+4E CPU), **8 GB RAM**, macOS 27.0, Ollama 0.24.0 (signed in to Ollama Cloud: `minimax-m2.5:cloud` is already listed), Python 3.14, Node 24, Go, Rust.

**How this was checked.** Versions, release dates, licences, gating, parameter counts and file sizes come from live PyPI JSON, the Hugging Face API (`/api/models/...?blobs=true`), the GitHub API and the ollama.com library pages, all queried on 2026-10-03. Benchmark figures are quoted from the cited sources. **Latency figures for this M2 are estimates.** They are scaled from llama.cpp's published M2 numbers and the vendors' own reports. Run the 10-minute measurement script in §7.4 in hour 1 to replace them.

---

## 0. TL;DR

**Build vs fork: build our own thin gateway and reuse components.** Don't fork a full gateway.
- Write a single-process Python gateway (FastAPI + uvloop + httpx, ~1.5–2.5k LOC) with an OpenAI-compatible ingress, an MCP proxy (official `mcp` SDK), a YAML policy that hot-reloads, a detector cascade, SQLite audit and budgets, and a small static dashboard.
- Reuse components rather than whole projects:
  - **Presidio** (PII, including a Polish PESEL recognizer)
  - **gitleaks rules** (222 secret regexes, MIT)
  - **NeMo Guardrails YARA rules** (code/SQLi/XSS/template injection, Apache-2.0) and **Vigil/Cisco YARA rules**, run through `yara-x`
  - **LiteLLM's pricing JSON** (vendored as a file, not the package) for commercial cost
  - **ONNX Runtime** encoders and **Ollama** for small generative guards
- Why not fork:
  - **LiteLLM proxy**: budgets need Postgres, the useful guardrail features are Enterprise-gated, it is heavy on 8 GB, and it had a PyPI supply-chain compromise in March 2026.
  - **agentgateway**: excellent, but it's a Rust codebase. Use it as a reference design, plus an optional "deploy behind agentgateway via webhook guard" story for the scalability criterion.
  - **Kong, Agent Router (ex-Envoy AI GW), Plano, Microsoft/Docker MCP gateways**: need Kubernetes, Envoy or Docker Desktop, or are Enterprise-gated. That doesn't fit 24 h on 8 GB.
  - Smaller MIT pieces you could lift code from: **Lasso mcp-gateway** (Python MCP stdio proxy plus plugin pattern) and **IBM ContextForge's** plugin hook names.

**Minimal model set** (resident ≈ 1.8 GB, peak ≈ 2.5 GB including the on-demand judge):

| # | Role | Model | Run with | Disk | RAM (est.) | M2 latency (est.) | Licence / gating |
|---|---|---|---|---|---|---|---|
| 1 | Prompt injection, direct and indirect, multilingual (incl. Polish), 8k context | `Horizon-Labs/prompt-injection-guard-small` v2 (mmBERT-small, 141M) | ONNX Runtime CPU, int8 file `onnx/model_quantized.onnx` | 268 MB | ~0.35 GB | 15–40 ms (vendor: 35 ms int8 / 36 ms fp32, hardware not stated) | Apache-2.0, ungated. **Released 2026-09-23 and the numbers are vendor-run: validate in hour 2.** Fallbacks: PIGuard (MIT) or ProtectAI v2 |
| 2 | High-precision jailbreak/injection vote (very low FPR) | `Llama-Prompt-Guard-2-22M` (int8 ONNX mirror `gravitee-io/Llama-Prompt-Guard-2-22M-onnx`, `model.quant.onnx`) | ONNX Runtime CPU | 72.5 MB | ~0.12 GB | 3–15 ms | Llama 4 Community License. The Meta repo is **gated with manual approval**; the gravitee mirror is ungated, which the licence permits as long as the notice and "Built with Llama" attribution are kept |
| 3 | Semantic signature feed (kNN against known attacks) and config-defined topic rules | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, `onnx/model_qint8_arm64.onnx` | ONNX Runtime CPU (or `fastembed`) | 118 MB | ~0.15 GB | 5–15 ms | Apache-2.0, ungated |
| 4 | PII detection and masking | Presidio analyzer/anonymizer + spaCy `en_core_web_sm` (12 MB), optional `pl_core_news_sm` (20 MB) | in-process | ~35 MB | ~0.2 GB | 5–20 ms | MIT |
| 5 | Harmful content on input and output, refusal detection, 119 languages | `Qwen3Guard-Gen-0.6B`, GGUF Q4_K_M (`hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M`); use Q8_0 (805 MB) if RAM allows | Ollama (Metal), `raw` prompt | 484 MB | ~0.6–0.8 GB at num_ctx 2048 | ~0.2–0.4 s warm | Apache-2.0, ungated |
| 6 | (on demand) LLM-as-judge for natural-language custom policies; doubles as the local demo upstream LLM | `qwen3.5:0.8b` (Ollama tag 1.0 GB incl. vision; text-only `hf.co/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M` 533 MB) or `qwen3:0.6b` (523 MB) | Ollama, `think:false`, JSON-schema `format` | 0.5–1.0 GB | ~0.6–1.1 GB | ~0.3–0.7 s | Apache-2.0 |
| alt-5 | Swap-in content guard if you need **custom categories from config** | `llama-guard3:1b` (official Ollama tag, Q4_K_M) | Ollama, raw prompt with your own S14+ categories | 955 MB | ~1.1–1.3 GB | ~0.3–0.6 s | Llama 3.2 Community; HF gated, Ollama ungated |

The deterministic tier needs no models: regex/RE2, gitleaks rules, YARA via `yara-x`, Aho-Corasick deny-lists, plus a normalizer for Unicode NFKC, zero-width and tag characters, homoglyphs and base64/hex/rot13/leet decoding. It costs about 50 MB and under 2 ms.

**Fallback when the model tier is slow or down.**
- The cascade is: deterministic tier (always, synchronous) → encoders (always, run in parallel) → Ollama guard (only when needed).
- Every detector has a timeout and an `on_timeout`/`on_error` setting: `block | allow_audited | degrade`. Defaults:
  - **fail-closed** for MCP tool calls with side effects, egress of secrets/PII to remote providers, and output secrets
  - **degrade** (encoder verdict with a stricter threshold, request tagged `unverified`) for chat input
  - **fail-open-audited** only for low-risk output moderation when explicitly configured
- A circuit breaker switches the gateway into "degraded" mode, and the dashboard shows it.

**Top gotchas.**
1. Python 3.14 breaks `nemoguardrails`, `guardrails-ai` (both `<3.14`) and `llm-guard` (`<3.13`). The ONNX/Presidio/spaCy/yara-x/re2 stack has 3.14 wheels. Use a `uv` venv on Python 3.13 if you want any of the frameworks.
2. Meta (Prompt Guard 2, Llama Guard) and Google (ShieldGemma, Gemma) HF repos are **gated**. Meta's approval is manual and can take hours, so request access now or use the Ollama tags and the gravitee ONNX mirror.
3. **LLM Guard and the ProtectAI HF models are archived and unmaintained.**
4. LiteLLM 1.82.7/1.82.8 were **malicious PyPI releases** (24 Mar 2026). If you use LiteLLM at all, pin a known-good version with hashes. Better: vendor only its pricing JSON.
5. Presidio defaults to `en_core_web_lg` (400 MB wheel, ~0.5 GB RAM). Configure `en_core_web_sm`.
6. Ollama's `llama-guard3` template **hardcodes the 13 categories**. Custom categories need `raw: true`. Qwen3Guard has no official Ollama tag; community GGUFs may not carry its moderation chat template, so build the prompt yourself with `raw`.
7. Qwen3/Qwen3.5 thinking mode must be off (`think: false`), or the judge emits hundreds of tokens.
8. On 8 GB:
   - no Docker Desktop: its VM eats 2–4 GB, and that rules out the Docker MCP gateway, Postgres in Docker and Plano
   - no `torch` in the hot path: import alone is ~0.3–0.5 GB RSS
   - one resident Ollama model, `num_ctx` 2048
   - a static or HTMX dashboard instead of a Next.js dev server
9. gitleaks regexes are Go RE2. Python `re` rejects mid-pattern `(?i)`, so use `google-re2` (cp314 wheels) or the `regex` module.
10. trufflehog is **AGPL-3.0**: don't copy its detectors into our code. Helicone ai-gateway is GPL-3.0. Several 2026 guard models and datasets are **CC-BY-NC** (sheltron prompt-guard-68m, piiranha, Qualifire and Mindgard eval sets): eval only, never ship.

---

## 1. Guardrail libraries (survey)

| Library | Licence | Latest release / activity | Py 3.14? | What it gives us | Verdict for 24 h |
|---|---|---|---|---|---|
| **LLM Guard** (Protect AI) — github.com/protectai/llm-guard | MIT | **Archived** (README banner: "no longer under active development", models included). PyPI 0.3.16 (2025-05-19) | No (`<3.13`) | Best scanner taxonomy around. Input: Anonymize, BanSubstrings, BanTopics, Code, Gibberish, InvisibleText, Language, PromptInjection, Regex, Secrets, Toxicity, TokenLimit. Output: Deanonymize, NoRefusal, MaliciousURLs, Relevance, Sensitive, JSON… | **Reference only.** Copy the scanner taxonomy and its Secrets plugin regex list (MIT); don't depend on it |
| **NVIDIA NeMo Guardrails** — github.com/NVIDIA-NeMo/Guardrails | Apache-2.0 | v0.24.1 (2026-09-16), very active | No (`<3.14`) | Colang flows, LLM self-check rails, `injection_detection` with **YARA rules (code.yara, sqli.yara, template.yara, xss.yara)**, jailbreak heuristics (perplexity with **gpt2-large, 774M**, too heavy), model-based jailbreak detect (NemoGuard JailbreakDetect = snowflake-arctic-embed-m-long + random forest, 44 MB ONNX, NVIDIA Open Model License), Presidio/GLiNER/Llama Guard/regex/topic-safety/tool-safety rails, Ollama as engine | **Steal the YARA rules and rail ideas.** A full runtime adds Colang learning curve and an extra LLM round-trip per rail |
| **Guardrails AI** — github.com/guardrails-ai/guardrails | Apache-2.0 | v0.11.0 (2026-08-14) | No (`<3.14`) | Validator framework plus Hub (DetectJailbreak, ToxicLanguage, DetectPII, SecretsPresent, CompetitorCheck…). Output structuring/re-asking | **Skip.** Hub install needs a (free) Hub token via `guardrails configure`, and most validators pull torch |
| **Microsoft Presidio** — github.com/data-privacy-stack/presidio (moved from microsoft/) | MIT | 2.2.364 (2026-07-22), active | **Yes** (`<3.15`) | Regex and checksum recognizers (credit card + Luhn, IBAN, email, phone, IP, MAC, URL, UUID, crypto, date) plus country packs including **Poland PL_PESEL**. NER through spaCy/stanza/transformers/**GLiNER**. Anonymizer operators (replace/mask/hash/**encrypt**, reversible) | **Use it.** It's the PII backbone |
| **Rebuff** — github.com/protectai/rebuff | Apache-2.0 | **Archived**, last push 2024-08 | No (`<3.13`) | Heuristics + LLM check + vector DB of past attacks + **canary tokens** | Ideas only: canary token in the system prompt, leak detection on output |
| **Vigil** — github.com/deadbits/vigil-llm | Apache-2.0 | Alpha, last push 2024-01, not on PyPI | n/a | YARA heuristics, vector-similarity against attack corpus with auto-update, transformer scanner, prompt–response similarity, canary tokens, sentiment | **Steal the YARA signatures and the "auto-updating vector DB" pattern** (our item 3 above) |
| **Meta LlamaFirewall** (PurpleLlama) — github.com/meta-llama/PurpleLlama/tree/main/LlamaFirewall | PyPI `llamafirewall` 1.0.3 (2025-05); repo-level licence is the Llama licence | Low activity | Unclear | PromptGuard 2 scanner, AlignmentCheck (agent goal-hijack check, needs a capable LLM, default remote), CodeShield (insecure-code via Semgrep/regex), regex scanner | Ideas only: AlignmentCheck concept and CodeShield for "insecure code in output" |
| **mozilla-ai any-guardrail** — github.com/mozilla-ai/any-guardrail | Apache-2.0 | 0.7.7 (2026-08-24), active | `>=3.11` | One API over ~40 guard models, including **bielik_guard**, qwen3_guard(+stream), prompt_guard, protectai, injec_guard (PIGuard), gli_guard, llama_guard, shield_gemma, granite_guardian, nemotron_content_safety, wild_guard, gpt_oss_safeguard. Returns a uniform `GuardrailOutput` (valid/score/categories/latency) | **Use offline** as an eval harness and for reference prompt templates and parsers. Not in the hot path (pulls torch/transformers) |
| **Microsoft Agent Governance Toolkit** — github.com/microsoft/agent-governance-toolkit | MIT | v4.1.0 (2026-06-09), active | n/a | Deterministic allow/deny policy over tool calls (YAML / OPA-Rego / Cedar), MCP security gateway, OWASP Agentic Top 10 mapping; claims 0.012 ms p50 per rule | Reference for **policy schema and OWASP-Agentic mapping** in our YAML |
| **Invariant guardrails** — github.com/invariantlabs-ai/invariant (now Snyk) | Apache-2.0 | last push 2026-01 | n/a | Rule DSL over agent traces, e.g. **toxic flows** ("read private data → send email") | Steal the idea of sequence/flow rules for MCP |
| **Lakera Guard** | Commercial SaaS (acquired by Check Point, 2025) | — | — | Top PINT score (95.2%) | Not usable (no key, closed). Open stand-ins are in §5 |

**Lakera-style open detectors** (classifier APIs that score a prompt for injection or jailbreak) are covered in §5. The candidates are Prompt Guard 2, ProtectAI v2, PIGuard, Horizon-Labs, Wolf Defender, NemoGuard JailbreakDetect and Bielik Guard.

---

## 2. Secret scanners and reusable signature rule sets

| Source | Licence | Size | How to reuse |
|---|---|---|---|
| **gitleaks** `config/gitleaks.toml` — github.com/gitleaks/gitleaks (v8.30.1, 2026-03) | MIT | **222 rules** (97 KB). Each rule has `regex`, `keywords` prefilter and `entropy` | Load the TOML at startup. Prefilter with Aho-Corasick on `keywords`, then run the regex via **`google-re2`** (Go-RE2 syntax; Python `re` chokes on mid-pattern `(?i)`). Add a Shannon-entropy gate |
| **detect-secrets** (Yelp) — v1.5.0 (2024-05), still maintained | Apache-2.0 | 27 plugins (AWS, GitHub, GitLab, JWT, OpenAI, private keys, Slack, Stripe, Telegram, Twilio, high-entropy, keyword…) | Port the high-entropy and keyword heuristics |
| **trufflehog** — v3.97.9 (2026-09) | **AGPL-3.0** | 800+ detectors, with live verification against vendor APIs | **Don't copy code.** At most invoke the binary as a separate process; verification calls the internet, so keep it off |
| **Lasso mcp-gateway** `plugins/guardrails/basic.py` | MIT | ~15 token regexes with replacement placeholders (GitHub, AWS, JWT, GitLab, HF, Slack…) | Good "mask with typed placeholder" UX pattern |
| **LLM Guard Secrets scanner** | MIT | detect-secrets + ~90 custom plugins | Regex source (archived repo, still readable) |
| **NeMo Guardrails YARA** `library/injection_detection/yara_rules/{code,sqli,template,xss}.yara` | Apache-2.0 | 4 rule files | Run via **`yara-x`** (Python bindings, abi3 wheels, Py 3.14 OK) on model **output** and **tool arguments** |
| **Vigil YARA rules** | Apache-2.0 | Injection/jailbreak phrase signatures | Seed for "historical exploit signature feed" |
| **Cisco mcp-scanner** YARA rules — github.com/cisco-ai-defense/mcp-scanner (4.8.6, 2026-10-02) | Apache-2.0 | Tool-poisoning / malicious tool-description rules (YARA engine runs offline; LLM and Cisco API engines are optional) | Run on MCP `tools/list` descriptions (tool-poisoning detection) |

---

## 3. AI gateways and proxies: fork, extend or learn?

| Project | Lang / licence | Latest / activity | Relevant features | Fork/extend in 24 h on 8 GB? |
|---|---|---|---|---|
| **LiteLLM proxy** — github.com/BerriAI/litellm | Python. MIT, except `enterprise/` (commercial) | v1.103.2 (2026-10-01), 60k★ | OpenAI-compatible front for 100+ providers. Guardrail hooks `pre_call / during_call / post_call / logging_only` plus a custom guardrail class. Built-in integrations (Presidio, Lakera, Bedrock, Azure, OpenAI moderation, Guardrails AI, Lasso, Pangea, Model Armor, generic API). Budgets at global/team/key/user/end-user scope. MCP gateway. Admin UI | **Not recommended.** (a) Every budget is enforced from **Postgres**; DB-less deployments cap nothing. (b) **Enterprise-only**: per-key guardrails, tag-based guardrails, model-level guardrail assignment, model-specific budgets. (c) Heavy RSS and dependency tree. (d) **Supply-chain compromise**: 1.82.7/1.82.8 shipped a credential-stealing `.pth` (24 Mar 2026). Judges would see "configured LiteLLM", not our layer. **Do reuse:** the `model_prices_and_context_window.json` pricing table (MIT), vendored as a file |
| **Portkey gateway** — github.com/Portkey-AI/gateway | TypeScript, MIT | v1.15.2 (2026-01-12), last push 2026-05 (slowing) | Fast router. Deterministic guardrail plugins (regexMatch, contains, jsonSchema, wordCount, validUrls, webhook…) plus paid partner guardrails | Budgets and virtual keys live in hosted Portkey, not OSS. **Learn from** its plugin manifest and hook shape |
| **agentgateway** (Linux Foundation → Agentic AI Foundation) — github.com/agentgateway/agentgateway | Rust, Apache-2.0 | v1.6.0 (2026-10-02), 5.2k★, very active | **MCP** (stdio/SSE/streamable HTTP, federation, OpenAPI→MCP, OAuth), **A2A**, LLM gateway with budgets/spend controls, **prompt guards** (`regex` mask/reject/audit, `openAIModeration`, **`webhook`**, Bedrock, Model Armor, Azure Content Safety; audit mode; multi-layer). CEL RBAC, rate limits, OTel, built-in UI, standalone binary with YAML that **hot-reloads** (except the top-level `config:` block) | **Don't fork** (large Rust codebase; cargo builds on 8 GB are slow). **Integrate optionally**: our guard service exposes a webhook endpoint, so "prod deployment = agentgateway in front, our brain behind" is a credible scalability slide. Guards skip tool-call content by default (needs `scope`) |
| **Agent Router (formerly Envoy AI Gateway)** — github.com/theagentrouter/agent-router | Go, Apache-2.0 | v1.1.0 (2026-08-21) | Envoy Gateway CRDs (`AIGatewayRoute`, `BackendSecurityPolicy`), token-cost rate limiting via CEL, MCP routing | **No.** Kubernetes and Envoy Gateway centric. Learn its token-cost CEL rate-limit model |
| **Kong AI Gateway** — github.com/Kong/kong | Lua/OpenResty, Apache-2.0 (OSS) | OSS 3.9.3 (2026-06) | OSS: AI Proxy, Prompt Decorator/Template. **Enterprise**: AI Semantic Prompt Guard, AI Sanitizer (PII), AI Rate Limiting Advanced, AI MCP Proxy, Semantic Cache | **No.** The interesting parts are Enterprise |
| **Lasso MCP Gateway** — github.com/lasso-security/mcp-gateway | Python, MIT | v1.2.0 (2026-01-21), 391★ | Wraps the MCP servers listed in `mcp.json`, intercepts requests and responses, plugins `basic` (token masking), `presidio`, `lasso` (API), `xetrack` tracing, server reputation scan | **Best candidate to lift code from** for the MCP stdio proxy part (small, MIT). Not worth forking whole |
| **Invariant Gateway** — github.com/invariantlabs-ai/invariant-gateway | Python, Apache-2.0 | last push 2025-11 (Snyk acquisition) | LLM/MCP proxy that traces to the hosted Invariant Explorer | No (pivots to hosted explorer) |
| **Snyk agent-scan** (ex-Invariant mcp-scan) — github.com/snyk/agent-scan | Python, Apache-2.0 | v0.6.8 (2026-09-29) | Scans agent configs, skills and MCP servers for tool poisoning, shadowing, toxic flows, credential handling | Needs `SNYK_TOKEN` and **sends tool descriptions to Snyk's API**, so it isn't offline. **Steal the risk taxonomy** and the "pin tool-description hash, detect rug-pull" idea |
| **Microsoft MCP Gateway** — github.com/microsoft/mcp-gateway | C#/.NET, MIT | active (2026-10-02); now requires MCP `2026-07-28` clients | K8s control plane + data plane, stateless routing, tool router, RBAC | No (Kubernetes/.NET). Note the new MCP protocol revision 2026-07-28 |
| **Docker MCP Gateway** — github.com/docker/mcp-gateway | Go, MIT | active (2026-09) | Container-isolated MCP servers, secrets management, **interceptors** (`pkg/interceptors`), call logging, profiles | No: needs Docker Desktop (2–4 GB VM). Learn: interceptors and secret-blocking |
| **IBM ContextForge** — github.com/IBM/mcp-context-forge | Python, Apache-2.0 | v1.0.11 (2026-09-28), 4.6k★ | MCP/A2A/REST federation, admin UI, OTel. **40+ plugins**: `regex_filter`, `deny_filter`, `pii` policy, `harmful_content_detector`, `content_moderation`, `code_safety_linter`, `schema_guard`, `virus_total_checker`, external `llmguard`/`opa`/`cedar`/`clamav` | Big codebase; requires JWT/auth secrets. **Learn its hook names** (prompt_pre_fetch, tool_pre_invoke, tool_post_invoke, resource_pre_fetch) and mirror them in our policy schema |
| **Plano** (ex-archgw, Katanemo) — github.com/katanemo/plano | Rust+Envoy, Apache-2.0 | 0.4.37 (2026-09-28) | Filter chains for guardrails, Arch-Guard model (MIT), routing. Default uses hosted Plano LLMs | No (Envoy/Docker; hosted models by default) |
| **Bifrost** (Maxim) — github.com/maximhq/bifrost | Go, Apache-2.0 | very active (2026-10-02) | Fast OpenAI-compatible router (claims µs-level overhead), budgets and virtual keys (governance plugin), Ollama support, UI. **Guardrails, clustering and full MCP gateway are Enterprise** | Could be the upstream router, but it adds a process and its value overlaps ours. Learn its budget hierarchy |
| TensorZero — github.com/tensorzero/tensorzero | Rust, Apache-2.0 | **archived on GitHub (2026-06)** | Gateway + eval + optimization | No |
| Helicone ai-gateway | Rust, **GPL-3.0** | stale since 2025-11 | — | Avoid (GPL) |

**Recommended architecture.** Build it ourselves and borrow from the projects above:
```
client / agent ──► [Ingress: OpenAI-compatible /v1/chat/completions (+ Anthropic /v1/messages passthrough), MCP proxy (stdio+streamable HTTP)]
                    │  identity: API key → tenant/team/app (from YAML)
                    ▼
     Policy engine (YAML, watched file → atomic swap; versioned; diffs into audit log)
                    │
     Detector cascade (async, parallel within a tier, per-detector timeout)
       T0 deterministic: normalizer → regex/RE2 (gitleaks) → Aho-Corasick deny-lists → YARA (yara-x) → Presidio patterns
       T1 encoders (ONNX, in-process): injection (Horizon small) ‖ PG2-22M ‖ embedding kNN vs signature feed/topic exemplars ‖ Presidio NER
       T2 generative (Ollama): Qwen3Guard-0.6B on uncertain band / always on output; judge LLM for NL custom rules (on demand)
                    │  decision = max-severity over rule hits → allow | mask | block | route-local | require-approval
                    ▼
     Router + budget governor (token/cost/requests per key/team/model; local "shadow price"; remote real price) → providers
                    ▼
     Output path: same cascade (secrets/PII leak, canary leak, harmful content, refusal), streaming = chunked buffer
                    ▼
     Audit (SQLite WAL, append-only + hash chain) → dashboard (static/HTMX + SSE live feed)
```

---

## 4. Build-vs-fork decision (explicit)

| Option | Effort to a working demo | Score potential | Risks | Decision |
|---|---|---|---|---|
| A. Own Python gateway plus borrowed components (above) | Medium. All code is ours, detectors are plug-ins | High: architecture, reporting and tests are fully ours; perf story via cascade, caching and in-process ONNX | Must write the MCP proxy ourselves (the `mcp` SDK 2.3.0 helps; Lasso code as a reference) | **Chosen** |
| B. Fork LiteLLM proxy and add custom guardrails | Low for LLM routing, high for budgets (Postgres) and dashboards (Enterprise gates) | Medium: judges see LiteLLM | Supply-chain history, heavy RAM, Enterprise gating, Python dependency hell | Rejected |
| C. agentgateway binary plus our webhook guard service | Medium. Learning its YAML; webhook can only reject/audit (no mask); tool content needs explicit scope | High on scalability; less control over reporting | Two processes; webhook contract docs thin | **Stretch goal / slide**: "drop-in behind agentgateway" |
| D. NeMo Guardrails as the engine | Medium-high (Colang) | Medium | Py <3.14, latency of LLM rails | Rejected for the core; steal YARA rules |

---

## 5. Small classifier / guard models that fit in 8 GB

### 5.1 Prompt-injection / jailbreak encoders (fast, CPU, ONNX)

| Model | Total params (HF) | Files | Context | Langs | Licence / gated | Notes |
|---|---|---|---|---|---|---|
| **Llama Prompt Guard 2 22M** (`meta-llama/Llama-Prompt-Guard-2-22M`) | 70.8M (22M backbone + multilingual embeddings) | fp32 283 MB. **int8 ONNX 72.5 MB** via `gravitee-io/Llama-Prompt-Guard-2-22M-onnx` (ungated mirror, has `tokenizer.json`) | 512 (chunk longer text) | en, fr, de, hi, it, pt, es, th (22M has a larger multilingual gap) | Llama 4 Community. Meta repo **gated (manual)** | Binary benign/malicious; targets **explicit** override and jailbreak techniques, not every instruction planted in data. Model card: AUC .995, recall@1%FPR 88.7%, APR@3% utility loss 78.4%, **19.3 ms on A100 @512 tokens**. Very conservative at threshold 0.5 (see §9.2), so use a lower threshold or treat it as the "high-precision vote" |
| Llama Prompt Guard 2 86M | 279M | fp32 1.1 GB; int8 ONNX 281 MB (gravitee) | 512 | multilingual (mDeBERTa) | Llama 4, gated | AUC .998, recall@1%FPR 97.5%, PINT 78.76%. 92.4 ms on A100. Better recall, 4× the RAM of 22M |
| **ProtectAI deberta-v3-base-prompt-injection-v2** | 184M | ONNX fp32 739 MB (no official int8; `onnxruntime.quantization.quantize_dynamic` gives ~240 MB) | 512 | **English only** | Apache-2.0, ungated. **Archived/unmaintained** | Card: post-training eval acc 95.25 / F1 95.49 (vendor set). "Does not detect jailbreak attacks", not for system prompts. PINT 79.14%. High over-defense (NotInject acc 0.56) |
| ProtectAI deberta-v3-small-…-v2 | 142M | ONNX 568 MB | 512 | en | Apache-2.0, **gated (auto)** | Smaller, same caveats |
| **PIGuard** (ex-InjecGuard; `leolee99/PIGuard`) | 184M (DeBERTa-v3-base) | safetensors 738 MB; ONNX mirror `filip-w/PIGuard-onnx` (fp16 369 MB) | 512 | en | **MIT**, ungated | ACL 2025, built to mitigate over-defense (NotInject). Strong on BIPIA (in-distribution), jackhhao |
| **Horizon-Labs prompt-injection-guard-small** v2 | 141M (mmBERT-small) | **int8 ONNX 268 MB** (`onnx/model_quantized.onnx`); fp32 563 MB | **8k** | 30 synthetic langs incl. **Polish** | Apache-2.0, ungated | v2 2026-09-23, only ~400 downloads, **vendor-run eval**. Covers direct and indirect (docs/tools/email) injection; macro-avg over external sets 0.867 (best except their 308M base). Has a **built-in obfuscation normalizer in the tokenizer** (NFKC, etc.): with raw `tokenizers` + ORT you must port `code/train/normalizer.py`. Vendor quant check: fp32 36 ms, int8 35 ms |
| Horizon-Labs …-guard-base | 308M | int8 ONNX 641 MB | 8k | 30 | Apache-2.0 | Best in their table (0.887); too big for our budget |
| Wolf Defender (`patronus-studio/wolf-defender-prompt-injection`) | 308M | int8+int4-emb ONNX 218 MB | — | — | Apache-2.0 | Best on jailbreak/evasion (Qualifire F1 .95, Mindgard evasion .98), weak on indirect (BIPIA .27). Good alternative "jailbreak vote" |
| NemoGuard JailbreakDetect (`nvidia/NemoGuard-JailbreakDetect`) | arctic-embed-m-long (137M) + random forest (4.7 MB) | `snowflake.onnx` 44 MB + `.pkl` | long | en | NVIDIA Open Model License | Embedding + RF, trained on AdvBench, WildJailbreak, jackhhao. Pickle loading = code execution risk; only load from the official repo |
| `deepset/deberta-v3-base-injection` | 184M | 738 MB | 512 | en | MIT | Flags ~94–100% of benign agentic text (FPR). **Don't use** |
| `sheltron-ai/prompt-guard-68m` | 68M | ONNX int8 124 MB | — | — | **CC-BY-NC-4.0** | Avoid (non-commercial) |
| `qualifire/prompt-injection-sentinel` | 396M | 1.6 GB | — | — | other, gated | Skip |
| `katanemo/Arch-Guard` | 279M | 1.1 GB | 512 | multi | MIT | PG1-86M derivative, stale (2025-05) |
| **Bielik Guard 0.1B v1.1** (`speakleash/Bielik-Guard-0.1B-v1.1`) | 124M (Polish RoBERTa) | 498 MB fp32 | 512 | **Polish only** | Apache-2.0, **gated (auto: accept, contact sharing)** | Polish **content-safety** classifier (hate/aggression, vulgarities, sexual, crime, self-harm), not an injection detector. Card: precision 77.65%, FPR **0.63%** on 3,000 Polish prompts, vs Qwen3Guard-0.6B FPR 17.17% and Llama-Guard-3-8B 9.30%. **Nice Kraków touch** if Polish prompts are expected (~0.25 GB int8 after export; needs one-off ONNX export) |
| IBM `granite-guardian-hap-38m` / `-125m` | 38M / 125M | 154 MB / 499 MB (no ONNX in repo) | — | en | Apache-2.0 | Hate/abuse/profanity, CPU-fast. Red Hat bench: HAP-125m 80.27% content-safety acc @33.2 ms. Needs ONNX export (one-off, uses torch) |

### 5.2 Small generative guard models (Ollama / llama.cpp)

| Model | Params | Ollama / GGUF | Disk | RAM est. (num_ctx 2048) | M2 warm latency (est.) | Licence / gated | Detects |
|---|---|---|---|---|---|---|---|
| **Qwen3Guard-Gen-0.6B** (`Qwen/Qwen3Guard-Gen-0.6B`, 2025-09) | 0.75B | No official tag. `hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M` (484 MB) / `hf.co/Hayanie/Qwen3Guard-Gen-0.6B-GGUF:q8_0` (805 MB). ONNX int4 at `nxp/Qwen3Guard-Gen-0.6B-ONNX`, OpenVINO at `pvelab/…` | 0.48–0.8 GB | 0.6–1.0 GB | 0.2–0.4 s (≈250-token template + input; ~10 output tokens) | Apache-2.0, ungated | Safe / **Controversial** / Unsafe. 9 categories: Violent, Non-violent Illegal, Sexual, **PII**, Suicide/Self-harm, Unethical, Politically Sensitive, Copyright, **Jailbreak** (input only). Response mode adds **Refusal: Yes/No**. 119 languages. Strict vs loose mode = how you map Controversial |
| Qwen3Guard-Stream-0.6B | 0.6B | transformers only (custom token-classification head) | 1.2 GB | needs torch | per-token | Apache-2.0 | Streaming output moderation (avg F1 ~2 pts below Gen). Interesting but torch-bound, so skip on 8 GB |
| **Llama Guard 3 1B** | 1.5B (HF total) | **`llama-guard3:1b`** (official, Q4_K_M 955 MB; q8_0 1.6 GB) | 0.95 GB | 1.1–1.3 GB | 0.3–0.6 s | Llama 3.2 Community. HF gated (manual), Ollama ungated | 13 MLCommons hazards S1–S13; 8 languages; **custom categories supported by prompt** (Ollama template hardcodes S1–S13, so use `raw:true`). Card F1 .899 / FPR .090 (English) |
| Llama Guard 4 12B | 12B | — | 24 GB bf16 | — | — | Llama 4; **multimodal, so the Llama 4 AUP withholds rights from EU-domiciled developers/companies** | Doesn't fit, and it's an EU licence problem |
| ShieldGemma 2B | 2.6B | `shieldgemma:2b` (1.7 GB) | 1.7 GB | ~2 GB | 0.5–1 s | Gemma ToU. HF gated | 4 harm policies, one yes/no probability per call. Weaker (ShieldGemma-9B avg F1 70.4 in the Qwen3Guard table). **Too big for budget** |
| Granite Guardian 3.1 2B / 3.2 3B-A800M / 3.3 8B / 4.1 8B | 2.5B / 3.3B MoE / 8B | `granite3-guardian:2b` (q8 **2.7 GB**) | ≥2.7 GB | >3 GB | ~1 s | Apache-2.0 | Harm, bias, jailbreak, profanity, violence + **RAG groundedness/relevance + function-call hallucination + bring-your-own criteria**. Best features, **over budget**. Mention as a "prod upgrade path" |
| HiveTraceGuard-Pro 0.6B (`hivetrace/HiveTraceGuard-Pro`, 2026-09) | 0.6B | needs GGUF conversion | ~0.5 GB q4 | ~0.7 GB | ~0.3 s | Apache-2.0 | PI + jailbreak + obfuscation, Russian-focused; robust-clean F1 0.88 (paper). Too new and unconverted for day 1 |
| YuFeng-XGuard-Reason-0.6B (Alibaba AAIG, 2026-06) | 0.75B | no GGUF yet | — | — | — | Apache-2.0 | PI-EN recall .87 (HiveTrace table); reasoning output = more tokens |
| GLiGuard-300M (`fastino/gliguard-LLMGuardrails-300M`, 2026-05) | 0.21B encoder | `pip install "gliner2[local]"` (torch) | 834 MB | ~1 GB with torch | tens of ms | Apache-2.0 | Six tasks in one pass: prompt safety, prompt toxicity (15 labels incl. PII), jailbreak (12 strategies), response safety and toxicity, refusal. Reported 87.7 / 82.7 avg F1 and 16× throughput vs decoder guards. **Strong future option**; torch dependency is why it's not in the minimal set |
| Shieldstral-1.0-3B (Mistral, 2026-07) | 3.85B | community GGUF | ~2.3 GB q4 | — | — | Apache-2.0 | Red Hat bench: PI 72.0%, content 74.8%. Too big, not better |
| Nemotron-3.5-Content-Safety (NVIDIA, 2026-05) | 4.3B | — | 8.6 GB | — | — | NVIDIA Open Model License | Too big |
| OpenGuardrails-Text-4B / gpt-oss-safeguard-20b | 4B / 20B | — | — | — | — | Apache-2.0 | Too big |

### 5.3 Small general LLMs for LLM-as-judge (and as the local demo upstream)

| Model | Ollama tag (size) | Licence | Comment |
|---|---|---|---|
| **Qwen3.5-0.8B** (2026-02) | `qwen3.5:0.8b` (1.0 GB, includes vision projector). Text GGUF `hf.co/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M` (533 MB) | Apache-2.0 | Best quality per MB in this class. Set `think:false` and JSON-schema `format` |
| Qwen3-0.6B | `qwen3:0.6b` (523 MB) | Apache-2.0 | Fallback judge; weak on nuanced policies |
| Qwen3-1.7B | `qwen3:1.7b` (1.4 GB) | Apache-2.0 | Better judge, but only if Qwen3Guard isn't resident |
| Gemma 3 1B / 270M | `gemma3:1b` (815 MB) / `gemma3:270m` (292 MB) | Gemma ToU (HF gated, Ollama not) | 270M is too weak for judging; OK for demo chat |
| Granite 4.0 350M-H / 1B-H | `granite4:350m-h` (366 MB) / `granite4:1b-h` (1.6 GB) | Apache-2.0 | Hybrid Mamba = low KV memory. Decent tiny upstream |
| Phi-4-mini 3.8B | `phi4-mini` (2.5 GB) | MIT | **Over budget** |
| Gemma 4 E2B | `gemma4:e2b` (4.6 GB) | Gemma | Over budget |

---

## 6. Recommended minimal set, RAM budget and fallback policy

### 6.1 RAM budget (target ≤ 2.5 GB for the control layer)

| Component | Resident? | RSS (est.) |
|---|---|---|
| Python 3.13 process (FastAPI, uvloop, onnxruntime, tokenizers, numpy, yara-x, re2) | yes | ~0.25 GB |
| Deterministic rules (gitleaks 222, YARA, deny-lists, signature metadata) | yes | ~0.05 GB |
| Horizon small int8 (injection) | yes | ~0.35 GB |
| Prompt Guard 2 22M int8 | yes | ~0.12 GB |
| MiniLM-L12 multilingual int8 + signature index (~20k vectors × 384 × fp16 ≈ 15 MB) | yes | ~0.17 GB |
| Presidio + spaCy `en_core_web_sm` (+`pl_core_news_sm`) | yes | ~0.2 GB |
| Ollama runner: Qwen3Guard-0.6B Q4_K_M, num_ctx 2048, KV q8_0 | yes (`keep_alive` 30m) | ~0.6–0.7 GB |
| **Resident total** | | **≈ 1.75–1.85 GB** |
| Judge `qwen3.5:0.8b` (text Q4_K_M) loaded on demand, also used as the local upstream LLM | on demand | +0.6–0.8 GB → **peak ≈ 2.5 GB** |
| **Lite profile** (memory pressure): drop T2, encoders + deterministic only | | ≈ 1.1 GB |

Put the demo **upstream** LLM on Ollama Cloud (`minimax-m2.5:cloud`, zero local RAM, but treat it as **external egress** in policy) or reuse the judge model. Never load a third local model.

### 6.2 Cascade and latency budget (p50 targets)

1. **T0 deterministic, ≤2 ms.** Normalize first: NFKC, strip zero-width and Unicode tag chars (U+E0000–E007F), fold homoglyphs and full-width forms, then decode base64/hex/rot13/URL-encoding layers (max depth 2) and scan **both** original and decoded text. Then RE2 regexes, Aho-Corasick deny-lists and YARA.
2. **T1 encoders, 15–40 ms, run in parallel** in a thread pool (ORT releases the GIL): injection (Horizon), PG2-22M, embedding kNN and Presidio. Chunk long inputs into 512-token windows (PG2) and score the max. Horizon handles 8k.
3. **T2 Qwen3Guard, +200–400 ms.** Runs (a) always on **output** when `output_moderation: on`, (b) on input when a T1 score sits in the **uncertain band** (e.g. 0.2–0.8) or a policy demands it.
   - Run input T2 **concurrently with the upstream call** (speculative). If it comes back unsafe, cancel the upstream request and return a block. This hides most T2 latency.
4. **Judge, +300–700 ms.** Only for rules of type `llm_policy` (natural-language rules typed by judges in config), with a JSON verdict schema.
5. **Cache.** LRU on `sha256(normalized_text, policy_version, detector_version)` makes repeated judge prompts free.
6. **Concurrency.** Ollama with `OLLAMA_NUM_PARALLEL=1` serializes. Put a semaphore in front, with a max queue wait of ~300 ms, then apply the fallback policy.

### 6.3 Fallback policy (fail-open vs fail-closed) as config

```yaml
detectors:
  qwen3guard: { timeout_ms: 800, on_timeout: degrade, on_error: degrade }
  judge:      { timeout_ms: 1500, on_timeout: degrade }
  injection_encoder: { timeout_ms: 150, on_timeout: block }   # cheap; if it fails something is badly wrong
degrade:
  injection_threshold: 0.30      # stricter than normal 0.50 when T2 unavailable
  tag: "unverified"              # shown in audit + response header X-Guard-Status
route_overrides:
  - match: { kind: mcp_tool_call, side_effects: true }      # write/send/exec tools
    on_unavailable: block                                    # fail-closed
  - match: { egress: external, contains: [pii, secret] }
    on_unavailable: block                                    # never leak when unsure
  - match: { kind: chat_output, risk: low }
    on_unavailable: allow_audited                            # fail-open but logged
circuit_breaker: { window: 20, p95_ms: 1200, error_rate: 0.3, cooldown_s: 30 }  # flips to degraded mode, visible on dashboard
```

---

## 7. Running it on the M2 / 8 GB

### 7.1 Python version
- Core stack wheels confirmed for **cp314 / abi3 on macOS arm64**: onnxruntime 1.30.0, tokenizers 0.23.2 (abi3), spaCy 3.8.16, numpy 2.5.3, pydantic-core, orjson, uvloop, regex, rapidfuzz, google-re2, yara-x (abi3), hyperscan, pyahocorasick, usearch, faiss-cpu. Presidio (pure, `<3.15`), fastembed (explicitly supports 3.14), `mcp` 2.3.0, fastapi are pure Python.
- **Not 3.14:** nemoguardrails (`<3.14`), guardrails-ai (`<3.14`), llm-guard (`<3.13`), rebuff (`<3.13`). `yara-python` has no cp314 wheel; use **yara-x**.
- **Recommendation:** `uv venv --python 3.13` (uv fetches a standalone CPython) so a framework can be pulled in later without a fight. The core works on 3.14 too.
- Avoid `torch` in the gateway process. Only use it in a one-off export script, if at all.

### 7.2 Fetching models without `hf` CLI (none installed) and without big installs
```bash
# ungated, direct
curl -L -o models/pg2-22m/model.quant.onnx https://huggingface.co/gravitee-io/Llama-Prompt-Guard-2-22M-onnx/resolve/main/model.quant.onnx
curl -L -o models/pg2-22m/tokenizer.json   https://huggingface.co/gravitee-io/Llama-Prompt-Guard-2-22M-onnx/resolve/main/tokenizer.json
curl -L -o models/hl-small/model_quantized.onnx https://huggingface.co/Horizon-Labs/prompt-injection-guard-small/resolve/main/onnx/model_quantized.onnx
curl -L -o models/hl-small/tokenizer.json       https://huggingface.co/Horizon-Labs/prompt-injection-guard-small/resolve/main/tokenizer.json
curl -L -o models/hl-small/normalizer.py        https://huggingface.co/Horizon-Labs/prompt-injection-guard-small/resolve/main/code/train/normalizer.py
curl -L -o models/minilm/model.onnx https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/resolve/main/onnx/model_qint8_arm64.onnx
curl -L -o models/minilm/tokenizer.json https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/resolve/main/tokenizer.json
# also grab each repo's config.json to read id2label (label index order differs per model!)
# gated repos: `uvx --from huggingface_hub hf auth login` then `uvx --from huggingface_hub hf download <repo> --include ...`

ollama pull hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M
ollama pull qwen3.5:0.8b            # or hf.co/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M (text-only, smaller)
ollama pull llama-guard3:1b         # alt content guard with custom categories
python -m spacy download en_core_web_sm   # (+ pl_core_news_sm)
```
Total pre-download ≈ 1.6–2.6 GB. **Do it before the venue Wi-Fi melts.**

### 7.3 Ollama settings for 8 GB
- Env: `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_CONTEXT_LENGTH=2048`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`.
- With the macOS app, set them via `launchctl setenv` and restart the app, or run `ollama serve` from a shell.
- Per request: `keep_alive: "30m"` for the guard, `"5m"` for the judge; `options: {temperature: 0, num_predict: 16–64}`.
- **Qwen3Guard prompt.** Build the official template from `tokenizer_config.json` (≈4 kB Jinja; categories are listed in the prompt) and send it with `/api/generate` and `raw: true`. Parse `^Safety: (Safe|Unsafe|Controversial)`, `^Categories: (.*)` and, for responses, `^Refusal: (Yes|No)`. Don't trust a community GGUF's embedded chat template; check it with `ollama show --template`.
- **Llama Guard custom categories.** Ollama's template hardcodes S1–S13. Send `raw: true` with your own category list (S14: e.g. "Investment advice", generated from YAML). Output is `safe` / `unsafe\nS1,S14`.
- **Judge.** Use `/api/chat` with `think: false` and `format: {json schema: {violation: bool, rule_id: str, confidence: number, reason: str}}`.

### 7.4 Hour-1 measurement script (replace estimates)
For each detector, time 50 warm calls on 3 input lengths (20 / 200 / 500 tokens), reporting p50/p95 and RSS (`psutil`). For Ollama, read `prompt_eval_duration` and `eval_duration` from the response JSON.

Minimal ONNX classifier (no torch):
```python
import numpy as np, onnxruntime as ort
from tokenizers import Tokenizer
so = ort.SessionOptions(); so.intra_op_num_threads = 4; so.enable_cpu_mem_arena = False
sess = ort.InferenceSession("models/pg2-22m/model.quant.onnx", so, providers=["CPUExecutionProvider"])
tok = Tokenizer.from_file("models/pg2-22m/tokenizer.json"); tok.enable_truncation(max_length=512)
names = {i.name for i in sess.get_inputs()}
def score(text: str, malicious_idx: int = 1) -> float:   # check config.json id2label!
    e = tok.encode(text)
    feeds = {"input_ids": np.array([e.ids], np.int64), "attention_mask": np.array([e.attention_mask], np.int64)}
    if "token_type_ids" in names: feeds["token_type_ids"] = np.zeros_like(feeds["input_ids"])
    logits = sess.run(None, {k: v for k, v in feeds.items() if k in names})[0][0]
    p = np.exp(logits - logits.max()); p /= p.sum(); return float(p[malicious_idx])
```
For fp32-only models (ProtectAI v2, PIGuard), quantize once: `from onnxruntime.quantization import quantize_dynamic, QuantType; quantize_dynamic("model.onnx", "model.int8.onnx", weight_type=QuantType.QInt8)`. Validate accuracy afterwards: DeBERTa quantization can shift scores. ONNX CoreML EP is optional; CPU int8 is fast enough and avoids dynamic-shape fallbacks.

### 7.5 Latency estimate basis
- llama.cpp's Apple Silicon table gives M2 (10-core GPU, 100 GB/s) **7B Q4_0 at pp512 ≈ 180 t/s and tg ≈ 22 t/s**. Scaling by parameter count gives roughly 900–1,100 t/s prefill and 90–110 t/s decode for 1B Q4, and ~1,500–2,000 t/s prefill and 130–160 t/s decode for 0.6B.
- So a guard call (~300 prompt tokens + ~10 output tokens) costs ~0.2–0.4 s warm. A cold load from SSD costs +1–2 s, so keep the guard resident.
- Encoders on M2 CPU int8 come out at a few ms (22M) to a few tens of ms (140–184M) for ≤512 tokens. One third party reports ~101 ms for a DeBERTa-v3-base INT8 injection model on M1, so measure.

---

## 8. Remote providers, with local-only still working

- **One internal provider interface, OpenAI-compatible wire format.**
  - `ollama` local: `http://localhost:11434/v1` or native `/api/chat` for token counts.
  - `openai`: `https://api.openai.com/v1`.
  - `anthropic`: native `/v1/messages`, or its OpenAI-SDK-compatible endpoint `https://api.anthropic.com/v1/`.
  - `gemini`: OpenAI-compatible `https://generativelanguage.googleapis.com/v1beta/openai/`.
  - `openrouter`: `https://openrouter.ai/api/v1`.
  - Groq, Cerebras and Mistral are also OpenAI-compatible.
  - Use plain `httpx` adapters (~150 LOC) rather than the LiteLLM package. If you do use LiteLLM's SDK, **pin and hash**.
- **Enable providers per environment variable.** `enabled_if_env: OPENAI_API_KEY`, etc. With no keys set, routes fall back to `local/*`, so judges can run `make demo-local` with zero keys. Model aliases in YAML (`chat-default → [anthropic/claude-x, openrouter/..., local/qwen3.5:0.8b]`) give automatic failover and budget-driven downgrade ("team over 80% of budget → route to local").
- **Egress classification.** Each provider and model is tagged `egress: local | external`. **Ollama `:cloud` models are external** even though they go through localhost:11434. Policy example: "PII or secrets detected → mask before external egress, or force route to local".
- **Budget governance.**
  - Remote cost: `usage` × price from the vendored LiteLLM `model_prices_and_context_window.json`. For streaming, use `stream_options: {include_usage: true}`.
  - Local cost: Ollama's `prompt_eval_count` / `eval_count` × a configurable **shadow price** (e.g. $0.02/1M tokens, or GPU-seconds × energy cost), so commercial and local budgets share one ledger.
  - Pre-call estimate with `tiktoken` (cp314 wheels) or chars/4. Hard stop vs soft alert per key/team/model.
- **Free / no-paid-key options** (all still need a free account/key; none is truly keyless and reliable):
  - **Ollama Cloud free tier.** Already signed in here (`minimax-m2.5:cloud`). Goes through the local daemon, so no key in our config. Session/weekly limits, 1 concurrent cloud model.
  - Google AI Studio (Gemini) free tier, Groq, Cerebras, Mistral free tier, OpenRouter `:free` models, GitHub Models (GitHub token).
  - Use them only for the "fronting remote providers" demo. Rate limits make them unsuitable for judge load tests.

---

## 9. Benchmark data for the recommended and competing detectors

### 9.1 PINT (Lakera prompt-injection benchmark; 4,314 inputs, 24 languages; 5.2% injections, 0.9% jailbreaks, 20.9% hard negatives)
| Detector | PINT score | Date |
|---|---|---|
| Lakera Guard (commercial) | 95.22% | 2025-05-02 |
| AWS Bedrock Guardrails | 89.24% | 2025-05-02 |
| Azure AI Prompt Shield | 89.12% | 2025-05-02 |
| **protectai/deberta-v3-base-prompt-injection-v2** | **79.14%** | 2025-05-02 |
| **Llama Prompt Guard 2 (86M)** | **78.76%** | 2025-05-05 |
| Google Model Armor | 70.07% | 2025-08-27 |
| Aporia | 66.44% | 2025-05-02 |
| Llama Prompt Guard 1 | 61.82% | 2025-05-02 |

### 9.2 Horizon-Labs comparison (vendor-run, threshold 0.5, same script; F1 with FPR in brackets)
| Set | HL-small | ProtectAI v2 | PIGuard | PG2-86M | PG2-22M | Wolf |
|---|---|---|---|---|---|---|
| NotInject (benign w/ trigger words), acc ↑ | 0.897 | 0.563 | 0.885 | 0.953 | **0.994** | 0.920 |
| OR-Bench-hard (benign), acc ↑ | **0.995** | 0.935 | 0.786 | 0.751 | 0.980 | 0.854 |
| jackhhao jailbreak, F1 | 0.883 (.03) | 0.911 (.02) | 0.957 (.05) | **0.967 (.01)** | 0.786 (.00) | 0.945 (.05) |
| deepset injections, F1 | 0.788 (.00) | 0.537 (.00) | 0.800 (.00) | 0.235 (.00) | 0.065 (.00) | 0.750 (.00) |
| Qualifire jailbreak vs benign, F1 | 0.730 (.22) | 0.657 (.23) | 0.670 (.23) | 0.661 (.11) | 0.186 (.00) | **0.950 (.02)** |
| BIPIA (indirect), F1 | 0.537 (.04) | 0.312 (.20) | **0.963 (.00)**† | 0.020 | 0.007 | 0.271 |
| PIArena (RAG indirect), F1 | **0.948 (.00)** | 0.366 | 0.713 | 0.150 | 0.003 | 0.338 |
| LLMail-Inject phase 2 (adaptive email), recall | **0.989** | 0.485 | 0.528 | 0.210 | 0.011 | 0.912 |
| Mindgard evaded samples, recall | 0.755 | 0.701 | 0.462 | 0.249 | 0.072 | **0.981** |
| **Macro avg (external sets)** | **0.867** | 0.637 | 0.793 | 0.540 | 0.380 | 0.776 |
| ROC-AUC jackhhao / deepset / PIArena | .960/.950/.985 | .980/.901/.732 | .995/.960/.898 | .995/.906/.742 | .968/.752/.559 | .977/.965/.909 |

† PIGuard was trained on BIPIA's training split. Read the "PG2 low F1" rows with care: PG2 is calibrated for very low FPR and explicit attacks, and its AUCs are fine. That's why it's the **high-precision vote** in the ensemble, with a lower threshold (~0.2–0.3), not a standalone detector.

### 9.3 Meta Prompt Guard 2 model card
| Metric | PG2-22M | PG2-86M | PG1 |
|---|---|---|---|
| AUC (English) | .995 | .998 | .987 |
| Recall @ 1% FPR | 88.7% | 97.5% | 21.2% |
| Attack prevention @ 3% utility loss | 78.4% | 81.2% | 67.6% |
| Latency (A100, 512 tok) | 19.3 ms | 92.4 ms | 92.4 ms |

### 9.4 Qwen3Guard technical report (arXiv 2510.14276): English F1
| Model | Prompt avg (ToxiC, OpenAIMod, Aegis, Aegis2, SimpST, HarmB, WildG) | Response avg (HarmB, SafeRLHF, BeaverTails, XSTest, Aegis2, WildG, Think) |
|---|---|---|
| **Qwen3Guard-Gen-0.6B** | **88.1** (best mode per set) | **82.0** |
| Qwen3Guard-Gen-4B / 8B | 89.3 / 90.0 | 83.7 / 83.9 |
| Qwen3Guard-Stream-0.6B | 86.3 | 79.2 |
| Llama Guard 3-8B | 79.4 | 70.7 |
| Llama Guard 4-12B | 75.9 | 67.5 |
| WildGuard-7B | 85.8 | 79.9 |
| ShieldGemma-9B / 27B | 70.4 / 70.0 | 62.2 / 65.9 |
| NemoGuard-8B | 82.9 | 78.1 |
| PolyGuard-Qwen-7B | 87.0 | 74.0 |

Caveat: on Polish user prompts (Bielik Guard card), Qwen3Guard-0.6B flagged 19.4% of prompts with **17.2% FPR**. Use **loose mode** (Controversial = allow + log) and/or Bielik Guard for Polish.

### 9.5 Llama Guard 3 model card (F1 / FPR)
| | English | French | German |
|---|---|---|---|
| Llama Guard 3-8B | .939 / .040 | .943 / .036 | .877 / .032 |
| **Llama Guard 3-1B** | **.899 / .090** | .939 / .012 | .845 / .036 |
| Llama Guard 3-1B INT4 | .904 / .084 | .873 / .072 | .835 / .145 |
| GPT-4 baseline | .805 / .152 | .795 / .157 | .691 / .123 |

### 9.6 HiveTraceGuard-Pro paper (arXiv 2609.01046, Sep 2026): 15-model head-to-head (GPU latency)
| Model | Params | PI-EN recall | Robust-clean F1 | Response F1 | Latency |
|---|---|---|---|---|---|
| HiveTraceGuard-Pro | 0.6B | 0.88† | 0.88 | 0.80 | 14.3 ms |
| YuFeng-XGuard-Reason-0.6B | 0.6B | 0.87 | 0.78 | 0.77 | 16.9 ms |
| **Qwen3Guard-Gen-0.6B** | 0.6B | 0.73 | 0.63 | 0.82 | 37.2 ms |
| PolyGuard-Qwen-Smol | 0.5B | 0.79 | 0.67 | 0.73 | 77.4 ms |
| **Llama-Guard-3-1B** | 1B | 0.68 | 0.48 | 0.61 | 20.5 ms |
| Qwen3Guard-Gen-4B | 4B | 0.83 | 0.76 | 0.83 | 96.9 ms |
| Shieldstral-1.0-3B | 3B | 0.74 | 0.72 | 0.81 | 14.7 ms |
| Llama-Guard-4-12B | 12B | 0.66 | 0.49 | 0.63 | 86.2 ms |

† training overlap flagged by the authors. The comparison is Russian-heavy.

### 9.7 Red Hat Developer (2026-10-02): "AI decision models vs traditional guardrails" (NeMo Guardrails EvalHub, class-balanced)
| Model | PI accuracy / latency | Content-safety accuracy / latency |
|---|---|---|
| DeBERTa-v3-base-prompt-injection-v2 | **89.01% / 54.1 ms** | — |
| Granite-guardian-hap-125m | — | 80.27% / 33.2 ms |
| Qwen3.6-35B (LLM judge) | 89.31% / 312.5 ms | 85.47% / 307.6 ms |
| Nemotron-3.5-Content-Safety 4B (custom prompt) | 84.84% / 240.4 ms | 85.07% / 241.5 ms |
| Shieldstral-1.0-3B | 72.02% / 187.9 ms | 74.80% / 191.9 ms |
| BART-large-mnli zero-shot | 61.49% / 115.0 ms | 68.67% / 144.2 ms |

Their conclusion: small pre-trained classifiers match a 35B judge on PI at ~6× lower latency. That supports the encoder-first cascade.

### 9.8 Others
- **GLiGuard-300M**: 87.7 avg F1 prompt harmfulness, 82.7 response, over 9 benchmarks; 16.2× throughput and 16.6× lower latency than decoder guards (model card / arXiv May 2026).
- **ProtectAI v2 (own eval, 20k prompts)**: acc 95.25%, P 91.59%, R 99.74%, F1 95.49%.
- **Bielik Guard 0.1B v1.1 (3,000 Polish prompts)**: precision 77.65%, alert rate 2.83%, FPR 0.63%. Llama-Guard-3-8B precision 13.62%, FPR 9.30%. Qwen3Guard-0.6B precision 11.36%, FPR 17.17%.

---

## 10. Datasets for the automated test suite and the exploit-signature feed

| Dataset | Licence | Use |
|---|---|---|
| `deepset/prompt-injections` | Apache-2.0 (<1k) | injection TP/TN unit tests |
| `jackhhao/jailbreak-classification` | Apache-2.0 (1–10k) | jailbreak TP/TN |
| `Lakera/gandalf_ignore_instructions` | MIT (1–10k) | signature feed seed |
| `Lakera/mosscap_prompt_injection` | MIT (100k–1M) | large signature/kNN corpus (dedupe, then sample) |
| `TrustAIRLab/in-the-wild-jailbreak-prompts` (jailbreak_llms, CCS'24) | MIT (10–100k) | "historical exploit" feed (DAN etc.) with dates and sources |
| `JailbreakBench/JBB-Behaviors` | MIT (<1k) | harmful-behaviour test prompts |
| `walledai/AdvBench` | MIT, gated-auto | harmful behaviours |
| `microsoft/llmail-inject-challenge` | MIT (100k–1M) | indirect/email injection, adaptive attacks |
| `neuralchemy/prompt-injection-dataset` | Apache-2.0 (10–100k, 2026-04) | modern injection mix |
| `leolee99/NotInject` | MIT (<1k) | **false-positive regression tests** (benign with trigger words) |
| `Paul/XSTest` | CC-BY-4.0 (<1k) | over-refusal / FPR tests |
| `allenai/wildjailbreak` | ODC-BY, gated-auto | adversarial jailbreak tactics |
| `qualifire/prompt-injections-benchmark`, `Mindgard/evaded-…` | **CC-BY-NC-4.0** | internal eval only, don't ship |
| **garak** (NVIDIA, Apache-2.0, v0.17.0 2026-09) / **promptfoo** (MIT, 0.123.1 2026-09) | — | generate red-team cases (encodings, DAN, latent injection, package hallucination). Run garak against our gateway's OpenAI endpoint in CI |

Signature-feed format idea: YAML/JSON entries `{id, first_seen, source, technique (OWASP LLM01/ATLAS id), type: regex|yara|exemplar, pattern|text, severity, langs}`. Exemplars get embedded once into a `usearch` index. Hot-reload the feed and show "feed version" and "hits per signature" on the dashboard.

---

## 11. Licence matrix (what we can ship in a demo that GS might reuse)

| Category | OK to ship | Ship with care | Avoid |
|---|---|---|---|
| Code | MIT / Apache-2.0: Presidio, gitleaks rules, detect-secrets, NeMo YARA, Vigil, Cisco YARA, Lasso, agentgateway, LiteLLM core (pinned), mcp SDK, yara-x (BSD-3), google-re2 (BSD) | LiteLLM `enterprise/` dir (commercial licence) | trufflehog (AGPL-3.0), Helicone ai-gateway (GPL-3.0) |
| Models | Apache/MIT: Horizon-Labs, PIGuard, ProtectAI v2, Wolf Defender, Qwen3Guard, Qwen3/3.5, Granite Guardian, Granite 4, MiniLM, e5, Bielik Guard (accept gate), GLiGuard, HiveTraceGuard | **Llama 3.2 / Llama 4 Community** (PG2, LG3-1B): attribution "Built with Llama", AUP, 700M-MAU clause. The EU restriction applies to Llama 4 **multimodal** models, so avoid LG4. **Gemma ToU** (ShieldGemma, Gemma 3) has prohibited-use flow-down. **NVIDIA Open Model License** (NemoGuard JailbreakDetect, gliner-pii, Nemotron) | CC-BY-NC(-ND): sheltron prompt-guard-68m, piiranha-v1 |
| Data | MIT/Apache/CC-BY sets in §10 | ODC-BY (WildJailbreak) needs attribution | CC-BY-NC sets in shipped feeds |

---

## 12. Day-0 checklist (do tonight / first hour)

1. **Request HF access now**, in case it's needed: `meta-llama/Llama-Prompt-Guard-2-22M` (manual approval), `speakleash/Bielik-Guard-0.1B-v1.1` (auto). Otherwise rely on the gravitee mirror and Ollama tags.
2. Pre-download everything in §7.2 (≈1.6–2.6 GB). Run `ollama show --template` on the Qwen3Guard GGUF.
3. `uv venv --python 3.13`. Install: `fastapi uvicorn[standard] httpx onnxruntime tokenizers numpy presidio-analyzer presidio-anonymizer spacy google-re2 yara-x pyahocorasick usearch tiktoken pyyaml watchfiles mcp`. No torch.
4. Configure Ollama env (§7.3) and restart the daemon.
5. Run the measurement script (§7.4) and replace the estimates in this doc with measured p50/p95/RSS.
6. Quick eval in hour 2: 200 prompts (50 deepset + 50 jackhhao + 50 NotInject + 50 gandalf/llmail), comparing Horizon-small, PIGuard-int8 and ProtectAI-int8. Keep whichever has the best F1 at FPR ≤ 5% as the main injection encoder.
7. Close Docker Desktop and heavy IDE indexers. Serve the dashboard as static files from the gateway.

---

## Sources

Libraries and tools
- LLM Guard (archived): https://github.com/protectai/llm-guard, https://pypi.org/project/llm-guard/
- NeMo Guardrails: https://github.com/NVIDIA-NeMo/Guardrails (library dir: `nemoguardrails/library/*`, YARA rules in `injection_detection/yara_rules`), https://pypi.org/project/nemoguardrails/
- Guardrails AI: https://github.com/guardrails-ai/guardrails, CLI token: https://guardrailsai.com/docs/cli, detect_jailbreak: https://github.com/guardrails-ai/detect_jailbreak
- Presidio: https://github.com/data-privacy-stack/presidio (PL PESEL recognizer under `predefined_recognizers/country_specific/poland`)
- Rebuff (archived): https://github.com/protectai/rebuff; Vigil: https://github.com/deadbits/vigil-llm
- LlamaFirewall: https://meta-llama.github.io/PurpleLlama/LlamaFirewall/, https://github.com/meta-llama/PurpleLlama
- any-guardrail: https://github.com/mozilla-ai/any-guardrail
- Microsoft Agent Governance Toolkit: https://github.com/microsoft/agent-governance-toolkit, https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit/
- Invariant: https://github.com/invariantlabs-ai/invariant, https://github.com/invariantlabs-ai/invariant-gateway; Snyk agent-scan: https://github.com/snyk/agent-scan
- Cisco mcp-scanner: https://github.com/cisco-ai-defense/mcp-scanner
- gitleaks: https://github.com/gitleaks/gitleaks (config/gitleaks.toml); detect-secrets: https://github.com/Yelp/detect-secrets; trufflehog: https://github.com/trufflesecurity/trufflehog
- garak: https://github.com/NVIDIA/garak; promptfoo: https://github.com/promptfoo/promptfoo

Gateways
- LiteLLM: https://github.com/BerriAI/litellm, guardrails: https://docs.litellm.ai/docs/proxy/guardrails/quick_start, budgets: https://docs.litellm.ai/docs/proxy/users, MCP: https://docs.litellm.ai/docs/mcp
- LiteLLM supply-chain compromise (Mar 2026): https://futuresearch.ai/blog/litellm-pypi-supply-chain-attack/, https://www.arthur.ai/column/litellm-supply-chain-attack-pypi-compromise-2026, https://bastion.tech/blog/litellm-pypi-supply-chain-attack
- Portkey: https://github.com/Portkey-AI/gateway
- agentgateway: https://github.com/agentgateway/agentgateway, prompt guards: https://agentgateway.dev/docs/standalone/latest/llm/prompt-guards/overview/, multi-layer: https://agentgateway.dev/docs/standalone/latest/llm/prompt-guards/multi-layer/, config file / hot reload: https://agentgateway.dev/docs/operations/config-file, AAIF: https://agentgateway.dev/blog/2026-06-04-agentgateway-joins-aaif/, AGT blog: https://agentgateway.dev/blog/2026-06-29-mcp-guardrails-microsoft-agent-governance-toolkit/
- Agent Router (ex-Envoy AI Gateway): https://github.com/theagentrouter/agent-router
- Kong: https://github.com/Kong/kong, https://konghq.com/company/press-room/press-release/ai-gateway, https://neuraltrust.ai/blog/neuraltrust-vs-kong
- Lasso MCP Gateway: https://github.com/lasso-security/mcp-gateway
- Microsoft MCP Gateway: https://github.com/microsoft/mcp-gateway; Docker MCP Gateway: https://github.com/docker/mcp-gateway
- IBM ContextForge: https://github.com/IBM/mcp-context-forge
- Plano: https://github.com/katanemo/plano; Bifrost: https://github.com/maximhq/bifrost; TensorZero: https://github.com/tensorzero/tensorzero; Helicone: https://github.com/Helicone/ai-gateway

Models (HF cards / API)
- https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M, https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M, https://huggingface.co/gravitee-io/Llama-Prompt-Guard-2-22M-onnx
- https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2, https://huggingface.co/leolee99/PIGuard (ACL 2025: https://aclanthology.org/2025.acl-long.1468.pdf), https://huggingface.co/filip-w/PIGuard-onnx
- https://huggingface.co/Horizon-Labs/prompt-injection-guard-small, https://huggingface.co/patronus-studio/wolf-defender-prompt-injection, https://huggingface.co/nvidia/NemoGuard-JailbreakDetect
- https://huggingface.co/speakleash/Bielik-Guard-0.1B-v1.1, https://huggingface.co/ibm-granite/granite-guardian-hap-38m
- https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B, https://huggingface.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF, Qwen3Guard report: https://arxiv.org/abs/2510.14276
- https://huggingface.co/meta-llama/Llama-Guard-3-1B, https://ollama.com/library/llama-guard3 (template blob shows hardcoded S1–S13)
- https://huggingface.co/google/shieldgemma-2b, https://ollama.com/library/shieldgemma, https://ollama.com/library/granite3-guardian
- https://huggingface.co/fastino/gliguard-LLMGuardrails-300M, https://huggingface.co/hivetrace/HiveTraceGuard-Pro (paper https://arxiv.org/abs/2609.01046), https://huggingface.co/mistralai/Shieldstral-1.0-3B
- Ollama library: https://ollama.com/library/qwen3, https://ollama.com/library/qwen3.5, https://ollama.com/library/gemma3, https://ollama.com/library/granite4, https://ollama.com/library/phi4-mini
- Embeddings: https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2, https://huggingface.co/intfloat/multilingual-e5-small

Benchmarks
- PINT: https://github.com/lakeraai/pint-benchmark
- Red Hat (2026-10-02): https://developers.redhat.com/articles/2026/10/02/benchmarking-ai-decision-models-against-traditional-guardrails
- llama.cpp Apple Silicon perf: https://github.com/ggml-org/llama.cpp/discussions/4167
- Llama 4 AUP (EU multimodal clause): https://developer.meta.com/ai/llama4/use-policy/

Remote / free tiers
- https://openrouter.ai/blog/tutorials/free-llm-apis-compared/, https://wetheflywheel.com/en/ai-model-access/free-llm-api-tiers-2026/, Ollama Cloud: https://agentdeals.dev/vendor/ollama-cloud
