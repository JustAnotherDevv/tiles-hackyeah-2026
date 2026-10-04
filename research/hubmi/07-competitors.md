# 07: Competitor scan, HubMI.pl track (HackYeah 2026)

**Snapshot:** Sun 4 Oct 2026, about 07:10 CEST. The scan covers 14 public repos: README files, repo trees, `.env.example`/`package.json`, and the
landing pages of the live demos. Most repos were still being pushed overnight (Wici last pushed at 06:30 CEST, Zaczyn at 06:20), so the
claims may change before 11:00. A row is marked "claimed" when only the README says it. Nothing was run or logged into.

## 1. TL;DR

- **The field is crowded and mature.** At least 9 of the 14 teams claim all 7 modules. Every team uses the same backbone: a text box
  ("opisz problem własnymi słowami"), then ranked innovations with a "dlaczego pasuje" reason, then a case or thread with ROPS, then an
  admin panel with trends. Breadth will not differentiate anyone.
- **Dominant approaches.**
  - Matching is hybrid: a lexical engine (BM25, TF-IDF or Polish stemming) plus an LLM rerank or explanation, behind a
    no-hallucination guard where the model may only show IDs returned by the search.
  - Personal data (PESEL, phone) is masked before the LLM sees the text.
  - Every team has an A+ text size and contrast toggle, and most have an ETR/easy-read mode.
  - Claude and Groq are the most common models. Next.js and FastAPI are the most common stacks.
  - The strongest teams publish matching evaluations (hit@3) and axe-core results.
- **The 5 most serious competitors:**
  1. **Już Działa** ([Flychuban/juz-dziala](https://github.com/Flychuban/juz-dziala)). Live demo, 114 real ROPS cards, server-verified
     verbatim quotes with source and date, published eval (top-3 = 94%), axe 0 violations on 19 screens, easy-read and PJM pages,
     GUS data for each gmina, Claude. This is the benchmark.
  2. **Wici** ([JohnnyArachnid/hackyeah-2026-hubmi](https://github.com/JohnnyArachnid/hackyeah-2026-hubmi)). The deepest build: 115
     real ROPS innovations, **real Obserwator indicators (9 × 22 powiaty)**, a cost calculator in code, a duplicate check, the INNO AGH
     canvas, a grant generator validated against the ROPS form, and Claude via LiteLLM, MCP and Langfuse. There is **no public demo yet**
     (phase F8 "planned").
  3. **HugMe** ([TomaszWu14/hugme](https://github.com/TomaszWu14/hugme)). A solo build with 211 tests and a 136/136-view axe audit
     gated in CI. It works without JS, has a deep pilot vertical (families of people with Down syndrome), and uses Claude Haiku
     optionally. The data is fictional. The demo returned 503 when we checked.
  4. **Splot** ([Defozo/splot-hubmi](https://github.com/Defozo/splot-hubmi)). Live demo plus PDF, PPTX and film, 115 domain tests and 22
     E2E tests tied to the build, Convex, Groq and OpenAI. All data is synthetic.
  5. **Szczep** ([szczygi77/hackyeah26](https://github.com/szczygi77/hackyeah26)). Live demo. Its distinctive feature is the
     **"Sprawdzenie warunków" transfer checklist** (macie / brakuje / do ustalenia) and **evidence levels E0–E2** on each card.
  - *Watch also:* **Zaczyn** ([hubertmalkowski/hubmi](https://github.com/hubertmalkowski/hubmi)), which has Elasticsearch hybrid
    search, PL/EN/UK, and crisis numbers, but no demo and fictional data. **Hubmi/MiNNO** ([nikiwiii/hubmi](https://github.com/nikiwiii/hubmi))
    makes big claims (17 indicators, kartogramy, "WCAG 2.2 AAA" lab), but has no demo, Windows `file:///` links and test credentials in
    the README.

## 2. Matrix (one row per repo)

Module key: I matchmaking · II knowledge store/trends · III idea creator/grant/canvas · IV tester · V communication · VI admin · VII Middleman.

| # | Team / brand | Stack | Modules | AI / models | Data | Accessibility claims | Demo | Notable / unique |
|---|---|---|---|---|---|---|---|---|
| 1 | **Już Działa** ([repo](https://github.com/Flychuban/juz-dziala)) | Next.js 15, tRPC, Drizzle, Neon PG, Vercel fra1, shadcn | I–VII | Claude (cost logged per call); keyword match + AI verification | **Real**: 114 ROPS cards with licences, Mapa Wyzwań, IWS 2.0 and "Usługa Wrażliwa" docs, INNO AGH canvas, GUS BDL by gmina, PRG borders; sha256 manifest | WCAG 2.1 AA, 18 px base, A+/A−, contrast, TTS, voice input, **one question per screen**, no resident accounts, map always with table, deklaracja, easy-read, **PJM page**; axe 0 violations, 19 screens × 2 viewports, 320 px | **Y** [juz-dziala.vercel.app](https://juz-dziala.vercel.app) | Server rejects quotes not found in the card; "nie wiem" means hand-off to an expert; published eval (top-3 83%→94%); "białe plamy"; self-assessment against 5 IWS 2.0 criteria; "Ramowy Plan Wdrożenia" for each gmina |
| 2 | **Wici** ([repo](https://github.com/JohnnyArachnid/hackyeah-2026-hubmi)) | FastAPI, React/Vite, Postgres, FastMCP, LiteLLM, Langfuse, Mailpit, Docker | I–VII, each page labelled with its module number | Claude via LiteLLM (GPT/Ollama qwen3 for comparisons); read-only MCP server | **Real**: 115 ROPS innovations verbatim, **Obserwator 9 indicators × 22 powiaty**, 8 Mapa Wyzwań areas, 3 ROPS publications, ISAP laws; fictional people and needs | Toolbar, "Wyjaśnij prościej" (AI ETR), read aloud, voice input, high contrast | **N** (localhost; F8 "planned") | All numbers come from a code calculator (cost profile × answers) and the LLM only describes; duplicate check; advisory assessment on **5 InnMałopolska 2019 criteria** (qualitative, not IWS 2.0 points); grant generator validates sums and period limits; idea poster as safe SVG; "Dla Ciebie" compares the powiat with the regional median; eval hit@1 19/20 |
| 3 | **HugMe** ([repo](https://github.com/TomaszWu14/hugme)) | Flask, Jinja, SQLite, **no JS framework**, Docker/Coolify | I–VII + "Razem z ZD", "Jestem potrzebny", "Praca" | Claude Haiku **optional**; BM25 + stemming + concept dictionary does the matching | Fictional ("PRZYKŁAD"); real ROPS import via CSV/JSON; real data only in "Praca" | **136/136 views axe-clean**, CI-gated, A+ and HC without JS, 44 px targets, easy text with pictures | **Y** [hugme.twapp.pl](https://hugme.twapp.pl) (503 at 07:05) | Deep vertical for families of people with Down syndrome; 211 tests; AI output always labelled, JSON validated against a schema; prompt-injection delimiters; `/admin/luki` (gaps) and powiat × area trends map |
| 4 | **Splot dla HubMI** ([repo](https://github.com/Defozo/splot-hubmi)) | React/Vite + Convex (DB and hosting), Playwright | I–VII ("Siedem modułów") | Groq + OpenAI (server-side) | **Synthetic**: 22 materials, 3 fictional indicators | `test:a11y`; WebVTT captions; explicitly "not a WCAG declaration" | **Y** [convex.site](https://agile-kiwi-698.eu-west-1.convex.site) + PDF, PPTX, film | 115/115 domain tests and 22/22 E2E bound to a build hash; partnerships, resource offers, pilot evaluation; 4 role logins |
| 5 | **Szczep** ([repo](https://github.com/szczygi77/hackyeah26)) | Next.js 15, Prisma, Supabase (pgvector), Playwright | I–VII | Optional OpenAI / Groq / Anthropic; template mode without keys; daily LLM cap | Declared **synthetic** (landing shows ROPS-like cards) | A11yDock (text size, contrast, "prosty język"), a11y smoke tests | **Y** [szczep.vercel.app](https://szczep.vercel.app) | **"Sprawdzenie warunków"**: what the innovation needed vs what you have (have / missing / to confirm); **evidence levels E0–E2**; gaps feed the admin view; CSV export |
| 6 | **Zaczyn** ([repo](https://github.com/hubertmalkowski/hubmi)) | SvelteKit, Drizzle/Postgres, Elasticsearch (Polish lemmatiser), shadcn-svelte | I–VII | "Jev" classifier (typesafe), Claude (explanations), Voyage embeddings; BM25 + kNN fused by RRF; `AI_MOCK` | **Fictional** 30 innovations; real TERYT and PRG | Larger text, contrast, easy-read, TTS, voice input; **PL/EN/UK UI**; Playwright + axe | **N** | Unmatched need becomes an **open challenge** for NGOs and gminy; place name in text sets the gmina; moderation; **crisis numbers 112 / 116 123 / 116 111**; eval hit@k and MRR |
| 7 | **MHIS** ([repo](https://github.com/Drop-the-Base/malopolski-hub-2026)) | FastAPI, SQLite, React 18/Vite, Docker | I–VII + JST challenge register | Groq LLM, **Whisper** voice, TF-IDF; template mode | 10 ROPS-based cards (demo), 22 powiaty | WCAG 2.1 AA target: 2 HC modes, 125/150% text, **ETR on by default**, read page, deklaracja | **N** (Docker) | **SUS questionnaire** in the tester; Middleman drafts a **resolution (uchwała) for the gmina**; mentor booking with `.ics`; PII filter |
| 8 | **Hubmi (MiNNO)** ([repo](https://github.com/nikiwiii/hubmi)) | Next.js 16 + FastAPI + Supabase pgvector; Expo mobile | I–VII (claimed) | Groq Llama 3.3 70B / Qwen; MiniLM embeddings; AI image generation | 115 innovations + **17 GUS/ROPS indicators × 22 powiaty, 2014–2024** (claimed) | Claims "WCAG 2.2 AAA"; colour-blindness, cataract and glaucoma **simulators**; contrast checker | **N** | SVG powiat kartogramy plus an indicator RAG; Middleman "Refine with AI"; TCO with on-prem Bielik; README has test credentials and `file:///c:/Users/...` links |
| 9 | **HubMI** ([repo](https://github.com/Majkelll/hubmi), README in `hubmi/`) | .NET 10 (MediatR, EF Core, Postgres), React/Vite, Playwright | I–VII | **No LLM** (TF-IDF + optional Jev classifier; LLM assistant "Z3.10" not done) | Invented | E2E accessibility spec; no README claims | **Y** [hubmi.onrender.com](https://hubmi.onrender.com) | Clean modular backend, an E2E spec for each module; weak on "AI platform" |
| 10 | **MaloHUB** ([repo](https://github.com/ofideveloper/hackyeah-2026-hubmi)) | Next.js PWA (BFF) + FastAPI/SQLModel, Vercel | I–VII | Any OpenAI-compatible model (OpenAI, OpenRouter, DeepSeek) | ROPS library (`innovation_library.json`, scraped on startup) | WCAG 2.1 AA aim, axe audit doc, reduced motion | **Y** [vercel.app](https://hackyeah-2026-hubmi.vercel.app) | "Opiekun AI" chat with 3 verdicts (match / clarify / not in base) checked by ID; **Middleman is a ROPS-staff tool**; PWA; cost section still "do uzupełnienia" |
| 11 | **Aikonik / "Kraków Społeczny"** ([repo](https://github.com/michalwilk123/aikonik)) | Next.js 16 on Cloudflare Workers, D1, Drizzle, Payload CMS, Resend | I, II, III (grant calls), IV, V, VI; VII unclear | OpenRouter, **Gemini 3.1 Flash Lite**, four-agent streaming chat | 115 ROPS snapshot + ROPS 2024/25 report facts | Not stated | **Y** [workers.dev](https://aikonik.michalwilk139.workers.dev) | Staff case assignment, private notes, single-use magic links for residents, grant generator open only inside the call window |
| 12 | **hubmi.pl** ([repo](https://github.com/MasterSun8/hubmi.pl)) | Next.js 16, Drizzle, OpenAI SDK | I; tree shows admin, nabory, canvas, needs map, reports (README roadmap says admin is unfinished) | OpenAI chat + embeddings (RAG) | Unknown; **Obserwator scraper** in tree | A/A+/A++, HC, "for seniors" | **N** | Two paths, "Zgłoś problem" and "Zaoferuj pomoc"; needs heatmap by powiat and gmina; risk-assessment prompt |
| 13 | **hubmi-app** ([repo](https://github.com/RafixoUwU/hubmi-app)) | Expo / React Native (README is the Expo template) | Nominally I–VII under `innovation/` inside a broad civic app | Gemini / OpenAI with **client-side `EXPO_PUBLIC_` keys** | Unknown; Katowice/Silesia APIs (smog, weather, parking) | civic/accessibility screen | **N** | Kitchen-sink app (blood, carpool, timebank, silent SOS) that is off-focus for ROPS |
| 14 | **HUBMI confidence team** ([repo](https://github.com/Wojciech151218/HUBMI-confidence-team)) | Next.js, TypeORM, Postgres pgvector, Docker | I (search), II (markdown KB), VI (no auth) | OpenAI `text-embedding-3-small` or local hashed embeddings | Own markdown seed | None | **N** | Initiative voting; admin panel has no authentication. Not a threat |

## 3. Common patterns and white space

**What everyone does (table stakes, not differentiators):**
- A free-text problem box, top-N innovations, and "dlaczego pasuje" explanations. Explainable matching is universal, and the top
  teams go further with verbatim quotes (Już Działa) or labelled keywords (Wici).
- A guard against hallucinated innovations (show only IDs from search, or "nie wiem" with hand-off to ROPS). PII masking before the
  LLM (at least 6 teams).
- A+/contrast toggle, skip link and focus rings. An ETR/easy-read mode appears in at least 6 teams. Voice input appears in at least 5
  (MHIS uses Whisper; Już Działa, Wici, Zaczyn and Hubmi/MiNNO use browser speech-to-text). Read-aloud appears in at least 4.
- Unmatched needs become trends or a gap list for the admin (HugMe `/admin/luki`, Już Działa "białe plamy", Szczep `gaps.ts`, Zaczyn open
  challenges, MaloHUB, Wici).
- A case or thread for each submission with notifications. A grant generator that is active only during an open call. A canvas.
  A Middleman "service card" (steps, resources, costs, risks, KPIs).
- An eval harness (hit@3) and axe/Playwright reports among the top 5.

**White space, judged against what we actually saw:**

| Candidate | Verdict | Evidence |
|---|---|---|
| Unmet needs / gap map | **Taken.** At least 5 teams have it. Worth having for module II/VI, but it won't stand out | HugMe, Już Działa, Szczep, Zaczyn, Wici |
| Voice-first senior UX | **Partly open.** Voice *input* is a commodity. Nobody builds a spoken loop (speak → AI asks one question aloud → answer read aloud → one big next step). Już Działa comes closest (one question per screen + TTS) | Voice-input components in 5 repos; no TTS-led flow seen |
| Real ROPS data with citations | **Taken by the leaders** (Już Działa quotes, Wici verbatim). **Still a must:** 5 teams use fictional or synthetic data (HugMe, Splot, Szczep, Zaczyn, HubMI) | — |
| AI pre-assessment on the **official IWS 2.0 Karta oceny** (5 × 0–10, max 50, pass ≥21, innowacyjność ≥5, others ≥4) | **Mostly open.** Wici uses the *2019 Rada* criteria with qualitative levels. Już Działa claims a "samoocena wg 5 kryteriów IWS 2.0" without visible numeric scoring or thresholds. Nobody shows "przeszłoby / nie przeszłoby i dlaczego" | `data/kryteria.yaml` (Wici); Już Działa README |
| **"Usługa Wrażliwa" implementation path** (Ścieżka A grant ≤600 000 zł / Ścieżka B advisory) | **Open.** Nobody turns the Middleman output into a Usługa Wrażliwa readiness check or route. Już Działa only lists the documentation as a source | No code or path hits in any tree |
| Gmina-level indicators from obserwator.rops.krakow.pl | **Partly open.** Wici pulls Obserwator data **at powiat level**. Już Działa uses **GUS BDL** by gmina. MasterSun8 has an Obserwator scraper (output unclear). Nobody shows the Obserwator "portret gminy" (ageing index, potencjał pielęgnacyjny) driving the match or the Middleman | `import_obserwator.py`, `fetch-gus.ts`, `obserwatorScraper.ts` |
| Explainable matching | **Taken** (universal) | — |
| Offline / low-literacy modes | Low literacy: **taken** (ETR, easy-read, pictograms in HugMe). Offline: **open but low value**, since the jury won't test it. Only MaloHUB is a PWA and only HugMe works without JS. A **printable one-page "kartka" for a senior or caregiver** wasn't seen | — |
| Other gaps we noticed | **Proxy mode** ("pomagam komuś": caregiver or social worker filling in on someone's behalf) isn't a first-class flow anywhere. **Phone/IVR channel**: nobody has one. **Side-by-side comparison of 2–3 innovations** exists only in Splot | — |

## 4. Names already taken (avoid collisions)

Brands: **Już Działa**, **Wici**, **HugMe**, **Splot / Splot dla HubMI**, **Szczep**, **Zaczyn**, **MHIS** (Małopolski Hub Innowacji
Społecznych), **Hubmi (MiNNO)**, **HubMI** (Majkelll), **Aikonik / Kraków Społeczny**, **MaloHUB**, **hubmi.pl**, **hubmi-app**,
**HUBMI confidence team**.

Module and feature names in use: "Pośrednik innowacji" (HugMe), "Towarzysz wdrożenia", "Warsztat pomysłów", "Skarbnica wiedzy",
"Dla Ciebie" (Wici), "Opiekun AI" (MaloHUB), "Sprawdzenie warunków" (Szczep), "Ramowy Plan Wdrożenia", "białe plamy" (Już Działa),
"Radar Trendów", "Rejestr wyzwań JST" (MHIS), "Laboratorium Dostępności" (MiNNO), "luki" (HugMe), "Jestem potrzebny", "Razem z ZD"
(HugMe).

Taglines and motifs: "Twój problem ktoś w Małopolsce już rozwiązał" (Już Działa); "Twój problem nie zostaje sam" (HugMe); "Mały krok.
Wspólna zmiana." (hubmi.pl); "dobre pomysły, które nie przepadają" (hubmi-app). Both Splot and HugMe use the **weaving/knot** motif and
both Szczep and Zaczyn use **growth/graft** metaphors. "Cyfrowe serce" (from the brief) is used by at least 3 teams.

## 5. Recommendations for a late entrant (about 3 h of build time)

The product decisions remain the user's. These are options ranked by differentiation per hour.

1. **Make "Usługa Wrażliwa" the Middleman's backbone (module VII + implementation potential, 20%).** After the service card, show
   "Czy to kwalifikuje się do Usługi Wrażliwej?" with a route to Ścieżka A (grant ≤600 000 zł) or Ścieżka B (advisory), a checklist
   of what the gmina must have, and the next step with the real ROPS contact. No competitor has this, and it shows the jury (ROPS)
   that we know their own funding pipeline.
2. **Pre-score ideas against the official IWS 2.0 Karta oceny (module III).** Five criteria at 0–10 each, an LLM rationale for each,
   and the **thresholds enforced in code** (sum ≥21, innowacyjność ≥5, others ≥4). The result is "przeszłoby / nie przeszłoby — popraw
   X". It is cheap to build (one structured LLM call plus deterministic rules) and is more official than Wici's 2019 criteria. Before
   claiming uniqueness, check how numeric Już Działa's self-assessment is.
3. **Senior-first spoken loop rather than "voice input too" (accessibility 20% + UI originality 10%).** A large microphone, a
   one-question-at-a-time interview read aloud in Polish (Web Speech TTS), results read aloud, and two big buttons: "Wydrukuj
   kartkę" (a print stylesheet one-pager) and "Pomagam komuś" (proxy mode for a caregiver or social worker). Keep the text path fully
   equal for WCAG. Voice input alone is already in 5 repos.
4. **Ground the result in the user's own gmina.** Pick a gmina, then show 2–3 Obserwator indicators on a "Dlaczego to ważne u Ciebie"
   strip that also feeds the Middleman. We already have `data/powiaty_indicators.csv`. If only powiat-level data is ready, label it
   honestly. Wici is powiat-level and Już Działa uses GUS, so a labelled, cited strip is enough to match them, and gmina level beats
   them.
5. **Don't skip the table stakes the leaders set:** real ROPS library cards with source links (we have
   `rops-biblioteka-innowacji.json`), a no-hallucination ID guard, PII masking, a published axe-core run (with numbers) and a small
   hit@3 eval, plus a **deployed URL, film and PDF** (materials, 10%; the top 4 of the 5 have a live demo). Keep modules II, IV, V
   and VI thin but working. Make no "WCAG 2.2 AAA" claims we can't back.
