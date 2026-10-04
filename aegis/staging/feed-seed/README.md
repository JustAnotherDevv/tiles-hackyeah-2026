# Aegis threat-intel signature feed (seed)

The **externally managed** threat-intel feed for Aegis: the historical-attack
signatures as **data**, plus a reference validator, matcher engine, and Ed25519
signing/verification. The gateway pins only the public key, pulls a signed bundle,
verifies it, runs each signature's inline tests, and swaps it in atomically — the
feed never contains code.

This directory is the "threat-intel service" side. Other agents own the gateway's
`FeedManager`; it can import `feedlib.py` directly or port its (documented) semantics.

```
feed-seed/
  signatures/           AEGIS-TI-000 .. AEGIS-TI-019  (published seed, enforced)
  pending/              AEGIS-TI-022  (disabled demo signature; publish to enable)
  demo/                 echoleak-proxy-payload.md  (harmless live-demo payload)
  schema.json           JSON Schema for ONE signature
  bundle.schema.json    JSON Schema for the bundle + latest.json envelopes
  feedlib.py            reference engine: matchers, Event, RE2, signing/verify
  jsonschema_lite.py    dependency-free JSON-Schema subset (so validate needs no extra deps)
  validate.py           schema + RE2 compile + inline vectors + ReDoS smoke + demo invariant
  keygen.py             demo Ed25519 keypair -> keys/   (private key gitignored)
  sign.py               build + Ed25519-sign a bundle -> dist/bundle-NNNNNN.json + latest.json
  verify.py             gateway-style verification (sig, sha256, rollback, expiry, self-test)
  scan.py               scan one event against the feed and print the decision
  keys/                 feed-public.key (committed) + feed-signing.key (gitignored)
  dist/                 generated signed bundles (gitignored)
```

## Quick start

```bash
cd aegis/staging/feed-seed

# 1. validate every signature (schema, RE2, inline tests, ReDoS, demo invariant)
uv run --python 3.13 --with google-re2 --with pyyaml python validate.py
#   add --with jsonschema to also cross-check against the reference JSON-Schema validator

# 2. make the demo signing keypair (writes keys/feed-signing.key, mode 600, gitignored)
uv run --python 3.13 --with pynacl python keygen.py

# 3. sign feed v1 (published signatures only) -> dist/bundle-000001.json + latest.json
uv run --python 3.13 --with pynacl --with google-re2 --with pyyaml python sign.py

# 4. verify the bundle the way the gateway does
uv run --python 3.13 --with pynacl --with google-re2 --with pyyaml python verify.py
```

One combined dev dependency set: `--with pynacl --with google-re2 --with pyyaml`
(`--with jsonschema` optional).

## Signature format

One YAML file per signature, named `<id>.yaml`. Full contract in `schema.json`.

| field | meaning |
|---|---|
| `id` | `AEGIS-TI-NNN` (unique; file name must start with it) |
| `title`, `description` | human text |
| `status` | `experimental` (monitor: evaluated + logged, never enforced) · `test`/`stable`/`deprecated` (enforced) · `withdrawn` (not evaluated — never delete a signature, withdraw it) |
| `severity` | `info` · `low` · `medium` · `high` · `critical` |
| `confidence` | `low` · `medium` · `high` (optional) |
| `aliases` | CVE / GHSA / vendor advisory IDs |
| `references` | source URLs |
| `tags` | OWASP LLM 2026 (`LLM01:2026`..`LLM10:2026`), Agentic ASI (`ASI01`..`ASI10`), MCP Top 10 (`MCP01:2025`..`MCP10:2025`), MITRE ATLAS (`AML.T0051`, `AML.CS0023`), `CWE-NNN`, or a free lowercase tag |
| `applies_to` | interception surfaces: `model_call` · `tool_call` · `mcp` · `egress` · `model_download` · `output` |
| `matcher` | one matcher tree (below) |
| `action` | `block` · `require_approval` · `quarantine` · `strip_tool` · `redact` · `alert` |
| `action_overrides` | per-surface action, e.g. `{output: alert}` |
| `message` | shown when it fires; written so a model can read it and stop |
| `tests` | `positive[]` (≥2, must match) and `negative[]` (≥2, must not) |

### Matcher types (a closed set — never code)

Combinators: `{any_of: [...]}`, `{all_of: [...]}`, `{not: {...}}`.

| type | what it matches | engine |
|---|---|---|
| `regex` | `pattern` (**RE2** syntax: no lookaround/backrefs, repetition ≤1000) over a `field` | google-re2 (linear time) |
| `literal` | any of `values` (Aho-Corasick-style containment; `case_insensitive` default true) | substring |
| `url` | parsed-URL conditions (`host_in`/`host_not_in`/`host_regex`, `port_in`, `path_regex`, `query_regex`, `query_min_length`, `scheme_in`/`scheme_not_in`, `method_in`); `extract: markdown\|text` pulls image/link/reference/`<img>`/autolink/bare URLs out of text first | urllib |
| `package` | parses install commands (pip/uv/poetry/pdm/pipx, npm/pnpm/yarn/bun, npx/bunx/dlx, `code --install-extension`, MCP `{command,args}` configs) and matches OSV-style `{ecosystem,name,versions}` (empty versions = any) | install-cmd parser |
| `hash` | sha256 of artifact bytes or (normalised) text — known-bad files / rug-pull fingerprints | set lookup |
| `bytes` | `magic_hex` at `offset` — file-magic sniffing | byte compare |
| `pickle_opcode` | streams opcodes with `pickletools.genops` (**never unpickles**), resolves globals (incl. memo indirection), flags any global outside `allow_globals` / inside `deny_globals`, scans every pickle-looking ZIP member regardless of extension; `on_parse_error: match` fails closed | pickletools |
| `jsonpath` | JSONPath-lite (`$ .k .* ..k ..* [n] [*] ['a','b']`) selecting a value that `equals` X and/or satisfies a nested `match`; `exists: false` matches absence | built-in |
| `semantic_exemplar` | gateway: max cosine(embed(input), embed(exemplar)) ≥ `threshold`; offline validator: char-trigram similarity ≥ `lexical_threshold` (catches paraphrases / non-English) | embeddings / trigrams |

`field` (text matchers): `all` (text + url + body + filename + every JSON string + a
synthetic `command args…` line for launch configs + compact JSON) · `text` · `url` ·
`body` · `filename` · `bytes`.

**Decision:** a signature's hit carries its (surface-resolved) action; across all hits
the **strongest enforced action wins** (`block` > `require_approval` > `quarantine` >
`strip_tool` > `redact` > `alert`); `experimental` signatures are monitor-only and
never change the decision.

### Example (abridged)

```yaml
id: AEGIS-TI-010
title: mcp-remote OAuth endpoint command injection (CVE-2025-6514)
status: stable
severity: critical
aliases: [CVE-2025-6514]
tags: [MCP05:2025, CWE-78]
applies_to: [mcp]
matcher:
  any_of:
    - {type: jsonpath, path: "$.authorization_endpoint", match: {type: url, scheme_not_in: [https]}}
    - {type: jsonpath, path: "$.authorization_endpoint", match: {type: regex, field: text, pattern: '\$\(|`|%24%28|\s'}}
action: block
tests:
  positive:
    - {name: non-https endpoint, surface: mcp, json: {authorization_endpoint: "http://a.example/x"}}
    ...
  negative:
    - {name: well-formed https, surface: mcp, json: {authorization_endpoint: "https://a.example/x"}}
    ...
```

Binary test inputs use `bytes_hex:` or `bytes_b64:` in an example instead of `text`.

## Signing & distribution

- **Bundle** (`dist/bundle-NNNNNN.json`): `{feed, schema_version, serial, created,
  expires, min_gateway_version, signature_count, signatures[], alg, key_id, signature}`.
- **latest.json**: tiny TUF-style pointer `{serial, created, expires, bundle, sha256,
  signature_count, alg, key_id, signature}`.
- **`signature`** is base64 Ed25519 (PyNaCl) over the **canonical JSON** of the document
  without its `signature` key: `json.dumps(doc, sort_keys=True, separators=(",",":"),
  ensure_ascii=False).encode()`. `key_id` = first 16 hex of `sha256(public_key)`.

**Gateway verification order** (`verify.py` mirrors it): verify `latest.json` signature →
bundle bytes' sha256 == `latest.sha256` (blocks mix-and-match) → verify bundle signature →
serial strictly `> last accepted` (**anti-rollback**) → not `expires` (stale ⇒ alert, keep
enforcing last-known-good) → schema-validate + run each signature's inline tests (failures
are **quarantined**, not activated). Any hard failure ⇒ keep last-known-good, emit
`feed.rejected`. Download cap 5 MB (endless-data defence).

```bash
# verify current feed, rejecting any serial <= 1
uv run ... python verify.py --min-serial 1
# verify a specific bundle directly
uv run ... python verify.py --bundle dist/bundle-000002.json
```

## Keys

`keygen.py` writes a demo Ed25519 keypair to `keys/`. `keys/.gitignore` ignores
`*.key` **except** `feed-public.key`, so the **private** `feed-signing.key` is never
committed; the gateway pins only `feed-public.key` / `feed-public.pub.txt`. In
production the key lives only in the threat-intel service (CI secret / HSM / minisign).

## The live demo (EchoLeak via an allowlisted proxy)

`demo/echoleak-proxy-payload.md` is a harmless model output containing a markdown
image whose URL points at an **allowlisted** internal asset host
(`assets.aegis-corp.example`) that exposes an open image-proxy (`/img/proxy?src=…`).
The query values are fake; no real data is present.

- **Before** publishing: the base EchoLeak signature `AEGIS-TI-014` allowlists that
  host, so the payload is **ALLOWED**.
- **After** publishing the disabled `pending/AEGIS-TI-022` (allowlisted-proxy abuse),
  the payload is **BLOCKED**.

```bash
# feed v1 (published only): ALLOW
uv run --python 3.13 --with pynacl --with google-re2 --with pyyaml python sign.py
uv run --python 3.13 --with google-re2 --with pyyaml python scan.py \
    --surface output --file demo/echoleak-proxy-payload.md            # -> ALLOW

# publish the demo signature -> feed v2 (serial bumps 1 -> 2): BLOCK
uv run --python 3.13 --with pynacl --with google-re2 --with pyyaml python sign.py --include-pending
uv run --python 3.13 --with google-re2 --with pyyaml python scan.py \
    --surface output --file demo/echoleak-proxy-payload.md --include-pending   # -> BLOCK AEGIS-TI-022
# or against the signed+verified bundle:
uv run --python 3.13 --with pynacl --with google-re2 --with pyyaml python scan.py \
    --from-bundle --surface output --file demo/echoleak-proxy-payload.md       # -> BLOCK
```

`validate.py` enforces this ALLOW-before / BLOCK-after invariant on every run.

## Seeded signatures (20 + 1 pending)

`000` canary · `001` malicious pickle (opcode allowlist) · `002` nullifAI 7z-magic ·
`003` unsafe format / torch.load (CVE-2025-32434) · `004` Keras Lambda
(CVE-2024-3660/2025-1550) · `005` GGUF SSTI (CVE-2024-34359) · `006` Probllama
(CVE-2024-37032) · `007` ShadowRay (CVE-2023-48022) · `008` Langflow (CVE-2025-3248) ·
`009` LLM-code-exec (CVE-2023-36258/2024-12366) · `010` mcp-remote OAuth
(CVE-2025-6514) · `011` MCP Inspector / LiteLLM (CVE-2025-49596 / CVE-2026-42271) ·
`012` MCP tool poisoning / rug pull · `013` Unicode tag smuggling · `014` EchoLeak
markdown exfil (CVE-2025-32711) · `015` config hijack auto-approve
(CVE-2025-53773/54135) · `016` slopsquatting · `017` compromised packages / MCP
(postmark-mcp, litellm, mistralai, CVE-2025-8217) · `018` model namespace reuse ·
`019` prompt-injection families · **pending** `022` EchoLeak via allowlisted proxy (demo).

## Safety note

Test vectors are **indicators, not working exploits**: the pickle/model-file vectors
use harmless off-allowlist globals (`collections.Counter`, `datetime.date`) and a
truncated stream to exercise the allowlist/fail-closed logic; others use CVE-shaped
request paths, header/package names and versions, and markdown-URL shapes.
