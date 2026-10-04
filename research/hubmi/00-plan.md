# 00: HubMI.pl research synthesis and build plan

Written Sun 4 Oct 2026, 06:45 CEST. The deadline is **11:00 CEST** on HackTribe, in Polish. This plan **proposes**; everything
marked **[DECIDE]** is the user's call (product, naming, stack, repo/IP, scope).

Track reports: [01 ROPS ecosystem](01-rops-ecosystem.md) · [02 data](02-data-sources.md) · [03 prior art](03-prior-art.md) ·
[04 architecture/AI/cost](04-architecture-ai-cost.md) · [05 accessibility/UX](05-accessibility-ux.md) ·
[06 rules/scoring/submission](06-rules-scoring-submission.md) · [07 competitors](07-competitors.md) ·
digest of all tasks: [../hackyeah-2026-all-tasks.md](../hackyeah-2026-all-tasks.md)

---

## 0. Situation (read this first)

- **We start ~16 h behind a crowded field.** There are at least **14 public competitor repos**, and at least 9 claim all 7 modules.
  The leaders have live demos, real ROPS data with verbatim citations, published hit@3 evals (94%) and axe reports with 0
  violations (07 §1). "Seven modules plus AI matching" is now **table stakes**, not a differentiator.
- **What still wins points for us:** the scoring is breadth-weighted (all 7 modules = 40%, 06 §2), and there is **real white space**
  that the ROPS jury will recognise as "their own" pipeline: **Usługa Wrażliwa**, the **IWS 2.0 Karta oceny** and **gmina context**
  (07 §3).
- **Opportunity cost:** the Aegis (Goldman) and Aegis Pocket (Huawei) uploads are targeted for 10:00 (SUBMISSION.md). HubMI
  must not put them at risk. **[DECIDE] go / no-go.**

## 1. Scoring → scope

| Criterion | Wt | How we earn it |
|---|---|---|
| Challenge fulfilment | 40 | All 7 modules working. Matchmaking is deep, the rest are thin but real (persisted, visible to the admin) |
| Implementation potential | 20 | EU hosting, one DB, swappable LLM (Bielik/PLLuM-ready), cost table, Usługa Wrażliwa and Witkac-export integration story |
| Accessibility and intuitiveness | 20 | WCAG 2.1 AA shell, senior-first spoken flow, a native "Ustawienia wyświetlania" control, an axe report, deklaracja dostępności |
| UI originality | 10 | A distinctive identity, the spoken loop, the printable "kartka" |
| Materials and MVP | 10 | Live URL, 10-slide PDF, ≤3-minute mp4, mockups from real screens, cost table |

## 2. Positioning (proposal) [DECIDE]

**"Od potrzeby do wdrożenia w Twojej gminie."** Most rivals stop at "here are matching innovations". We take the match all the
way into **ROPS's own implementation and funding pipeline**:

1. **Senior-first, spoken intake.** Big microphone, one question at a time read aloud (pl-PL TTS), results read aloud, and an
   equal text path. Includes **"Pomagam komuś"** (a carer or social worker reports on someone's behalf) and **"Wydrukuj kartkę"**
   (a one-page print view). Rivals have voice *input*; nobody has the loop or proxy mode (07 §3).
2. **Matchmaking on real ROPS data:** 115 Biblioteka cards, CC BY 4.0, credited and linked. Hybrid retrieval, an **ID guard**
   (the LLM can only pick from retrieved IDs), "Dlaczego pasuje" with matched terms, and a **"Dlaczego to ważne u Ciebie"** strip
   of gmina/powiat indicators (GUS BDL, labelled with source and year).
3. **Pośrednik → Usługa Wrażliwa.** The middleman's service card separates the **core that must stay** from the **elements to
   adapt** (the EU SI+ transfer method, 03 §TL;DR-4). It then runs a **readiness check for Usługa Wrażliwa** (path A grant ≤600k zł
   / path B advisory) with next steps. **Nobody has this** (07 §3).
4. **Kreator → IWS 2.0 pre-score.** The idea card and canvas (built from IWS 2.0 form sections 3–8) get an AI score per criterion
   on the **official Karta oceny** (5 × 0–10), with the **thresholds enforced in code** (sum ≥21, innowacyjność ≥5, the others ≥4).
   The result is "przeszłoby / nie przeszłoby — popraw X". The grant draft is in the IWS 2.0 form structure. This is mostly open (07 §3).
5. **Loop closure for ROPS.** Unmatched needs feed the admin's trends and gaps view, which is table stakes, so we keep it thin.

Label every AI output as AI with a human fallback ("Zapytaj pracownika ROPS"), as the AI Act Art. 50 requires (04, 05).

## 3. Modules → minimal working version

| # | Module | Must work in the demo | Extra if time |
|---|---|---|---|
| I | Matchmaking | Text/voice → structured chips (editable) → top 5 with explanation and ROPS link → next-step buttons | Read-aloud loop, proxy mode, print card |
| II | Knowledge store | Library list and detail (filters, YouTube with captions, CC BY credit), challenges (Mapa areas) as a table, powiat indicators table | Map with a table alternative |
| III | Idea creator | Fiszka form → canvas → **IWS 2.0 pre-score** → grant draft (during a DEMO call) | DOCX export |
| IV | Tester | "Zgłoś się do testów", 1–5 rating and feedback on a card, aggregate on the card, visible to the admin | — |
| V | Communication | Thread per report/idea; new item → **admin bell + e-mail log**; admin reply → **author notified** | Mentor assignment |
| VI | Admin panel | Inbox (status nowe / w weryfikacji / opublikowane), edit and publish a library entry, trends by area and powiat (chart + table) | Gap list |
| VII | Middleman | Innovation × institution profile → service card (core vs adapt, steps, costs, KPIs) → **Usługa Wrażliwa check** | Print/export |

## 4. Stack (from 04) [DECIDE]

**Recommended:** Next.js (App Router, TS) + Vercel AI SDK on **Vercel `fra1`**, **Vercel AI Gateway** (OIDC, no API keys),
**Neon Postgres (Frankfurt)** via `vercel integration add neon`, shadcn/Radix with the 05 palette fixes (borders ≥#767676).
- LLM: `anthropic/claude-haiku-4.5` for structuring and rerank, `anthropic/claude-sonnet-5.5` for generation (middleman,
  pre-score, grant draft).
- Embeddings: `alibaba/qwen3-embedding-8b` (best PIRB among Gateway models, open-weight), precomputed at build time into JSON
  for an in-memory search over 115 items, with **MiniSearch BM25** and RRF fusion.
- **Keyless fallback:** BM25 plus tags with deterministic explanations, and templates instead of generation.
- **Human-only setup steps (first 10 minutes):** enable AI Gateway on the Vercel team. Free credits may need a card on file;
  buy $10–20 if Sonnet isn't in the free tier, since expected spend is under $5. Run `vercel integration add neon`, which means
  accepting Neon's terms. The agent must not add cards or accept terms.

## 5. Data (from 01/02)

| File | What | Use |
|---|---|---|
| `data/innovations.json` | 115 real ROPS Biblioteka entries; summaries paraphrased by AI and **not yet reviewed**; organisations only, no personal names | Library, matchmaking corpus |
| `data/innovations_rops_sections.json` | Original sections for 100 CC BY 4.0 entries | Retrieval text, quotes |
| `rops-biblioteka-innowacji.json` | Raw scrape (115, incl. video/ZIP links, "wybrana do upowszechniania") | Video embeds, evidence badge |
| `data/challenges.json` | 8 Mapa Wyzwań areas (national data) plus a regional record | Knowledge store, area taxonomy |
| `data/powiaty_indicators.csv` | 12 GUS BDL indicators × 22 powiats (mostly 2025) | "Ważne u Ciebie" strip, trends |
| `data/teryt_malopolska.csv` | 299 units with population and 65+ share (183 vs 182 gminas, verify) | Gmina picker |
| `data/synthetic_problems.json` | 25 **SYNTHETIC** reports with expected tags | Demo inputs and the **hit@3 eval** |
| `data/institutions.json` | 19 institutions, partial | Middleman profiles |

Gaps: weak coverage for poverty, depopulation, labour market and homelessness. **Say so honestly** in the UI ("brak dobrego
dopasowania → zgłoś pomysł"). The backup corpus is innowacjespoleczne.pl (~1 200, Excel export), but that is post-MVP.

## 6. Build timeline (if go)

| CEST | Work | Who |
|---|---|---|
| 06:50–07:05 | Decisions (§7). New repo. Vercel project, AI Gateway and Neon | **User** |
| 07:00–07:20 | Scaffold Next.js plus the a11y shell (lang=pl, skip link, landmarks, display settings, footer with deklaracja). Seed import. Build-time embeddings | Agent |
| 07:20–08:10 | **Module I** end to end, plus voice in/out, the ID guard and PII mask. hit@3 eval script on the 25 synthetic reports | Agent |
| 08:10–09:20 | Modules VII (+UW), III (+IWS pre-score), II, IV, V, VI, thin and parallelisable by route folder | Agent (2–3 subagents) |
| 09:20–09:40 | Deploy to prod, axe/Lighthouse run on 5 screens, fixes | Agent |
| 09:40–10:00 | **Aegis and Aegis Pocket HackTribe uploads** (SUBMISSION.md) | **User** |
| 10:00–10:35 | Polish materials: screenshots as mockups, 10-slide PDF, cost table (04 §6), deklaracja page. **Record the ≤3-minute mp4** | Agent plus **user (video)** |
| 10:35–10:50 | HubMI upload on HackTribe. Buffer | **User** |

**Cut order if late:** extras column first, then voice read-aloud loop polish, then the map, then the DOCX export. **Never drop a
whole module.** If AI Gateway is blocked, switch to the keyless fallback immediately; don't debug billing past 10 minutes.

## 7. Decisions

**Locked by the user at 06:50:** go, but plan first and don't build yet · positioning §2 "Need → wdrożenie" · name **Iskra** ·
**new private repo**. The detailed, verifiable task plan is in **[08-iskra-task-plan.md](08-iskra-task-plan.md)**. Its open items
D1–D7 are listed there.

Original decision list, kept for the record:

1. **Go / no-go** on HubMI, given the field (07) and the 10:00 Aegis uploads.
2. **Name.** Taken (avoid): Już Działa, Wici, HugMe, Splot, Szczep, Zaczyn, MHIS, MiNNO, HubMI, Aikonik, MaloHUB, Kraków Społeczny,
   "Pośrednik innowacji", "białe plamy". Ideas: *Most* / *Most Innowacji*, *Łącznik*, *Iskra*, *Kompas Innowacji*, *Przystań*.
3. **Positioning:** take §2 ("from need to implementation in your gmina": spoken senior intake + Usługa Wrażliwa + IWS 2.0
   pre-score) or choose another emphasis.
4. **Repo:** a new separate repo (recommended; this repo is the public Huawei entry). Choose its **visibility and licence**.
   Winners must assign copyright to the organiser and warrant the work is unpublished except for evaluation (06 §1). We should also
   move `research/hubmi/` there and give it its own `AI_WORKFLOW`/AI disclosure.
5. **Stack and accounts:** approve §4, enable AI Gateway (plus credits if needed) and Neon on your Vercel account.
6. **Who records the video** and narrates in Polish (the rules require a Polish pitch and materials).

## 8. Open verification items (carried from tracks)

- PDF **and** video, or either? (RULES vs DETAILS). Default: both.
- Whether Sonnet 5.5 is in the free AI Gateway tier. The UW path A cap (≤600k zł) and current call status, from the ROPS site.
- How numeric Już Działa's IWS self-assessment is (07 rec. 2), before claiming uniqueness on stage.
- The 15 non-CC-BY library entries: show them with a link only, or exclude them.
