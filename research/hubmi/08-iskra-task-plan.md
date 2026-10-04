# 08: Iskra build plan: tasks and verifiable atomic subtasks

**Status:** PLAN ONLY. Nothing is built yet (per user, Sun 4 Oct ~06:50 CEST). Deadline is **11:00 CEST** on HackTribe, in Polish.
Background and justification: [00-plan](00-plan.md) and tracks 01–07.

## Locked decisions (user, 06:50)

| Decision | Choice |
|---|---|
| Go / no-go | **Go**, but plan first. Do not build until the user says so |
| Positioning | **"Od potrzeby do wdrożenia w Twojej gminie"**: spoken senior-first intake → real ROPS matches → Middleman with **Usługa Wrażliwa** readiness → Kreator with **IWS 2.0** pre-score |
| Name | **Iskra**. No HubMI/HackYeah collision found on GitHub (07:00). Unrelated repos named "Iskra" exist |
| Repo | **New private repo**, separate from this public Huawei repo |

## Still open: needed before T+0 [DECIDE]

- [ ] **D1** GitHub owner for the private repo (`gh` is logged in as `LekondoDaniel`; git user is `JustAnotherDevv`).
- [ ] **D2** Vercel scope/team for the project (CLI user `justanotherdevv`).
- [ ] **D3** AI Gateway: free tier only, or add a card / buy $10–20 credits if Sonnet 5.5 isn't free. Only a human may add cards.
- [ ] **D4** Accept Neon terms via `vercel integration add neon` (human).
- [ ] **D5** Demo access: **open, with no login** and a visible "Tryb demo: wybierz rolę" role switcher (recommended), or a demo account.
- [ ] **D6** Who narrates and records the Polish video, plus HackTribe team ID and member list (never commit those).
- [ ] **D7** Lane parallelism: one agent working sequentially, or **4 subagents in git worktrees** after the foundation (recommended, §3).

---

## 1. Conventions

- **ID**: `P<phase>.<task>.<sub>`. **Owner**: `U` = user, `A` = agent. **Est.** = minutes. **Dep** = prerequisite IDs.
- **Verify** is the objective check that closes a subtask. If the check fails, the subtask stays open.
- **[CUT n]** marks something that can be dropped under time pressure; lower n is cut first. Anything unmarked is required for scoring.
- T+0 = start of build. If T+0 = 07:15, the gates fall at **G0 07:35 · G1 08:35 · G2 09:40 · G3 10:25 · G4 10:50**.

## 2. Architecture contract (fixed in Phase 1 so lanes don't collide)

**Stack:** Next.js (App Router, TS, pnpm) + Tailwind + shadcn/Radix. AI SDK (`ai`) with AI Gateway model strings (OIDC, no keys).
Drizzle + `@neondatabase/serverless`. MiniSearch, Zod, Vitest, Playwright + `@axe-core/playwright`. Functions run in `fra1`. All
dependencies are installed in Phase 1. **Lanes may not add dependencies.**

**Models:**
- `anthropic/claude-haiku-4.5`: structuring, rerank, "wyjaśnij prościej".
- `anthropic/claude-sonnet-5.5`: middleman, IWS pre-score, grant draft.
- `alibaba/qwen3-embedding-8b`: embeddings. Use a 1024-d output if supported; otherwise use the native dimension and record it in
  `data/corpus.meta.json`.
- All model ids live in `lib/ai/models.ts` and each can be overridden by an environment variable (the "Bielik/PLLuM-ready" story).

**Directory layout:**
```
app/(public)/page.tsx                    landing
app/(public)/zglos/…                     I   intake wizard + wyniki/[id] + wyniki/[id]/kartka (print)
app/(public)/biblioteka/…                II  library list + [id] detail (incl. IV tester widget)
app/(public)/wyzwania/page.tsx           II  Mapa areas + powiat indicators (table first)
app/(public)/wiedza/page.tsx             II  educational content (static MDX/TSX)
app/(public)/pomysl/…                    III fiszka → kanwa → ocena-iws → wniosek
app/(public)/wdrozenie/…                 VII Middleman Innowacji + Usługa Wrażliwa check
app/(public)/testuj/page.tsx             IV  innovations open for testing + my signups
app/(public)/wiadomosci/…                V   my threads + [id]
app/admin/…                              VI  inbox, trendy, luki, biblioteka/[id] edit, nabory, poczta (email log), testy, koszty-ai
app/(public)/dostepnosc|etr|pjm|o-projekcie   deklaracja, ETR page, PJM placeholder, AI and data disclosure
lib/ai/{models,gateway,prompts,schemas}.ts   lib/match/{redact,structure,retrieve,rerank,gap}.ts
lib/iws.ts  lib/uw.ts  lib/taxonomy.ts  lib/db/{schema,client,queries}.ts  lib/session.ts  lib/notify.ts
data/corpus.json  data/corpus.embedded.json  data/{teryt,powiaty,challenges,synthetic}.json
scripts/{build-corpus,embed,seed-db,eval-match,a11y-scan,shots}.ts
```

**DB tables (Drizzle, Neon Frankfurt):** `sessions`, `innovations` (seeded from the corpus, with embedding `real[]`, `status`, and
`edited_at`), `reports`, `ideas`, `calls`, `threads`, `messages`, `notifications`, `email_log`, `test_signups`, `ratings`,
`middleman_cards`, `ai_audit` (kind, model, tokens in/out, latency, created_at). Every user-generated row has a `synthetic boolean`
flag (true for seeded demo rows).

**Roles (demo, no auth):** a cookie holds `role ∈ {mieszkaniec, ngo, jst, ekspert, rops}` plus an anonymous `session_id`. A header
switcher reads "Tryb demo". `/admin` requires `role=rops`. **login.gov.pl appears only on the roadmap slide.**

**Taxonomy (`lib/taxonomy.ts`):** `obszar` = the 9 library categories (Dzieci, młodzież i rodzina · Seniorzy · Osoby z
niepełnosprawnością sensoryczną · Osoby o ograniczonej mobilności · Osoby z niepełnosprawnością intelektualną · Zdrowie i medycyna
· Cudzoziemcy · Rynek pracy · Osoby w kryzysie bezdomności) plus `Inne`, with a crosswalk to the 8 Mapa Wyzwań areas (01 report).
Match labels are **Bardzo pasuje / Pasuje / Może pasować**. No percentages (05 §3.3).

---

## Phase 0: preflight (T−15 → T+0)

| ID | Task | Owner | Est | Dep | Verify |
|---|---|---|---|---|---|
| P0.1 | Resolve D1–D7 | U | 5 | — | All boxes ticked in this file |
| P0.2 | Create the private repo `iskra` under D1; clone to `~/Development/hackathons/_october_2026/iskra` | U/A | 3 | P0.1 | `gh repo view <owner>/iskra --json visibility -q .visibility` → `PRIVATE` |
| P0.3 | Create the Vercel project, link it, set function region `fra1` | A | 3 | P0.2 | `vercel project ls` lists `iskra`; `vercel.json` has `"regions":["fra1"]` |
| P0.4 | Enable AI Gateway; add credits if D3 | U | 5 | P0.3 | Vercel dashboard → AI Gateway shows enabled; credit balance > 0 |
| P0.5 | `vercel integration add neon` (Frankfurt), then `vercel env pull .env.local` | U | 5 | P0.3 | `.env.local` contains `DATABASE_URL` and `VERCEL_OIDC_TOKEN` (check names only, never print values) |
| P0.6 | Copy `research/hubmi/` (docs + data) into the new repo `docs/research/`. Leave the copy here untouched | A | 2 | P0.2 | `ls iskra/docs/research/data/*.json` shows 7 files |

## Phase 1: foundation (T+0 → T+25) · Gate **G0**

| ID | Task | Owner | Est | Dep | Verify |
|---|---|---|---|---|---|
| P1.1 | Scaffold Next.js (TS, App Router, Tailwind, ESLint), pnpm, `.gitignore` (env, .vercel, node_modules, .next) | A | 4 | P0.2 | `pnpm build` passes; `git check-ignore .env.local` returns the path |
| P1.2 | Install **all** deps (ai, zod, drizzle-orm, drizzle-kit, @neondatabase/serverless, minisearch, shadcn primitives, vitest, playwright, @axe-core/playwright, tsx) | A | 4 | P1.1 | `pnpm ls --depth 0` lists each one; `pnpm build` passes |
| P1.3 | Design tokens from 05 §3.8 (text #1B1B1B, primary #0052A5, border #767676, focus ring, 18 px base, ≥44 px targets) in `globals.css`. Iskra wordmark (text plus a spark glyph, no gov.pl or herb) | A | 4 | P1.1 | Unit test: `contrast(token.fg, token.bg) ≥ 4.5` for text pairs, `≥ 3` for borders and focus |
| P1.4 | A11y shell: `<html lang="pl">`, skip link "Przejdź do treści głównej", header/nav/main/footer landmarks, one `<h1>`, route-change focus to `<h1>` plus `document.title`. Header has ETR/PJM entry points, the role switcher and the "Ustawienia wyświetlania" panel (A/A+/A++, high contrast, saved to localStorage in try/catch). Footer links to Deklaracja dostępności, O projekcie (AI disclosure), and the ROPS contact (institutional only) | A | 10 | P1.3 | Playwright: Tab #1 focuses the skip link; toggling A++ changes the root font size; axe on `/` shows 0 serious/critical |
| P1.5 | `lib/session.ts`: role and session cookie, `requireRole('rops')` | A | 3 | P1.1 | Vitest: unknown role → `mieszkaniec`; `/admin` with a non-rops role → redirect |
| P1.6 | `lib/db/schema.ts` with **all** tables from §2; `drizzle-kit push` to Neon | A | 6 | P0.5, P1.2 | `pnpm drizzle-kit push` exits 0; `select count(*) from information_schema.tables where table_schema='public'` ≥ 14 |
| P1.7 | `lib/ai/models.ts` and `gateway.ts`, plus `scripts/smoke-ai.ts` (one Haiku call in Polish, one embedding) | A | 4 | P0.4, P1.2 | `pnpm tsx scripts/smoke-ai.ts` prints Polish text and `dim=<n>` with n > 0. **G0 PASS** |
| P1.8 | **Fallback switch** `AI_MODE=off`: every AI call goes through `lib/ai/gateway.ts`, which returns a deterministic template when off | A | 3 | P1.7 | Vitest: with `AI_MODE=off`, `structure("…")` returns valid schema output with no network |
| P1.9 | First commit and push; first `vercel deploy` (preview) | A | 2 | P1.4 | Preview URL returns 200 with `lang="pl"` (`curl -s <url> \| grep 'lang="pl"'`) |

**G0 rule:** if P1.7 still fails at T+25, set `AI_MODE=off`, continue with BM25-only matching and templates, and tell the user.
**Do not debug billing for more than 10 minutes.**

## Phase 2: data (T+10 → T+35, runs in parallel with P1.4–P1.9)

| ID | Task | Owner | Est | Dep | Verify |
|---|---|---|---|---|---|
| P2.1 | `scripts/build-corpus.ts`: merge `innovations.json`, `innovations_rops_sections.json` and the raw scrape into `data/corpus.json`. Fields: id, title, summary, problem, targetGroups, obszar (taxonomy), type, evidence ("Rekomendowana do upowszechniania" if selected_for_scaling, else "Przetestowana w inkubatorze ROPS"), whoCanUse, the 5 ROPS sections, videoUrls, materialsZip, sourceUrl, licence, attribution "Źródło: ROPS Kraków, Biblioteka Innowacji Społecznych" | A | 8 | P0.6 | `jq length data/corpus.json` = **115**; each record has sourceUrl and licence; 0 records with `obszar` outside the taxonomy |
| P2.2 | **PII audit of the corpus**: regex for person-name patterns, phones and e-mails in all text fields; manual spot check of 10 random records | A | 4 | P2.1 | The script prints 0 phone/e-mail hits; the spot-check list is noted in `docs/data-audit.md` |
| P2.3 | Licence handling: the 15 entries without CC BY mark get `licence:"brak oznaczenia"` and show only title, summary and link (no long text) | A | 2 | P2.1 | Vitest: those 15 have no `sections` text exposed in the API payload |
| P2.4 | `scripts/embed.ts`: embed `title + summary + problem + targetGroups + keywords` → `data/corpus.embedded.json` and `corpus.meta.json` (model, dim, date) | A | 4 | P1.7, P2.1 | 115 vectors, all of the same dim, no NaN (script asserts). Skipped if `AI_MODE=off` |
| P2.5 | Convert `teryt_malopolska.csv`, `powiaty_indicators.csv` and `challenges.json` into typed JSON plus a Małopolska average row | A | 4 | P0.6 | `data/teryt.json` has 182–183 gminas; `powiaty.json` has 22 rows; the averages are computed |
| P2.6 | `scripts/seed-db.ts`: innovations (from the embedded corpus); one call "Nabór DEMO – Inkubator (IWS 2.0) – symulacja" (active); **25 synthetic reports** run through the real match pipeline (`synthetic=true`); 3 ideas; 6 ratings; 1 thread with an admin reply | A | 8 | P1.6, P2.4, P3.4 | Counts: innovations 115, reports ≥25 (all synthetic), calls 1 active. The admin trends page renders non-empty |

## Phase 3: Module I, matchmaking (T+25 → T+85) · Gate **G1**

| ID | Task | Owner | Est | Dep | Verify |
|---|---|---|---|---|---|
| P3.1 | `lib/match/redact.ts`: mask PESEL, phone, e-mail, IBAN and street-address patterns **before** any LLM call or DB write | A | 5 | P1.2 | Vitest: 8 fixtures, e.g. "PESEL 90010112345", "tel. 600 100 200" → masked; plain text unchanged |
| P3.2 | `lib/match/structure.ts`: Haiku `generateObject` with a Zod schema `{obszar (enum), grupa_docelowa[], slowa_kluczowe[] (lemmas plus synonyms), skala, podsumowanie, pytania? (≤2, each with ≤4 options plus "Nie wiem")}` | A | 8 | P1.7, P3.1 | Vitest (live, skipped when AI off): syn-001 → `obszar=Seniorzy`; schema-valid for 5 synthetic reports |
| P3.3 | `lib/match/retrieve.ts`: MiniSearch BM25 (title^3, keywords^2, summary, sections; `processTerm` lowercases, strips diacritics and takes a 6-char prefix; fuzzy 0.2) + cosine over embeddings + a tag-overlap boost → **RRF k=60** → top 10 | A | 12 | P2.4 | Vitest (offline): query "samotność seniorów na wsi" → top 10 includes ≥1 `obszar=Seniorzy`; `AI_MODE=off` path works on BM25 alone |
| P3.4 | `lib/match/rerank.ts`: Haiku `generateObject`. **The `id` field is a `z.enum(candidateIds)`** (the ID guard). Output per pick: label (Bardzo pasuje / Pasuje / Może pasować), `dlaczego` (≤2 plain bullets), `dopasowane_slowa[]`, `co_dostosowac` | A | 10 | P3.2, P3.3 | Vitest: a mocked LLM returning a non-candidate id → rejected by the schema; a live run returns only ids ⊂ candidates |
| P3.5 | `lib/match/gap.ts`: `luka=true` if there are no picks, or only "Może pasować" picks, or the fused score is below the threshold. Stored on the report | A | 3 | P3.4 | Vitest: an empty-picks fixture → `luka=true` |
| P3.6 | Server action `submitReport`: redact → structure → retrieve → rerank → save the report (structured, matched ids, luka, gmina, onBehalf, helperRole) → notify the admin (bell + `email_log`) → log `ai_audit` | A | 8 | P3.1–P3.5, P1.6 | Playwright: submit syn-003 text → redirected to `/zglos/wyniki/<id>`; DB has the report with ≥1 matched id; `notifications` has an admin row; `ai_audit` has ≥2 rows |
| P3.7 | `/zglos` wizard per 05 §3.3: **Krok 1 z 3** big textarea with hint and topic chips, mic button **only if** `SpeechRecognition` exists (pl-PL; transcript shown and editable; never auto-submit), gmina autocomplete (optional), **"Pomagam komuś"** toggle with a "Kim jesteś dla tej osoby?" select. **Krok 2** up to 2 AI questions as radio buttons with "Nie wiem / Pomiń". **Krok 3** results. "Wstecz" never loses input; the draft autosaves | A | 15 | P3.6 | Playwright: keyboard-only path completes Krok 1→3; Wstecz keeps text; mic button absent in Firefox UA emulation; axe 0 serious/critical |
| P3.8 | Results page: an `aria-live` status ("Szukam rozwiązań…" → "Gotowe. Znaleźliśmy N rozwiązań."), cards (title, 1-sentence summary, label, Dlaczego pasuje, evidence badge, source link), and per card **Przeczytaj na głos** (speechSynthesis pl-PL), **Wyjaśnij prościej** (Haiku, labelled "uproszczona wersja (AI)"), **Wdróż u siebie** → VII, and **Zapytaj pracownika ROPS** → V. An AI disclaimer. If luka: "Nic nie pasuje? Zgłoś pomysł" → III, prefilled | A | 12 | P3.6 | Playwright: the status region text equals "Gotowe…"; the read-aloud button calls `speechSynthesis.speak` (stubbed); the "Wyjaśnij prościej" response is labelled AI |
| P3.9 | **"Dlaczego to ważne u Ciebie"** strip: if a gmina is given, show 3 indicators (65+ share, old-age dependency, social-assistance beneficiaries per 10k) against the Małopolska average, with "Źródło: GUS BDL, rok 2025/2024" | A | 5 | P2.5, P3.8 | Playwright: with gmina Szczurowa the strip shows 3 numbers plus a source line; without a gmina it is hidden |
| P3.10 | **"Wydrukuj kartkę"**: `/zglos/wyniki/[id]/kartka` print stylesheet (A4, large type: summary, top 3, ROPS institutional contact, short URL) | A | 5 | P3.8 [CUT 3] | `playwright page.pdf()` produces a 1-page PDF; the text includes the top-1 title |
| P3.11 | **Spoken loop** ("Tryb głosowy"): after a user gesture, read the Krok 1 prompt and the Krok 2 questions aloud, and read results aloud in sequence | A | 8 | P3.7, P3.8 [CUT 4] | Playwright with a stubbed `speechSynthesis`: speak is called for the prompt, each question, and results |
| P3.12 | `scripts/eval-match.ts`: run the 25 synthetic reports → **hit@3** (relevant = the pick's `obszar` or targetGroups/keywords intersect `expected_tags`) and MRR → `docs/eval.md` table. Run `AI_MODE=on` and `off` | A | 6 | P3.6 | `docs/eval.md` exists with both numbers. **G1 PASS** = the deployed preview completes P3.6's Playwright test **and** hit@3 is recorded (target ≥80%; report the honest value) |

## Phase 4: modules II–VII (T+85 → T+150) · Gate **G2**

Lanes run in parallel after G1 (D7). Each lane owns only its route folders plus one `lib/` file. Shared files (schema, nav, tokens)
are frozen; to change them, ask the lead.

### Lane B: II knowledge store + IV tester

| ID | Task | Est | Verify |
|---|---|---|---|
| P4.B1 | `/biblioteka`: list with filters (obszar, type, evidence, "z filmem") as a **form with a submit button** (no auto-filter surprises) and a result count announced in `role=status` | 10 | Playwright: filter Seniorzy → count = number of corpus records with `obszar=Seniorzy` |
| P4.B2 | `/biblioteka/[id]`: the 5 ROPS sections (for CC BY entries), a YouTube iframe with a `title` and `cc_load_policy=1&cc_lang_pref=pl`, no autoplay, a "Transkrypcja/opis" expander, a materials ZIP link, attribution and licence, plus the Przeczytaj, Wyjaśnij prościej and Wdróż u siebie buttons | 10 | axe 0 serious/critical on 3 detail pages (with a video, without, and a no-licence entry) |
| P4.B3 | **IV tester widget** on the detail page: "Zgłoś się do testów" (role, gmina, optional message) and an accessible 1–5 rating (a radio group, not stars only), feedback, and "co poprawić". Shows the aggregate | 10 | Playwright: rate 4 plus feedback → the aggregate updates; rows in `ratings` and `test_signups` |
| P4.B4 | `/testuj`: innovations flagged "szukamy testerów" (admin-set) plus "Moje zgłoszenia do testów" for the session | 5 | Playwright: a signup made in B3 appears here |
| P4.B5 | `/wyzwania`: the 8 Mapa areas (definition, key challenges, Mapa source) plus a **powiat indicators table** (sortable, with `<caption>`) and a 2-sentence summary. Map **[CUT 2]** only with a "Widok listy" equivalent | 8 | The table has 22 rows plus a caption; axe 0 serious/critical |
| P4.B6 | `/wiedza`: static plain-Polish pages: Czym jest innowacja społeczna, Jak ROPS testuje innowacje (pomysł → test → akceleracja → rekomendacja → wdrożenie), Usługa Wrażliwa, Jak zgłosić pomysł. Each links to its sources | 6 | 4 sections render; every external claim has a link |

### Lane C: III Kreator pomysłów + IWS 2.0 pre-score + grant draft

| ID | Task | Est | Verify |
|---|---|---|---|
| P4.C1 | `lib/iws.ts`: the 5 criteria (Innowacyjność rozwiązania, Adekwatność do potrzeb odbiorców i użytkowników, Efektywność kosztowa, Uniwersalność, Wizja rozwoju pomysłu w przyszłości), each 0–10. `passes(scores)` = sum ≥21 **and** innowacyjność ≥5 **and** each other ≥4. First run **R2** | 4 | Vitest: 6 boundary fixtures (20/21 sum, innowacyjność 4/5, another criterion 3/4) |
| P4.C2 | `/pomysl` step 1 **fiszka**: tytuł, na czym polega, dla kogo, jaki problem, etap realizacji. Prefilled from a luka report when `?z=<reportId>`. Saved as an idea; admin notified | 8 | Playwright: create a fiszka → the idea row exists → the admin bell count +1 |
| P4.C3 | Step 2 **kanwa** (from IWS 2.0 form §3–8: problem, odbiorcy, rozwiązanie, zmiana, innowacyjność, skala/wdrożenie, zasoby/koszty, zespół), labelled "inspirowana formularzem IWS 2.0". The AI assistant button suggests up to 3 improvements per empty or weak field | 10 | Playwright: kanwa saved; the AI suggestions panel labelled AI appears |
| P4.C4 | Step 3 **Ocena wstępna IWS 2.0**: Sonnet `generateObject` → a score of 0–10 plus a one-sentence rationale per criterion. **The pass/fail verdict comes from `lib/iws.ts`, not the LLM.** Shows "Przeszłoby / Nie przeszłoby — popraw: …". Disclaimer: "symulacja, nie jest oceną ROPS" | 8 | Vitest: the verdict equals `passes()` for a mocked LLM output; Playwright: the verdict renders with a disclaimer |
| P4.C5 | Step 4 **Generator wniosku**: visible only while a call is active. Sonnet drafts the IWS 2.0 form sections from the fiszka and kanwa; editable textareas; "Pobierz (.txt/.md)". **[CUT 3]** for DOCX | 10 | With the call active: draft sections render; after the admin deactivates the call: step 4 hidden with an explanation |

### Lane D: VII Middleman Innowacji + Usługa Wrażliwa

| ID | Task | Est | Verify |
|---|---|---|---|
| P4.D1 | `/wdrozenie?innowacja=<id>`: institution profile form (type: OPS/CUS/gmina/NGO/szkoła/DPS…, gmina (TERYT), size, budget range, staff, partners) | 6 | Playwright: the form is reachable from a results card and a library card, with the innovation preselected |
| P4.D2 | Sonnet `generateObject` **service card**: `rdzen[]` (must stay, the EU SI+ transfer method), `do_dostosowania[]`, `kroki[]` (with months), `role[]`, `koszty_orientacyjne` (a range with assumptions), `partnerzy[]`, `ryzyka[]`, `wskazniki[]`, `zrodla_finansowania[]`. Grounded in the innovation's "Kto może skorzystać" and "Czy to działa" | 10 | Vitest: schema-valid on 2 innovations (live, skipped when off); the card cites the innovation's sourceUrl |
| P4.D3 | `lib/uw.ts` **Usługa Wrażliwa readiness check** (deterministic rules from **R1**): Małopolska TERYT (12*), institution type eligible, innovation in the ROPS library, budget ≤600 000 zł → **Ścieżka A (grant)**, otherwise or without capacity → **Ścieżka B (doradztwo)**. Output: route, checklist (macie / brakuje / do ustalenia), next step with the ROPS UW page link. Label: "uproszczone zasady — sprawdź regulamin naboru" | 8 | Vitest: 5 fixtures (non-Małopolska → ineligible; budget 700k → B; complete OPS → A; …) |
| P4.D4 | Save the card plus the UW result to `middleman_cards`; "Wyślij do ROPS" opens a thread (V); print view **[CUT 3]** | 5 | Playwright: generate → saved → "Wyślij do ROPS" creates a thread with the card summary |

### Lane E: V communication + VI admin

| ID | Task | Est | Verify |
|---|---|---|---|
| P4.E1 | `lib/notify.ts`: `notify(recipient, type, ref)` inserts into `notifications`; `email(to, subject, body)` inserts into `email_log` (**simulated, labelled "symulacja wysyłki"**). A header bell with an unread count (`aria-label="Powiadomienia, 3 nowe"`) | 6 | Vitest: notify, then count; Playwright: the bell label updates |
| P4.E2 | Threads: `/wiadomosci` (my threads by session), `/wiadomosci/[id]` (messages, accessible form). Author ↔ ROPS ↔ mentor. **Admin reply → notification and email_log to the author** | 10 | Playwright (two contexts): resident creates a thread → admin sees a bell → admin replies → the resident's bell +1 → the email_log row exists. **This is the DETAILS §6 "szybkość komunikacji" proof** |
| P4.E3 | `/admin` inbox: reports and ideas with status (nowe / w weryfikacji / opublikowane / zamknięte), filter, change status (logged), open thread, assign mentor **[CUT 2]** | 10 | Playwright: change status → persisted; the author is notified |
| P4.E4 | `/admin/trendy`: counts by obszar × powiat × week from reports (chart **plus** "Pokaż dane w tabeli" `<table>` with caption plus a text summary) and **Luki**: luka reports grouped by obszar with sample (redacted) texts → "Przekaż jako temat naboru" | 10 | Playwright: the seeded 25 synthetic reports make non-empty table rows; luka count ≥1 |
| P4.E5 | `/admin/biblioteka/[id]`: edit title, summary, obszar, "szukamy testerów", status published/hidden; save → visible on the public page immediately (re-embedding **[CUT 2]**) | 8 | Playwright: edit the title → the public detail shows the new title |
| P4.E6 | `/admin/nabory` (toggle the DEMO call), `/admin/poczta` (email_log viewer), `/admin/testy` (signups and ratings), `/admin/koszty-ai` (ai_audit: calls, tokens, estimated cost at current prices) | 8 | All 4 pages render with seeded data; the koszty-ai sum > 0 after P3.12 |

**G2 PASS:** all 7 modules are reachable from the nav on **production**, each persists ≥1 row through its UI (one Playwright smoke
test per module), and `pnpm build` is clean.

## Phase 5: quality, compliance and deploy (T+150 → T+175)

| ID | Task | Owner | Est | Dep | Verify |
|---|---|---|---|---|---|
| P5.1 | `scripts/a11y-scan.ts`: Playwright + axe (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`) on `/`, `/zglos`, a results page, `/biblioteka/[id]`, `/pomysl`, `/wdrozenie`, `/admin/trendy` → `docs/a11y-report.md` | A | 6 | G2 | The report lists 7 routes with **0 serious/critical** violations (fix until true, or list the remaining ones honestly) |
| P5.2 | Lighthouse accessibility on `/` and `/zglos` (mobile) | A | 4 | G2 | Scores recorded in `docs/a11y-report.md` (target 100; report the actual) |
| P5.3 | Manual checks: 320 px reflow, 200% zoom, the keyboard path through I + III, the high-contrast theme. Screenshots for the PDF | A | 6 | G2 | 4 screenshots in `docs/shots/a11y-*.png` |
| P5.4 | `/dostepnosc`: Deklaracja dostępności from the 05 §4 template (placeholders, no personal data, `a11y-*` ids, `<time>`) | A | 4 | P1.4 | The page contains the template ids `a11y-podmiot`, `a11y-data-publikacja`, `a11y-data-aktualizacja`, `a11y-kontakt` and `a11y-procedura`, plus `<time datetime=…>` elements |
| P5.5 | `/o-projekcie`: AI disclosure (models, where AI is used, human oversight, AI Act Art. 50 label), data sources and licences (ROPS CC BY 4.0, GUS BDL), **synthetic-data notice**, "Tryb demo" notice, roadmap (Bielik/PLLuM endpoint, login.gov.pl, Witkac export) | A | 5 | — | The page lists every model id from `lib/ai/models.ts` (test reads both) |
| P5.6 | `/etr` (a simple easy-read page *about the service*, **not** labelled as certified ETR) and `/pjm` (an honest placeholder: "Tłumaczenie PJM – w przygotowaniu", plus a contact) | A | 4 | — | Both routes are 200 and linked from the header |
| P5.7 | Production deploy: `vercel deploy --prod`; seed the prod DB; smoke test all modules on the prod URL | A | 6 | P5.1–P5.6 | `scripts/smoke-prod.ts` passes against the prod URL (7 module checks) |
| P5.8 | `README.md` (PL + EN short): what it is, live URL, demo roles, setup (`pnpm i`, `vercel env pull`, `pnpm db:push`, `pnpm seed`, `pnpm dev`), data sources and licences, AI use, a **dependency list** (contract §1.7 asks for the toolchain), and a note on what existed before the hackathon (only the research) | A | 6 | P5.7 | A fresh clone builds following the README (`pnpm i && pnpm build`) |
| P5.9 | `AI_WORKFLOW.md` for Iskra (tools, agents, main prompts, validation, limitations), with no secrets | A | 5 | — | The file exists; `git grep -nE "(sk-\|DATABASE_URL=postgres)"` finds nothing |

## Phase 6: materials in Polish (T+165 → T+200) · Gate **G3**

| ID | Task | Owner | Est | Dep | Verify |
|---|---|---|---|---|---|
| P6.1 | `scripts/shots.ts`: Playwright screenshots of 8 key screens at 1440 and 390 widths → `docs/mockups/`. Annotate them as the **UX/UI mockups** deliverable (a board PNG) | A | 8 | P5.7 | ≥8 PNGs plus `docs/mockups/board.png` |
| P6.2 | **Cost slide**: adapt the 04 §6 tables (pilot vs region, PLN) plus the 05 §7.2 line items (PJM translation, external WCAG audit, marked "szac."). Use actual `ai_audit` token stats per operation to justify the AI cost | A | 6 | P4.E6 | The table sums are consistent (a script recomputes them); the source footnotes are present |
| P6.3 | **10-slide PDF (PL)** built as an HTML deck → `page.pdf()`, 16:9: 1 Iskra + one line · 2 Problem (Mapa Wyzwań, regional numbers) · 3 Rozwiązanie + loop · 4 Demo screens · 5 Moduły I–VII matrix (built/simulated) · 6 Dostępność (axe/Lighthouse grid, law) · 7 AI: architektura, ID guard, PII, AI Act, eval hit@3 · 8 Wdrożenie: UW + IWS 2.0 + integracje + **koszty** · 9 Roadmap · 10 Zespół + links | A | 20 | P6.1, P6.2, P3.12, P5.1 | The PDF has exactly ≤10 pages, is in Polish, and every number traces to `docs/eval.md`, `docs/a11y-report.md` or the cost script |
| P6.4 | **Video script (PL, ≤3:00)** following 05 §7.1, adapted to Iskra: persona from synthetic data, spoken intake → results → Wyjaśnij prościej → Wdróż u siebie (UW route) → Kreator IWS verdict → admin bell, reply, trendy/luki → a11y flash. Plus burned-in captions (`.srt`) | A | 8 | G2 | The script times sum to ≤2:55; the `.srt` exists |
| P6.5 | **Record the video** (screen + Polish voice), export mp4 ≤3:00 | **U** | 20 | P6.4, P5.7 | `ffprobe` duration ≤ 180 s; captions visible |
| P6.6 | HackTribe text (PL): title, description (problem, solution, modules, data sources, AI disclosure, synthetic data, how to test, demo roles), cost summary, links. **Team names and e-mails go only in HackTribe, never in the repo** | A | 8 | P6.3 | Word count ≤500 (FAQ); `git grep` finds no e-mail addresses in the repo |

**G3 PASS** (target 10:25): the prod URL, PDF, mp4, mockups board, cost table and description are all ready.

## Phase 7: submit (T+200 → deadline) · Gate **G4**

| ID | Task | Owner | Est | Verify |
|---|---|---|---|---|
| P7.1 | **Aegis and Aegis Pocket uploads first** (SUBMISSION.md), slot ~09:40–10:00 | U | 20 | Both visible on HackTribe |
| P7.2 | Upload Iskra to HackTribe: category HubMI.pl, title, team ID, description, PDF, mp4, demo link, mockups, cost, repo access note | U | 15 | HackTribe shows the submitted state before 10:50 |
| P7.3 | Re-run `smoke-prod.ts` after upload; freeze the deploy (no changes after 11:00) | A | 2 | Pass at ≥10:50 |

---

## 3. Parallelisation and critical path

```
P0 ─► P1 (foundation) ─► G0 ─► P3 (Module I) ─► G1 ─┬─► Lane B (II+IV)  ─┐
       └─► P2 (data, parallel) ─────────────┘       ├─► Lane C (III)     ├─► G2 ─► P5 ─► P6 ─► G3 ─► P7 ─► G4
                                                    ├─► Lane D (VII)     │
                                                    └─► Lane E (V+VI)   ─┘
```
- **Critical path:** P0.4/P0.5 (human setup) → P1.6/P1.7 → P2.4 → P3.3–P3.6 → G1 → the longest lane (E, ~52 min) → P5.7 → P6.3.
- **With D7 = 4 worktree subagents:** Phase 4 takes about 55 min. **Sequentially**, about 150 min, which **does not fit**. In that
  case pre-cut every [CUT ≤3] item and keep each lane's first 2–3 subtasks only.
- Merge discipline: lanes rebase on the foundation, touch only their folders, run `pnpm build` and their Playwright smoke test before
  merging, and the lead merges in the order E → D → C → B (E owns `notify.ts`, which C and D call).

## 4. Risk register

| Risk | Signal | Mitigation |
|---|---|---|
| AI Gateway blocked or no credit | P1.7 fails | `AI_MODE=off`. BM25 matching, templates for generation, honest "tryb bez AI" banner |
| Embedding model or dimension mismatch | P2.4 assertion | Switch to `cohere/embed-v4.0` or `openai/text-embedding-3-small` via an env var; or BM25-only |
| Neon unavailable | P1.6 fails | SQLite (better-sqlite3) is **not** deployable on Vercel. Use a Vercel Blob JSON store or keep only a local demo and tell the user (scoring needs a live link) |
| Time overrun | G1 later than T+85 | Pre-cut all [CUT ≤3] items; lanes ship their first 2 subtasks only; **never drop a whole module** |
| Hallucinated innovations | Rerank returns an unknown id | `z.enum(candidateIds)` plus a server-side re-check against the DB |
| PII in a demo | A user types real data during judging | Redaction before the LLM and the DB, plus a notice "nie podawaj danych osobowych" |
| Weak corpus areas (poverty, depopulation) | Low hit@3 for those synthetic reports | Show luka honestly → Kreator; mention the innowacjespoleczne.pl (~1 200) import on the roadmap |
| Accessibility regressions from lanes | P5.1 violations | Shared tokens and components from P1.3–P1.4 only; axe in each lane's smoke test |
| Collision with the Aegis uploads | Clock 09:40 | P7.1 is a hard slot; the agent continues P6 meanwhile |

## 5. Research to verify before or during the build

| ID | Question | When | Verify |
|---|---|---|---|
| R1 | Usługa Wrażliwa: who may apply (JST/OPS/CUS/NGO?), the Ścieżka A cap (600 000 zł), Ścieżka B scope, call status | before P4.D3 | Rules cite the ROPS UW page / regulamin URL in `lib/uw.ts` comments |
| R2 | IWS 2.0 Karta oceny thresholds (sum ≥21, innowacyjność ≥5, others ≥4) | before P4.C1 | Matches the zał. 5 PDF; URL in a `lib/iws.ts` comment |
| R3 | Which Gateway models are on the free tier (Sonnet 5.5?) and `qwen3-embedding-8b` dimension options | P0.4 | Recorded in `data/corpus.meta.json` / README |
| R4 | PDF **and** video, or either (RULES vs DETAILS) | before P6 | Default both; ask at the ROPS booth/Discord if possible |
| R5 | How numeric Już Działa's IWS self-assessment is (re-check their live demo ~09:30) | before P6.3 | Adjust the "unikalne" wording on slide 8 accordingly |

## 6. Demo script anchors (used by P2.6, P6.4)

- **Persona (synthetic):** syn-001: 82-year-old mother alone on a farm, gmina Szczurowa (powiat brzeski). A daughter reports via
  **"Pomagam komuś"**.
- **Expected flow:** voice → Seniorzy match → "Dlaczego to ważne u Ciebie" (Szczurowa 65+ share vs Małopolska) → **Wdróż u siebie**
  as the GOPS Szczurowa profile → UW **Ścieżka A/B** → "Wyślij do ROPS" → admin bell → reply → daughter notified.
- **Gap example:** pick a synthetic report in a weak area (depopulation/poverty) → luka → Kreator fiszka prefilled → IWS verdict
  "nie przeszłoby — popraw: Efektywność kosztowa".
