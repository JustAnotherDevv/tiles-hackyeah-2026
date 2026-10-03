# Local models: downloaded, benchmarked, recommended defaults

Measured on 2026-10-03 on the team laptop (Apple M2, 8 GB RAM, 37–45 % free during the runs, macOS 27, Ollama 0.24.0, Python 3.13, onnxruntime 1.30.0, tokenizers 0.23.2). ONNX sessions use the CPU provider with 2 intra-op threads. Latency is wall-clock in-process: warm, p50/p95 over the EN+PL samples in `samples.py`. Memory: `footprint` is macOS `phys_footprint` of the whole Python process (Activity Monitor's number; includes ~40 MB of interpreter). For Ollama it is `ollama ps` size plus runner RSS.

Reproduce:
```bash
bash staging/models/download_models.sh        # ~2.0 GB: 0.8 GB ONNX + 1.2 GB Ollama, pinned commits, writes models/MANIFEST.sha256
uv run --python 3.13 --with onnxruntime --with tokenizers --with httpx --with psutil --with jinja2 \
    python staging/models/bench.py all         # one subprocess per model, Ollama unloaded between runs
```
Raw numbers and per-sample outputs are in `bench_results/*.json`.

## 1. Results table

| Model (role) | Path / tag | Disk | Memory | Load | Latency p50 / p95 | Licence | Quality on our 10–16 EN+PL samples | Recommended thresholds |
|---|---|---|---|---|---|---|---|---|
| **Horizon-Labs prompt-injection-guard-small v2** (injection, direct + indirect, multilingual) | `models/pi-horizon-small/model_quantized.onnx` | 289 MB | 438 MB footprint (peak RSS +530 MB while loading) | 1.2 s | **14 / 45 ms** short; 246 ms at 375 tokens (188 ms with 4 threads) | Apache-2.0 | **15/16**. Every injection scored ≥ 0.9999: EN, PL, indirect-in-email, full-width, Unicode-tag smuggling (its normaliser is already baked into `tokenizer.json`). Benign ≤ 0.006, except the hard negative "Ignore the outliers…" at 0.53. A 480-token report with one injected sentence scored 1.0; the same report without it scored 0.009 | **block ≥ 0.80, review 0.50–0.80** (escalate to Qwen3Guard). Degraded mode (T2 down): block ≥ 0.50 |
| **Llama Prompt Guard 2 22M** (explicit-jailbreak vote) | `models/pg2-22m/model.quant.onnx` (gravitee mirror) | 89 MB | 298 MB | 0.35 s | 6 / 13 ms; 125 ms at 440 tokens | Llama 4 Community, so ship the "Built with Llama" notice | **11/16**. Zero false positives (benign ≤ 0.0075), and catches EN direct, DAN and full-width. **Misses all 3 Polish injections**, the indirect one and tag smuggling (no normaliser) | Optional. If used, run it on T0-normalised text, block ≥ 0.30, EN only. **Drop it under memory pressure**: it costs about 260 MB in the combined process and adds nothing Horizon misses |
| **paraphrase-multilingual-MiniLM-L12-v2** (exemplar / semantic signatures) | `models/minilm-l12-multi/model_qint8_arm64.onnx` | 138 MB | 490 MB standalone. Its tokenizer adds only ~60 MB when it shares NER's vocab (see the combined row) | 0.4 s | **3 / 4 ms** per embed; kNN k=3 3–5 ms; long doc (sentence-segmented) 140 ms | Apache-2.0 | **7/8** top-1, with EN↔PL cross-lingual matches (cos EN/PL paraphrase 0.95, unrelated −0.04). The miss was "compound interest", which matched investment_advice over benign_finance. Token windows hide an injected sentence (0.12), so long texts are split into sentences (0.49–0.50 vs 0.34 benign) | Count a hit when the top-1 label is an attack label, sim ≥ **0.55**, and it beats the best benign-exemplar sim. 0.45–0.55 = review signal. Our attack paraphrases scored 0.53–0.77 against 2–3 exemplars each, while a benign query hit a *topic* rule at 0.59. So feed 5–10 exemplars per signature plus benign counter-exemplars, and use topic matches as a signal, not a sole blocker |
| **bardsai/eu-pii-anonimization-multilang** INT8 (NER for PII + GDPR Art. 9) | `models/eu-pii-ner/model_quantized.onnx` | 288 MB | 673 MB | 0.6 s | **13 / 19 ms** short; 231 ms at 512 tokens (2 windows) | Apache-2.0 | 16/25 expected labels. **Names 6/6** (PL inflected included), email 2/2, phone 2/2, DOB 1/1, IBAN, street addresses (tagged LOCATION, remapped to POSTAL_ADDRESS when the span has digits), HEALTH_DATA ("cukrzycę typu 2"), RELIGION ("katolikiem" 0.33). Structured IDs get the right type but **low confidence**: PESEL 0.17, ID card 0.23, AWS key 0.17, IP 0.09; the card number was tagged DOCUMENT_REFERENCE. "Kraków" stays LOCATION; "NSZZ Solidarność" came out as ORG, not union membership | min score **0.50** default, PERSON_NAME 0.55, LOCATION / ORG 0.60, Art. 9 categories **0.30**. Leave PESEL / NIP / IBAN / PAN / IP / keys to the deterministic tier (regex + checksum); NER is corroboration only (`ner_pii.LABEL_MIN_SCORE`) |
| **T1 combined in one process**: Horizon + NER + MiniLM (shared XLM-R vocab) | — | — | **1.07–1.23 GB** (1.51 GB without vocab sharing; +PG2 1.33 GB) | 1.8 s | all 3 per prompt: **20 / 47 ms** in a 4-thread pool, 29 / 67 ms sequential | — | — | — |
| **Qwen3Guard-Gen-0.6B** Q4_K_M (content safety, 119 languages, input + output + refusal) | Ollama `aegis-guard` (from `hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M`) | 484 MB | **751 MB** (`ollama ps`, ctx 2048), runner RSS 720 MB | 0.8 s warm-disk, 1st call 0.4 s | **223 / 348 ms**; 417 ms with a 480-token document (~310 prompt tokens, 8–17 output) | Apache-2.0 | **11/13**. Correct: violent, phishing, PL theft, PII request, self-harm, 4 benign finance (EN+PL), response refusal = Yes, laundering answer Unsafe with refusal = No. The 2 "misses" were still flagged: the EN prompt-leak came back **Controversial / Jailbreak**, the PL one **Unsafe / PII** | **strict on input** (Controversial counts as unsafe for jailbreak / PII / illegal), **loose on output** (Controversial means allow and log). Prompt format is fixed: see §3 |
| **Qwen3.5-0.8B** Q4_K_M text-only (judge for NL policy rules, local demo chat) | Ollama `aegis-judge` (text blob of `hf.co/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M` + `RENDERER/PARSER qwen3.5`) | 533 MB (+204 MB unused mmproj) | **1317 MB** (`ollama ps`, ctx 2048), runner RSS 1.09 GB | 1.2 s | **315 / 381 ms per rule** (yes/no logprob); JSON explanation 1.45 s; chat decode **34 tok/s** | Apache-2.0 | yes/no P(violation): **6/6** at threshold 0.08 (violations 0.093–0.231, clean ≤ 0.066). Generated JSON verdict: **3/6**, always "no violation". Polish chat output is weak | per-rule threshold **0.08** default (the "adherence" knob). Use it as a review vote, never as the sole blocker. Tune on your own rules |
| qwen3:0.6b (comparison; fast demo chat) | Ollama `qwen3:0.6b` (library) | 523 MB | 1029 MB (ctx 4096) | 0.7 s | 120 / 221 ms per rule; chat decode **130 tok/s** | Apache-2.0 | As a judge, strongly yes-biased: P(yes) 0.94–0.99 on clean text, 3/6 | Demo chat only, never as judge |

## 2. Recommended defaults (what the gateway should load)

1. **Resident T1 (in-process, ORT CPU, 2 threads each, run in a thread pool):** Horizon (injection) + bardsai NER (PII) + MiniLM (signatures) **sharing one XLM-R tokenizer** (`ner_pii.load_tokenizer(..., share_vocab_with=...)`; ids verified identical). Footprint is about 1.1–1.2 GB, and all three cost ~20 ms p50 per prompt.
2. **Resident T2 (Ollama):** `aegis-guard` with `keep_alive: "30m"` and `num_ctx 2048`, 0.75 GB. Run it on the uncertain band (Horizon 0.5–0.8), always on output when `output_moderation: on`, and on input speculatively, in parallel with the upstream call (~220 ms).
3. **On demand:** `aegis-judge` for `llm_policy` rules only, `keep_alive: "5m"`, 1.3 GB. Don't keep it resident next to the guard on 8 GB. If the demo needs a local upstream chat model, prefer `minimax-m2.5:cloud`: it costs no local RAM and **shows redaction on external egress**. Use `qwen3:0.6b` only if a fast local chat is required.
4. **PG2-22M:** optional, off by default ("lite" profile). Enable it as an English-only second vote if RAM allows.
5. **Total budget:** T1 ~1.15 GB + guard 0.75 GB ≈ **1.9 GB resident**, plus the judge 1.3 GB on demand (≈ 3.2 GB peak). Leave the judge unloaded in the default profile.
6. **Ollama server env:** `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_CONTEXT_LENGTH=2048`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`. Put a semaphore in front of Ollama with a ~300 ms queue wait, after which the fallback policy applies.
7. **Long inputs:** Horizon costs ~0.65 ms per token. Cap encoder scanning at ~2k tokens per segment (head + tail) for tool results and RAG docs, or scan them asynchronously. NER windows are 512 tokens with a 64-token overlap.

## 3. Gotchas found (each one breaks something if ignored)

- **The Qwen3Guard GGUF's Ollama template is garbled.** It renders only `.System`, always with the *response*-moderation prompt, and **drops `.Prompt`**, so `/api/chat` would moderate an empty conversation. Fixes:
  - `aegis-guard` replaces the template with `{{ .Prompt }}`.
  - `ollama_guard.build_prompt()` rebuilds the official template from `Qwen/Qwen3Guard-Gen-0.6B` `tokenizer_config.json`. It is **byte-identical to a jinja2 render in 15/15 cases** (`bench.py template`).
  - Send it with `raw: true`, `temperature 0`, `num_predict 32`, `stop ["<|im_end|>"]`.
  - Output to parse: `Safety: Safe|Unsafe|Controversial`, then `Categories: … | None`, plus `Refusal: Yes|No` in response mode.
  - `sanitize()` defangs `<|im_start|>`, `<|im_end|>` and `<think>` in user content; otherwise raw mode lets a hostile input close the template.
  - Ollama reuses the KV cache of the ~300-token shared header across calls (that's why the steady state is ~200 ms).
- **`qwen3.5:0.8b` (the official tag) is 1.04 GB**, so it was skipped under the 1 GB cap. The hf.co unsloth GGUF pull also fetches the vision mmproj, and a model **with** a projector is sent to Ollama's llama.cpp runner, which **fails with "unknown model architecture: qwen35"**. Loading only the text blob routes it to Ollama's own engine, which works. The hf.co import also only has a `{{ .Prompt }}` template (no system role, no `think:false`). `Modelfile.judge` fixes both with `FROM <text blob>` + `RENDERER qwen3.5` + `PARSER qwen3.5`. `download_models.sh` resolves the blob path automatically.
- **Ollama 0.24 does not enforce JSON-schema `format` for the qwen35 engine.** You get valid JSON but missing keys and sometimes ```` ```json ```` fences. The parser in `ollama_judge.parse_explain` is tolerant.
- **Tiny judges are miscalibrated when they generate verdicts.** Score with per-rule yes/no and `logprobs: true` / `top_logprobs`, which Ollama 0.24 supports; `num_predict: 1` gives P(violation). Always send `think: false`.
- **HF `tokenizers` is the hidden RAM cost.** A 250k-piece vocab costs 150–340 MB per tokenizer (Unigram trie; `malloc_zone_pressure_relief` frees nothing, the memory is live). That's more than the int8 weights. MiniLM and bardsai share the identical XLM-R vocab, and sharing it saved 280–450 MB. Ownership note: the embedder (semantic-models) and NER (redaction-engine) live in different workstreams, so expose one shared XLM-R tokenizer through the runtime container (`rt`).
- **Horizon's `model_quantized.onnx` quantizes only the embedding table.** The transformer layers are fp32 MatMuls, which matches the vendor's "35 ms int8 vs 36 ms fp32". Peak RSS while loading is ~0.6 GB, then it settles around 0.25–0.44 GB.
- **MiniLM max_seq_length is 128.** For long documents, use sentence segmentation (`Embedder.embed_windows`), not only token windows.
- **bardsai NER offsets:** word-level "first sub-token" aggregation plus BIO merge works. Trim trailing punctuation, but keep "(415)" brackets.

## 4. Gated, skipped or failed

- **Nothing gated was needed.** Meta's `meta-llama/Llama-Prompt-Guard-2-22M` is gated (manual approval), so we used the ungated `gravitee-io/Llama-Prompt-Guard-2-22M-onnx` mirror, which the licence permits with attribution. Qwen3Guard, bardsai, Horizon, MiniLM, unsloth and QuantFactory are all ungated.
- **ProtectAI deberta-v3-base-prompt-injection-v2: skipped.** It isn't needed (Horizon covers EN+PL), the repo is archived, it's EN-only and has high over-defence, and the 739 MB fp32 ONNX would have pushed downloads past 3 GB. Fetch it with `WITH_PROTECTAI=1` if wanted; `pi_classifier.SPECS["protectai-v2"]` is ready, quantize with `quantize_dynamic`.
- **Official `qwen3.5:0.8b` tag: skipped** (1.04 GB). Replaced by the unsloth text Q4_K_M (533 MB). Its raw hf.co tag fails to load as explained in §3; the `aegis-judge` alias works.
- Downloaded in total: ONNX 0.80 GB + Ollama 1.74 GB (guard 484 MB, Qwen3.5 533 + 204 MB mmproj, qwen3:0.6b 523 MB) = **2.55 GB**. `ollama rm hf.co/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M` frees the unused 204 MB mmproj, because `aegis-judge` keeps the text blob. `ollama rm qwen3:0.6b` frees 523 MB if it isn't needed.

## 5. Files

| File | What |
|---|---|
| `pi_classifier.py` | `PromptInjectionClassifier.load("horizon-small" \| "pg2-22m" \| "protectai-v2", dir)`, `.score()` (max over 512-token windows, stride 64), `.score_batch()`, `.classify()`. `PIEnsemble` gives block / review / allow |
| `ner_pii.py` | `PiiNer(dir).detect(text) -> [Span(label, start, end, text, score)]` (char offsets into the original text), `redact()` with numbered placeholders + vault, `load_tokenizer(share_vocab_with=)`, label sets `PII_LABELS` / `SPECIAL_CATEGORY_LABELS` |
| `embedder.py` | `Embedder(dir).embed(texts)` (L2-normalised, 384-d), `embed_windows()`, `ExemplarIndex.add / search / best_by_label` (brute-force cosine kNN) |
| `ollama_guard.py` | `build_prompt(messages)` (exact official template), `parse_output()`, `QwenGuard` / `AsyncQwenGuard`: `.check_prompt()`, `.check_response()`, `GuardVerdict.is_unsafe(mode="strict" \| "loose")` |
| `ollama_judge.py` | `Judge` / `AsyncJudge`: `.evaluate(rules, content)` (per-rule logprob P(violation), per-rule `threshold`), `.explain()` (JSON reason), `.chat()` |
| `samples.py`, `bench.py`, `bench_results/` | Sanity corpus, isolated per-model benchmark (`bench.py all \| horizon \| pg2 \| minilm \| ner \| combined \| guard \| judge \| template \| summary`) |
| `download_models.sh`, `Modelfile.guard`, `Modelfile.judge` | Reproducible fetch (HF commits pinned; `models/MANIFEST.sha256` for supply-chain verification) plus the two Ollama aliases |

Runtime deps for the modules: `onnxruntime`, `tokenizers`, `numpy`, `httpx`. The bench also needs `psutil` and `jinja2`. No torch anywhere.
