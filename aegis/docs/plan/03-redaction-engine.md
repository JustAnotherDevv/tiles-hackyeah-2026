# 03 — redaction-engine: local redaction / data-minimization engine (HEADLINE)

Workstream `redaction-engine` · task prefix `RED` · research refs 07 (primary), 01 §5.3/§6.2/§6.10, 03 §1/§6 · staging reuse: `staging/pii/*`, `staging/models/ner_pii.py`, `staging/spikes/streaming/aegis_stream/placeholders.py` (+ `jsonlex.json_escape`).

Owned paths (CONTRACTS §1.2): `src/aegis/redaction/**`, `src/aegis/controls/dlp/**`, `src/aegis/api/routes/redaction.py`, `config/snippets/redaction-engine.yaml`, `tests/unit/redaction_engine/**`, this file.

---

## 1. Goal & demo value

**What judges see (flow F1, the opening scene of the demo):**
- A prompt containing a Polish PESEL, an IBAN, a card number with expiry and CVV, and an email is sent to a remote model through the playground or Claude Code. The mock/remote model receives only `[PESEL_1] … [IBAN_1] … [PAN_1] exp [CARD_EXPIRY_1], CVV [REDACTED:CVV] … [EMAIL_1]` (shown in mock_llm `/_mock/requests` and the decision drawer's original vs outbound view).
- The answer streams back with the real values restored for the local user. The CVV is gone for good: it is never vaulted and never fingerprinted.
- The same prompt sent to the local model (`aegis-judge`) keeps the PESEL (CONFIDENTIAL→local = allow) but still tokenizes the PAN (RESTRICTED→local = redact).
- The same PESEL sent to a third-party tool, or a card to WebFetch, is **blocked** by the destination matrix.
- An AWS key in a prompt is **blocked** (DLP-02, flow F2). The same key inside a `tool_result` is tokenized, so a Claude Code turn is not killed. A secret or PII emitted by the model is masked irreversibly (DLP-05); the canary blocks.
- A customer row returned by `acme-db.query` is tokenized before it reaches a remote model (DLP-05 on `mcp.result`, F4).
- Claude Code's `Write`/`Edit` tool input gets the real values back, but only for local tools (DLP-08 → hook `updatedInput`). WebFetch and third-party MCP tools keep the placeholders.
- Live policy edits flip verdicts in under a second:
  - set `destinations.matrix.CONFIDENTIAL.remote: block` → the next prompt is blocked;
  - raise DLP-07 `threshold` 0.6 → 0.8 → ML-only names are logged instead of redacted while PESEL/PAN stay redacted;
  - set DLP-02 `action: redact` → secrets are tokenized instead of blocked.
- A **precision / recall / leak-rate table** for the dashboard comes from `GET /api/redaction/metrics`: 626 labelled EN/PL fixtures, 23 entity types, adversarial set A1–A13, hard negatives, and p50/p95 latency.

**Judging criteria served:**
- Guardrail robustness & quality (30%): checksum-validated detectors, anti-evasion normalizer, NER for PL/EN, 0% leak rate on validated types.
- Security reporting (20%): spans plus HMAC fingerprints in the audit, never raw values; per-entity metrics.
- Self-testing (15–20%): inline policy tests, unit and property tests, the fixture evaluation.
- Architecture & performance (20%): Tier D p50 ≈ 0.13 ms per case, content-hash cache, NER under a timeout with a deterministic fallback.
- Implementability (10–15%): one plug-in detector folder, RE2 for user patterns, Apache/MIT only.

---

## 2. Design

### 2.1 Module layout (all inside owned paths)

```
src/aegis/redaction/
  __init__.py          docstring only (no import-time side effects)
  entities.py          ENTITY catalog = CONTRACTS §3.4 (+ gap entities §4.3): entity -> (data_class, category,
                       reversible, preview_kind); STAGED_TO_CONTRACT type map; SECRET_RULE_TO_ENTITY map;
                       IRREVERSIBLE = {CVV, TRACK_DATA}; DLP01_DEFAULT, DLP02_DEFAULT, NER_DEFAULT entity sets
  validators.py        PUBLIC SURFACE (§3.3) – port of staging/pii/validators.py (names unchanged)
  normalize.py         PUBLIC SURFACE (§3.3) – port of staging/pii/normalize.py (normalize(text) -> Normalized
                       with .text, .to_original(a, b))
  scan.py              core Tier-D scanner = port of staging/pii/detectors.py (renamed: Detector->Scanner,
                       DetectorConfig->ScanConfig, Finding->Hit) + fixes listed in §2.4
  placeholders.py      PUBLIC SURFACE (gap §4.2): PLACEHOLDER_RE, PARTIAL_PLACEHOLDER_RE, MAX_PLACEHOLDER_LEN,
                       canonical_key(), irreversible(entity) -> "[REDACTED:ENTITY]", Vault, VaultStore, VaultFull,
                       rehydrate_text(text, resolve, json_string=False) -> (str, n), StreamRehydrator
  preview.py           type-aware masks: pan_mask ("411111******1111"), excerpt masks, mask_for_log impl,
                       fingerprint(entity, canonical) -> "hmac:<16 hex>" via aegis.core.crypto.hmac_hex(purpose="redaction")
  policy.py            DLP params models (pydantic, defaults, unknown keys -> warning), matrix resolution,
                       "neutral action" semantics, span->Finding builder, Decision builder (shared by 5 controls)
  engine.py            create(rt) -> RedactionEngineImpl (RedactionEngine protocol + extras); detector discovery;
                       per-snapshot scanner compile (snap.compiled["redaction-engine:scanner"]); LRU scan cache;
                       VaultStore; known-value rescan; apply/rehydrate/mask_for_log
  ner.py               port of staging/models/ner_pii.py (PiiNer, load_tokenizer, make_session, _merge) +
                       NerService (lazy background load, 1-slot lock, LRU cache, timeout, label->entity map, status())
  ner_fallback.py      deterministic heuristics used when NER is off/unavailable (degraded): PERSON (first-name
                       lexicon + capitalised surname, honorific/"nazywam się" anchors), ADDRESS (PL ul./al./pl./os. +
                       number, PL postcode + city, UK/US street anchors), HEALTH (EN/PL lexicon: "choruje na",
                       "cukrzyc*", "diagnos*", …), DOB (context; reuses scan.dob)
  evaluate.py          port of staging/pii/evaluate.py; contract entity names; NER rows when loaded; finance-benign
                       FP check; `python -m aegis.redaction.evaluate [--check] [--bench] [--write]`
  detectors/
    __init__.py
    _base.py           CoreView(Detector): thin view over the shared core scan (skipped by discovery: "_" prefix)
    pci.py             PAN, CARD_EXPIRY, CVV, TRACK_DATA
    pl_ids.py          PESEL, NIP, REGON, PL_ID_CARD, PASSPORT
    banking.py         IBAN (incl. 26-digit NRB -> IBAN)
    contact.py         EMAIL, PHONE
    personal.py        DOB (context-anchored)
    crypto.py          CRYPTO_ADDRESS (BTC base58check/bech32(m), ETH EIP-55)            [gap entity]
    secrets.py         AWS_KEY, AWS_SECRET, GITHUB_TOKEN, SLACK_TOKEN, STRIPE_KEY, OPENAI_KEY, ANTHROPIC_KEY,
                       JWT, PRIVATE_KEY, PASSWORD, CONNECTION_STRING, GENERIC_SECRET
    network.py         IP_ADDRESS (detector ids pii.ip.public / pii.ip.private), MAC_ADDRESS [gap entity]
    metadata.py        USERNAME (from /Users/<x>, /home/<x>, C:\Users\<x>) – for DLP-03's use
  data/
    fixtures/*.jsonl   copied from staging/pii/fixtures (6 files, 626 cases, ~215 KB)
    first_names.txt    ~300 PL+EN given names (incl. inflected PL forms Jana/Janem/Anny…) for ner_fallback
    health_terms.txt   EN/PL health lexicon for ner_fallback

src/aegis/controls/dlp/
  __init__.py
  dlp01_pii.py         DLP-01  PII/PCI/Polish-ID tokenization (destination matrix)         D  prio 40
  dlp02_secrets.py     DLP-02  Secrets & credentials                                        D  prio 30
  dlp05_output.py      DLP-05  Output & tool-result leak detection (+ canary)               D  prio 40
  dlp07_ner.py         DLP-07  Multilingual NER (bardsai ONNX) + heuristic fallback         S  prio 60
  dlp08_vault.py       DLP-08  Vault & controlled re-identification                         D  prio 90

src/aegis/api/routes/redaction.py   GET /api/redaction/entities (+ gap endpoints §4.3)
config/snippets/redaction-engine.yaml
tests/unit/redaction_engine/{conftest.py, test_*.py}
```

### 2.2 Data flow

```
REQUEST hop (prompt.user | model.request | tool.input | mcp.call | egress.request), dest_class from core
  DLP-02 (prio 30) ─┐  per redactable segment: engine.scan(snap, text)  ── one shared core scan per text
  DLP-01 (prio 40) ─┤       normalize (offset map) → candidates → validators/context → decode-and-rescan
                    │       → JSON cross-field join → map to ORIGINAL offsets → allow-lists → min_score → merge
                    │     + engine.known_value_spans(ctx, text)   (exact vault values: no history drift)
                    │  per span: action = matrix[data_class][dest_class] ⊕ control action (§2.3) ⊕ forced rules
                    │  → Decision(action=max, findings=[Finding(segment_index,start,end,entity,…, excerpt masked,
                    │              meta.fp=HMAC)] only for spans to transform; log-only spans have no offsets)
  DLP-07 (S, prio 60) NER on user-authored segments (to_thread, timeout) → same matrix logic
                    │  (NER off/timeout → ner_fallback heuristics, Decision.degraded=True)
pipeline combine → final redact → rt.redactor.apply(ctx, segments, findings)
        → merge overlaps (longest wins) → Finding.replacement | [REDACTED:CVV|TRACK_DATA] | vault.put → [PESEL_1]
        → new segments + Redaction records (offsets in ORIGINAL text, placeholder, reversible, control_id)
        → audit stores Redaction + findings (entity, offsets, masked excerpt, hmac fp) – never raw values

RESPONSE hop (model.response | tool.output | mcp.result | egress.response)
  DLP-05: scan placeholder-bearing text BEFORE rehydration; canary → block;
          model.response → irreversible [REDACTED:ENTITY] (model-emitted data is never vaulted);
          tool.output/mcp.result → reversible tokenize via vault (local user still sees real values later)
  DLP-08: model.response → allow + meta {rehydrate: true, roles: ["assistant"]};
          tool.input to a LOCAL tool containing vault placeholders → log + meta.rehydrate (respecting matrix);
          third-party tool → placeholders pass through untouched (finding logged)
  core-gateway / hook handler → rt.redactor.rehydrate(ctx, text) (session vault, tolerant regex,
          entity filter from ctx.state["redaction.rehydrate_entities"])
  streaming: MVP `buffered` (core assembles, then rehydrate); holdback (stretch) uses
          aegis.redaction.placeholders.StreamRehydrator / engine.vault_view(ctx).resolve
```

### 2.3 Decision semantics (one place: `aegis.redaction.policy`)

1. **Matrix first.** Each span's data class is looked up in `snap.doc.destinations.matrix[data_class][interaction.destination.dest_class]` and gives an `Action`. A class with no row means `allow`.
2. **Control `action` relative to a per-control neutral action.** The neutral action is DLP-01 `redact`, DLP-02 `block`, DLP-05 `redact`, DLP-07 `redact`. This makes the contract defaults and judges' live edits both behave sensibly.
   - `cfg.action == neutral` → the matrix is authoritative.
   - `cfg.action` weaker than neutral (`log`, `allow`, or `redact` on DLP-02) → cap every span at `cfg.action`. So "DLP-02 action: redact" tokenizes secrets instead of blocking.
   - `cfg.action` stronger than neutral (DLP-01 `block` or `require_approval`) → every span the matrix would redact or block is escalated to `cfg.action` (a "strict" knob).
3. **Score ladder.**
   - A span is acted on only if `score ≥ max(cfg.threshold or 0, params.min_scores[entity] or scanner default)`.
   - A span below that is recorded as `log` (with `meta.below_threshold`), and its offsets are not attached.
   - Validated types score 0.9–1.0, so threshold slides mostly affect context, NER and heuristic hits (demo knob).
4. **Forced rules (never overridable by the matrix).**
   - `TRACK_DATA` → `block` (`params.force_block`).
   - `CVV` / `TRACK_DATA` are never tokenized: the replacement is `[REDACTED:CVV]`, and they have no fingerprint and no preview.
   - PAN shows at most first 6 + last 4 anywhere.
   - With `mask_style: pci` the model also gets `411111******1111` (irreversible) instead of `[PAN_1]`.
5. **Request-level rules (DLP-01).**
   - `redaction_ratio_block` (default 0.6): if a segment with role in `ratio_roles` (default `[user, tool_args]`) has `len ≥ 200` and redacted chars / len > ratio → `block` with reason "bulk sensitive data".
   - `max_entities_per_request` (default 200) → `block`.
6. **Role-aware secrets (DLP-02).**
   - Spans in segments with role in `params.redact_roles` (default `[tool_result, document]`) are capped at `redact`. A `.env` dump inside a Claude Code `tool_result` becomes `[AWS_KEY_1]` instead of killing the turn.
   - A user-typed key to remote is still `block` (F2, and contract test `aws-key-blocked`).
   - `allow_doc_examples: true` → known documentation values (`AKIAIOSFODNN7EXAMPLE`, `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`) are `log`.
7. **`require_approval` from the matrix** (a judge may set a cell to it) → `Decision(require_approval, approval=ApprovalDraft(kind="action", action_type="dlp.release", title="Send PESEL×1, PAN×1 to remote (<dest>)", payload={entities counts, dest} – no values))`.
8. **Findings carry what the transform needs, nothing raw.** Each finding has: `control_id`, `detector` (e.g. `pii.pesel`), `category`, `entity`, `data_class`, `severity=cfg.severity`, `score`, `segment_index/start/end` (only when the span is to be transformed), `excerpt = mask_for_log(context ±24 chars)`, `replacement` (None → vault placeholder; set for irreversible / pci / model.response), and `meta = {fp: "hmac:<16hex>" (absent for CVV/TRACK_DATA), op: tokenize|drop|mask|log, tier, dest_class, cell: "CONFIDENTIAL.remote"}`.
9. **Decision `reason` reads like the live feed.**
   - "Tokenized 5 values for remote (PESEL, IBAN, PAN, CARD_EXPIRY, EMAIL); dropped CVV"
   - "PAN → third_party blocked by destinations.matrix.RESTRICTED.third_party"
   - "TRACK_DATA never leaves (PCI SAD)"
   - `Decision.meta = {entities: {PESEL: 1, …}, dest_class, cells: {...}, observed_only: n, cache_hits: k, scan_ms: x}`.

### 2.4 Fixes to staged code (found by running it today)

| Issue | Evidence | Fix |
|---|---|---|
| Contract golden test `aws-key-blocked` (`"key AKIA0123456789ABCDEF"`) is **not detected**: the staged rule uses `[A-Z2-7]{16}` (current gitleaks). Policy self-test would reject the policy. | `Scanner.detect` → `[]` | Add rule `aws-access-key-legacy` `(?:A3T[A-Z0-9]\|AKIA\|ASIA\|ABIA\|ACCA)[A-Z0-9]{16}` with a boundary check, score 0.9 → `AWS_KEY` |
| AWS docs key `AKIAIOSFODNN7EXAMPLE` is silently dropped by the `_placeholder()` filter. The contract wants `allow_doc_examples` → `log`. | `[]` | Known doc-example values are emitted with `meta.doc_example=True`, score 0.9. DLP-02 maps them to `log`. Other placeholders (`YOUR_API_KEY`) stay filtered. |
| Emails on reserved TLDs (`anna.nowak@poczta.example`, `…@acme.test`) are **not detected**, but demo and mock data use them | `[]` | `ScanConfig.email_reserved_tlds = ("example", "test")` accepted by default (param `email_reserved_tlds`) |
| `phonenumbers` is imported at module top but is **not in CONTRACTS §7.6** | — | Guarded import. Without it, a regex fallback (PL `+48` / 9-digit with context, E.164 `+CC` 8–15 digits) runs and the detector id gets the suffix `:fallback`. The dep is requested (§7). |
| Contract `entropy_min: 4.0`, `min_len: 20` would drop 19 fixture secrets if applied to every rule (password / conn-string / AWS id / twilio entropy < 4) | measured | Apply them **only** to generic rules (`generic-credential`, `env-assignment`, `bearer-token`); format-specific rules keep their built-in gates |
| Staged entity names ≠ contract (`CREDIT_CARD`, `PL_PESEL`, `CARD_CVV`, `[CVV]` …) | — | Map at the scanner boundary (`entities.STAGED_TO_CONTRACT`, table §3.2). Placeholders and markers follow the contract: `[PAN_1]`, `[PESEL_1]`, `[REDACTED:CVV]`. |

### 2.5 Engine service (`aegis.redaction.engine`)

- **`create(rt)`** is cheap: no model load, no compile.
- **`start()`**:
  - discovers `detectors/*.py` (pkgutil, skips `_*`, each import wrapped in try/except);
  - builds the default scanner;
  - registers `rt.policy.on_change(self._on_policy)` to rebuild the scanner and set the vault TTL / max entries from DLP-08 params;
  - if `settings.semantic != "off"` and `models/eu-pii-ner/model_quantized.onnx` exists and DLP-07 is enabled, starts `NerService.load()` in a background thread (`AEGIS_TEST_MODE=1` → lazy on first use instead), then publishes bus `system` `{level: info, message: "NER model loaded (eu-pii-ner, 0.6 s)", component: "redaction"}` or a warning on failure.
- **`stop()`** wipes all vaults.
- **Protocol methods (exact signatures from CONTRACTS §3.2):**
  - `detect(text, *, entities=None, use_ner=False) -> list[Span]`: sync, deterministic. Uses the current snapshot's scanner and the LRU cache keyed `(sha256(text), scanner_version, frozenset(entities))` (4096 entries). Runs core types plus non-core plugin detectors; with `use_ner=True` it adds NER only if already loaded. It maps entities to contract names.
  - `async detect_async(text, *, entities=None, use_ner=True)`: Tier D via `asyncio.to_thread` when `len(text) > 4096`; NER via `NerService.detect_async` with timeout (DLP-07 `timeout_ms`, default 400). On NER error it returns Tier D only and sets `self.last_ner_degraded = True`.
  - `apply(ctx, segments, findings) -> (segments, redactions)`:
    - groups findings by `segment_index` and drops findings without offsets;
    - skips `redactable=False` segments and leaves them byte-identical;
    - merges overlaps (longest first, then irreversible/explicit replacement, then data-class rank SECRET > RESTRICTED > CONFIDENTIAL > INTERNAL);
    - replaces right-to-left: `finding.replacement` if set; else `[REDACTED:X]` for IRREVERSIBLE; else `vault.put(entity, raw=segment.text[s:e], canonical)` → `[ENTITY_N]`;
    - `VaultFull` → the irreversible marker (never leaks; logs WARNING);
    - returns new `TextSegment` copies plus `Redaction(segment_index, path, start, end (original), entity, data_class, placeholder, control_id, reversible)`.
  - `rehydrate(ctx, text) -> str`:
    - uses the session vault `ctx.session_id` and the tolerant `PLACEHOLDER_RE`;
    - only placeholders this session issued are restored (`[Step 1]`, `arr[0]`, `[EMAIL_9]` and `[REDACTED:…]` are untouched);
    - optional entity filter from `ctx.state["redaction.rehydrate_entities"]` (set by DLP-08);
    - counts are stored in `ctx.state["redaction.rehydrated"]`.
  - `mask_for_log(text, max_len=160) -> str`:
    - deterministic detect (cached, no NER);
    - PAN → `411111******1111`, CVV/TRACK → `[REDACTED:CVV]`, everything else → `[ENTITY]` (`[EMAIL]`, `[PESEL]`, `[AWS_KEY]`);
    - truncates with `…`;
    - never raises (on internal error it masks every digit run ≥ 4 and every `x@y`).
  - `detectors() -> list[Detector]`.
- **Extras (duck-typed, gap §4.2):**
  - `vault_view(ctx)` → object with `.resolve(canonical_key)`, `.values()` and `__len__` (the aegis_stream `Vault` protocol);
  - `stream_rehydrator(ctx, *, json_escape=False)`;
  - `rehydrate_obj(ctx, obj)` (string leaves of dict/list);
  - `known_value_spans(ctx, text)`;
  - `forget_session(session_id)`;
  - `session_stats(session_id) -> {entities: {PESEL: 1,…}, entries, created_at, last_used}` (counts only);
  - `scanner_for(snap)`;
  - `ner_status()`.
- **Vault** (`placeholders.Vault`):
  - keyed by `ctx.session_id`; Claude Code's `x-claude-code-session-id` equals the hook `session_id` (verified in `staging/spikes/claude-code/FINDINGS.md` 1b), so proxy redaction and PreToolUse rehydration share one vault;
  - in RAM only; never logged or persisted;
  - per-entity counters with deterministic numbering by first appearance; the same canonical value always gets the same placeholder (prompt cache stays stable: FINDINGS 2b);
  - canonical forms: PAN/PESEL/NIP/REGON → digits; IBAN → upper alnum; PHONE → E.164 if parsable else digits; EMAIL → lower; others exact;
  - stores the first surface form for rehydration;
  - idle TTL `vault_ttl_s` (DLP-08 param, default 3600), cap 10 000 entries/session, thread-safe.
- **Known-value rescan (must; replaces staging's InverseCache).** On every request hop toward a non-local destination, DLP-01 adds exact-match spans for every value already in the session vault (≥ 3 chars, longest-first, compiled per vault version). Without it, a name or context-detected NIP that was rehydrated into the assistant's reply would leak on the next Claude Code turn. Claude Code resends history, and NER/context may not fire on the model's paraphrase.
- **Scanner compile per snapshot.** `scanner_for(snap)` builds the scanner from DLP-01 and DLP-02 params:
  - `phone_regions`, `email_reserved_tlds`, `decode_depth`, `min_scores`, `allow_patterns` (google-re2 only), `allowlist_values` (`hmac:<16hex>` fingerprints or literal canonical test values), `entropy_min`, `min_len`, `extra_rules` (RE2).
  - The result is memoised in `snap.compiled["redaction-engine:scanner"]`, so self-test candidates get their own.
  - Invalid user regex → keep the default scanner for that snapshot, `log.warning`, bus `system` warning, `Decision.degraded=True`.

### 2.6 Controls (summary; catalog rows from CONTRACTS §4.4 are binding)

| ID | `applies_to.surfaces` | kind / prio | What it does |
|---|---|---|---|
| DLP-01 | prompt.user, model.request, tool.input, mcp.call, egress.request | deterministic / 40 | §2.3 over `DLP01_DEFAULT` entities (CONFIDENTIAL + RESTRICTED Tier-D + CRYPTO_ADDRESS) plus known vault values. INTERNAL entities are left to DLP-03 unless added via `params.entities`. |
| DLP-02 | prompt.user, model.request, tool.input, mcp.init, mcp.call, egress.request, a2a.message, tool.output, mcp.result | deterministic / 30 | SECRET entities; matrix SECRET row (local log / remote block / third_party block); role-aware redact; doc examples → log |
| DLP-05 | model.response, tool.output, mcp.result, egress.response | deterministic / 40 | Canaries (`params.canaries`) → block. DLP-01 ∪ DLP-02 entities on placeholder-bearing text. `model.response` → irreversible `[REDACTED:X]` (+ `meta.reidentified=True` if the raw value is in the vault). Tool / MCP / egress results → reversible tokenize per matrix (local-only agent ⇒ `local` ⇒ allow). |
| DLP-07 | prompt.user, model.request, tool.output, mcp.result | **semantic** / 60, `fail_mode: open`, threshold 0.6 | NER entities PERSON, ADDRESS, HEALTH, DOB on segments with role in `params.roles` (default `[user, tool_args, tool_result, document]`), ≤ `max_chars` 8000 each, ≤ `max_segments` 8 (newest first), fenced code stripped. Spans already covered by Tier D are dropped. NER not ready / timeout → `ner_fallback`, `degraded=True`. |
| DLP-08 | model.response, tool.input | deterministic / 90 | **model.response:** if `local_user ∈ rehydrate_to` and the vault is non-empty → `allow` + `meta {rehydrate: true, roles: ["assistant"]}` and `ctx.state["redaction.rehydrate_entities"] = None` (all). **tool.input:** if dest `local`, `local_tools ∈ rehydrate_to`, args contain vault placeholders, and the tool is not in `deny_tools` → `log` ("rehydrated 2 placeholders for local tool Write") + `meta.rehydrate=true`, entity filter = classes whose `matrix[class].local ∈ {allow, log}` (`respect_matrix`). **Third-party / remote tools:** `allow`, placeholders stay, `meta.passthrough=n`. An explicit `tool_args.aegis_rehydrate: true` toward third_party → `block` (A15). Raw values never appear in findings. |

`Control` objects are `BaseControl` subclasses with the ClassVars (`id`, `family="DLP"`, `name`, `kind`, `applies_to`, `owasp`, `priority`) and `CONTROLS = [Dlp01()]` per module. Each `evaluate` validates `cfg.params` with its own pydantic model (defaults; unknown keys → `log.warning` once per policy version). It returns `None` when nothing is found and never raises for "not applicable". All CPU work for segments > 4 KB runs in `asyncio.to_thread`.

### 2.7 Config keys read, events emitted, endpoints served

- **Policy:**
  - `destinations.matrix`;
  - `controls[DLP-01|02|05|07|08]`: `enabled`, `mode`, `action`, `threshold`, `severity`, `timeout_ms`, `fail_mode`, `params`;
  - `defaults.rehydrate_responses` (read by core-gateway; DLP-08 mirrors it in meta).
- **Settings (env, via `aegis.settings`):** `models_dir` (`AEGIS_MODELS_DIR`), `semantic` (`AEGIS_SEMANTIC`), `vault_secret` (`AEGIS_VAULT_SECRET`, opaque-token derivation, could), `test_mode`.
- **Events:** bus `system` only (NER loaded, failed or degraded; invalid user regex in DLP params). `decision` events are published by the pipeline; the Prometheus `aegis_redactions_total{entity,dest_class}` is incremented by audit-metrics from `verdict.redactions` (we do not double count).
- **Endpoints:** `GET /api/redaction/entities` (contract), plus gap endpoints §4.3: `GET /api/redaction/metrics`, `GET /api/redaction/sessions/{session_id}`, `DELETE /api/redaction/sessions/{session_id}`.

---

## 3. Reuse map (staging is read-only: copy/port, never import)

| Staging source | → Owned path | Adaptation |
|---|---|---|
| `staging/pii/validators.py` | `src/aegis/redaction/validators.py` | Verbatim (names are the §3.3 public surface: `luhn_ok`, `card_ok`, `pesel_ok`, `nip_ok`, `regon_ok`, `iban_ok`, `pl_id_card_ok`, `digits_only`, `shannon_entropy` + the rest). ruff format. |
| `staging/pii/normalize.py` | `src/aegis/redaction/normalize.py` | Verbatim (public surface `normalize(text) -> Normalized`) |
| `staging/pii/detectors.py` (1428 lines; P=R=1.000, leak 0 % on 626 fixtures, p50 0.13 ms, 76 patterns all RE2-compilable – measured today) | `src/aegis/redaction/scan.py` | Rename classes; relative imports; fixes §2.4; contract-name mapping in `entities.py`; config from DLP params; keep `_merge`, `_Scan`, `SECRET_RULES`, `load_gitleaks_rules` (unused unless a vendored gitleaks.toml appears) |
| `staging/pii/placeholders.py` | `src/aegis/redaction/placeholders.py` + `preview.py` | `Vault` / `VaultStore` / `StreamRehydrator` / `PH_RE` kept. Canonical key upper-cases type **and** id (matches aegis_stream). Opaque ids are upper-case. `[CVV]` → `[REDACTED:CVV]`. `pci_preview` → `411111******1111` (contract format). `redact()`/`_decide()`/zones T0–T2 are replaced by `engine.apply` + `policy.py` (T0/T1/T2 → local/remote/third_party). `InverseCache` is replaced by the known-value rescan. `leak_scan` → DLP-05. `fingerprint()` → `preview.fingerprint` via `aegis.core.crypto.hmac_hex`. |
| `staging/spikes/streaming/aegis_stream/placeholders.py`, `jsonlex.json_escape` | merged into `src/aegis/redaction/placeholders.py` | One regex for both paths: `PLACEHOLDER_RE` id `[A-Za-z0-9]{1,12}`, `PARTIAL_PLACEHOLDER_RE` hold-back ≤ 48, `rehydrate_text(text, resolve, json_string)`, `rehydrate_json_value`. The rest of aegis_stream (SSE transformers, LeakScanner) belongs to **core-gateway** (`proxy/streaming.py`). |
| `staging/pii/evaluate.py` | `src/aegis/redaction/evaluate.py` | Contract entity names; fixtures from `aegis/redaction/data/fixtures`; JSON output schema §4.3; `--check` (exit 1 if validated-type recall < 1.0 or leak > 0 or hard-negative FP > 0); `--bench`; NER rows (PERSON/ADDRESS/HEALTH gold labels) when NER is loaded; finance-benign FP rate from the corpora (copied subset, see below) |
| `staging/pii/fixtures/*.jsonl` | `src/aegis/redaction/data/fixtures/` | Verbatim copy; gold types mapped at load |
| `staging/corpora/handwritten/finance_benign.jsonl` (42, Aegis-original) | `src/aegis/redaction/data/fixtures/finance_benign.jsonl` | Copy as the "no PII expected" precision set (expect allow) |
| `staging/models/ner_pii.py` + `RESULTS.md` thresholds | `src/aegis/redaction/ner.py` | `PiiNer` verbatim + `NerService` (load in a thread, `threading.Lock` 1 slot, LRU 512 by sha256, timeout, label map PERSON_NAME→PERSON, POSTAL_ADDRESS/LOCATION-with-digits→ADDRESS, DATE_OF_BIRTH→DOB, HEALTH_DATA→HEALTH; other Art. 9 labels → `SPECIAL_CATEGORY` only if gap §4.1 is accepted, else ignored). `LABEL_MIN_SCORE` kept; `cfg.threshold` is the global floor. |
| `staging/seed/policy.yaml` (`data_protection`, DLP-01/02/05/07/08) | `config/snippets/redaction-engine.yaml` | Vocabulary translated per CONTRACTS §1.4 (T0/T1/T2 → local/remote/third_party, `*_pct` → 0–1, `examples` → `tests`, `[CREDIT_CARD_1]` → `[PAN_1]`) |
| research 07 Appendix A vectors, §11.2 A1–A15 | `tests/unit/redaction_engine/` | Vectors and adversarial cases as tests |
| `staging/pii/gen_fixtures.py` | not ported (needs Faker) | reference only |

---

## 4. Interfaces

### 4.0 Provided (exactly as CONTRACTS)

- `aegis.redaction.engine:create(rt) -> RedactionEngine` implements (§3.2, verbatim):
  ```python
  class RedactionEngine(Protocol):
      def detect(self, text: str, *, entities: set[str] | None = None, use_ner: bool = False) -> list[Span]: ...
      async def detect_async(self, text: str, *, entities: set[str] | None = None, use_ner: bool = True) -> list[Span]: ...
      def apply(self, ctx: RequestContext, segments: list[TextSegment], findings: list[Finding]
                ) -> tuple[list[TextSegment], list[Redaction]]: ...
      def rehydrate(self, ctx: RequestContext, text: str) -> str: ...
      def mask_for_log(self, text: str, max_len: int = 160) -> str: ...
      def detectors(self) -> list[Detector]: ...
  ```
- Detector plug-ins: `src/aegis/redaction/detectors/*.py` → `DETECTORS: list[Detector]` with `id` (`"pii.pesel"`), `entity` (canonical), `data_class`, `category` (`pii|pci|secret|metadata`), `languages`, and `detect(text) -> list[Span]` (pure, sync, checksums validated).
- Public import surfaces (§3.3): `aegis.redaction.validators` (names above), `aegis.redaction.normalize` (`normalize(text) -> Normalized` with `.text`, `.to_original(a, b)`).
- Controls DLP-01, DLP-02, DLP-05, DLP-07, DLP-08 (`CONTROLS` lists) with catalog defaults (§4.4).
- Route `redaction.py` (`router`, absolute paths; `ORDER` default): `GET /api/redaction/entities` → `{items: [{entity, data_class, category, detectors: string[]}]}` (viewer ≥ member; includes `ner.eu-pii-ner` / `heuristic.*` detectors for NER entities).
- `config/snippets/redaction-engine.yaml` (draft in §9).
- Entities, placeholders `[ENTITY_N]` and irreversible `[REDACTED:ENTITY]` exactly per §3.4.

### 4.1 Consumed

| From | What | If missing |
|---|---|---|
| scaffold (frozen) | `aegis.core.types` (`Span`, `Finding`, `Redaction`, `TextSegment`, `Decision`, `ApprovalDraft`, `RequestContext`, `Interaction`), `aegis.core.protocols` (`BaseControl`, `Detector`, `RedactionEngine`), `aegis.core.policy_schema` (`ControlConfig`, `PolicySnapshot`, `DestinationsSection`) | — (hard dependency) |
| core-gateway | `aegis.core.crypto.hmac_hex(value, purpose="redaction")` | Guarded import → local HMAC-SHA256 with `AEGIS_HMAC_KEY` or a random per-process key (WARNING) |
| core-gateway | `aegis.core.deps.get_rt`, `viewer`, `require_role("admin")`; `aegis.core.errors.api_error` | Route returns plain JSON / `HTTPException` |
| core-gateway | `rt.settings` (`models_dir`, `semantic`, `vault_secret`, `test_mode`), `rt.bus.publish("system", …)`, `ctx.session_id` resolution, pipeline transform (calls `apply`), response path (calls `rehydrate` when a DLP-08 meta says so), `interaction.destination.dest_class` per §3.4 | Defaults (`models`, `auto`); bus failures swallowed |
| policy-engine | `rt.policy.snapshot()` (or `ctx.policy`), `rt.policy.on_change(cb)`; merges our snippet; self-test gate runs our inline tests | Defaults = `DestinationsSection()` matrix + param defaults |
| claude-code-integration | hook handler maps DLP-08 meta → `updatedInput` via `rt.redactor.rehydrate` / `rehydrate_obj`; PostToolUse redact → `updatedToolOutput`; optional `forget_session` on `SessionEnd` | Rehydration into local tools does not happen (placeholders written to files) |
| semantic-models (optional, gap §4.4) | shared XLM-R tokenizer | Load our own (+~250 MB) |

### 4.2 Contract gaps — public import surface and engine extras (addendum proposal)

Add to §3.3 "Public import surfaces":

| Module | Owner | Exposes |
|---|---|---|
| `aegis.redaction.placeholders` | redaction-engine | `PLACEHOLDER_RE`, `PARTIAL_PLACEHOLDER_RE`, `MAX_PLACEHOLDER_LEN`, `canonical_key(type, id) -> "[TYPE_ID]"`, `rehydrate_text(text, resolve: Callable[[str], str \| None], *, json_string=False) -> tuple[str, int]`, `rehydrate_json_value(obj, resolve) -> tuple[Any, int]`, `StreamRehydrator(resolve, *, json_escape=False)` with `.feed(chunk) -> str`, `.flush() -> str`, `.count` |

Engine extras, used by core-gateway (holdback streaming) and claude-code-integration via `getattr(rt.redactor, "<name>", None)` with fallback:
- `vault_view(ctx)` → `.resolve(key)`, `.values()`, `__len__` (aegis_stream `Vault` protocol);
- `stream_rehydrator(ctx, *, json_escape=False)`;
- `rehydrate_obj(ctx, obj)`;
- `forget_session(session_id) -> bool`;
- `session_stats(session_id) -> dict`.

The Null fallback (`aegis.core.nulls`) does not need them.

**Response-path clarification (core-gateway):**
- Rehydrate only segments whose role is in the DLP-08 decision's `meta.roles` (default `["assistant"]`, i.e. text blocks).
- **Never rehydrate `tool_use` inputs in a model response.** Local tools get real values via the PreToolUse hook (DLP-08 on `tool.input`). Rehydrating tool_use inputs in the response would hand raw values to WebFetch / third-party tools.

### 4.3 Contract gaps — entities and endpoints

**Entities** (`Span.entity` and the TS types are plain strings, so nothing frozen breaks). Proposed additions to the §3.4 table:

| Entity | Class | Category | Why |
|---|---|---|---|
| `CRYPTO_ADDRESS` | CONFIDENTIAL | pii | In scope (BTC base58check/bech32(m), ETH EIP-55) with no contract name; `detector` distinguishes `pii.crypto.btc` / `pii.crypto.eth` |
| `MAC_ADDRESS` | INTERNAL | metadata | Staged detector exists; device identifier |
| `SPECIAL_CATEGORY` | CONFIDENTIAL | pii | GDPR Art. 9 from NER other than health (religion, politics, orientation, ethnicity, union). Off unless listed in DLP-07 `params.entities`. |

**Mappings** (no addendum needed):
- 26-digit NRB → `IBAN` (detector `pii.nrb`).
- URL secret params → `GENERIC_SECRET` (detector `secret.url_param`).
- Path usernames → `USERNAME` (detector `meta.path_username`; acted on by DLP-03, not DLP-01).
- Cookie session ids → `GENERIC_SECRET`.

**Endpoints** in our own `redaction.py` (add to §1.3 / §5.4):

| Method & path | Response | Notes |
|---|---|---|
| `GET /api/redaction/metrics` | `RedactionMetrics` (below) | Latest `reports/dlp-metrics.json`, or computed on demand in `to_thread` (~0.3 s, cached per process). `?refresh=1` recomputes. |
| `GET /api/redaction/sessions/{session_id}` | `{session_id, entries, entities: {ENTITY: n}, created_at, last_used, ttl_s}` | Counts only, never values or placeholders→values |
| `DELETE /api/redaction/sessions/{session_id}` | `{ok, wiped}` | **admin**; also the target for a Claude Code `SessionEnd` hook |

`RedactionMetrics` JSON (page-local TS type for dashboard-security):
```json
{"generated_at": "…", "cases": 626, "gold": 816, "ner_loaded": false,
 "overall": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "leak_rate": 0.0, "leak_rate_validated": 0.0,
             "hard_negative_fp_rate": 0.0, "finance_benign_fp_rate": 0.0, "case_accuracy": 1.0},
 "latency_ms": {"p50": 0.13, "p95": 0.42, "per_kb_p95": 1.1},
 "by_entity": [{"entity": "PAN", "data_class": "RESTRICTED", "validated": true, "gold": 106, "tp": 106, "fp": 0,
                "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0, "covering_recall": 1.0, "leak_rate": 0.0,
                "adversarial_recall": 1.0}],
 "by_lang": {"en": {…}, "pl": {…}}, "adversarial": {"A1": 1.0, "A2": 1.0, …}}
```

### 4.4 Contract gap — shared tokenizer (optional, RAM)

`staging/models/RESULTS.md` §3: bardsai NER and MiniLM share the identical XLM-R vocabulary. Sharing it saves 200–300 MB on the 8 GB machine.

Proposal: semantic-models exposes `rt.semantic.shared_tokenizer("xlmr") -> tokenizers.Tokenizer | None` (duck-typed, optional). `NerService` passes it to `load_tokenizer(..., share_vocab_with=…)` when present, otherwise loads its own.

---

## 5. Tasks

Priorities: **must** = headline flows F1/F2/F4 + contract MVP; **should** = NER model, metrics, perf; **could** = polish. The estimates assume the staged code ports cleanly (it does: measured P=R=1.0, all patterns RE2-compatible).

### RED-01 · Interfaces first: package skeleton with safe stubs — must · demo_critical yes · 10 min
- [ ] `src/aegis/redaction/{__init__,entities,engine,placeholders,preview,policy}.py`, `detectors/__init__.py`, `src/aegis/controls/dlp/__init__.py`. Empty-but-valid `CONTROLS` per control module; `engine.create(rt)` returns an engine whose methods work (detect → `[]`, apply → identity, rehydrate → text, mask_for_log → digit/@ masking) so others can import immediately.
- [ ] `src/aegis/api/routes/redaction.py` with `router` + `GET /api/redaction/entities` from the `entities.py` catalog.
- [ ] `entities.py`: full contract catalog (§3.4) + gap entities, `STAGED_TO_CONTRACT`, `SECRET_RULE_TO_ENTITY`, `IRREVERSIBLE`, default entity sets per control.
- Deps: frozen core files (scaffold). Verify: RED-V01.

### RED-02 · Port validators + normalizer (public surfaces) — must · yes · 5 min
- [ ] Copy `staging/pii/validators.py` → `aegis/redaction/validators.py`, `normalize.py` → `aegis/redaction/normalize.py`; ruff check/format.
- [ ] Tests: Appendix A vectors (PESEL `44051401359` ✔ / `…58` ✘, NIP `1234563218`, REGON `123456785`, ID `ABA300000`, passport `ZS0000177`, IBAN PL/GB/DE ✔ and `…2875` ✘, NRB, 6 PANs, BTC/bech32), plus the normalizer offset invariant (`orig[to_original(a, b)]` covers fullwidth, zero-width and Arabic-Indic digits).
- Deps: RED-01. Verify: RED-V02.

### RED-03 · Core Tier-D scanner port + fixes + detector plug-ins — must · yes · 18 min
- [ ] `scan.py` ← `staging/pii/detectors.py` (rename, relative imports, `ScanConfig` fields from §2.5).
- [ ] Fixes §2.4: AWS legacy rule; doc-example tagging; reserved-TLD emails; guarded `phonenumbers` + regex fallback; `entropy_min` / `min_len` on generic rules only; google-re2 for all user-supplied patterns (`allow_patterns`, `extra_rules`, `custom_patterns`).
- [ ] Hit → `Span` mapping (contract entity, data_class, category, `detector_id` like `pii.pesel`, `secret.aws_access_key`, `pci.pan`).
- [ ] `detectors/_base.py` `CoreView` + 9 family modules exposing `DETECTORS` (§2.1). Engine discovery (pkgutil, skip `_*`, try/except per module, ERROR log); core views share one scan per text, and non-core plug-ins run individually and are merged by tier/length/score.
- Deps: RED-02. Verify: RED-V02, RED-V03, RED-V04.

### RED-04 · Placeholders, vault, rehydration — must · yes · 10 min
- [ ] `placeholders.py`: tolerant `PLACEHOLDER_RE`, `PARTIAL_PLACEHOLDER_RE`, `canonical_key`, `irreversible()`, `Vault` (`put`, `resolve`, `values`, `contains_value`, `__len__`, `wipe`), `VaultStore` (TTL, cap, thread-safe, `stats`), `VaultFull`, `rehydrate_text`, `rehydrate_json_value`, `StreamRehydrator` (hold-back ≤ 48, `json_escape`), per-entity canonicalizers.
- [ ] Known-value matcher per vault version (longest-first, ≥ 3 chars).
- Deps: RED-01. Verify: RED-V05.

### RED-05 · Engine service — must · yes · 15 min
- [ ] `RedactionEngineImpl` per §2.5: `start` / `stop`, `_on_policy`, `scanner_for(snap)` memoised in `snap.compiled`, LRU scan cache, `detect`, `detect_async`, `apply` (overlap merge, replacements, Redaction records, VaultFull fallback), `rehydrate` (+ `ctx.state` entity filter + count), `mask_for_log` (never raises), `detectors()`, extras (`vault_view`, `stream_rehydrator`, `rehydrate_obj`, `known_value_spans`, `forget_session`, `session_stats`, `ner_status`).
- [ ] `preview.py`: `pan_mask` (first6 + `*` + last4), excerpt masks (email `a***@p***.example`, IDs last-2 only, never the PESEL birth-date prefix), `fingerprint()` via `hmac_hex` (guarded fallback); SAD → no fingerprint, no preview.
- Deps: RED-03, RED-04. Verify: RED-V05, RED-V06, RED-V10.

### RED-06 · Shared DLP decision logic (`policy.py`) — must · yes · 10 min
- [ ] Pydantic params models for DLP-01 / 02 / 05 / 07 / 08 (defaults in §9; `extra="allow"` + warning).
- [ ] `resolve_span_action(span, dest_class, matrix, cfg, neutral, params, role)` implementing §2.3 (matrix, neutral-action semantics, thresholds, forced rules, role-aware secrets, doc examples).
- [ ] `build_findings` (offsets only for transformed spans, masked excerpt, `meta.fp`, `op`, `cell`); `build_decision` (max action, reason text, meta counts, ApprovalDraft for `require_approval`, `degraded`).
- [ ] Request-level ratio / max-entities rules.
- Deps: RED-05. Verify: RED-V07.

### RED-07 · DLP-01, DLP-02, DLP-05, DLP-08 controls — must · yes · 20 min
- [ ] `dlp01_pii.py`: per redactable segment (skip `redactable=False`): core scan (to_thread if > 4 KB) + known-value spans → policy logic. `PolicyTest` text segments use role `user`.
- [ ] `dlp02_secrets.py`: SECRET entity set; role-aware; doc examples; `fail_mode` closed.
- [ ] `dlp05_output.py`: canaries (exact + normalized match) → block; model.response → `replacement="[REDACTED:X]"` (PAN → masked), `meta.reidentified`; tool / MCP / egress results → reversible per matrix.
- [ ] `dlp08_vault.py`: model.response meta rehydrate; tool.input local vs third party; `respect_matrix` entity filter into `ctx.state["redaction.rehydrate_entities"]`; `deny_tools`; `aegis_rehydrate` force → block; vault TTL from params.
- Deps: RED-06. Verify: RED-V07, RED-V08, RED-V11.

### RED-08 · DLP-07 control + deterministic heuristic fallback — must · yes · 10 min
- [ ] `ner_fallback.py` (PERSON lexicon + anchors, ADDRESS anchors, HEALTH lexicon, DOB) with scores 0.65–0.75 so `threshold` edits flip them. Lexicons in `data/first_names.txt` and `data/health_terms.txt`.
- [ ] `dlp07_ner.py` (kind `semantic`): role/size/segment caps, code-fence skip, drops spans overlapping Tier-D hits, uses `NerService` if ready else fallback (`degraded=True`), same policy logic (neutral `redact`).
- Deps: RED-06 (and RED-12 for the real model). Verify: RED-V07 (heuristic cases), RED-V12.

### RED-09 · Policy snippet with inline tests — must · yes · 6 min
- [ ] Write `config/snippets/redaction-engine.yaml` from §9. Include only tests whose outcome is invariant to the matrix cells where the contract schema default and §4.3 disagree (CONFIDENTIAL → third_party), and that pass with `AEGIS_SEMANTIC=off`. The policy self-test gate must never reject a policy because of us.
- Deps: RED-07, RED-08. Verify: RED-V09.

### RED-10 · Unit tests (must set) — must · yes · 12 min
- [ ] `tests/unit/redaction_engine/`:
  - `test_validators.py`, `test_normalize.py`;
  - `test_scan_fixtures.py` (validated recall = 1.0, leak 0, hard-negative FP 0 — calls `evaluate.evaluate()`);
  - `test_re2_portability.py`;
  - `test_engine_apply.py`, `test_vault_rehydrate.py`, `test_stream_rehydrator.py` (2000 seeded random chunkings; JSON-escape round trip `O"Brien \ x`);
  - `test_controls.py` (fake rt + `PolicySnapshot` built from `PolicyDoc()` + a ControlConfig per control);
  - `test_privacy.py` (no gold value appears in `Decision.model_dump_json()`, `Redaction`, `mask_for_log`, `session_stats`);
  - `test_route.py` (FastAPI app with only our router, in-process ASGI).
- [ ] Local `conftest.py`: `fake_rt` (settings, policy stub with `snapshot()`/`on_change`, bus stub), `ctx(session_id)`, `make_interaction(surface, dest, text|tool_args)`.
- Deps: RED-02…RED-09. Verify: RED-V02…RED-V11.

### RED-11 · Metrics: evaluate module + `/api/redaction/metrics` — should · yes · 12 min
- [ ] `evaluate.py` port with contract names, `by_entity`, `by_lang`, adversarial A-codes, finance-benign FP, latency (`--bench`: 1/4/16 KB prose+code, p50/p95), NER rows when loaded. CLI writes `reports/dlp-metrics.json` + `reports/dlp-metrics.md`; `--check` gate.
- [ ] Route `GET /api/redaction/metrics` (file if present and newer than the code, else compute in `to_thread`, cache).
- Deps: RED-03, RED-05. Verify: RED-V03, RED-V13.

### RED-12 · NER service (bardsai INT8 ONNX) — should · yes · 20 min
- [ ] `ner.py`: port `PiiNer`; `NerService` (`load()` in a background thread at `start()`; `AEGIS_SEMANTIC=off` → disabled; missing files → disabled + system warning; optional `psutil` guard: skip load if available RAM < 900 MB → degraded), 1-slot lock, LRU 512, `detect_async(text, timeout_s)` via `asyncio.to_thread`, label → entity map, `status()` (`loaded`, `load_ms`, `p50_ms`, `degraded`, `rss_mb`).
- [ ] Optional shared tokenizer (gap §4.4) via `getattr(rt.semantic, "shared_tokenizer", None)`.
- [ ] Engine `detect(..., use_ner=True)` + DLP-07 wired to it.
- [ ] Test marked `semantic`: PL inflected names (`Jana Kowalskiego`), "Kraków is the capital…" → no PERSON / ADDRESS, health "choruje na cukrzycę" → HEALTH.
- Deps: RED-08. Verify: RED-V12.

### RED-13 · Performance: scan cache, threading, budget check — should · no · 6 min
- [ ] Cache hit-rate counters in `Decision.meta.cache_hits`; to_thread thresholds; a 20-turn Claude-Code-shaped transcript fixture (generated in the test) → second evaluation ≥ 90 % cache hits; Tier D p95 < 15 ms on 16 KB.
- Deps: RED-05. Verify: RED-V13.

### RED-14 · Session vault endpoints + lifecycle — should · no · 5 min
- [ ] `GET` / `DELETE /api/redaction/sessions/{id}` (DELETE needs admin via `require_role("admin")`); `forget_session`; bus `system` info on wipe.
- Deps: RED-05. Verify: RED-V14.

### RED-15 · Cross-segment fragments (A7/A8) — could · no · 10 min
- [ ] In DLP-01, run the staged `detect_segments` join over the user-authored segments of one request (and over `tool_args` leaves). A PAN or IBAN split across segments gets an irreversible `[REDACTED:PAN]` per fragment (`meta.fragment=True`).
- Deps: RED-07. Verify: unit test with `{"a": "4111 1111", "b": "1111 1111"}`.

### RED-16 · Opaque tokens + `AEGIS_VAULT_SECRET` — could · no · 8 min
- [ ] DLP-08 `params.token_format: indexed|opaque`. The opaque id is the first 4 base32 characters of HMAC(`vault_secret`, session|entity|canonical) in upper case (deterministic per session, unguessable). Collision → extend to 6 characters.
- Deps: RED-04. Verify: unit test (stable across calls, distinct across sessions, rehydrates).

### RED-17 · Rehydration safety for shell egress — could · no · 6 min
- [ ] DLP-08 `params.deny_command_patterns` (RE2, default `\b(curl|wget|nc|ncat|scp|ssh|rsync|ftp)\b`, `https?://`) for `Bash` / `shell` tools: no rehydration, finding logged ("placeholder kept: command has network egress").
- Deps: RED-07. Verify: unit test.

### RED-18 · Allowlist fingerprint CLI — could · no · 4 min
- [ ] `python -m aegis.redaction.preview fp <ENTITY> <value>` prints `hmac:<16hex>` for `allowlist_values` (value read from stdin if `-`).
- Deps: RED-05. Verify: round trip: allowlisted value no longer redacted.

### Verification tasks

| ID | Proves | Command / check | Expected |
|---|---|---|---|
| RED-V01 | Interfaces importable, no import-time side effects | `uv run --frozen python -c "import aegis.redaction.engine as e, aegis.redaction.validators, aegis.redaction.normalize, aegis.redaction.placeholders; import aegis.controls.dlp.dlp01_pii, aegis.controls.dlp.dlp02_secrets, aegis.controls.dlp.dlp05_output, aegis.controls.dlp.dlp07_ner, aegis.controls.dlp.dlp08_vault, aegis.api.routes.redaction"` | exit 0, < 1 s, no model loaded (check `ps` RSS unchanged) |
| RED-V02 | Validators + normalizer | `uv run --frozen pytest tests/unit/redaction_engine/test_validators.py tests/unit/redaction_engine/test_normalize.py -q` | all pass |
| RED-V03 | Detection quality = staged baseline | `uv run --frozen python -m aegis.redaction.evaluate --check --write` | `P=1.000 R=1.000` on validated types, `leak=0.0000%`, `hardneg_fp=0.00%`, `finance_benign_fp=0`; files `reports/dlp-metrics.{json,md}` written |
| RED-V04 | RE2 portability (judges can't ReDoS) | `pytest tests/unit/redaction_engine/test_re2_portability.py` (every built-in pattern compiles with `re2`; invalid user pattern → ValueError and the default scanner is kept) | pass |
| RED-V05 | Vault/rehydrate invariants | `pytest tests/unit/redaction_engine/test_vault_rehydrate.py test_stream_rehydrator.py` | `rehydrate(apply(x)) == x`; `apply(rehydrate(y)) == y`; same value → same placeholder; other session → untouched; `[Step 1]`, `arr[0]`, `[EMAIL_9]`, `[REDACTED:CVV]` untouched; `[ pesel_1 ]` restored; 2000/2000 random chunkings identical; JSON-escaped values keep `partial_json` valid; TTL eviction; cap → irreversible marker |
| RED-V06 | `apply` semantics | `pytest tests/unit/redaction_engine/test_engine_apply.py` | overlaps longest-wins; `redactable=False` byte-identical; `Redaction` offsets index the ORIGINAL text; CVV → `[REDACTED:CVV]` + `reversible=False`; explicit `replacement` honoured |
| RED-V07 | Control decisions (matrix, neutral action, thresholds) | `pytest tests/unit/redaction_engine/test_controls.py` | F1 prompt → remote: DLP-01 `redact` with PESEL, IBAN, PAN, CARD_EXPIRY, CVV (CVV replacement irreversible) and no raw value in the outbound segments. Same → local: PESEL/IBAN `allow`, PAN/CVV `redact`. `%B4111…^…?` → `block` everywhere. PAN in WebFetch args → `block`. `Order 4111 1111 1111 1112` / `44051401358` → `None`. DLP-02: `key AKIA0123456789ABCDEF` user → `block`; same in a `tool_result` → `redact`; `AKIAIOSFODNN7EXAMPLE` → `log`; local → `log`. Edits: matrix `CONFIDENTIAL.remote: block` → `block`; DLP-01 `action: log` → `log`; DLP-02 `action: redact` → `redact`; DLP-07 `threshold: 0.8` → heuristic PERSON `log`, PESEL still redacted by DLP-01 |
| RED-V08 | DLP-05 + DLP-08 | same file | canary in model.response → `block`; secret in model.response → `redact` with `replacement="[REDACTED:AWS_KEY]"`; IBAN in `mcp.result` toward remote → reversible tokenize; local-only agent → `allow`. DLP-08: model.response → `allow` + `meta.rehydrate`; `Write` with `[EMAIL_1]` (vault has it) → `log` + rehydrate; `WebFetch` → placeholders kept; `[PAN_1]` into `Write` with `respect_matrix` → not rehydrated; `aegis_rehydrate: true` → third_party `block` |
| RED-V09 | Snippet tests pass deterministically | `pytest tests/unit/redaction_engine/test_snippet.py` (loads `config/snippets/redaction-engine.yaml`, validates each control entry with `ControlConfig`, runs every inline test through our controls with the contract-default matrix **and** the §4.3 matrix, `AEGIS_SEMANTIC=off`) + the contract global tests `pesel-to-remote`, `invalid-pesel`, `aws-key-blocked` | all pass in both matrices |
| RED-V10 | Privacy by construction | `pytest tests/unit/redaction_engine/test_privacy.py` | No gold value (verbatim or digits-only) in any `Decision` / `Finding` / `Redaction` JSON, `mask_for_log`, `session_stats`, log records (caplog) or route responses. Fingerprints are `hmac:` and differ from `sha256(value)`. |
| RED-V11 | Whole unit suite fast | `AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/redaction_engine -q -m "not semantic"` + `uv run --frozen ruff check src/aegis/redaction src/aegis/controls/dlp src/aegis/api/routes/redaction.py tests/unit/redaction_engine` | green in < 10 s; ruff clean |
| RED-V12 | NER real model | `AEGIS_SEMANTIC=auto uv run --frozen pytest tests/unit/redaction_engine/test_ner.py -m semantic -q` | PERSON for `Jan Kowalski`, `Jana Kowalskiego`; ADDRESS for `ul. Floriańskiej 15`; HEALTH for `cukrzycę`; none for "Kraków is the capital…"; warm p95 ≤ 60 ms short text; `status().loaded` true; timeout 1 ms → fallback + `degraded` |
| RED-V13 | Perf budget | `uv run --frozen python -m aegis.redaction.evaluate --bench` | Tier D p95 ≤ 15 ms @16 KB; 20-turn transcript second pass ≥ 90 % cache hits; mask_for_log ≤ 1 ms @2 KB |
| RED-V14 | Routes in-process | `pytest tests/unit/redaction_engine/test_route.py` | `/api/redaction/entities` lists all §3.4 entities with ≥ 1 detector each (NER entities list `heuristic.*` / `ner.eu-pii-ner`); `/metrics` returns the §4.3 shape; `DELETE /sessions/x` as member → 403, as admin → `{ok: true}` |
| RED-V15 | Integration (after core-gateway lands; manual + e2e) | In-process app (`aegis_env` fixtures): `POST /api/playground {"text": "<F1 prompt>", "destination": "remote", "model": "mock-echo", "send": true}`, then `GET mock_llm /_mock/requests` | Verdict `redact`; upstream body contains `[PESEL_1]`, `[IBAN_1]`, `[PAN_1]`, `[REDACTED:CVV]`, no `44051401359` / `4111 1111` / `CVV 123`; `response.local` contains `44051401359`; `X-Aegis-Redactions ≥ 5`; same with `destination: "local"` (`aegis-judge`, `send:false`) → PESEL kept, PAN tokenized; decision drawer shows original vs outbound; audit JSONL grep for `44051401359` → 0 hits |
| RED-V16 | Live policy edit (manual on stage) | Edit `config/policy.yaml`: `destinations.matrix.CONFIDENTIAL.remote: block` → playground re-run | `block` within ~1 s; revert → `redact` |

---

## 6. Demo cut

**Must really work live (never faked):**
- DLP-01 tokenization of PESEL / IBAN / PAN / expiry / email / phone to remote, CVV dropped irreversibly, track data blocked; local destination keeps PESEL and tokenizes PAN; third-party PAN blocked. Visible in mock_llm `/_mock/requests` and the drawer.
- Rehydration of the model answer for the local user (buffered stream mode) and of local tool inputs via the PreToolUse hook (`Write` / `Edit` get real values; WebFetch keeps placeholders).
- DLP-02 secret block in prompts (plus tokenization inside tool results).
- DLP-05 tool / MCP-result redaction before a remote model, and canary block.
- Live matrix / threshold / action edits flipping verdicts.
- Audit holds only spans, masked previews and HMAC fingerprints.

**May be simplified / stubbed convincingly:**
- **DLP-07** runs on deterministic heuristics (badge `degraded`) if the ONNX NER cannot be loaded under RAM pressure. The heuristic catches the scripted names, addresses and health terms. Say so honestly on stage.
- **Holdback streaming:** MVP is `buffered`. The `StreamRehydrator` exists and is unit-tested (split placeholders), so we can show the test instead of a live holdback stream.
- **Precision / recall table** may be served from a pre-generated `reports/dlp-metrics.json`. The dashboard's mock fallback shows the same shape.
- **Not built:** opaque tokens, cross-segment fragments, shell-egress rehydration guard, allowlist CLI. Metadata stripping is DLP-03 (metadata-egress), and OCR / files are out of scope.

---

## 7. Dependencies

**Python runtime** (all in §7.6 unless marked):
- `pydantic>=2.9`, `fastapi`;
- `google-re2` (user/feed patterns; built-ins on stdlib `re` with ASCII flags);
- `onnxruntime` (1.30 measured), `tokenizers` (0.23 measured), `numpy` for NER;
- `psutil` (optional RAM guard).
- **`phonenumbers` (Apache-2.0, ≥ 9.0) — DEPS REQUESTED.** The staged phone detector uses it. The import is guarded and a regex fallback runs if it is absent; precision on phones degrades slightly, and RED-V03 reports `PHONE` separately.

**Python dev:** `pytest`, `pytest-asyncio`, `asgi-lifespan`, `httpx`, `ruff`. `hypothesis` is **not required**: the property-style tests use seeded `random`.

**Not used:**
- Presidio / spaCy: optional per contract, not needed. Our NER covers PL+EN; Polish spaCy is GPL.
- faker (fixtures already generated).
- gitleaks.toml (not available offline; the staged rule set is gitleaks-derived and RE2-clean).
- torch / transformers (forbidden).

**Models:** `models/eu-pii-ner/{model_quantized.onnx, tokenizer.json, config.json}`, already present (read only). Footprint ~673 MB (RESULTS.md), or ~400 MB with a shared tokenizer.

---

## 8. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Our inline policy tests fail in the self-test gate (matrix differs, NER off) → the whole policy is rejected | Gateway runs a stale or rejected policy | Snippet tests avoid matrix-ambiguous cells and NER-only outcomes; RED-V09 runs them under both matrices with `AEGIS_SEMANTIC=off`. The AWS legacy rule fixes the contract's own `aws-key-blocked` test. |
| Raw values leak on later Claude Code turns (rehydrated history paraphrased by the model; NER / context miss) | Headline promise broken | Known-value rescan from the session vault (must); deterministic numbering; known-value spans score 1.0 |
| Rehydrating tool_use inputs in model responses sends raw values to third-party tools | Data exfil | DLP-08 meta `roles: ["assistant"]` + an explicit request to core-gateway (§4.2); tool inputs are rehydrated only via the PreToolUse hook for `local` tools, respecting the matrix |
| NER RAM (673 MB) on 8 GB next to Ollama | Swapping or OOM in the demo | Lazy background load, `AEGIS_SEMANTIC=off` / DLP-07 disabled → never loaded, psutil guard, shared tokenizer (gap §4.4), deterministic fallback with `degraded` badge, `fail_mode: open` |
| NER latency spikes (first call, 512-token windows) | DLP-07 timeouts | `timeout_ms: 400`, segment / size caps, LRU cache, warm-up call after load, semantic phase runs concurrently |
| Tier D on huge Claude Code requests exceeds `timeout_ms` with `fail_mode: closed` → false blocks | Claude Code turns blocked | Content-hash cache (history ≈ always a hit), `to_thread` for > 4 KB, snippet `timeout_ms: 2000` for DLP-01 / DLP-02 / DLP-05 |
| False positives annoy judges (NIP / REGON / ID ≈ 10 % random checksum pass, phones in tables) | Bad UX | Context-required `min_scores` (0.6 / 0.7), hard-negative fixtures (127) at 0 FP, the finance-benign set, `allowlist_values` / `allow_patterns`, monitor mode |
| Judges paste exotic evasions (spelled digits, homoglyphs, base64) | Missed detection | Normalizer (fullwidth, Arabic-Indic, zero-width, NBSP, dashes, homoglyphs, `[at]`, spelled-out digits EN+PL ≥ 6 words) + decode-and-rescan depth 2; adversarial recall 100 % on fixtures; known gaps (OCR, reference-style links) documented |
| Placeholder mismatch between streaming (core) and engine | Values not restored / foreign tokens restored | One regex module (`aegis.redaction.placeholders`, gap §4.2); canonical upper-case keys; unit-tested 2000 random chunkings |
| `phonenumbers` missing from manifests | Import error at boot | Guarded import + regex fallback; deps request |
| Demo copy still shows the staging names (`[CREDIT_CARD_1]`, `[PL_PESEL_1]`, `[CVV]`) | Inconsistent story | Request to demo-mocks-docs / dashboards to use `[PAN_1]`, `[PESEL_1]`, `[REDACTED:CVV]` (contract) |
| Judge enters an invalid RE2 in DLP params | Scanner compile error | Keep the default scanner for that snapshot, `system` warning toast, `degraded` flag; never crash |

---

## 9. Snippet draft (`config/snippets/redaction-engine.yaml`)

Proposed entries; policy-engine merges them. Params have code defaults, so a missing key is fine. Tests use only matrix cells on which the contract schema default and §4.3 agree, and they pass with `AEGIS_SEMANTIC=off`.

```yaml
# --- proposed destinations.matrix (same as CONTRACTS §4.3; judges edit cells live) ---
destinations:
  matrix:
    CONFIDENTIAL: {local: allow,  remote: redact, third_party: block}
    RESTRICTED:   {local: redact, remote: redact, third_party: block}
    SECRET:       {local: log,    remote: block,  third_party: block}
    INTERNAL:     {local: allow,  remote: redact, third_party: redact}   # acted on by DLP-03 (metadata-egress)

controls:
  - id: DLP-01
    name: PII/PCI/Polish-ID tokenization (destination matrix)
    action: redact            # neutral: matrix decides. log = detect-only, block/require_approval = escalate every hit
    severity: high
    fail_mode: closed
    timeout_ms: 2000
    # threshold: 0.5          # optional global min detector score (validated hits score 0.9-1.0)
    params:
      entities: [EMAIL, PHONE, DOB, PESEL, NIP, REGON, PL_ID_CARD, PASSPORT, IBAN, PAN, CARD_EXPIRY, CVV, TRACK_DATA, CRYPTO_ADDRESS]
      mask_style: placeholder # placeholder -> [PAN_1] (reversible) | pci -> 411111******1111 (irreversible)
      min_scores: {NIP: 0.6, REGON: 0.7, PL_ID_CARD: 0.7, PASSPORT: 0.7}
      force_block: [TRACK_DATA]
      redaction_ratio_block: 0.6
      ratio_min_chars: 200
      ratio_roles: [user, tool_args]
      max_entities_per_request: 200
      known_values: true      # re-tokenize values already in the session vault (multi-turn safety)
      phone_regions: [PL, GB, US, DE]
      email_reserved_tlds: [example, test]
      decode_depth: 2
      allowlist_values: []    # "hmac:<16 hex>" fingerprints (python -m aegis.redaction.preview fp ENTITY value)
      allow_patterns: []      # RE2 against the canonical value
    owasp: [LLM02:2026, ASI03, MCP10:2025]
    tests:
      - {name: pesel-to-remote, text: "Klient Jan, PESEL 44051401359", destination: remote, expect: redact, control: DLP-01}
      - {name: invalid-pesel, text: "Zamowienie 44051401358 wyslane", destination: remote, expect: allow}
      - {name: client-pii-to-remote, destination: remote, expect: redact, control: DLP-01,
         text: "Please draft a reply confirming the refund to IBAN PL61 1090 1014 0000 0712 1981 2874. His PESEL is 44051401359 and the card on file is 4111 1111 1111 1111 exp 12/27, CVV 123."}
      - {name: same-pii-to-local, destination: local, expect: allow,
         text: "Client PESEL 44051401359, IBAN PL61 1090 1014 0000 0712 1981 2874 - summarise the KYC file."}
      - {name: card-to-local-tokenized, destination: local, text: "Refund card 4111 1111 1111 1111 please", expect: redact, control: DLP-01}
      - {name: non-luhn-order-number, destination: remote, text: "Order 4111 1111 1111 1112 shipped yesterday.", expect: allow}
      - {name: invalid-iban-lookalike, destination: remote, text: "Reference PL61 1090 1014 0000 0712 1981 2875 is a ticket id.", expect: allow}
      - {name: track-data-always-blocks, destination: local, text: "Parse this swipe: %B4111111111111111^KOWALSKI/JAN^2712101000000000000?", expect: block}

  - id: DLP-02
    name: Secrets & credentials
    action: block             # neutral: matrix SECRET row decides. redact = tokenize secrets instead of blocking
    severity: critical
    fail_mode: closed
    timeout_ms: 2000
    params:
      entropy_min: 4.0        # generic high-entropy rules only (format-specific rules keep built-in gates)
      min_len: 20
      allow_doc_examples: true  # AKIAIOSFODNN7EXAMPLE & co. -> log
      redact_roles: [tool_result, document]   # secrets inside tool output are tokenized, not turn-killing
      extra_rules: []         # [{id, pattern (RE2), entity: GENERIC_SECRET, score: 0.9}]
    owasp: [MCP01:2025, LLM02:2026, ASI03]
    tests:
      - {name: aws-key-prompt, text: "Deploy with key AKIA0123456789ABCDEF please", destination: remote, expect: block, control: DLP-02}
      - {name: aws-doc-example-logged, text: "AWS docs show AKIAIOSFODNN7EXAMPLE as the sample key id", destination: remote, expect: log, control: DLP-02}
      # (no generic must-allow prose here: other controls, e.g. INJ-03 off-topic `log`, could change the final action)

  - id: DLP-05
    name: Output & tool-result leak detection (+ canary)
    action: redact
    severity: high
    fail_mode: closed
    timeout_ms: 2000
    params:
      canaries: ["AEGIS-CANARY-7f3a91"]
      response_replacement: irreversible   # model-emitted sensitive values are never vaulted
      detect_reidentification: true
    owasp: [LLM02:2026, LLM05:2026, MCP10:2025]
    tests:
      - {name: canary-in-response, kind: model_call, surface: model.response, text: "Sure! My instructions say: AEGIS-CANARY-7f3a91 You are...", expect: block}
      - {name: secret-in-response, kind: model_call, surface: model.response, text: "Use key AKIA0123456789ABCDEF to connect", expect: redact, control: DLP-05}
      - {name: crm-result-to-remote, kind: mcp, surface: mcp.result, destination: remote, expect: redact, control: DLP-05,
         text: "{\"name\": \"Anna Nowak\", \"email\": \"anna.nowak@poczta.example\", \"iban\": \"PL61 1090 1014 0000 0712 1981 2874\"}"}
      - {name: clean-answer, kind: model_call, surface: model.response, text: "The portfolio beta is roughly 1.1 versus WIG20.", expect: allow}

  - id: DLP-07
    name: Multilingual NER sensitive data (incl. Polish)
    action: redact
    threshold: 0.6
    severity: medium
    fail_mode: open
    timeout_ms: 400
    params:
      entities: [PERSON, ADDRESS, HEALTH, DOB]
      roles: [user, tool_args, tool_result, document]
      max_chars: 8000
      max_segments: 8
      skip_code: true
      heuristic_fallback: true
      label_min_scores: {PERSON: 0.55}
    owasp: [LLM02:2026, MCP10:2025]
    tests:
      - {name: polish-name-address-health, destination: remote, expect: redact,
         text: "Jan Kowalski mieszka przy ul. Floriańskiej 15, 31-019 Kraków i choruje na cukrzycę."}
      - {name: place-not-person, destination: remote, text: "Kraków is the capital of the Lesser Poland Voivodeship.", expect: allow}

  - id: DLP-08
    name: Vault & controlled re-identification
    action: allow
    severity: high
    fail_mode: closed
    params:
      rehydrate_to: [local_user, local_tools]
      vault_ttl_s: 3600
      max_entries: 10000
      respect_matrix: true            # into local tools only classes whose matrix.<class>.local is allow/log
      deny_tools: [WebFetch, WebSearch]
      audit_tool_rehydration: true    # tool-input rehydration shows as `log` in the live feed
      token_format: indexed           # indexed [EMAIL_1] | opaque [EMAIL_K7F3] (could)
    owasp: [LLM02:2026, MCP10:2025, ASI03]
    tests:
      - {name: response-with-placeholder, kind: model_call, surface: model.response, text: "Draft for [PERSON_1] is ready.", expect: allow}
```

---

## 10. Requests to other owners (for the integration report)

| Owner | Request |
|---|---|
| scaffold | Contract addenda §4.2–§4.4 (placeholders public surface + engine extras; entities `CRYPTO_ADDRESS`, `MAC_ADDRESS`, `SPECIAL_CATEGORY`; three extra `/api/redaction/*` endpoints; optional shared tokenizer); add **`phonenumbers`** to the manifests |
| core-gateway | Response path: rehydrate only roles in the DLP-08 `meta.roles` (assistant text), never `tool_use` inputs; holdback streaming (stretch) via `rt.redactor.vault_view(ctx)` / `aegis.redaction.placeholders.StreamRehydrator`; keep `ctx.session_id` = `x-claude-code-session-id` = hook `session_id`; the PolicyTest → Interaction builder gives `text` a `user`-role segment |
| claude-code-integration | DLP-08 decision `meta.rehydrate` on `tool.input` → `updatedInput` via `rt.redactor.rehydrate_obj(ctx, tool_input)` (fallback: per-string `rehydrate`); PostToolUse redact → `updatedToolOutput`; `SessionEnd` → `getattr(rt.redactor, "forget_session")(session_id)` |
| metadata-egress | INTERNAL entities: we provide `IP_ADDRESS`, `USERNAME`, `MAC_ADDRESS` detectors via `rt.redactor.detect(text, entities={…})`; DLP-01 does not act on INTERNAL by default; DLP-03 findings with explicit `replacement` are honoured by `apply` |
| policy-engine | Merge the snippet (matrix + 5 controls); keep DLP inline tests in the self-test gate |
| audit-metrics | Increment `aegis_redactions_total{entity,dest_class}` from `verdict.redactions` + `interaction.destination.dest_class` |
| dashboard-security | "Redaction quality" panel (P/R/F1, leak rate, adversarial recall per entity) from `GET /api/redaction/metrics` (page-local TS type §4.3); entity chips from `/api/redaction/entities`; placeholder chips in the drawer's outbound view (search `\[[A-Z_]+_\d+\]` / `\[REDACTED:[A-Z_]+\]`) |
| demo-mocks-docs | Mock data emails may use `.example` (we detect them); scripts/README/video copy use `[PAN_1]`, `[PESEL_1]`, `[REDACTED:CVV]`; `make test-dlp`-style entry = `python -m aegis.redaction.evaluate --check --write` |
| semantic-models | Optional `rt.semantic.shared_tokenizer("xlmr")` (saves ~250 MB) |
| redteam-eval-perf | May embed `reports/dlp-metrics.json` into `reports/eval.json` / `bench.json` |
