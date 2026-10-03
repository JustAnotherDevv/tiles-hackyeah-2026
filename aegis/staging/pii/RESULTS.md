# PII / secrets Tier-D — fixtures, reference implementation, results

_Generated 2026-10-03 by `python -m pii.evaluate --write-results` (numbers are live from the current code + fixtures; holdout first-run row is recorded)._

## Summary

- **626 labelled cases** in 6 JSONL files, **816 Tier-D gold entities** (+ PERSON / ADDRESS labels for the NER tier), **all 17 evasion techniques** (77 cases), **145 hard negatives**.
- Tier-D on all fixtures: **precision 1.000 · recall 1.000 · F1 1.000** (exact span match, scored on CONTRACTS §3.4 canonical entities). **Leak rate 0.0%** overall and **0.0% on validated types** (bytes that would leave toward a `remote` model). Hard-negative cases with any finding: **0 / 145**.
- **Aligned with `docs/CONTRACTS.md` §3.4** (written in parallel): canonical entities (`PAN`, `PESEL`, `CVV`, `TRACK_DATA`, `GITHUB_TOKEN`, …), placeholders `[PESEL_1]` / irreversible `[REDACTED:CVV]`, the shipped `destinations.matrix`, PAN mask `411111******1111`; `validators.py` function names and `normalize()`/`Normalized.to_original()` already match the contract's `aegis.redaction.*` table.
- Holdout (unseen phrasing) first run: recall 0.938, 6 leaks — both root causes fixed (see below); now P 1.000 / R 1.000.
- Random-input base rates match research 07: Luhn+IIN ≈ 4.2% of random 16-digit strings, weak checksums (NIP / REGON / ID card) **0 %** without context words, 0.0% on Faker prose.
- Latency (CPython 3.13, M-series, shared 8 GB box): per fixture p50 0.11 ms / p95 0.35 ms; PII-dense 4 KB prose p50 7.1 ms; all pathological inputs linear (≤ ~20 ms / 10 KB).
- **Caveat (read this):** the generator and the detector were written by the same agent, so the main-set 100 %-style numbers are optimistic by construction. The honest signals are the holdout first run, the random-input base rates and the fuzz/pathological tests. Judges' ad-hoc prompts will find gaps (see *Known gaps*).

## Run it

```bash
cd aegis/staging/pii
uv run --python 3.13 --with faker --with phonenumbers --with google-re2 --with pytest pytest -q
# regenerate fixtures / this report (from aegis/staging):
uv run --python 3.13 --with faker --with phonenumbers --with google-re2 python -m pii.gen_fixtures
uv run --python 3.13 --with faker --with phonenumbers --with google-re2 python -m pii.evaluate --write-results
# add --no-project to `uv run` if aegis/ later gets a pyproject.toml
```

## Files

| File | Purpose |
|---|---|
| `normalize.py` | anti-evasion view + exact offset map (`Normalized.to_original`) |
| `validators.py` | Luhn+IIN, IBAN mod-97 + country lengths, NRB, PESEL (+date), NIP, REGON 9/14, ID card, passport, base58check, bech32/bech32m, EIP-55 (pure-Python Keccak), JWT, IP, TLDs |
| `detectors.py` | `Detector`/`DetectorConfig`, 25 entity types, 37 secret rules (gitleaks formats + generic/env/header/conn-string) + `load_gitleaks_rules()`, decode-and-rescan, JSON cross-field join, `detect_segments()`, merge, `fingerprint()`, `compile_user_pattern()` (RE2) |
| `placeholders.py` | session `Vault`/`VaultStore`, `redact()` (zone × class matrix, operators, audit spans), PCI previews, `rehydrate()`, `StreamRehydrator`, `InverseCache`, `leak_scan()` |
| `gen_fixtures.py` | deterministic Faker generator (seed 20261003) for all fixture files |
| `evaluate.py` | metrics, stress base rates, latency bench, this report |
| `fixtures/*.jsonl` | labelled cases (schema below) |
| `tests/` | 101 tests: validators, normaliser offsets, fixture metrics, behaviour units, contract projection, vault/rehydration, linear-time, fuzz |

## Fixtures

Schema per line: `{id, text, lang: pl|en|code, entities: [{type, start, end, value, subtype?}], expect: redact|allow, tags}` — `type` is the CONTRACTS §3.4 canonical entity; `subtype` keeps the granular type where it differs (`PL_NRB`, `URL_SECRET`, `SECRET:gitlab`, …); `value == text[start:end]` (Python str offsets). Values are Faker `pl_PL/en_US/en_GB/de_DE/fr_FR/it_IT/nl_NL` outputs asserted valid by the checksum validators; hard negatives are asserted **invalid** by the same validators **and** by libphonenumber (independent of the detector). Tags: `positive`, `adversarial` + `A1…A17`, `hard-negative` + reason (`off-by-one`, `context-gated`, `tracking-number`, `timestamp`, `phone-like-id`, …), `holdout`.

| File | Cases | Entities (all labels) |
|---|---:|---:|
| `adversarial.jsonl` | 77 | 81 |
| `hard_negatives.jsonl` | 127 | 0 |
| `holdout.jsonl` | 96 | 102 |
| `positives_en.jsonl` | 100 | 275 |
| `positives_pl.jsonl` | 130 | 345 |
| `secrets_code.jsonl` | 96 | 144 |
| **total** | **626** | **947** |

## Per-entity metrics (all fixtures, default thresholds, destination `remote`)

*Validated* = checksum/structure validated (leak target exactly 0); *ctx* = context/format scored. Exact = same type and exact span; *covering* = predicted span of the same type covers the gold span. *Leak* = gold value still present (verbatim, normalised, or as a digit subsequence) in the redacted output.

| Entity | Validated | Gold | TP | FP | FN | Precision | Recall | F1 | Covering recall | Leak rate | Adversarial recall |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CRYPTO_BTC | yes | 18 | 18 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| CRYPTO_ETH | yes | 15 | 15 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| IBAN | yes | 103 | 103 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| JWT | yes | 7 | 7 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| NIP | yes | 31 | 31 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| PAN | yes | 106 | 106 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| PASSPORT | yes | 19 | 19 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| PESEL | yes | 54 | 54 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| PL_ID_CARD | yes | 28 | 28 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| PRIVATE_KEY | yes | 6 | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| REGON | yes | 23 | 23 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| TRACK_DATA | yes | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| ANTHROPIC_KEY | ctx | 10 | 10 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| AWS_KEY | ctx | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| AWS_SECRET | ctx | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| CARD_EXPIRY | ctx | 23 | 23 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| CONNECTION_STRING | ctx | 6 | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| CVV | ctx | 26 | 26 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| DOB | ctx | 25 | 25 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| EMAIL | ctx | 95 | 95 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| GENERIC_SECRET | ctx | 56 | 56 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| GITHUB_TOKEN | ctx | 12 | 12 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| IP_ADDRESS | ctx | 37 | 37 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| MAC_ADDRESS | ctx | 10 | 10 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| OPENAI_KEY | ctx | 6 | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| PASSWORD | ctx | 9 | 9 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| PHONE | ctx | 62 | 62 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| SLACK_TOKEN | ctx | 6 | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| STRIPE_KEY | ctx | 6 | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | n/a |
| USERNAME | ctx | 8 | 8 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.0% | 100.0% |
| **all Tier-D** | | **816** | **816** | **0** | **0** | **1.000** | **1.000** | **1.000** | | **0.0%** | |

By language: **code** P 1.000 R 1.000 (n=165) · **en** P 1.000 R 1.000 (n=285) · **pl** P 1.000 R 1.000 (n=366)  
Case-level expect accuracy 1.000; rehydration round-trip exact on 480/480 fully-tokenized cases.

## Evasion catalogue (research 07 §11.2)

| # | Technique | Cases | Passed (exact spans, no leak) |
|---|---|---:|---:|
| A1 | separators (`.` `-` mixed) | 6 | 6 |
| A2 | one char per gap | 4 | 4 |
| A3 | fullwidth / Arabic-Indic / Devanagari digits | 7 | 7 |
| A4 | zero-width, soft hyphen, word joiner | 5 | 5 |
| A5 | NBSP / thin space / Unicode dashes | 5 | 5 |
| A6 | homoglyphs (Cyrillic/Greek) | 5 | 5 |
| A7 | split across messages (joined view) | 4 | 4 |
| A8 | split across JSON fields | 3 | 3 |
| A9 | base64 / base64url / hex / %-encoding | 7 | 7 |
| A10 | spelled-out digits (EN + PL) | 4 | 4 |
| A11 | obfuscated email `[at]` `(dot)` `{małpa}` | 4 | 4 |
| A12 | line-wrapped values | 4 | 4 |
| A13 | code fences / markdown table / CSV / JSON array | 5 | 5 |
| A14 | re-identification prompt (expect allow) | 3 | 3 |
| A15 | rehydration-targeted injection | 3 | 3 |
| A16 | metadata dumps (EXIF / PDF Info / docProps) as text | 3 | 3 |
| A17 | HTTP headers (XFF, Cookie, Bearer, x-api-key) | 5 | 5 |

A14/A15 are gateway behaviours: detection must *not* fire on placeholders, and `rehydrate()` refuses untrusted hops (`tests/test_placeholders.py::test_rehydration_only_to_trusted_hops`). A16 binary metadata stripping (JPEG/PNG/PDF/OOXML) is out of this module's scope; the fixtures cover the *text* those dumps leak.

## Holdout (unseen phrasing)

| run | cases | Tier-D gold | precision | recall | F1 | leaked | hard-neg FP |
|---|---:|---:|---:|---:|---:|---:|---:|
| first run (unseen phrasing) | 96 | 96 | 1.000 | 0.938 | 0.968 | 6 / 96 | 0 / 18 |

First-run misses: (1) `my Polish ID OZJ753764` — "ID"/"Polish ID" was not a context phrase for dowód osobisty (weak checksum → context-gated); (2) `login admin, hasło Xy7!…` — Polish password phrasing without `:`/`=`. Fixes: added ID context words; new `password-inline` rule that only fires when the value has ≥ 3 character classes. After fixes: P 1.000 / R 1.000 / leak 0.0%.

## Random-input base rates (not fixtures; 2000 samples each, seed 7)

| Probe | Flagged |
|---|---:|
| 16 digits, compact, no context -> CREDIT_CARD | 4.2% |
| 16 digits, 4-4-4-4, 'karta' context -> CREDIT_CARD | 3.8% |
| 11 digits, no context -> PL_PESEL | 1.0% |
| 10 digits, no context -> PL_NIP | 0.0% |
| 10 digits, 'NIP' context -> PL_NIP | 8.8% |
| 9 digits, no context -> PL_REGON | 0.0% |
| AAA999999, no context -> PL_ID_CARD | 0.0% |
| AAA999999, 'dowód' context -> PL_ID_CARD | 10.5% |
| 26 digits, compact -> PL_NRB | 1.1% |
| 9 digits, no context -> PHONE | 0.0% |
| Faker prose paragraphs (pl+en) with any finding | 0.0% |

Luhn+IIN collisions (~4 %) and contextual NIP/REGON/ID collisions (~9–10 %) are inherent to the checksums (research 07 measured 3.96 % / 8.94 % / 9.98 %); that is exactly why weak types require context words (`min_score` 0.6–0.7) and why judges should see them as *log-only* below threshold (`Detector.analyze`).

## Latency

Per fixture (avg 93 chars): p50 0.11 ms · p95 0.35 ms · max 10.9 ms.

| Payload (fixture text concatenated = PII-dense, ~1 entity / 90 chars) | p50 ms | p95 ms |
|---|---:|---:|
| prose 1 KB | 2.1 | 2.5 |
| prose 4 KB | 7.1 | 7.6 |
| prose 16 KB | 29.7 | 30.7 |
| code 1 KB | 0.9 | 1.1 |
| code 4 KB | 4.5 | 5.1 |
| code 16 KB | 21.9 | 25.9 |

CPython reference numbers; real traffic is far sparser and the gateway should cache by `sha256(segment) + policy_version` (Claude Code resends history). Pathological inputs (10 KB of single-digit groups, `eyJ`×3000, 1000 BEGIN markers, 10 KB local-part without `@`, 3000 number words, …) run in ≤ ~20 ms each — a regression test enforces < 250 ms (`test_pathological_inputs_stay_linear`).

## Drop-in integration notes

```python
from pii.detectors import Detector, DetectorConfig
from pii.placeholders import VaultStore, redact, rehydrate, StreamRehydrator, may_rehydrate, mask_for_log

det = Detector(DetectorConfig(min_scores={'PL_NIP': 0.6}, deny_terms=('Project Falcon',)))
vaults = VaultStore(ttl_s=3600)                     # DLP-08 vault_ttl_s; per session, in-memory only
fs = det.detect(segment.text)                        # f.entity / f.to_span() == core Span fields
res = redact(segment.text, fs, vault=vaults.get(session_id), zone='remote', hmac_key=KEY)
if res.blocked: ...                                  # res.reasons, res.spans -> Finding/Redaction/audit
upstream_text = res.text                             # '[PESEL_1]', '[PAN_1]', '[REDACTED:CVV]'
if may_rehydrate('local_user'): text = rehydrate(model_text, vaults.get(session_id))
sr = StreamRehydrator(vaults.get(session_id))        # holdback mode: one per SSE content block
```

| Detector `type` (granular) | Canonical `entity` (§3.4) | Data class |
|---|---|---|
| `CREDIT_CARD` | `PAN` | RESTRICTED |
| `CARD_CVV` | `CVV` | RESTRICTED |
| `CARD_EXPIRY` | `CARD_EXPIRY` | RESTRICTED |
| `CARD_TRACK` | `TRACK_DATA` | RESTRICTED |
| `IBAN` | `IBAN` | CONFIDENTIAL |
| `PL_NRB` | `IBAN` | CONFIDENTIAL |
| `PL_PESEL` | `PESEL` | CONFIDENTIAL |
| `PL_NIP` | `NIP` | CONFIDENTIAL |
| `PL_REGON` | `REGON` | CONFIDENTIAL |
| `PL_ID_CARD` | `PL_ID_CARD` | CONFIDENTIAL |
| `PL_PASSPORT` | `PASSPORT` | CONFIDENTIAL |
| `EMAIL` | `EMAIL` | CONFIDENTIAL |
| `PHONE` | `PHONE` | CONFIDENTIAL |
| `IP_ADDRESS` | `IP_ADDRESS` | INTERNAL |
| `JWT` | `JWT` | SECRET |
| `PRIVATE_KEY` | `PRIVATE_KEY` | SECRET |
| `URL_SECRET` | `GENERIC_SECRET` | SECRET |
| `PATH_USERNAME` | `USERNAME` | INTERNAL |
| `DATE_OF_BIRTH` | `DOB` | CONFIDENTIAL |
| `MAC_ADDRESS` | `MAC_ADDRESS` *(extension, not in §3.4)* | INTERNAL |
| `CRYPTO_BTC` | `CRYPTO_BTC` *(extension, not in §3.4)* | CONFIDENTIAL |
| `CRYPTO_ETH` | `CRYPTO_ETH` *(extension, not in §3.4)* | CONFIDENTIAL |
| `DENY_TERM` | `DENY_TERM` *(extension, not in §3.4)* | CONFIDENTIAL |
| `CUSTOM` | `CUSTOM` *(extension, not in §3.4)* | CONFIDENTIAL |
| `SECRET` (rule id → entity) | `aws-access-key`→`AWS_KEY`, `aws-secret-key`→`AWS_SECRET`, `github-pat`→`GITHUB_TOKEN`, `github-oauth`→`GITHUB_TOKEN`, `github-app-token`→`GITHUB_TOKEN`, `github-refresh-token`→`GITHUB_TOKEN`, `github-fine-grained-pat`→`GITHUB_TOKEN`, `slack-token`→`SLACK_TOKEN`, `slack-webhook-url`→`SLACK_TOKEN`, `stripe-access-token`→`STRIPE_KEY`, `openai-api-key`→`OPENAI_KEY`, `anthropic-api-key`→`ANTHROPIC_KEY`, `connection-string-password`→`CONNECTION_STRING`, `password-label`→`PASSWORD`, `password-inline`→`PASSWORD`, `basic-auth-header`→`PASSWORD`; generic rule with a password-like key → `PASSWORD`; all other rules → `GENERIC_SECRET` | SECRET |

- **Offsets:** `Finding.start/end` index the *original* string (fullwidth digits, ZW chars, `[at]` included) — exactly what `Redaction.start/end` needs; `Finding.canonical` is the normalised compact value (vault key + HMAC input).
- **PCI invariants enforced in code, not policy:** `CVV` and `TRACK_DATA` → `[REDACTED:CVV]` / `[REDACTED:TRACK_DATA]` (drop; `Vault.put` raises; no fingerprint, no preview; a policy asking to tokenize is coerced); PAN preview first 6 / last 4 `411111******1111` (`mask_style: pci` sends that to the model instead of `[PAN_1]`); fingerprints are keyed HMAC-SHA256 (`hmac:<16 hex>`), never plain hashes.
- **Audit spans** (`RedactionResult.spans`): `{type, entity, data_class, detector, score, op, ph, reversible, start, end, orig_len, preview, fp}` with offsets into the *redacted* text — log the payload as sent, never raw values. `mask_for_log()` is a reference for `rt.redactor.mask_for_log` (findings masked + every other digit/`@`).
- **Thresholds** (`DetectorConfig.min_scores`, default 0.5; NIP 0.6, REGON/ID/passport 0.7) are the live "adherence %" sliders; validated types score 0.9–1.0 so moving the slider mostly affects context-scored types.
- **User / feed regexes** (`deny_terms`, `custom_patterns`, `allow_patterns`) compile with google-re2 only (`compile_user_pattern`) → no ReDoS from live edits. All 76 built-in patterns are RE2-compatible (tested) but run on stdlib `re` (faster in CPython); their super-linear paths were removed and are regression-tested.
- **Destination matrix:** `DEFAULT_POLICY['matrix']` is the shipped `destinations.matrix` (CONFIDENTIAL local allow / remote redact / third_party block; RESTRICTED redact/redact/block; SECRET log/block/block; INTERNAL allow/redact/redact). So demo F1 holds: local model → PESEL allowed, PAN tokenized, CVV dropped. `zone` accepts `local|remote|third_party` (and research-07 aliases `T0|T1|T2`). Rehydration only to `rehydrate_to: [local_user, local_tools]`.
- **Cross-message / cross-field splits:** pass the request's user-authored string leaves to `Detector.detect_segments()`; fragments come back with `meta.fragment=True` → non-reversible `[TYPE_FRAGMENT]`.
- **Full gitleaks set:** `Detector(extra_secret_rules=load_gitleaks_rules('gitleaks.toml'))` (MIT data; keyword prefilter honoured).

## Known gaps / limitations

- Names, addresses, organisations, GDPR Art. 9 categories are **Tier M** (NER) — labelled in the fixtures (`PERSON`, `ADDRESS`) but not detected here.
- Extensions not in CONTRACTS §3.4: `MAC_ADDRESS` (INTERNAL), `CRYPTO_BTC`, `CRYPTO_ETH`, `DENY_TERM` (CONFIDENTIAL) — add them to the vocabulary or drop those detectors when porting. `CONNECTION_STRING` spans the password only (the URL stays usable).
- DLP-02 knobs (`entropy_min: 4.0`, `min_len: 20`, `allow_doc_examples: true` → AWS docs key = *log*) are not wired: rules use per-rule entropy (3.0–3.5) and documentation/placeholder keys are dropped silently.
- Weak-checksum IDs (NIP, REGON, ID card, passport) **without** a context word or canonical formatting are deliberately not redacted (visible via `analyze()`); a bare 9-digit Polish mobile without grouping/context scores 0.4 (log-only).
- Random 16-digit numbers pass Luhn+IIN ~4 % of the time → occasional over-redaction of order numbers (safe direction). IMEI/serial/ISBN/tracking context words suppress it.
- Single-digit-gap (A2) detection is limited to digit runs of ≤ 256 groups (DoS guard); phone matching skips digit soups > 40 chars.
- Spelled-out digits need ≥ 6 consecutive digit words (EN/PL); mixed forms ("forty-one eleven…") are not parsed — leave to the semantic tier.
- If a user literally types an indexed placeholder that collides with a vault entry, rehydration will replace it; use `token_format='opaque'` for high-security sessions.
- Python `re` is used for built-ins: patterns are bounded and pathological inputs are tested, but a Go/RE2 port is the way to *guarantee* linear time.

## Dependencies requested (do not add to manifests myself)

- runtime: `phonenumbers` (Apache-2.0), `google-re2` (BSD-3). stdlib otherwise (no pycryptodome: Keccak is in `validators.py`).
- dev/test only: `faker` (MIT), `pytest` (MIT).
