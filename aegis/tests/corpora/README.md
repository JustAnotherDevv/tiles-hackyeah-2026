# Aegis evaluation corpora

Licence-clean red-team and false-positive corpora for the Aegis AI Control Layer self-test and
`make eval` suites. Every row is one JSON object per line (JSONL) with a fixed schema; the same
schema is shared across public subsets, hand-written sets and generated obfuscations so a single
loader can read them all.

## Row schema

| field | meaning |
|---|---|
| `id` | unique, stable, prefix encodes the source family (e.g. `JBB-ATT-001`, `PL-INJ-002`, `OBF-INJ-EN-01-base64`) |
| `text` | the prompt / tool input / tool result / model output under test |
| `label` | `attack` (must block/redact/flag/require-approval) or `benign` (must allow) |
| `category` | dotted taxonomy, e.g. `direct_injection`, `indirect_injection.email`, `exfil.markdown_image.reference`, `mcp.tool_poisoning.shadowing`, `benign_finance.jargon`, `obfuscated.base64.injection` |
| `lang` | `en` `pl` `de` `uk` `ru` |
| `source` | upstream id + revision, or `aegis-handwritten` / `aegis-generated` |
| `licence` | per-row licence (see `LICENSES.md`) |
| `expected_action` | `block` \| `redact` \| `flag` \| `require_approval` \| `allow` |
| `notes` | rationale, upstream metadata, which control it exercises |

Optional extra fields appear where useful: `surface` (`user_prompt`, `tool_input`,
`tool_result`, `mcp_tool_description`, `model_output`), `tool`, `user_task`, `injected`,
and for the generated matrix `seed_id` / `transform` / `seed_text`.

## Files and counts

Total **1194 rows** — **684 attack / 510 benign** — unique ids, schema-validated, 0 errors.

### `public/` — vendored subsets of permissive public datasets
| file | rows | attack | benign | source · licence |
|---|--:|--:|--:|---|
| `deepset_prompt_injections.jsonl` | 150 | 75 | 75 | deepset/prompt-injections @4f61ecb · Apache-2.0 |
| `lakera_gandalf.jsonl` | 150 | 150 | 0 | Lakera/gandalf_ignore_instructions @04737b6 · MIT |
| `jailbreakbench_behaviors.jsonl` | 200 | 100 | 100 | JailbreakBench/JBB-Behaviors @886acc3 · MIT |
| `xstest_safe.jsonl` | 200 | 0 | 200 | paul-rottger/xstest · CC-BY-4.0 (attribution) |
| `indirect_injections.jsonl` | 65 | 45 | 20 | BIPIA + InjecAgent attack strings in Aegis carriers · MIT |

### `handwritten/` — Aegis-original
| file | rows | attack | benign | purpose |
|---|--:|--:|--:|---|
| `polish_multilingual.jsonl` | 83 | 49 | 34 | 42 PL attacks (incl. no-diacritics twins) + 30 PL benign + DE/UK/RU seeds |
| `finance_benign.jsonl` | 42 | 0 | 42 | finance jargon naive filters over-block ("kill switch", "execute the order", "liquidate", "short the position", "attack surface review", "egzekucja zlecenia") |
| `agentic_tools.jsonl` | 51 | 39 | 12 | dangerous commands, MCP tool-poisoning descriptions, markdown/HTML image exfil, base64 / unicode-tag / zero-width / emoji-varsel smuggling, spend & data-access requests, with benign twins |

### `generated/` — Aegis-original
| file | rows | attack | benign | purpose |
|---|--:|--:|--:|---|
| `obfuscation_matrix.jsonl` | 253 | 226 | 27 | seeds × transforms metamorphic set (base64, rot13, leetspeak, homoglyph, zero-width, unicode-tags, spacing, dotting, case, payload-split, diacritics-strip) → the attack×transform heatmap |

### By top-level category
| category | attack | benign |
|---|--:|--:|
| direct_injection | 238 | 0 |
| obfuscated (+ obfuscated_benign) | 232 | 27 |
| exaggerated_safety (XSTest) | 0 | 200 |
| harmful (JBB goals) | 103 | 0 |
| benign_lookalike (JBB benign twins) | 0 | 100 |
| benign_general / benign | 0 | 109 |
| indirect_injection | 48 | 0 |
| benign_finance | 0 | 42 |
| benign_tool_result | 0 | 20 |
| agentic (cmd/data/spend/ssrf) | 24 | 0 |
| jailbreak | 21 | 0 |
| benign_agentic | 0 | 12 |
| exfil | 7 | 0 |
| mcp.tool_poisoning | 7 | 0 |
| system_prompt_leak | 4 | 0 |

### By language
| lang | attack | benign |
|---|--:|--:|
| en | 537 | 427 |
| pl | 114 | 49 |
| de | 29 | 32 |
| uk | 2 | 1 |
| ru | 2 | 1 |

## Regenerating

Nothing here touches project dependency manifests — all tooling is ephemeral.

```bash
# public subsets (downloads pinned upstream files, samples with fixed seed, writes MANIFEST)
uv run --python 3.13 --with pandas --with pyarrow \
  python aegis/staging/corpora/build_public.py          # writes public/ + MANIFEST.public.json

# obfuscation matrix (stdlib only)
python3 aegis/staging/corpora/obfuscate.py               # writes generated/obfuscation_matrix.jsonl
python3 aegis/staging/corpora/obfuscate.py --demo "Ignore all previous instructions"
```

`obfuscate.py` is also importable by the test suite: `from obfuscate import TRANSFORMS, apply,
build_matrix`. The metamorphic property it encodes: if seed *S* is blocked, every `T(S)` must be
blocked too; for benign seeds only meaning-preserving transforms are applied and must still be
allowed (false-positive guard).

## Licences
See [`LICENSES.md`](LICENSES.md) and [`licenses/`](licenses/) for full upstream texts and
attribution. Only permissive/ungated sources are vendored; prompts/behaviours only, never model
completions. All identifier-shaped values are synthetic or published test values.
