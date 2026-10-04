# 13 · threat-feed — Threat-intel signature feed (plan)

Workstream **threat-feed** · task prefix **TI** (task IDs `TI-01…`, verification `TI-V01…`; do not confuse them with signature IDs `AEGIS-TI-0xx`) · research ref **04** (§2–3) · staging input `staging/feed-seed/` (20 validated signatures, `feedlib.py`, schemas, ed25519 keygen/sign/verify/scan, pending demo signature `AEGIS-TI-022`).

Owned paths (CONTRACTS §1.2): `src/aegis/feed/**`, `src/aegis/controls/signatures/**`, `feed_service/**`, `config/feeds/**`, `src/aegis/api/routes/feed.py`, `config/snippets/threat-feed.yaml`, `tests/unit/threat_feed/**`, this plan. Nothing else is touched. Every other need is listed under **Contract gaps / requests** (§4.3).

---

## 1. Goal & demo value

Requirement 4 of the brief: *"detect/block known exploits … via signatures fed from an externally managed system."* Headline flow **F8** (CONTRACTS §8).

What judges see:

1. **A separate threat-intel service** on `:8790` with its own dark UI that matches the dashboard. It lists 21 signatures: 20 published and 1 draft (`AEGIS-TI-022`). Each row shows CVE aliases, severity, action, surfaces and test-vector status. A judge can edit a signature's YAML, click **Validate** (schema, RE2 compile, inline vectors, ReDoS smoke), save it, enable or withdraw it, and click **Publish**. Publishing builds the bundle, re-runs every vector, Ed25519-signs it and bumps the serial.
2. **The EchoLeak flip (live, under 2 s).** A model response contains a markdown image routed through the firm's allowlisted asset CDN's open image proxy (`assets.acme-capital.example/img/proxy?src=https://…&ref=…`). On feed v1 it is **ALLOWED**: `AEGIS-TI-014` and DLP-06 both trust the allowlisted host. The judge enables `AEGIS-TI-022` and clicks Publish. The gateway gets an SSE push, pulls the bundle, verifies it, self-tests it and swaps it in atomically. The serial goes **#1 → #2** in the dashboard header, and the same payload is now **BLOCKED by SIG-01 · AEGIS-TI-022 · CVE-2025-32711**. Every decision is stamped with `feed_serial`.
3. **Tamper button.** It simulates a compromised distribution server: the bundle is modified (critical signatures withdrawn) and the serial bumped, but nothing is re-signed. The gateway rejects it (`feed.rejected reason="bad signature (latest.json)"`), the dashboard shows a red banner, and enforcement **stays on the last-known-good serial**. Further buttons cover replaying an old bundle (anti-rollback) and signing with a rogue key.
4. **Model-file gate (SIG-02).** `ollama pull/push/create` through the gateway's Ollama front is gated on registry, namespace (feed `AEGIS-TI-018`), push exfiltration and Modelfile template SSTI (`AEGIS-TI-005`). Model artifact bytes (`artifact.file`) are scanned by magic bytes, not extension. A pickle with an off-allowlist global, a broken pickle stream (nullifAI), 7z magic and a Keras Lambda layer are all **blocked**. safetensors and GGUF are **allowed**. Any parse error fails closed.
5. **Canary across every surface.** `AEGIS-TEST-SIGNATURE-7F3A` in a prompt, tool argument, MCP description or egress body is blocked everywhere. This proves end-to-end coverage.

Judging criteria served: guardrail robustness (30 %: closed matcher set, RE2, fail-closed parsers, signed feed), architecture (20 %: external service, pinned key, atomic swap, last-known-good, under 2 s activation), security reporting (20 %: `feed.updated`/`feed.rejected` audit + SSE + metrics, feed serial on every decision), self-testing (15 %: every signature carries positive and negative vectors, run feed-side before signing *and* gateway-side before activation; failures are quarantined), implementability (TUF-lite design, Git-repo production path).

---

## 2. Design

### 2.1 Files (all inside ownership)

```
src/aegis/feed/
  __init__.py               re-exports nothing heavy (no import side effects)
  schema.py                 pydantic: Signature, SigTests, SigExample, SigAppliesTo, BundleHeader, Bundle, FeedPointer;
                            constants (SURFACES, STATUSES, ENFORCED/MONITOR); staging-alias normalizer
  verify.py                 load_pubkey(path) (base64 or hex), key_id(pub)->hex8, verify_detached(), FeedRejected
  compile.py                CompiledFeed (immutable snapshot) + compile_bundle(bundle, ...) + diff(old, new)
  manager.py                FeedManager (implements protocols.FeedManager) + create(rt)
  gate.py                   model-artifact helpers: sniff_format(), scan_artifact(), parse_gguf_kv(), registry helpers;
                            CLI `python -m aegis.feed.gate scan|samples` (should)
  samples.py                runtime generators of benign test artifacts (tests, demo; nothing malicious committed)
  demo.py                   `python -m aegis.feed.demo echoleak` scripted flip + activation latency (should)
  matchers/__init__.py      PUBLIC: compile_signature(sig, lists=None), match(compiled, interaction) -> list[dict],
                            Event, event_from_interaction(), event_from_example(), run_tests(), FeedError, MATCHERS
  matchers/core.py          Event, compile_matcher (any_of/all_of/not, depth cap), CompiledSignature, RE2 helpers,
                            ACTION precedence (contract), printable()
  matchers/text.py          MATCHERS: regex, literal_set (+alias literal), semantic (+alias semantic_exemplar)
  matchers/structured.py    MATCHERS: url (+extract markdown/text), package (+parse_install_commands), json_path (+alias jsonpath)
  matchers/artifact.py      MATCHERS: hash, bytes, pickle_globals (+alias pickle_opcode); scan_pickle_stream, zip_members,
                            looks_like_pickle, is_safetensors
src/aegis/controls/signatures/
  __init__.py               (empty)
  _common.py                (underscore: skipped by discovery) feed access, overrides, finding builders
  sig01_engine.py           CONTROLS = [ExploitSignatureEngine()]   SIG-01
  sig02_artifact.py         CONTROLS = [ModelArtifactGate()]        SIG-02
  sig03_packages.py         CONTROLS = [PackageInstallGuard()]      SIG-03
src/aegis/api/routes/feed.py  /api/feed/status, /api/feed/signatures, /api/feed/refresh (+ gap endpoints §4.3)
feed_service/
  __init__.py  __main__.py  app.py  signing.py  build.py
  port_staging.py           one-off converter staging YAML -> contract YAML (kept for provenance; idempotent)
  signatures/AEGIS-TI-000..019.yaml, AEGIS-TI-022.yaml (enabled: false)
  lists/packages.yaml  lists/models.yaml  lists/iocs.yaml
  demo/echoleak-proxy-payload.md
  ui/index.html  ui/app.js  ui/app.css   (vanilla, no build, no CDN; tokens copied from staging prototype)
  state/                    gitignored runtime state (keys, workspace, dist, serial.json, events.jsonl)
config/feeds/feed_pubkey.b64  seed_bundle.json  seed_bundle.json.sig
config/snippets/threat-feed.yaml
tests/unit/threat_feed/     test_matchers.py test_signing.py test_service.py test_manager.py test_sig01.py
                            test_sig02.py test_sig03.py conftest.py (local fixtures: tmp keys, ASGI feed app)
```

### 2.2 Adapting staging to the contract (CONTRACTS wins)

| Staging (`feed-seed`) | Contract (§4.7) / this plan |
|---|---|
| inline `signature` field over canonical JSON of the doc | **detached** `.sig` files: base64 Ed25519 over the **exact file bytes** (`latest.json.sig`, `bundle-NNNNNN.json.sig`, `seed_bundle.json.sig`) |
| `latest.json` = `{feed, schema_version, serial, created, expires, bundle, sha256, signature_count, alg, key_id, signature}` | exactly `{"feed","serial","version","bundle","sha256","published","expires","key_id"}` |
| bundle = flat `{feed, schema_version, serial, created, …, signatures}` | `{"feed": {name, schema_version: 1, serial, version, published, expires, min_gateway_version, key_id, signature_count}, "lists": {...}, "signatures": [...]}` (the `feed` header may carry extra keys) |
| `key_id` = 16 hex chars | `key_id` = **8 hex chars** = `sha256(raw_pubkey)[:8]` ("hex8") |
| public key hex in `keys/feed-public.key` | `config/feeds/feed_pubkey.b64` (base64 of the raw 32 bytes); the loader also accepts hex |
| `applies_to: [output, tool_call]` (6 coarse surfaces) | `applies_to: {surfaces: [model.response, tool.output, …]}`, using contract `Surface` values. The per-signature table is in §2.3 |
| `matcher:` | `match:` (alias accepted on input) |
| leaf types `literal`, `pickle_opcode`, `jsonpath`, `semantic_exemplar` | `literal_set`, `pickle_globals`, `json_path`, `semantic` (old names accepted as aliases by the compiler) |
| actions `block, require_approval, quarantine, strip_tool, redact, alert` | contract `Action`: `quarantine`/`strip_tool` → `redact` (+ `redact_scope: segment`), `alert` → `log` |
| `action_overrides` keyed by staging surface | keyed by contract `Surface` |
| `pending/` folder for drafts | authoring-only field `enabled: false` (stripped from the bundle). "Withdraw" = `status: withdrawn` (shipped, not evaluated, OSV style) |
| signature IDs | already `AEGIS-TI-0xx` |
| demo host `assets.aegis-corp.example` | `assets.acme-capital.example` (demo cast). TI-014's `host_not_in` and TI-022's `host_in` get `*.acme-capital.example` added (aegis-corp entries kept); the payload and TI-022/TI-014 vectors switch to acme-capital |

New optional signature fields (threat-feed owns `schema.py` details): `redact_scope: match|segment` (default `match`), `redact_with: str|null` (default `[REDACTED:<id>]`; `""` = strip, used by TI-013), `confidence`, `description`, `notes`, `published`, `modified`, `references`. Tests need **≥ 1 positive and ≥ 1 negative** (≥ 2 recommended, a warning if fewer) so judge-authored signatures stay easy.

### 2.3 Surfaces: where signatures are evaluated

Coarse staging surfaces map to contract surfaces and their producers like this:

| Staging | Contract surfaces | Produced by (handler owner) |
|---|---|---|
| `model_call` | `prompt.user`, `model.request` | hooks UserPromptSubmit / playground; Anthropic/OpenAI/Ollama proxies (core-gateway) |
| `tool_call` (arguments) | `tool.input`, `mcp.call` | hook PreToolUse, `/v1/guard`; MCP proxy |
| `tool_call` (indirect content) | `tool.output`, `mcp.result`, `mcp.list` | hook PostToolUse; MCP proxy (results, `tools/list`) |
| `mcp` | `mcp.init`, `mcp.call`, `mcp.result` | MCP proxy |
| `egress` | `egress.request` | `/egress` (metadata-egress) |
| `output` | `model.response`, `tool.output`, `mcp.result` | proxies (response path), hooks, MCP proxy |
| `model_download` | `model.admin`, `artifact.file`, `egress.request` | Ollama front `/ollama/api/pull|push|create|…` (core-gateway), blob uploads / downloads / `/v1/guard` |

Per-signature port table. This is the input to `feed_service/port_staging.py`. Each staging test example maps to the **first** surface listed for its staging surface, unless the column says otherwise.

| Signature | Contract `applies_to.surfaces` | Action (overrides) | Example surface mapping |
|---|---|---|---|
| 000 canary | all 15 except `config.change` | block | model_call→model.request, tool_call→tool.input, output→model.response |
| 001 pickle | artifact.file | block | model_download→artifact.file |
| 002 nullifAI 7z | artifact.file | block | →artifact.file |
| 003 unsafe format | egress.request, model.admin, model.response, tool.output | require_approval (model.response, tool.output: log) | url example→egress.request; output→model.response |
| 004 Keras Lambda | artifact.file | block | →artifact.file |
| 005 GGUF SSTI | artifact.file, model.admin, egress.request | block | json/filename→artifact.file; egress→egress.request |
| 006 Probllama | egress.request | block | →egress.request |
| 007 ShadowRay | egress.request, tool.input, mcp.call | block | →egress.request |
| 008 Langflow | egress.request | block | →egress.request |
| 009 LLM code exec | tool.input, mcp.call, model.response | block (model.response: log) | tool_call→tool.input; output→model.response |
| 010 mcp-remote OAuth | mcp.init, mcp.result, egress.response | block | mcp→mcp.result |
| 011 stdio spawn | egress.request, mcp.call, tool.input | block | egress→egress.request; mcp→mcp.call |
| 012 tool poisoning | mcp.list, tool.output, mcp.result | redact, `redact_scope: segment` | tool_call→mcp.list |
| 013 invisible Unicode | prompt.user, model.request, model.response, mcp.list, tool.input, mcp.call | redact, `redact_with: ""` (mcp.list, tool.input, mcp.call: block) | model_call→model.request; tool_call→mcp.list; output→model.response |
| 014 EchoLeak | model.response, tool.output, mcp.result, tool.input, mcp.call | redact (match scope) | output→model.response |
| 015 config hijack | tool.input, mcp.call | require_approval | →tool.input |
| 016 slopsquatting | tool.input, mcp.call, model.response | require_approval (model.response: log) | tool_call→tool.input; output→model.response |
| 017 compromised pkgs | tool.input, mcp.call, mcp.init, model.response, egress.request | block | tool_call→tool.input; egress→egress.request |
| 018 namespace reuse | egress.request, model.admin | require_approval | →egress.request |
| 019 PI families | prompt.user, model.request, tool.output, mcp.result, model.response | block (tool.output, mcp.result: redact `segment`; model.response: log) | model_call→model.request; tool_call→tool.output |
| 022 EchoLeak proxy (draft) | model.response, tool.output, mcp.result, tool.input, mcp.call | block | output→model.response |

Deliberate exclusions: TI-006 is not mapped to `model.admin`, because that would block every legitimate pull through the gateway; SIG-02 owns that surface. TI-011 is not mapped to `mcp.init`, because legitimate stdio launch configs carry `{command, args}` and MCP-01 governs them.

### 2.4 Matcher engine (`aegis.feed.matchers`), ported from `feedlib.py`

- The code is copied from `feedlib.py` with only these changes: contract leaf names plus aliases, contract action precedence (`ACTION_PRECEDENCE` from `aegis.core.types`), and surfaces as contract `Surface`. Each module exports `MATCHERS: dict[str, factory]`. `matchers/__init__.py` merges them, so dropping in a new leaf type needs no registry edit (CONTRACTS §2.1). All limits are kept: regex ≤ 2048 chars, RE2 only (`re2.Options`, `log_errors=False`), matcher depth ≤ 6, scan cap 256 KB per view, JSONPath ≤ 10k nodes, pickle ≤ 2M ops, ZIP ≤ 4096 members, 64 MB per member.
- **Span-aware evidence** (new, small): `regex`, `literal_set` and `url` evidence also carries `start`/`end` of the match within the view text. In redact mode, `regex` collects all `finditer` spans (≤ 100). When an `Event` contains only `text`, `view("all") == text`, so the spans index the segment directly.
- `event_from_example(ex)` matches staging `Event.from_example`: `text`, `json`, `url`, `method`, `body`, `filename`, `bytes_hex`/`bytes_b64`.
- `event_from_interaction(i, *, segments=None, max_chars=…)` builds the Event:
  - `text`: the joined texts of the selected segments (see SIG-01 `history_scan`).
  - `json`: `i.tool_args`, else `i.raw` if it is a dict/list, else `i.meta.get("json")`.
  - `url`: `i.url`; for `tool.input`/`mcp.call`, falls back to the first `tool_args` key in `url|uri|endpoint|href`. For `model.admin` with an `hf.co/<ns>/<repo>[:tag]` or `huggingface.co/...` model name, a synthesized `https://huggingface.co/<ns>/<repo>`, so URL signatures (TI-018) apply to Ollama pulls.
  - `method`: `i.http_method`.
  - `body`: `i.raw` as text if it is str/bytes-decodable, else `json.dumps(i.raw)` for dict bodies, else the joined segment text. This keeps `field: body` regexes (TI-006/008) working whatever the egress handler stores.
  - `filename`: `i.meta.filename` or the `tool_args` `filename`/`path` basename.
  - `data` (bytes) comes from the first that exists: `i.raw` if bytes; `i.meta["artifact_b64"]` (≤ 32 MB decoded); `i.tool_args["artifact_b64"]`; `i.meta["artifact_path"]` (only under allowed roots, see SIG-02).
- `compile_signature(sig: dict, lists: dict | None = None) -> CompiledSignature` (contract public surface). `CompiledSignature.evaluate(ev) -> hit | None` returns `{signature_id, title, severity, aliases, tags, action (surface-resolved), mode ("monitor" for experimental), message, evidence[]}`.
- `match(compiled, interaction) -> list[dict]` (contract public surface) accepts one `CompiledSignature` or an iterable of them, builds the Event from the interaction, filters by `applies_to.surfaces`, and returns the hits.
- `run_tests(compiled) -> (n_vectors, failures[])` is used identically by the feed service (pre-sign) and the gateway (pre-activation).
- `semantic` matcher: the gateway and feed both use the deterministic **lexical reference** (`lexical_threshold`, char-trigram containment), capped at `semantic_max_chars` (8 KB). Embedding cosine via `rt.semantic` is **could** (TI-18). Evidence says `mode: lexical-reference`.

### 2.5 Feed service (`python -m feed_service`, :8790)

**CLI** (`__main__.py`): `serve [--host 127.0.0.1] [--port 8790] [--state DIR]` (default subcommand) · `keygen [--force|--if-missing]` · `publish [--enable ID…] [--note TEXT]` · `reset [--hard]` · `verify [--workspace|--dist]` (vectors + demo invariant; mirrors staging `validate.py`/`verify.py`). The state dir defaults to `feed_service/state` (env `AEGIS_FEED_STATE`). The gateway URL for the sync chip comes from env `AEGIS_GATEWAY_URL` (default `http://127.0.0.1:8787`).

**State** (`feed_service/state/`, gitignored):
```
keys/feed_signing.key (base64 seed, chmod 600)   keys/feed_public.b64
workspace/signatures/*.yaml   workspace/lists/*.yaml     (editable copy; seeded from feed_service/signatures|lists)
dist/latest.json(.sig)  dist/bundle-NNNNNN.json(.sig)   (served files; last 20 kept)
serial.json {"serial": N, "high_water": M}               events.jsonl (activity timeline)
```

**`signing.py`**: `generate() -> (seed, pub)`, `load_signing_key(state)`, `sign_detached(data: bytes) -> str` (base64), `verify_detached(data, sig_b64, pub)`, `key_id(pub) -> hex8`. PyNaCl only. The private seed never leaves `state/keys/`.

**`keygen`** (also `make feed-keys`):
1. Write the keypair to `state/keys/`.
2. Write `config/feeds/feed_pubkey.b64`.
3. Build the **seed bundle** from the repo `feed_service/signatures` (enabled only) + `lists`, with serial **1** and TTL **30 days**. Write `config/feeds/seed_bundle.json` + `.sig`.
4. Re-initialize `state/dist` so that **serial 1 = the seed bundle bytes**: copy them and write a signed `latest.json` for serial 1. The gateway on seed v1 and the service at v1 then agree byte-for-byte (sha equal → no-op, status `ok`).
5. Print the key_id and "restart the gateway to pin the new key".

`--if-missing` is a no-op when both the private key and `config/feeds/feed_pubkey.b64` exist. If the pubkey exists but the private key does not (fresh clone), it **refuses** and tells the user to run `keygen --force`.

**`build.py`**:
- `Workspace`: `list()`, `get(id)`, `put(id, yaml_text)`, `set_enabled(id, bool)`, `withdraw(id)`.
- `validate_signature(dict) -> Report`: schema → RE2 compile → `run_tests` → ReDoS smoke (staging adversarial inputs, < 100 ms each) → test surfaces ⊆ applies_to.
- `build_bundle(serial, ttl_h) -> bytes`: canonical JSON as in staging `canonical_json`, sorted keys, `allow_nan=False`.
- `publish(force=False)`: under an asyncio lock. Validate every enabled signature (refuse with 422 + per-signature problems unless `force`). Set serial = `max(serial, high_water) + 1`. Write the bundle + `.sig`, then `latest.json` + `.sig`, then append to `events.jsonl` and broadcast SSE `published {serial, sha256}`.
- `tamper(mode)`.
- `reset(hard)`: soft = restore the workspace from the repo, then `publish()` (new serial, v1 content). Hard = also restore dist/serial to the seed (serial 1). Use hard only together with a gateway `make reset`, otherwise the gateway correctly reports a rollback.

**Tamper modes** (`POST /api/tamper {"mode": …}`, default `unsigned`):

| mode | what the service serves | gateway result |
|---|---|---|
| `unsigned` | new serial N+1. Bundle modified ("attacker withdraws every critical signature"), `latest.json` points at it with a correct sha256, but both `.sig` files are the *previous* ones | `feed.rejected reason="bad signature (latest.json)"`, keeps N |
| `rollback` | re-serves an older, validly signed `latest.json` + bundle (serial < N) | `feed.rejected reason="rollback: serial 1 <= current 2"` |
| `wrong_key` | new serial signed by a freshly generated rogue key | `feed.rejected reason="key_id 3f…≠ pinned a9…"` |
| `swap_bundle` | valid signed `latest.json` for N+1 but the bundle file is replaced by other bytes (needs the key: models a mirror swap) | `feed.rejected reason="bundle sha256 mismatch"` |

Each tamper broadcasts `published` so the rejection shows in under 2 s. A later legitimate `publish` uses serial = `max(…)+1` and recovers.

**HTTP API** (contract §5.6 + extras inside our service):

| Method & path | Response |
|---|---|
| `GET /feed/latest.json`, `GET /feed/latest.json.sig` | exact bytes (`application/json`, `text/plain`), `Cache-Control: no-store`, `ETag` = sha256 |
| `GET /feed/bundle/{serial}.json`, `GET /feed/bundle/{serial}.json.sig` | `{serial}` is an int (leading zeros ok); also `GET /feed/bundle/bundle-000042.json(.sig)` |
| `GET /feed/pubkey` | `{"alg":"ed25519","key_id":"a98d15ea","public_key":"<b64>"}` (informational; the gateway never TOFUs it) |
| `GET /feed/events` | SSE (sse-starlette, ping 15 s): `event: published` / `data: {"serial":N,"sha256":"…"}` |
| `GET /` + `/ui/{asset}` | editor UI |
| `GET /api/state` | `{serial, version, published, expires, key_id, sha256, signatures_published, pending: {added, removed, modified}, last_event, gateway}` (gateway = server-side `GET {AEGIS_GATEWAY_URL}/api/feed/status`, 800 ms timeout, `null` on error) |
| `GET /api/signatures` | `{items: [{id, title, severity, status, enabled, action, surfaces, aliases, tags, valid, problems, vectors: {passed,total}, published: bool}]}` |
| `GET /api/signatures/{id}` | `{id, yaml, signature, report}` |
| `PUT /api/signatures/{id}` | body = YAML (`text/plain`/`application/yaml`, ≤ 64 KB, `yaml.safe_load`, id must match). Saves to the workspace and returns `{saved, valid, problems[], tests[]}` (422 only if it is not a YAML mapping or the id mismatches) |
| `DELETE /api/signatures/{id}` | sets `status: withdrawn` (never deletes) |
| `POST /api/signatures/{id}/enabled` | `{enabled: bool}` (draft toggle) |
| `POST /api/validate` | `{yaml}` → report without saving |
| `POST /api/scan` | `{surface, text?, json?, url?, method?, body?, filename?, bytes_b64?, set: "workspace"|"published"}` → `{decision, hits}` ("Try it", should) |
| `POST /api/publish` | `{force?: bool, note?: str}` → `{serial, version, sha256, signatures, enabled_ids, vectors, published}`; 422 `{problems}` on invalid |
| `POST /api/tamper` | `{mode}` → `{serial_attempted, mode, description}` |
| `POST /api/reset` | `{hard?: bool}` → state |

Hardening: binds `127.0.0.1` only, no auth (demo; documented), size caps, `safe_load` only, signatures are data and never executed, the private key is never served.

### 2.6 Feed editor UI (`feed_service/ui/`): small but good-looking

Vanilla HTML/JS/CSS, no build, **no CDN** (venue Wi-Fi). `app.css` = `staging/design/prototype/assets/tokens.css` + the needed subset of `app.css` (`.btn`, `.badge.{allow,redact,approval,block,neutral}`, `.banner`, `.status-dot`, `.tl-item`, `.tag`, toast) copied as-is. The font stack falls back to system fonts (Geist/Inter are not fetched). Dark, calm, the same visual language as the dashboard (DESIGN_TOKENS §1–3: decision colours only for decisions, mono for IDs/hashes/YAML).

Layout (1280 × 800 target; it must look good on the projector):
- **Top bar**: logo mark (iris gradient) + "Aegis Threat Intel" + subtitle "external signature feed · signs with Ed25519".
  - Chips: `serial #2`, `version 2026.10.03-2`, `key a98d15ea`, `expires in 23 h`, and a **gateway sync chip**, polled from `/api/state` every 1 s: green "Gateway enforcing #2 ✓", amber "Gateway on #1, syncing…", red "Gateway rejected #3: bad signature · enforcing #2", grey "Gateway offline".
  - Buttons on the right: **Publish** (primary iris; label shows pending changes, e.g. "Publish +1"), **Tamper ▾** (destructive solid `#C43350`; menu with the 4 modes and one-line explanations), `Reset` (ghost).
- **Left pane (360 px)**: a search box and the signature list. Each row shows a status dot (enforcing / monitor / withdrawn / draft / invalid), the mono ID, the title, the severity badge, the action badge, CVE alias chips and an enabled switch. Drafts (`AEGIS-TI-022`) are highlighted with a "Draft · not published" tag. A "+ New signature" button opens a template (regex matcher, two surfaces, 2+2 tests).
- **Main pane**: the YAML editor (`<textarea>` with mono font, a line-number gutter, tab inserts two spaces, ⌘S saves, ⌘Enter validates). Under it, a **validation panel** lists each check (Schema ✓, RE2 ✓, vectors 4/4 ✓ with per-vector rows: name, expected match/no-match, got, evidence snippet, ReDoS worst ms). Buttons: Validate · Save · Enable/Disable · Withdraw.
- **Right column (should)**: a "Try it" box: surface select, text area, Scan against workspace vs published, decision badge plus hits. Below it, an **activity timeline** from `events.jsonl`: published #2 (+AEGIS-TI-022, 87 vectors ✓, sha 3a1f…), tampered #3 (unsigned), reset.
- Toasts for every action. When a tamper produces a gateway rejection, the sync chip turns red and a banner appears: "Gateway refused bundle #3: bad signature. Still enforcing #2 (last-known-good)."

### 2.7 Gateway `FeedManager` (`aegis.feed.manager:create(rt)`)

Implements `protocols.FeedManager` (`serial`, `status()`, `async refresh()`, `signatures()`) plus threat-feed-internal extras that only our own controls/route use: `active` (CompiledFeed), `previous`, `scan(interaction, *, ctx=None, segments=None) -> list[Hit]`, `lists() -> dict`, `async rollback(serial, actor, reason)`, `start()`, `stop()`. The constructor accepts an optional `httpx` transport (used for ASGI-based tests).

**Config read**:
- `rt.settings.feed_url` (`AEGIS_FEED_URL`; `"disabled"` → no network) and `rt.settings.feed_pubkey` (`AEGIS_FEED_PUBKEY`).
- `rt.policy.snapshot().doc.feeds.sources[0]`: `poll_s`, `sse`, `enabled`, `max_age_s`, `seed_bundle`, `id`. This is re-read on every loop tick, so policy hot reload applies.
- `feeds.overrides` are applied at evaluation time by SIG-01, so no recompilation is needed.
- `rt.settings.test_mode` → no background tasks.

**`start()`** (fast, no network): create the `feed_state` and `signature_hits` tables (§6.1 DDL). Load the pubkey; if it is missing, status `disabled` with `last_error`. Read the high-water serial from `feed_state`. Then activate the first that verifies: **(a)** the highest cached bundle in `data/feed/` (re-verified), **(b)** `config/feeds/seed_bundle.json(.sig)` (status `seed`), **(c)** nothing (0 signatures; SIG-02/03 built-ins still work). Preload 24 h hit counts. Unless test mode is on or the URL is disabled, spawn `_loop()`.

**`_loop()`**: an immediate `refresh("startup")`. Then two tasks:
1. **SSE listener**: `GET {url}/feed/events` via `httpx.AsyncClient.stream`, parsing `event:`/`data:` lines; on `published` → `refresh("sse")`. Reconnect backoff 1/2/5/10 s.
2. **Poll**: every `poll_s` (10 s) → `refresh("poll")`.

**`refresh(trigger)`** runs under an `asyncio.Lock`, never raises, and returns `FeedStatus`. Hard failures abort with `FeedRejected(reason)`:
1. `GET /feed/latest.json` + `.sig` (timeout 3 s, ≤ 64 KB). Network error → status `unreachable` (one WARNING + a `system` SSE event on transition) and keep enforcing.
2. Verify the Ed25519 signature over the exact `latest.json` bytes with the pinned key. If the `key_id` mismatches and the pubkey file changed on disk, reload it once (keygen recovery), log a WARNING and retry.
3. Parse `FeedPointer`; `feed` must equal the source id.
4. **No-op** if `serial == active.serial and sha256 == active.sha256` (status `ok`, `last_check`).
5. **Anti-rollback**: accept only `serial > active.serial` **and** (`serial > high_water` **or** a cached verified bundle with the same serial and sha256 exists, which is the unpin case).
6. `GET /feed/bundle/{serial}.json` + `.sig` (≤ 5 MB, endless-data defence). `sha256(bytes) == pointer.sha256` (mix-and-match). Verify the detached signature.
7. Parse `Bundle` (pydantic): header serial/name equal the pointer's, and `signatures` ≤ 5000. A schema error → **reject the whole bundle**.
8. `compile_bundle()`: compile every signature with RE2. An uncompilable regex or unknown matcher → **reject the whole bundle** (contract). Run `run_tests` per signature; failures → **quarantined** (kept out of `by_surface`, listed with the reason).
9. **Atomic swap**: `self.previous, self.active = self.active, new` (one reference assignment; in-flight requests keep their object).
10. Persist: the cache files (`data/feed/latest.json`, `bundle-NNNNNN.json(.sig)`, last 5), a `feed_state` row (serial, version, sha256, applied_at, status, last_error, history_json ≤ 20).
11. Diff (added/removed/modified by id + sha256 of the canonical signature JSON).
12. `rt.audit.record(AuditEvent(event_type="feed.updated", feed_serial=new, data={from, to, version, sha256, key_id, added, removed, modified, quarantined, vectors, latency_ms, trigger}))`, `rt.bus.publish("feed.updated", status | {added, removed, modified})`, `rt.metrics.set_gauge("aegis_feed_serial", serial)`, `rt.metrics.inc("aegis_feed_reloads_total", {"result": "ok"})`. INFO log: `feed applied serial=… added=… ms=…`.

On `FeedRejected`: status `rejected`, `last_error = reason`. `audit feed.rejected` with `data={reason, serial_attempted, kept_serial, url, trigger}`, `bus feed.rejected {reason, serial_attempted, kept_serial}`, `metrics reloads{result=rejected}`. **Dedupe**: the same (pointer sha256, reason) is reported only once, so the 10 s poll does not spam the banner.

Expiry: on every refresh/status, if `active.expires < now` → status `stale` (keep enforcing; a `system` warning on transition).

**`status()`** fills `FeedStatus`: `feed_id`, `url`, `status`, `serial`, `version`, `published`, `expires`, `key_id`, `signatures_total`, `signatures_active` (enforce, not quarantined, not withdrawn, not disabled by an override), `signatures_monitor`, `signatures_quarantined`, `last_check`, `last_update`, `last_error`, `history` (`[{serial, version, applied_at, added, removed, modified, sha256, quarantined, vectors, verify_ms, compile_ms, source}]`; extra keys are allowed in the `dict`).

**`signatures()`** returns `FeedSignatureView` dicts (exact keys `id, title, severity, status, aliases, tags, surfaces, action, hits_24h`, where `status = "quarantined"` when quarantined) plus extras `message`, `references`, `quarantine_reason`, `mode`, `cves`.

**Operator rollback** (should): `rollback(serial)` re-verifies the cached bundle for that serial, activates it and sets `pinned=True` (newer pulls are reported but not applied while pinned). It is audited as `feed.updated` with `data.rollback=true`, actor and reason. `refresh()` called from `POST /api/feed/refresh` clears the pin.

### 2.8 SIG-01 — External exploit-signature engine (`sig01_engine.py`)

`id="SIG-01", family="SIG", kind="deterministic", applies_to=AppliesTo()` (any; the per-signature surface index narrows it), `priority=100` (default, on purpose: on equal action, ties go to the alphabetically earlier owner control such as DLP-06, EXE-01, INJ-01 or MCP-02, so other teams' attribution tests stay stable). `owasp` from config.

`evaluate(ctx, i, cfg)`:
1. Skip `config.change`. `feed = get_runtime().feed`; if it lacks `scan` (Null fallback) → `None`. Pin the feed snapshot: if `ctx.feed_serial == feed.previous.serial`, use `previous` (one request never sees two feed versions).
2. **Segment selection** (`params.history_scan: false`): for `model.request`, scan only the newest message (highest `messages[N]` index parsed from `segment.path`, plus non-`messages` user segments such as Ollama `prompt`). All other surfaces scan everything. This avoids re-blocking every later Claude Code turn because an old tool result in the history matched TI-019.
3. `hits = feed.scan(i, segments=…)`. Per-signature exceptions are caught (logged, count `degraded`), never raised.
4. Apply **policy overrides** `ctx.policy.doc.feeds.overrides[<id>]`: `enabled: false` / `mode: off` → drop; `mode: monitor` → monitor; `action` → replace.
5. **Response direction** (`i.direction == "in"`): `require_approval` → `params.response_require_approval_as` (default `log`), because responses cannot be held.
6. Combine: the strongest enforce-mode action wins (contract precedence). Primary hit = strongest, then severity, then id.
   - `Decision(action, reason="AEGIS-TI-022 · CVE-2025-32711 · EchoLeak exfiltration via an allowlisted image proxy", severity=max, owasp=⋃ OWASP-shaped tags, findings=[one Finding per hit], meta={"signatures": [...], "feed_serial": snap.serial, "feed_version": …})`.
   - `Finding(control_id="SIG-01", detector=f"sig.{id}", category="signature", severity, excerpt=rt.redactor.mask_for_log(snippet, 120), meta={signature_id, title, aliases, tags, mode, action, evidence (sanitized: matcher/at/kind; url/snippet masked)})`.
7. **Redact** hits: re-run the matching signature per selected segment (Event with `text` only) to locate spans. `redact_scope: match` uses evidence `start/end` (all regex matches; for `url` the URL span, so `![chart]([REDACTED:AEGIS-TI-014])` keeps the markdown readable but unfetchable). `segment` scope or no span → the whole segment. Findings carry `segment_index/start/end`, `entity="SIGNATURE"`, `replacement = sig.redact_with if set else "[REDACTED:<id>]"`, which the pipeline hands to `rt.redactor.apply`. Non-redactable segments are skipped.
8. Only monitor hits → `Decision(action="log", mode="monitor", meta.would_action=<strongest>)` (safe even if core ignores `mode`; see the contract gap).
9. Hit recording (skipped when `ctx.dry_run`): in-memory 24 h counters, a batched `signature_hits` insert via `asyncio.to_thread` (decision_id `NULL`; request_id is not in the schema, so put it in the log only at DEBUG), `rt.metrics.inc("aegis_signature_hits_total", {"signature_id": id})`. INFO log: `signature hit id=… surface=… action=…` (no content).

Performance: 21 signatures indexed by surface. Typical surfaces have 4–9 signatures; RE2; views built once per Event. Target p95 < 2 ms for an 8 KB prompt (measured in TI-V12). Inputs > 64 KB run via `asyncio.to_thread`. `timeout_ms: 250`, `fail_mode: closed`.

### 2.9 SIG-02 — Model-artifact gate (decision: front Ollama + bytes gate; HF egress at URL level)

**Decision.** We gate model files at the two points we really intercept offline. We do **not** MITM Ollama's own registry download, because the gateway cannot see those bytes before Ollama writes them.

1. **Front Ollama (primary, demo-critical)**: `model.admin` from core-gateway's `/ollama/api/{pull|push|create|copy|delete}`.
   - `pull`: the registry host of the model name must be in `params.registries_allow` (`registry.ollama.ai`, `hf.co`, `huggingface.co`; bare names = `registry.ollama.ai`), else **block**. `insecure: true` → **block**. HF namespaces are judged by feed signatures (SIG-01 `AEGIS-TI-018` on the synthesized URL → require_approval).
   - `push` → **block** (weights exfiltration; `params.admin_ops_block`).
   - `create`: the `from` registry is checked like `pull`; the template/system/modelfile strings are scanned by SIG-01 (`AEGIS-TI-005`, SSTI gadgets) and by SIG-02's own `gguf_template_markers`.
   - `copy` / `delete`: `log`.
   - `POST /api/blobs/sha256:<digest>` (the local-file import path of `ollama create -f Modelfile` with `FROM ./x.gguf`) → requested from core-gateway as an `artifact.file` interaction with `raw=bytes` (§4.3).
2. **Artifact bytes (`artifact.file`)**, sniffed by **magic bytes, never the extension**:
   - `safetensors`: valid header length + JSON header → allow.
   - `gguf`: magic + KV header parse; `tokenizer.chat_template` scanned for SSTI markers → block on hit; a malformed header → block.
   - ZIP (torch / `.keras`): every pickle-looking member is opcode-scanned whatever its name; central/local name mismatch → block; a `config.json` member with a `Lambda` layer or `enable_unsafe_deserialization` → block.
   - Raw pickle: off-allowlist / deny-listed global → block; parse error → block (nullifAI fail-closed); clean → allowed if `pickle_clean` ∈ `allowed_formats`, else require_approval.
   - 7z magic → block. HDF5 / unknown → `cfg.action` (block) unless the format is allowed. JSON configs → Keras Lambda check.
   - This reuses `matchers.artifact` (`scan_pickle_stream`, `zip_members`, `is_safetensors`) so SIG-01 and SIG-02 share one fail-closed implementation. Scanning runs in `asyncio.to_thread`, capped at `max_scan_mb`.
3. **HF egress (secondary)**: URL-level only, automatic via SIG-01 on `egress.request` (TI-003 `.bin/.pt/…` → require_approval, TI-018 unpinned/re-registered → require_approval) as soon as metadata-egress sets `Interaction.url`. Response-bytes scanning (`artifact.file` on downloaded bodies) is a request to metadata-egress (should; §4.3).
4. **Universal entry**: `/v1/guard` with `surface: artifact.file`, `meta.artifact_b64`, `meta.filename` (tests, self-test, our CLI `python -m aegis.feed.gate scan <file>`).

Byte sources, in order: `i.raw` (bytes) → `i.meta.artifact_b64` → `i.tool_args.artifact_b64` → `i.meta.artifact_path`. The last is honoured only if the path resolves under `params.artifact_roots` (`data/artifacts`, `models`, `demo`), which prevents a local-file oracle. No bytes and no admin op → `None`.

Findings: `category="model"`, `detector` ∈ `sig02.format|pickle_global|pickle_parse|zip_header|keras_lambda|gguf_ssti|registry|admin_op`, `meta={format, globals[:8], member, registry}`. Reason examples: "pickle global collections.Counter outside tensor-rebuild allowlist (weights.bin)", "GGUF chat_template contains SSTI gadget __globals__ (CVE-2024-34359)".

`id="SIG-02", kind="deterministic", applies_to=AppliesTo(surfaces={"model.admin","artifact.file"})`, `priority=100`, `timeout_ms: 2000`, `fail_mode: closed`.

### 2.10 SIG-03 — Package-install / slopsquatting guard (`sig03_packages.py`)

`applies_to` surfaces `tool.input`, `mcp.call`, `mcp.init`.
1. `parse_install_commands(view("all"))` (pip/uv/poetry/pdm/pipx, npm/pnpm/yarn/bun, npx/bunx/dlx, `code --install-extension`, MCP `{command,args}` launch lines).
2. Look each package up in the bundle `lists` (from `feed.lists()`):
   - `malicious_versions` (OSV-like `{ecosystem, name, versions}`): exact version or empty versions → **block**. Name is known-bad but the install is unpinned → `log` ("unpinned; known-bad versions exist").
   - `hallucinated_packages` → **require_approval**.
   - `known_good_packages` → allow.
   - Otherwise → `params.unknown_action` (default `require_approval` on `tool.input`/`mcp.call`, `params.unknown_action_mcp_init: log`).
3. No lists available (feed empty) → `None` with `meta.degraded`. This control never blocks blindly.

Lists (`feed_service/lists/packages.yaml`):
- `malicious_versions`: postmark-mcp 1.0.16, litellm 1.82.7/1.82.8, mistralai 2.4.6, amazonwebservices.amazon-q-vscode 1.84.0 (from TI-017), plus event-stream 3.3.6 and ua-parser-js 0.7.29/0.8.0/1.0.0 (historic npm compromises, used by the SIG-03-only self-test).
- `hallucinated_packages` (huggingface-cli, langchain-community-tools, openai-helper).
- `known_good_packages` (≈100 PyPI + ≈60 npm common names incl. `@modelcontextprotocol/*`, `requests`, `numpy`, `pandas`, `fastapi`, `huggingface-hub`, `safetensors`, `react`, `vite`, `typescript`, `zod`).

`models.yaml`: `reregistered_hf_namespaces: [ghost-author-demo, orphaned-ns-demo]`. `iocs.yaml`: TI-017 IOC literals. Lists ship in the bundle's `lists`.

### 2.11 Route `api/routes/feed.py`

| Method & path | Auth | Response |
|---|---|---|
| `GET /api/feed/status` | member+ (`viewer`) | `FeedStatus` (`model_dump(mode="json")`) |
| `GET /api/feed/signatures` | member+ | `{items: FeedSignatureView[]}` (+ extras) |
| `POST /api/feed/refresh` | `require_role("admin")` | `FeedStatus` (clears the operator pin) |
| `GET /api/feed/signatures/{id}` | member+ | full signature JSON + `quarantine_reason`, `hits_24h`, last self-test results (gap; should) |
| `POST /api/feed/rollback` | admin | `{serial, reason}` → `FeedStatus` (gap; should) |

Errors use `aegis.core.errors.api_error`. `rt.feed` lacking our extras → 501 `not_implemented` for the gap endpoints only.

### 2.12 Config keys read, events emitted

- **Reads**: settings `feed_url`, `feed_pubkey`, `data_dir`, `test_mode`; policy `feeds.sources[0].*`, `feeds.overrides`; control `params` for SIG-01/02/03 (each validated by a private pydantic params model with defaults; unknown keys → WARNING).
- **Emits**: SSE `feed.updated`, `feed.rejected`, `system` (unreachable/stale/key reload transitions); audit `feed.updated`, `feed.rejected`; metrics `aegis_feed_serial`, `aegis_feed_reloads_total{result=ok|rejected|unreachable}`, `aegis_signature_hits_total{signature_id}`. SQLite `feed_state`, `signature_hits` (own tables only).

---

## 3. Reuse map (staging → owned paths)

| Staging file | Destination | How |
|---|---|---|
| `feed-seed/feedlib.py` (matchers, Event, pickle/zip, JSONPath-lite, URL extractors, package parser, canonical_json) | `src/aegis/feed/matchers/{core,text,structured,artifact}.py` | copy + rename leaf types (keep aliases), contract actions/surfaces, add span evidence + `event_from_interaction`; drop signing helpers (→ `verify.py`/`signing.py`) |
| `feedlib.sign_document/verify_document/key_id_for/read_hex_key` | `src/aegis/feed/verify.py`, `feed_service/signing.py` | rewrite as **detached** sign/verify over exact bytes; key_id hex8; key file base64 (hex accepted) |
| `feed-seed/schema.py` + `bundle.schema.json` + `jsonschema_lite.py` | `src/aegis/feed/schema.py` | re-expressed as pydantic models (the contract shapes); JSON-schema-lite not needed |
| `feed-seed/validate.py` (`check_signature`, `run_vectors`, `redos_smoke`, `demo_invariant`, `_ADVERSARIAL`) | `src/aegis/feed/matchers/__init__.py:run_tests`, `feed_service/build.py:validate_signature`, `__main__ verify` | port functions; the demo invariant becomes a unit test + `verify` check |
| `feed-seed/sign.py` (`build_bundle`, monotonic `current_serial`) | `feed_service/build.py` | port; new bundle/pointer shapes; detached `.sig`; serial = max(serial, high_water)+1 |
| `feed-seed/verify.py` (gateway order) | `src/aegis/feed/manager.py:refresh` | port order; adds anti-rollback high-water, dedupe, quarantine, swap, events |
| `feed-seed/keygen.py` | `feed_service/__main__.py keygen` | port; writes `state/keys`, `config/feeds/feed_pubkey.b64`, seed bundle |
| `feed-seed/scan.py` | `feed_service` `POST /api/scan`, `aegis.feed.gate scan` | port logic |
| `feed-seed/signatures/AEGIS-TI-000..019.yaml` | `feed_service/signatures/*.yaml` | converted by `feed_service/port_staging.py` (ruamel round-trip keeps comments) using the §2.3 table |
| `feed-seed/pending/AEGIS-TI-022.yaml` | `feed_service/signatures/AEGIS-TI-022.yaml` | converted + `enabled: false`; host → acme-capital |
| `feed-seed/demo/echoleak-proxy-payload.md` | `feed_service/demo/echoleak-proxy-payload.md` | copy; host → `assets.acme-capital.example` |
| research 04 §3.3 `lists` | `feed_service/lists/*.yaml` | new data files |
| `seed/policy.yaml` SIG-01/02/03 entries (`config`, examples, owasp) | `config/snippets/threat-feed.yaml` | translated per the CONTRACTS translation table |
| `design/prototype/assets/tokens.css` + subset of `app.css`; `view-feed.js` (banner/timeline copy) | `feed_service/ui/app.css`, `ui/app.js` | copy tokens verbatim; reuse class names + copy text |
| `staging/feed-seed/keys/*` | — | **not reused**; a new keypair is generated (private key never leaves `feed_service/state/keys`) |

---

## 4. Interfaces

### 4.1 Consumed (exact contract names)

- Frozen: `aegis.core.types` (`Interaction`, `TextSegment`, `Decision`, `Finding`, `FeedStatus`, `AuditEvent`, `AppliesTo`, `ACTION_PRECEDENCE`, `new_id`, `utcnow`), `aegis.core.protocols` (`BaseControl`, `FeedManager`, `RuntimeProto`), `aegis.core.policy_schema` (`ControlConfig`, `FeedsSection`, `FeedSource`, `FeedOverride`, `PolicySnapshot`).
- core-gateway: `aegis.core.runtime.get_runtime()`; `aegis.core.deps.get_rt`, `viewer`, `require_role("admin")`; `aegis.core.errors.api_error`; `aegis.settings.get_settings()` (`feed_url`, `feed_pubkey`, `data_dir`, `test_mode`).
- Services: `rt.bus.publish`, `rt.audit.record`, `rt.metrics.inc/set_gauge`, `rt.db()`, `rt.policy.snapshot()`, `rt.redactor.mask_for_log`. Optional later: `rt.semantic.similarity` (TI-18).
- Pipeline semantics §3.5 (phases, monitor mode, redaction of span findings with `replacement`, `ctx.feed_serial` stamping from `rt.feed.serial`).

### 4.2 Provided

- `rt.feed` via `aegis.feed.manager:create(rt)`: the `FeedManager` protocol (`serial`, `status()`, `refresh()`, `signatures()`), plus `start()/stop()`. Extras for other teams to read defensively (`getattr`): `lists() -> dict` (e.g. MCP-01 can check `malicious_versions` for launch packages).
- Public import surface `aegis.feed.matchers`: `compile_signature(sig: dict, lists: dict | None = None)`, `match(compiled, interaction) -> list[dict]` (also used by `feed_service`).
- Controls `SIG-01`, `SIG-02`, `SIG-03` (catalog §4.4).
- Routes `GET /api/feed/status` → `FeedStatus`, `GET /api/feed/signatures` → `{items: FeedSignatureView[]}`, `POST /api/feed/refresh` (admin) → `FeedStatus`.
- SSE `feed.updated` = `FeedStatus & {added, removed, modified}`, `feed.rejected` = `{reason, serial_attempted, kept_serial}`; audit `feed.updated` / `feed.rejected`; metrics per §6.4.
- Feed service §5.6 endpoints (+ extras in §2.5), `python -m feed_service keygen` (Makefile `feed-keys`).
- Files `config/feeds/feed_pubkey.b64`, `config/feeds/seed_bundle.json` + `.sig`; latest/bundle formats exactly as §4.7.

### 4.3 Contract gaps / requests (proposed addenda, not conflicting shapes)

1. **core-gateway: `model.admin` interaction shape** for `/ollama/api/{op}`: `kind="model_call"`, `surface="model.admin"`, `destination=local`, `model=<body.model or body.name>`, `tool_name=f"ollama.{op}"`, `tool_args=<parsed JSON body>` (its string leaves become segments as usual), `url="/api/{op}"`, `http_method`, `meta={"ollama_op": op}`. A blocked admin op answers `403 {"error": "[Aegis] Blocked by <control>: <reason>"}` (the Ollama CLI prints `error`).
2. **core-gateway: Ollama blob uploads** `POST /ollama/api/blobs/{digest}` → evaluate `artifact.file` (`kind="egress"`, `direction="in"`, `segments=[]`, `raw=<bytes>`, `meta={"filename": digest, "source": "ollama.blob", "sha256": digest}`). Buffer ≤ 64 MB; for larger blobs, scan the first 16 MB (`meta.truncated=true`; GGUF metadata lives at the head) and stream the rest. Should, not demo-critical.
3. **Artifact convention (all producers)**: `artifact.file` interactions carry bytes in `raw` (in-process) or `meta.artifact_b64` (`/v1/guard`), never in `segments`. Use `direction="in"` (content arriving) and optional `meta.filename`/`meta.source_url`. This prevents DLP-02/DLP-04 from flagging base64 blobs as secrets.
4. **metadata-egress**: `egress.request` interactions set `url`, `http_method`, and `raw` = outbound body (dict for JSON, str otherwise), so feed `field: body`/`url` matchers work. **Should:** for binary or model-file responses (`application/octet-stream`, `.bin|.pt|.pth|.ckpt|.pkl|.safetensors|.gguf|.onnx|.keras|.h5`), also evaluate an `artifact.file` interaction (same convention) before returning the body.
5. **core-gateway pipeline**: in the combine step, honour a control-returned `Decision.mode == "monitor"` (SIG-01 experimental signatures). SIG-01 also returns `action="log"` in that case, so nothing breaks either way.
6. **policy-engine**:
   - (a) Merge `config/snippets/threat-feed.yaml`.
   - (b) Add `assets.acme-capital.example` to `destinations.allowed_link_domains` (EchoLeak "allow before" needs DLP-06 to trust the firm's own asset CDN).
   - (c) The self-test builder should pass PolicyTest extras `meta`, `url`, `direction`, `http_method` into the `Interaction` (so artifact/egress tests can live in policy).
   - (d) `feeds.overrides` edits are `ChangeKind="feed.override"`. Disabling or `mode: off` should be `loosening=True`.
7. **New endpoints under our `/api/feed/*` prefix** (owned route file; not in frozen `types.ts` → dashboard-security uses page-local types): `GET /api/feed/signatures/{id}`, `POST /api/feed/rollback {serial, reason}` (admin). `FeedStatus.history` items get extra keys (`sha256, quarantined, vectors, verify_ms, compile_ms, source`); `FeedSignatureView` items get extras (`message, references, quarantine_reason, mode, cves`).
8. **dashboard-security**: the threats page shows a red banner on SSE `feed.rejected` ("enforcing #N"), animates the serial flip on `feed.updated`, shows `quarantined` status, adds an "Open feed editor ↗" link to `http://127.0.0.1:8790/`, and adds a playground preset "EchoLeak proxy payload" (`surface: model.response`, text = `feed_service/demo/echoleak-proxy-payload.md`).
9. **demo-mocks-docs**:
   - `scripts/run_stack.py` runs `python -m feed_service keygen --if-missing` and then starts the feed service **before** the gateway.
   - mock_llm gets a trigger `[[EMIT_ECHOLEAK_PROXY]]` that emits the payload markdown.
   - Runbook scene 5 uses AEGIS-TI-022 (EchoLeak flip) instead of "TI-017 added in v2", because TI-017 is part of the published v1 set.
   - Preflight runs `python -m aegis.feed.demo check` (gateway serial == feed serial, key ids equal).
   - Reset between judges = `make reset` + `python -m feed_service reset --hard`.
10. **scaffold**: `.gitignore` already lists `feed_service/state/**`. Please also gitignore `data/artifacts/` (CLI samples). Makefile `feed-keys` = `uv run --frozen python -m feed_service keygen --if-missing`.

---

## 5. Tasks

Order = graceful degradation. TI-01…TI-12 (must, ≈ 142 min; TI-01…TI-08 alone ≈ 100 min deliver F8) cover F8 end-to-end plus the model gate. Should/could come after. Estimates assume heavy copy-port from staging.

### TI-01 · Interfaces first (stubs) — must · demo_critical: yes · 5 min · deps: CONTRACTS §3.2/§3.3
- [ ] `aegis/feed/__init__.py`, `manager.py` with `create(rt)` returning a `FeedManager` (status `disabled`, `serial=None`, empty signatures), `matchers/__init__.py` exporting `compile_signature`, `match` (raising `NotImplementedError` until TI-02).
- [ ] `controls/signatures/{__init__,sig01_engine,sig02_artifact,sig03_packages}.py` each with `CONTROLS=[…]` whose `evaluate` returns `None`.
- [ ] `api/routes/feed.py` with the 3 contract endpoints wired to `rt.feed`.
- [ ] No import-time side effects (no network, no file reads at import).

### TI-02 · Port matcher engine — must · demo_critical: yes · 15 min · deps: TI-01
- [ ] Split `feedlib.py` into `matchers/{core,text,structured,artifact}.py`, each with `MATCHERS`; `__init__` merges them and exposes the public API + `FeedError`.
- [ ] Canonical leaf names `literal_set`, `pickle_globals`, `json_path`, `semantic` + aliases; contract action precedence; contract surfaces.
- [ ] Span evidence (`start/end`) for regex/literal_set/url; regex collects all spans when asked (`all_spans=True`).
- [ ] `event_from_example`, `event_from_interaction` (§2.4 rules incl. hf.co URL synthesis and byte sources), `run_tests`.

### TI-03 · Schema + signature port — must · demo_critical: yes · 10 min · deps: TI-02
- [ ] `aegis/feed/schema.py`: `SigExample`, `SigTests` (≥ 1/≥ 1), `SigAppliesTo{surfaces, fields=[]}`, `Signature` (id `^AEGIS-TI-\d{3,4}$`, status, severity, aliases, tags, references, `match`, `action: Action`, `action_overrides: dict[Surface, Action]`, `redact_scope`, `redact_with`, optional metadata; authoring-only `enabled`), `BundleHeader`, `Bundle`, `FeedPointer`. A before-validator normalizes staging aliases (`matcher`, list-form `applies_to` via the §2.3 default table, `alert/quarantine/strip_tool`).
- [ ] `feed_service/port_staging.py`: read `staging/feed-seed/{signatures,pending}` and write `feed_service/signatures/` per the §2.3 table (ruamel round-trip). TI-022 gets `enabled: false`. Rewrite the demo host to acme-capital (TI-014 `host_not_in` + TI-022 `host_in` add `*.acme-capital.example`; vectors + payload switch). Then run all vectors and the demo invariant. Exit non-zero on any failure.
- [ ] `feed_service/lists/{packages,models,iocs}.yaml`; `feed_service/demo/echoleak-proxy-payload.md`.

### TI-04 · Signing, verification, keygen, seed bundle — must · demo_critical: yes · 8 min · deps: TI-03
- [ ] `feed_service/signing.py` + `aegis/feed/verify.py` (`load_pubkey` b64|hex, `key_id` hex8, `verify_detached`, `FeedRejected`).
- [ ] `python -m feed_service keygen [--force|--if-missing]` per §2.5. Produces `config/feeds/feed_pubkey.b64` and `seed_bundle.json(.sig)` (serial 1, TTL 30 d), and seeds `state/dist` with serial 1 = the seed bytes.

### TI-05 · Feed service core API — must · demo_critical: yes · 20 min · deps: TI-04
- [ ] `build.py`: Workspace, `validate_signature` (schema → RE2 → vectors → ReDoS smoke → surfaces), `build_bundle` (canonical JSON), `publish(force)`, `tamper(mode)` (4 modes), `reset(hard)`, serial.json (serial/high_water), events.jsonl, asyncio lock.
- [ ] `app.py` `create_app(state_dir=None, repo_root=None, gateway_url=None)`: distribution endpoints, authoring endpoints, `/api/state` (with gateway status proxy), SSE broadcaster (`published`) via sse-starlette, static UI. `__main__.py`: `serve|keygen|publish|reset|verify` (uvicorn on 127.0.0.1:8790 by default).

### TI-06 · Gateway FeedManager — must · demo_critical: yes · 25 min · deps: TI-04
- [ ] `compile.py`: `CompiledFeed` (serial, version, sha256, published, expires, key_id, sigs, `by_surface`, quarantined{id: reason}, lists, vectors, timings) + `compile_bundle` (reject on schema/RE2, quarantine on vectors) + `diff`.
- [ ] `manager.py`: `start()` (tables, pubkey, cache → seed), `_loop()` (SSE listener + poll; off in test mode / disabled URL), `refresh()` per §2.7 (anti-rollback high-water, sha, sig, dedupe, atomic swap with `previous`, persist cache last 5 + `feed_state`, audit/bus/metrics, `system` transitions), `status()`, `signatures()`, `scan()`, `lists()`; injectable httpx transport.

### TI-07 · SIG-01 control — must · demo_critical: yes · 12 min · deps: TI-06
- [ ] Per §2.8: newest-message selection, overrides, response-direction downgrade, combine, findings with masked excerpts, redact spans (`match`/`segment`, `redact_with`), monitor-only → `log`+`mode=monitor`, snapshot pinning, hit recording (skip on dry_run), error isolation per signature.

### TI-08 · Route — must · demo_critical: yes · 4 min · deps: TI-06
- [ ] `/api/feed/status`, `/api/feed/signatures` (+ hits_24h), `POST /api/feed/refresh` (admin).

### TI-09 · SIG-02 model-artifact gate — must · demo_critical: yes (model-gate scene) · 12 min · deps: TI-02
- [ ] `gate.py`: `sniff_format(bytes, filename)`, `scan_artifact(bytes, filename, params) -> list[finding dicts]` (safetensors header, ZIP members + header tricks + Keras `config.json`, raw pickle allow/deny + fail-closed, 7z, HDF5/unknown, JSON config), registry helpers (`registry_of(name)`).
- [ ] `sig02_artifact.py`: params model (§6 snippet), byte sources incl. `artifact_roots` restriction, `model.admin` op rules (pull registry/insecure, push block, create `from` + template markers, copy/delete log), `asyncio.to_thread` + `max_scan_mb`.
- [ ] `samples.py`: generators for clean safetensors, clean torch-zip, Counter pickle, STACK_GLOBAL `datetime.date` pickle, truncated pickle, ZIP-hidden pickle, 7z-magic `.bin`, Keras Lambda `config.json`, GGUF with SSTI template, clean GGUF header. Reuse the staging vectors' bytes where they exist.

### TI-10 · Feed editor UI — must · demo_critical: yes · 15 min · deps: TI-05
- [ ] `ui/index.html`, `ui/app.css` (tokens + subset), `ui/app.js` per §2.6 must-parts: top bar with serial/version/key/expiry chips + gateway sync chip (1 s poll of `/api/state`), signature list with search + enabled switch + draft tag, YAML editor with Validate/Save/Enable/Withdraw + validation panel (per-vector rows), Publish button with pending-count label, Tamper menu (4 modes), Reset, toasts, red banner when the gateway rejects.

### TI-11 · Unit tests — must · demo_critical: no · 12 min · deps: TI-02…TI-09
- [ ] `tests/unit/threat_feed/` per the verification tasks below. Hermetic: tmp state dirs/keys, in-process ASGI (`httpx.ASGITransport`), no fixed ports, no models, `AEGIS_SEMANTIC=off`, `AEGIS_TEST_MODE=1`.

### TI-12 · Policy snippet — must · demo_critical: yes · 4 min · deps: TI-07, TI-09
- [ ] `config/snippets/threat-feed.yaml` (content in §6.1), validated against `ControlConfig`.

### TI-13 · SIG-03 package guard — should · demo_critical: no · 10 min · deps: TI-06
- [ ] `sig03_packages.py` per §2.10 using `parse_install_commands` + bundle `lists`; params `unknown_action`, `unknown_action_mcp_init`, `ecosystems`.

### TI-14 · Demo + gate CLIs — should · demo_critical: yes (scripted fallback for F8) · 10 min · deps: TI-05, TI-06
- [ ] `python -m aegis.feed.demo echoleak [--gateway URL] [--feed URL]`:
  - POST `/v1/guard` (`surface: model.response`, payload) → prints ALLOW.
  - Enable TI-022 + publish on the feed service.
  - Poll `/api/feed/status` until the serial bumps → prints the activation ms.
  - `/v1/guard` again → prints BLOCK `SIG-01 AEGIS-TI-022 CVE-2025-32711`.
  - `--reset` disables TI-022 and republishes.
  - `python -m aegis.feed.demo check` (key ids + serial in sync; preflight).
- [ ] `python -m aegis.feed.gate scan <file> [--agent ID]` (POST `/v1/guard` artifact.file with `meta.artifact_b64`) · `python -m aegis.feed.gate samples --out data/artifacts/`.

### TI-15 · GGUF + Keras depth — should · demo_critical: no · 10 min · deps: TI-09
- [ ] GGUF v2/v3 KV parser (string/array/numeric skipping, caps on counts/lengths) → `tokenizer.chat_template` SSTI scan; malformed → block. `.keras` ZIP `config.json` Lambda check; HDF5 Keras → `allowed_formats` decision.

### TI-16 · Operator rollback + signature detail — should · demo_critical: no · 8 min · deps: TI-06, TI-08
- [ ] `FeedManager.rollback()` + pin semantics; `POST /api/feed/rollback`, `GET /api/feed/signatures/{id}`.

### TI-17 · UI polish — should · demo_critical: no · 10 min · deps: TI-10
- [ ] "Try it" scan panel (`POST /api/scan`), publish diff preview (`pending` added/removed/modified), force publish (to demo gateway-side quarantine), activity timeline, keyboard shortcuts, list row animation on publish.

### TI-18 · Stretch — could · demo_critical: no · 20 min
- [ ] Embedding similarity for `semantic` leaves via `rt.semantic.similarity` (precomputed per bundle, async pre-pass; lexical stays the fallback).
- [ ] Per-surface RE2 `Set` pre-filter.
- [ ] `list_ref` in `package`/`literal_set` (TI-017 IOC/version data moves to `lists`).
- [ ] Ollama post-pull verification (`/api/show` template scan → quarantine via `/api/delete`).
- [ ] TI-003 `extract: text` branch so `curl -o pytorch_model.bin https://…` in Bash needs approval.
- [ ] CORS for the dashboard origins on `/api/state`.

### Verification tasks

| ID | Proves | Command / check | Expected |
|---|---|---|---|
| TI-V01 | Imports, no side effects | `uv run --frozen python -c "import aegis.feed.manager, aegis.feed.matchers, aegis.feed.gate, aegis.controls.signatures.sig01_engine, aegis.controls.signatures.sig02_artifact, aegis.controls.signatures.sig03_packages, aegis.api.routes.feed, feed_service.app"` | exit 0, no network, no files created |
| TI-V02 | Ported signatures + vectors | `uv run --frozen python feed_service/port_staging.py --check` and `uv run --frozen pytest tests/unit/threat_feed/test_matchers.py -q` | 21 signatures, ≥ 87 vectors (staging count), 0 failures; every example surface ∈ applies_to; RE2 rejects `(a)\1` and lookaround; ReDoS smoke < 100 ms per pattern on 100 KB |
| TI-V03 | Demo invariant | test: payload on `model.response` → `allow` with the published set; with TI-022 enabled → `block` by `AEGIS-TI-022` | pass |
| TI-V04 | Signing | `pytest tests/unit/threat_feed/test_signing.py -q` | valid sig verifies; 1 flipped byte, other key and truncated sig each fail; key_id is 8 hex |
| TI-V05 | Feed service API | `pytest tests/unit/threat_feed/test_service.py -q` (ASGI) | keygen (tmp) → `/feed/latest.json` verifies against the tmp pubkey; publish → serial 2, monotonic; PUT invalid regex → `valid:false` with "not valid RE2"; publish refused (422) unless `force`; DELETE → `withdrawn`; each tamper mode leaves `latest.json` unverifiable (or rollback/sha-mismatch as designed); SSE broadcaster queue receives `published` |
| TI-V06 | Manager pipeline | `pytest tests/unit/threat_feed/test_manager.py -q` (feed app via `httpx.ASGITransport`) | start on seed (status `seed`, serial 1) → refresh no-op `ok`; enable TI-022 + publish → refresh → serial 2, `added=1`, bus `feed.updated`, audit record; `unsigned` tamper → `rejected`, serial stays 2, exactly one `feed.rejected` across 3 refreshes; `rollback` → rejected; `swap_bundle` → "sha256 mismatch"; `wrong_key` → key_id mismatch; force-published failing vector → `signatures_quarantined == 1` and that signature never matches; regex error bundle → rejected; expired → `stale` but still enforcing; restart from cache → same serial |
| TI-V07 | SIG-01 semantics | `pytest tests/unit/threat_feed/test_sig01.py -q` | canary blocks on prompt.user, tool.input, mcp.list, egress.request; TI-014 redact replaces only the URL span; TI-013 strips invisibles (`redact_with: ""`); experimental → `log` + `mode=monitor`; policy override `enabled:false` → allow; override `action: log` applied; `require_approval` on model.response → `log`; an old history message with "ignore all previous instructions" is not blocked (newest-only) but a new one is; findings' excerpts are masked; dry_run records no hits |
| TI-V08 | SIG-02 model gate | `pytest tests/unit/threat_feed/test_sig02.py -q` | samples: clean safetensors allow, clean torch-zip allow, Counter pickle block, STACK_GLOBAL date pickle block, truncated pickle block, ZIP-hidden pickle block, 7z `.bin` block, Keras Lambda block, GGUF SSTI block (if TI-15), unknown format `model.xyz` block; model.admin push block, pull `registry.evil.example/x` block, pull `llama3.2` allow, `create` with `__globals__` template block (SIG-01 TI-005 and/or SIG-02); `artifact_path` outside roots ignored |
| TI-V09 | SIG-03 | `pytest tests/unit/threat_feed/test_sig03.py -q` | `pip install litellm==1.82.8` block; `npm i event-stream@3.3.6` block; `pip install huggingface-cli` require_approval; `pip install requests` allow; `pip install acme-quant-utils` require_approval; `pip install litellm` (unpinned) log |
| TI-V10 | Lint | `uv run --frozen ruff check src/aegis/feed src/aegis/controls/signatures src/aegis/api/routes/feed.py feed_service tests/unit/threat_feed` + `ruff format --check` (same paths) | clean |
| TI-V11 | Snippet validity | `uv run --frozen python -c "import yaml; from aegis.core.policy_schema import ControlConfig, FeedsSection; d=yaml.safe_load(open('config/snippets/threat-feed.yaml')); [ControlConfig(**c) for c in d['controls']]; FeedsSection(**d['feeds'])"` | exit 0 |
| TI-V12 | Performance | test (marker `bench`, non-gating): 200× SIG-01 scan of an 8 KB prompt on `model.request` with the full feed | p95 < 2 ms (report; fail only if > 10 ms) |
| TI-V13 | UI renders | `uv run --frozen python -m feed_service --port 0` (prints the port), open it in the browser preview, read console + screenshot; then stop it | no console errors; list shows 21 rows with TI-022 "Draft"; Validate shows vectors; Publish toast "serial #2"; Tamper menu works; sync chip "Gateway offline" (no gateway) |
| TI-V14 | Live F8 (integration only; lead runs it with fixed ports) | `make feed-keys`, start the feed service then the gateway; `curl -s :8787/api/feed/status \| jq '.status,.serial'` → `"ok"`/`1`; enable TI-022 in the UI → Publish; `uv run --frozen python -m aegis.feed.demo echoleak` | serial 1→2 in < 2 s; output ALLOW → BLOCK `AEGIS-TI-022 (CVE-2025-32711)`; Tamper → `/api/events` shows `feed.rejected`, `/api/feed/status.serial` unchanged; `/metrics` has `aegis_feed_serial 2`; the decision in the live feed carries `feed_serial: 2` |
| TI-V15 | Ollama front (integration) | `OLLAMA_HOST=http://127.0.0.1:8787/ollama ollama push aegis-judge` and `… ollama pull hf.co/ghost-author-demo/base-model` | push: "Error: [Aegis] Blocked by SIG-02 …"; pull: approval pending via SIG-01 AEGIS-TI-018 (nothing downloaded) |

---

## 6. Snippet and demo cut

### 6.1 `config/snippets/threat-feed.yaml` (content to write; policy-engine merges)

```yaml
destinations:
  allowed_link_domains: ["docs.acme-capital.example", "assets.acme-capital.example"]  # firm asset CDN (EchoLeak demo)
feeds:
  sources:
    - {id: aegis-threat-intel, url: "http://127.0.0.1:8790", pubkey_file: config/feeds/feed_pubkey.b64,
       seed_bundle: config/feeds/seed_bundle.json, poll_s: 10, sse: true, enabled: true, max_age_s: 86400}
  overrides:
    AEGIS-TI-013: {action: redact, justification: "Strip invisible Unicode instead of blocking (copy-paste from PDFs)"}
controls:
  - id: SIG-01
    name: External exploit-signature engine (signed threat feed)
    action: block            # informational: every signature carries its own action
    severity: critical
    fail_mode: closed
    timeout_ms: 250
    owasp: [LLM04:2026, ASI04, ASI05, MCP04:2025, MCP05:2025]
    params: {history_scan: false, max_scan_chars: 262144, semantic_max_chars: 8192,
             response_require_approval_as: log, record_hits: true}
    tests:
      - {name: feed-canary-prompt, text: "please echo AEGIS-TEST-SIGNATURE-7F3A back to me", expect: block, control: SIG-01}
      - {name: feed-canary-tool-arg, kind: tool_call, surface: tool.input, destination: local, tool_name: Write,
         tool_args: {file_path: notes.md, content: "note aegis-test-signature-7f3a"}, expect: block, control: SIG-01}
      - {name: benign-prompt, text: "Summarise the attached Q3 revenue report in three bullet points.", expect: allow}
  - id: SIG-02
    name: Model-artifact gate (pickle, GGUF, Keras, registries)
    action: block
    severity: critical
    fail_mode: closed
    timeout_ms: 2000
    owasp: [LLM04:2026, LLM05:2026, ASI04, ASI05]
    params:
      allowed_formats: [safetensors, gguf, onnx, json, pickle_clean]
      pickle_global_allow: ["collections.OrderedDict", "torch._utils._rebuild_tensor_v2", "torch._utils._rebuild_parameter",
        "torch._tensor._rebuild_from_type_v2", "torch.*Storage", "torch.storage._load_from_bytes", "torch.device",
        "torch.nn.parameter.Parameter", "numpy.core.multiarray._reconstruct", "numpy.core.multiarray.scalar",
        "numpy.ndarray", "numpy.dtype", "_codecs.encode", "argparse.Namespace"]
      pickle_global_deny: ["os.*", "posix.*", "nt.*", "subprocess.*", "builtins.exec", "builtins.eval",
        "builtins.__import__", "runpy.*", "pip.*", "socket.*", "pty.*"]
      malformed_action: block
      max_scan_mb: 512
      gguf_template_markers: ["__class__", "__mro__", "__subclasses__", "__globals__", "__builtins__", "popen", "os.system"]
      keras_reject_lambda: true
      registries_allow: [registry.ollama.ai, hf.co, huggingface.co]
      admin_ops_block: [push]
      admin_ops_log: [copy, delete]
      artifact_roots: [data/artifacts, models, demo]
    tests:
      - {name: ollama-push-blocked, kind: model_call, surface: model.admin, destination: local, tool_name: ollama.push,
         tool_args: {model: aegis-judge}, expect: block, control: SIG-02}
      - {name: ollama-pull-library-model, kind: model_call, surface: model.admin, destination: local, tool_name: ollama.pull,
         tool_args: {model: aegis-judge}, expect: allow}
      # artifact.file byte tests live in unit tests / tests/cases until PolicyTest `meta` passthrough exists (gap 6c)
  - id: SIG-03
    name: Package-install & slopsquatting guard
    action: block
    severity: high
    fail_mode: closed
    timeout_ms: 50
    owasp: [LLM04:2026, ASI04, MCP04:2025]
    params: {unknown_action: require_approval, unknown_action_mcp_init: log, ecosystems: [pypi, npm, vscode]}
    tests:
      - {name: malicious-npm-version, kind: tool_call, surface: tool.input, destination: local, tool_name: Bash,
         tool_args: {command: "npm install event-stream@3.3.6"}, expect: block, control: SIG-03}
      - {name: no-install-command, kind: tool_call, surface: tool.input, destination: local, tool_name: Bash,
         tool_args: {command: "ls -la"}, expect: allow}
```

Test-design rule: a `control:` attribution is set only where no other team's control can plausibly decide the same input. SIG-01 keeps default priority 100, so it loses ties to the alphabetically earlier controls that overlap (DLP-06, EXE-01, INJ-01, MCP-02).

### 6.2 Demo cut

**Must really work live**
- Feed service UI: edit/enable/withdraw → Validate → **Publish** → gateway serial bump in < 2 s (SSE) → **EchoLeak payload ALLOW → BLOCK (SIG-01, AEGIS-TI-022, CVE-2025-32711)**. Shown via the playground preset or `python -m aegis.feed.demo echoleak`.
- **Tamper** (`unsigned`) → `feed.rejected` (audit + SSE red banner, both in the dashboard and the feed UI sync chip) while enforcement stays on last-known-good.
- Gateway-side self-test/quarantine + anti-rollback (shown in tests; live via Tamper → `rollback`).
- Canary blocked on any surface. Feed serial stamped on every decision.
- Model gate: `ollama push` blocked, `hf.co/ghost-author-demo/*` pull → approval, and a malicious-shaped pickle blocked via `python -m aegis.feed.gate scan data/artifacts/weights.bin`.

**May be simulated or simplified (and honestly labelled)**
- The `semantic` matcher uses the lexical-reference scorer (`mode: lexical-reference` in evidence); embeddings come later (TI-18).
- HF egress: URL-level only (bytes scanning needs metadata-egress gap 4).
- Ollama blob upload scanning depends on core-gateway gap 2; the CLI/guard path demonstrates the same scanner.
- Operator rollback: API only, no UI.
- Feed service authentication: none (localhost demo; production = Git PR + CI signing, research 04 §3.2).

**EchoLeak fallback** if DLP-06 strips the allowlisted image anyway (gap 6b not merged): run the same flip on `tool.input`, where DLP-06 does not apply. `Write` a `report.md` containing the payload: before = allow, after = block by TI-022.

---

## 7. Dependencies

Python (all in CONTRACTS §7.6; **no new deps**): `pynacl` (Ed25519), `google-re2` (import `re2`; staging verified it works on 3.13 / arm64), `pyyaml` (`safe_load` only), `ruamel.yaml` (comment-preserving port script), `pydantic>=2.9`, `fastapi`, `uvicorn[standard]`, `httpx` (feed client + SSE line reader; no `httpx-sse`), `sse-starlette` (feed service SSE). Stdlib: `pickletools`, `zipfile`, `hashlib`, `base64`, `struct` (GGUF), `sqlite3`, `asyncio`.
Dev: `pytest`, `pytest-asyncio`, `asgi-lifespan`, `httpx.ASGITransport` (`respx` optional).
Frontend: none. The feed UI is vanilla HTML/CSS/JS with no CDN; it does not use `web/` deps.
Other workstreams: core-gateway (runtime, pipeline, Ollama front, `/v1/guard`), policy-engine (snippet merge, overrides), audit-metrics (sinks; Null fallbacks are fine), dashboard-security (threats page), demo-mocks-docs (run_stack order, mock trigger, runbook), metadata-egress (egress interaction shape). With Null fallbacks everything degrades to "feed works, events no-op".

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| SIG-01 false positives on Claude Code traffic (TI-019 delimiters, TI-013 emoji ZWJ, TI-009 `exec(` in written code) break the live session | newest-message-only scanning on `model.request`; TI-013 redacts (strips) rather than blocks on prompts; per-signature `feeds.overrides` (one-line policy edit, hot reloaded); judges can set a signature to `experimental` (monitor) in the feed UI and republish in seconds |
| Attribution clashes in policy self-tests (SIG-01 duplicates EXE-01/INJ-01/DLP-06/MCP-02 verdicts) reject other teams' policies | default priority 100 → alphabetical tie-break favours their controls; SIG tests use inputs only SIG controls decide; overlap list documented for test-suite |
| Key mismatch (fresh clone, regenerated key) → every pull rejected | `keygen` rewrites pubkey + seed + dist atomically; gateway reloads a changed pubkey file once on key_id mismatch; `aegis.feed.demo check` in preflight; `--if-missing` refuses half-states with a clear message |
| Anti-rollback blocks rehearsal resets | soft reset always bumps the serial; `reset --hard` documented to pair with gateway `make reset` (wipes `data/` high-water); the rollback rejection is itself a demo feature |
| Feed service down at demo time | gateway keeps last-known-good (cache → seed); status `unreachable` banner; 10 s poll reconnects; seed bundle committed |
| Event-loop stalls on large artifacts / huge prompts | `asyncio.to_thread` for > 64 KB texts and all byte scans; caps (`max_scan_mb`, 256 KB views, 5 MB bundle, 2M pickle ops); per-signature try/except; timeouts per cfg |
| Judge-authored broken or hostile signatures (ReDoS, deep nesting, huge lists) | RE2 only + length cap; depth ≤ 6; list/size caps; feed-side validation + ReDoS smoke before signing; gateway rejects uncompilable bundles and quarantines failing vectors |
| DLP-06 strips the allowlisted image before TI-022 matters (no "allow before") | policy request 6b; fallback flip on `tool.input` (§6.2) |
| Tamper spam (poll re-reports the same rejection) | dedupe on (pointer sha256, reason); status stays `rejected` until a valid publish |
| Monitor-mode handling differs in core | SIG-01 returns `action=log` for monitor-only hits, so the final action can never exceed `log` |
| Time overrun (scope is large for one agent) | strict order: TI-01…08 deliver F8 first (~100 min); cut order if late: TI-18 → TI-17 → TI-16 → TI-15 → TI-13 → UI right column → SIG-02 `create`/GGUF parts (keep push/registry + pickle) |
| Privacy (evidence snippets may contain PII/IOCs) | excerpts and evidence pass through `rt.redactor.mask_for_log`; logs contain only signature ids/surfaces/actions; artifact bytes are never logged or persisted |
