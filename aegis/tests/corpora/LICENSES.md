# Corpora licences and attribution

All upstream sources below were re-verified live on **2026-10-03** via the Hugging Face Hub API
(`/api/datasets/...`) and the GitHub API (`gh api repos/...`). Only **permissive / ungated**
sources are vendored here. Full upstream licence texts are in [`licenses/`](licenses/).
Per-file SHA-256 of every upstream artifact and every generated subset is recorded in
[`MANIFEST.json`](MANIFEST.json) (upstream pins under `upstream`).

We vendor **prompt / behaviour strings only** — never model completions, and never harmful
answer text. JailbreakBench "harmful" rows are the *goal* strings (the thing to refuse), used
as attacks the guardrail must block.

## Vendored public subsets (`public/`)

| Subset file | Upstream | Revision (pin) | Licence | Attribution / notes |
|---|---|---|---|---|
| `deepset_prompt_injections.jsonl` | [deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections) | `4f61ecb` | **Apache-2.0** | deepset GmbH. Direct injections, EN+DE, label 1/0. |
| `lakera_gandalf.jsonl` | [Lakera/gandalf_ignore_instructions](https://huggingface.co/datasets/Lakera/gandalf_ignore_instructions) | `04737b6` | **MIT** | © 2023 Lakera AI. Real Gandalf player attempts. Cite: Pfister et al., *Gandalf the Red* (arXiv:2501.07927). |
| `jailbreakbench_behaviors.jsonl` | [JailbreakBench/JBB-Behaviors](https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors) | `886acc3` | **MIT** | © 2023 JailbreakBench Team. 100 harmful + 100 matched benign behaviour goal strings. |
| `xstest_safe.jsonl` | [paul-rottger/xstest](https://github.com/paul-rottger/xstest) | `main` (2025-02-24) | **CC-BY-4.0** | **Attribution required** — Röttger et al., *XSTest: A Test Suite for Identifying Exaggerated Safety Behaviours in LLMs*, NAACL 2024. Safe prompts only, used as the false-positive wall. |
| `indirect_injections.jsonl` | [microsoft/BIPIA](https://github.com/microsoft/BIPIA) + [uiuc-kang-lab/InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent) | `main` | **MIT** (both) | BIPIA: © Microsoft (licence file is indented so GitHub shows NOASSERTION; read by hand → MIT). InjecAgent: © 2023 Qiusi Zhan. We embed the upstream **attack strings** in our *own* carrier contexts (email/web/table/doc/RAG) and reuse InjecAgent tool-response templates; benign filler text is Aegis-original. |

### Licence-class policy applied (from research 05 §3.1)
- **MIT / Apache-2.0 / BSD** → vendor small subsets + keep upstream licence text in `licenses/`.
- **CC-BY-4.0** → vendor with attribution (XSTest above; attribution also belongs in the HTML eval report).
- **CC-BY-SA-4.0** (e.g. NASK-PIB/PL-Guard), **CC-BY-NC**, gated, or **no-licence** (MCPTox, Tensor Trust, PINT dataset) → **not vendored**. Download-on-demand or cite-only; techniques are re-implemented in our own words under `handwritten/` and `generated/`.

## Hand-written sets (`handwritten/`) — Aegis-original

`polish_multilingual.jsonl`, `finance_benign.jsonl`, `agentic_tools.jsonl`.
Authored by us, so there is no third-party licence constraint. Released as **Aegis-original**
(treat as MIT alongside the repo). These exist because no permissively licensed Polish
injection set is public (PINT Polish is withheld, CyberSecEval MT has no Polish, PL-Guard is
CC-BY-SA safety data). MCP tool-poisoning, EchoLeak-style markdown-image exfil and
smuggling cases are re-implementations of publicly described *techniques* (Invariant Labs,
embracethered.com ASCII Smuggler, Paul Butler emoji variation-selector smuggling,
postmark-mcp BCC backdoor) — techniques are not copyrightable; we wrote all strings.

## Generated set (`generated/`) — Aegis-original

`obfuscation_matrix.jsonl` is produced by `obfuscate.py` from 20 attack + 8 benign seeds.
All seed text and transform code is Aegis-original (`licence: Aegis-original`).

## Fixture values
All PESEL/NIP/REGON/IBAN/card/key-shaped values appearing in any case are **synthetic or
published test values** (card-network test PANs, checksum-valid example PESEL, reserved
`.test` / `.example` domains, `203.0.113.0/24` TEST-NET). No real personal data or live
secrets are included.
