# 09: Iskra massively parallel build runbook (contract-first fan-out)

Written Sun 4 Oct 08:20 CEST. This **supersedes the execution model of 08**. The architecture, the decisions and the per-task
acceptance checks in 08 still apply. **Nothing runs until the user gives a thumbs-up.**

Source of truth for the work: **[iskra-wps.json](iskra-wps.json)**. It holds 54 work packages (WPs), each with exclusive file
ownership, a spec, verify commands, dependencies and a time box, plus the shared agent rules.
Executable orchestration: [wf/iskra-wf-foundation.js](wf/iskra-wf-foundation.js) ·
[wf/iskra-wf-fanout.js](wf/iskra-wf-fanout.js) (launched 3× concurrently: partitions A, B, C) ·
[wf/iskra-wf-integrate.js](wf/iskra-wf-integrate.js). All three are syntax-checked, and the partitions are verified to cover every
fan-out WP exactly once, with no dependency crossing partitions.

## 0. Hard facts that shape this

| Fact | Consequence |
|---|---|
| **Time: 08:20.** Deadline 11:00. The Aegis uploads are a fixed user slot 09:40–10:00 | About 2 h of build at most. Materials and the upload need the last ~40 min |
| **This Mac has 8 CPUs, 8 GB RAM, ~22 GB free disk** | Workflow concurrency is capped at **6 agents per workflow**. Worktrees per agent (node_modules × N) are impossible. RAM is the binding limit |
| **Dependency critical path is ~72 min** (F0 → F3 → C1 → C2 → X4 → G5) | **Above ~20 concurrent agents there is no gain.** 50 agents finish no faster than 20 (list-scheduling simulation: 6 → 124 min, 12 → 86, 16 → 78, **20 → 72**, 50 → 72) |

**Design that follows from this:**
1. **Contract-first.** One short foundation step freezes every shared interface: types, DB schema, AI gateway, UI kit, nav, typed
   **stubs** for every module and a **skeleton for every route**. Every later agent can then compile and run its page immediately,
   without waiting for the others.
2. **One shared working tree with exclusive file ownership**, instead of worktrees. Agents never commit, install, build, or run
   their own `tsc`/dev server.
3. **Shared heavy processes run once, owned by the lead:** a single `tsc --watch` writes `.tsc-watch.log`
   (agents read their own errors via `pnpm check:owned <paths>`), and a single `next dev` on :3000 serves everyone's curl/e2e checks.
4. **Three concurrent fan-out workflow runs** (A, B and C, 6 agents each) give **~18 live agents**, which sits at the useful maximum.

## 1. Preflight: human only, do it NOW in parallel with your review (≈10 min)

- [ ] **Free RAM.** Quit DevEco Studio and the HarmonyOS emulator (unless you still need them for Aegis Pocket), Docker Desktop and
      Ollama, and close browser tabs. Check with `memory_pressure | tail -1` (want "normal").
- [ ] **D1 GitHub owner.** Create the private repo, e.g. `gh repo create <owner>/iskra --private --clone` in
      `~/Development/hackathons/_october_2026/`.
- [ ] **D2 Vercel scope.** `cd iskra && vercel link` (new project `iskra`).
- [ ] **D3 AI Gateway.** Enable it in the Vercel dashboard. Add credits ($10–20) if Sonnet 5.5 isn't on the free tier (needs a card,
      so you have to do it).
- [ ] **D4 Neon.** `vercel integration add neon` (accept the terms, region Frankfurt), then `vercel env pull .env.local`.
- [ ] **D5** Open demo with the "Tryb demo" role switcher (default) **· D6** who records the video, and the HackTribe team ID.

## 2. Launch sequence (what I run after the thumbs-up)

| Step | Action | Concurrency | Est. | Gate |
|---|---|---|---|---|
| L0 | Read the preflight results, write `.env.local` checks (names only) | lead | 1 | — |
| **L1** | `Workflow(scriptPath: wf/iskra-wf-foundation.js, args: iskra-wps.json)` → F0, then F1‖F2‖F3‖F4 | 1 → 4 | ~22 | **G0**: F3 `smoke-ai` prints Polish text and dim>0. If it fails, set `AI_MODE=off` and continue |
| L2 | Lead: `pnpm build`, `git commit -m "foundation: contracts v1"`, start `pnpm tsc:watch` and `pnpm dev` in the background, curl all 30 skeleton routes | lead | 3 | All routes 200 |
| **L3** | **Three concurrent** `Workflow(scriptPath: wf/iskra-wf-fanout.js, args: {…json, partition})` for **A** (Module I, library, tester; 18 WPs), **B** (Kreator/IWS, Middleman/UW, communication, admin; 15 WPs), **C** (landing, static pages, docs, deck, cost, video script, HackTribe text; 11 WPs) | **~18 live** | **~46** (A is the longest) | Each WP self-verifies. Live `tsc` errors stay visible to everyone |
| L3b | While L3 runs, the lead commits snapshots every ~10 min (`git add -A && git commit`), triages `contract_requests` and applies shared-file changes **serially** | lead | — | — |
| L4 | Lead: stop `next dev`, then `Workflow(scriptPath: wf/iskra-wf-integrate.js)`: build-fix by owner (≤2 rounds) **‖ seed (X4) ‖ eval (E2)** → a11y scan (Q1) → per-owner a11y fixers → final build → local smoke (Q2) ‖ screenshots (G5) | up to 6 | ~35 | **G2**: build green, smoke all ✓ |
| L5 | Lead: `vercel deploy --prod`, run `pnpm seed` against prod DB (same Neon), `BASE_URL=<prod> smoke-prod` | lead | 6 | Prod smoke ✓ |
| L6 | Materials: fill the deck placeholders (shots, eval hit@3, axe/Lighthouse, cost, URLs) → `page.pdf()` (≤10 pages); finalise the HackTribe text with real numbers | 2 agents | ~12 | **G3** |
| L7 | **User:** record the ≤3:00 mp4 following `docs/video/checklist.md` on the prod URL; upload to HackTribe | user | ~25 | **G4** before 10:50 |

**Projected clock** (if the thumbs-up and preflight finish by 08:35):
- foundation 08:35–08:58
- fan-out 09:00–09:50
- **Aegis uploads 09:40–10:00 (user)**
- integrate 09:50–10:25
- prod deploy ~10:30
- materials 10:25–10:40
- **video and upload 10:35–10:55**

**This leaves almost no buffer**, so the cut policy (§4) is applied by clock, not by feel.

## 3. Rules every agent gets (from `iskra-wps.json.rules`)

- Agents create or edit only their `owns` paths. Frozen shared files are changed by the lead only, via `contract_requests`.
- Agents never run install, build, dev, a full tsc, git, vercel or db:push. Verification uses `pnpm check:owned`, per-file
  `vitest`, curl against :3000, and optional per-WP Playwright specs.
- Agents import other modules by contract path; typed stubs keep everything compiling until the real implementation lands.
- Polish plain-language UI and the WCAG rules (labels, `StatusRegion`, `AiLabel`, table alternatives, tokens only).
- AI only through `lib/ai/gateway.ts`, with an offline fallback, mocked in tests, at most 2 live calls per agent. Redact user text
  before AI or the DB.
- Every agent returns a structured result `{id, status, files, verify[{cmd, pass}], contract_requests, notes}`. **No claimed pass
  without a run.**

## 4. Cut policy by clock

| Clock | If behind | Cut |
|---|---|---|
| 09:15 | A partition < 50% done | Skip U8 (spoken loop) and U7 (kartka); K5 ships .md only |
| 09:45 | Fan-out not finished | Stop the remaining WPs (`partial` is fine). Integrate with what exists; every module must still have one working page |
| 10:15 | Build not green | Lead fixes the top errors only. As a last resort, stub-out the failing page with a "W przygotowaniu" notice (never delete a module) |
| 10:30 | No prod deploy | Deploy whatever builds. Record the video on prod or, failing that, on localhost |
| 10:45 | — | **Upload whatever exists.** Late = not judged |

## 5. Monitoring and failure handling

- Watch the progress trees of the 3 fan-out runs. Each WP logs `ID: status`. Re-launch a single failed WP with
  `args.only: ["WP-ID"]` (same script, same partition).
- **Memory guard:** if `memory_pressure` reports "critical", pause partition C (it's docs and static pages) and resume it after A
  or B finishes.
- **AI Gateway down or out of credit:** set `AI_MODE=off` in `.env.local` and restart dev. Every AI call has an offline fallback,
  so the demo works in deterministic mode with an honest banner.
- **Shared-file conflicts** are impossible by construction (exclusive ownership). Contract changes are applied serially by the lead,
  who then notifies the affected WPs via a re-run with `only`.

## 6. Work packages (generated from iskra-wps.json)

| WP | Wave / run | Title | Owns (exclusive) | After | Min | Cut |
|---|---|---|---|---|---|---|
| F0 | W1 scaffold | Scaffold, all dependencies, configs, shared processes | `*` | — | 8 |  |
| F1 | W1 contracts | Design system + accessible app shell | `app/layout.tsx`, `app/globals.css`, `components/ui/`, `components/shell/`, `lib/nav.ts`, `app/(public)/layout.tsx`, `app/admin/layout.tsx` | F0 | 12 |  |
| F2 | W1 contracts | Database schema + client + push | `lib/db/schema.ts`, `lib/db/client.ts`, `drizzle.config.ts`, `lib/db/q/_shared.ts` | F0 | 10 |  |
| F3 | W1 contracts | Contracts, AI gateway, session, stubs for every module, route skeletons | `lib/contracts.ts`, `lib/ai/`, `lib/session.ts`, `lib/data.ts`, `STUBS (see spec)`, `ROUTE SKELETONS (see spec)`, `scripts/smoke-ai.ts` | F0 | 14 |  |
| F4 | W1 contracts | Data build: corpus, TERYT, powiaty, challenges, PII and licence audit | `scripts/build-corpus.ts`, `data/`, `docs/data-audit.md` | F0 | 12 |  |
| M1 | W2 fan-out (A) | PII redaction | `lib/match/redact.ts`, `lib/match/redact.test.ts` | F3 | 8 |  |
| M2 | W2 fan-out (A) | Problem structuring (LLM) | `lib/match/structure.ts`, `lib/match/structure.test.ts`, `lib/match/prompts/structure.ts` | F3 | 12 |  |
| M3 | W2 fan-out (A) | Hybrid retrieval (BM25 + dense + RRF) | `lib/match/retrieve.ts`, `lib/match/retrieve.test.ts`, `lib/match/stem.ts` | F3, F4 | 15 |  |
| M4 | W2 fan-out (A) | Rerank + explanation with ID guard | `lib/match/rerank.ts`, `lib/match/rerank.test.ts`, `lib/match/prompts/rerank.ts` | F3 | 12 |  |
| M5 | W2 fan-out (A) | Match orchestrator + gap + submitReport action | `lib/match/index.ts`, `lib/match/gap.ts`, `lib/match/index.test.ts`, `app/(public)/zglos/actions.ts`, `lib/db/q/reports.ts` | F2, F3 | 14 |  |
| E1 | W2 fan-out (A) | Build-time embeddings | `scripts/embed.ts`, `data/corpus.embedded.json`, `data/corpus.meta.json` | F3, F4 | 8 |  |
| U1 | W2 fan-out (A) | Intake wizard /zglos (Krok 1–3 flow) | `app/(public)/zglos/page.tsx`, `components/zglos/IntakeForm.tsx`, `components/zglos/GminaPicker.tsx`, `e2e/U1.spec.ts` | F1, F3 | 18 |  |
| U2 | W2 fan-out (A) | Voice: speech input + read aloud | `components/voice/MicButton.tsx`, `components/voice/ReadAloudButton.tsx`, `components/voice/useSpeech.ts`, `components/voice/voice.test.tsx` | F1, F3 | 12 |  |
| U3 | W2 fan-out (A) | Clarifying questions component | `components/zglos/Clarify.tsx`, `components/zglos/Clarify.test.tsx` | F1, F3 | 8 |  |
| U4 | W2 fan-out (A) | Results page /zglos/wyniki/[id] | `app/(public)/zglos/wyniki/[id]/page.tsx`, `app/(public)/zglos/wyniki/[id]/actions.ts`, `components/zglos/ResultCard.tsx`, `e2e/U4.spec.ts` | F1, F3 | 18 |  |
| U5 | W2 fan-out (A) | 'Wyjaśnij prościej' (AI simplification) | `components/SimplifyButton.tsx`, `app/api/simplify/route.ts`, `lib/ai/prompts-simplify.ts` | F1, F3 | 8 |  |
| U6 | W2 fan-out (A) | 'Dlaczego to ważne u Ciebie' local context strip | `lib/local-context.ts`, `lib/local-context.test.ts`, `components/zglos/LocalContextStrip.tsx` | F3, F4 | 10 |  |
| U7 | W2 fan-out (C) | Printable 'kartka' | `app/(public)/zglos/wyniki/[id]/kartka/page.tsx`, `app/(public)/zglos/wyniki/[id]/kartka/print.css` | F1, F3 | 8 | 3 |
| U8 | W2 fan-out (A) | Spoken loop 'Tryb głosowy' | `components/voice/VoiceMode.tsx`, `components/voice/VoiceMode.test.tsx` | U2 | 10 | 4 |
| L1 | W2 fan-out (A) | Library list /biblioteka | `app/(public)/biblioteka/page.tsx`, `components/biblioteka/Filters.tsx`, `lib/db/q/innovations.ts`, `e2e/L1.spec.ts` | F1, F2, F3 | 12 |  |
| L2 | W2 fan-out (A) | Innovation detail /biblioteka/[id] | `app/(public)/biblioteka/[id]/page.tsx`, `components/biblioteka/VideoEmbed.tsx`, `components/biblioteka/Sections.tsx`, `e2e/L2.spec.ts` | F1, F3 | 14 |  |
| L3 | W2 fan-out (C) | Challenges /wyzwania | `app/(public)/wyzwania/page.tsx`, `e2e/L3.spec.ts` | F1, F3, F4 | 10 |  |
| L4 | W2 fan-out (C) | Knowledge pages /wiedza | `app/(public)/wiedza/page.tsx`, `content/wiedza.ts` | F1 | 10 |  |
| T1 | W2 fan-out (A) | Tester widget (module IV) | `components/tester/TesterWidget.tsx`, `components/tester/actions.ts`, `lib/db/q/tester.ts`, `e2e/T1.spec.ts` | F1, F2, F3 | 14 |  |
| T2 | W2 fan-out (A) | /testuj page | `app/(public)/testuj/page.tsx` | T1, L1 | 8 |  |
| K1 | W2 fan-out (B) | IWS 2.0 criteria + thresholds (verify R2) | `lib/iws.ts`, `lib/iws.test.ts` | F3 | 8 |  |
| K2 | W2 fan-out (B) | Kreator step 1: fiszka /pomysl | `app/(public)/pomysl/page.tsx`, `app/(public)/pomysl/actions.ts`, `lib/db/q/ideas.ts`, `components/pomysl/IdeaSteps.tsx`, `e2e/K2.spec.ts` | F1, F2, F3 | 14 |  |
| K3 | W2 fan-out (B) | Kreator step 2: kanwa + AI assistant | `app/(public)/pomysl/[id]/kanwa/page.tsx`, `app/(public)/pomysl/[id]/kanwa/actions.ts`, `lib/ai/prompts-kanwa.ts` | K2 | 14 |  |
| K4 | W2 fan-out (B) | Kreator step 3: IWS 2.0 pre-score | `lib/prescore.ts`, `lib/prescore.test.ts`, `app/(public)/pomysl/[id]/ocena/page.tsx`, `app/(public)/pomysl/[id]/ocena/actions.ts` | K1, K2 | 14 |  |
| K5 | W2 fan-out (B) | Kreator step 4: grant application draft | `app/(public)/pomysl/[id]/wniosek/page.tsx`, `app/(public)/pomysl/[id]/wniosek/actions.ts`, `lib/ai/prompts-wniosek.ts` | K2 | 14 |  |
| W1 | W2 fan-out (B) | Middleman: institution profile /wdrozenie | `app/(public)/wdrozenie/page.tsx`, `app/(public)/wdrozenie/actions.ts`, `lib/db/q/middleman.ts` | F1, F2, F3 | 12 |  |
| W2 | W2 fan-out (B) | Middleman: service card generation + page | `lib/middleman.ts`, `lib/middleman.test.ts`, `lib/ai/prompts-middleman.ts`, `app/(public)/wdrozenie/[id]/page.tsx` | W1 | 14 |  |
| W3 | W2 fan-out (B) | Usługa Wrażliwa readiness rules (verify R1) | `lib/uw.ts`, `lib/uw.test.ts` | F3 | 12 |  |
| W4 | W2 fan-out (B) | Usługa Wrażliwa panel UI | `components/wdrozenie/UwPanel.tsx`, `components/wdrozenie/UwPanel.test.tsx` | F1, F3 | 8 |  |
| C1 | W2 fan-out (B) | Notifications + e-mail simulation + Bell | `lib/notify.ts`, `lib/notify.test.ts`, `components/shell/Bell.tsx`, `app/api/notifications/route.ts` | F1, F2, F3 | 12 |  |
| C2 | W2 fan-out (B) | Threads /wiadomosci (module V) | `app/(public)/wiadomosci/page.tsx`, `app/(public)/wiadomosci/[id]/page.tsx`, `app/(public)/wiadomosci/actions.ts`, `lib/db/q/threads.ts`, `e2e/C2.spec.ts` | C1 | 16 |  |
| A1 | W2 fan-out (B) | Admin inbox /admin | `app/admin/page.tsx`, `app/admin/actions.ts`, `e2e/A1.spec.ts` | F1, F2, F3 | 14 |  |
| A2 | W2 fan-out (B) | Admin trends + gaps | `app/admin/trendy/page.tsx`, `app/admin/luki/page.tsx`, `lib/db/q/trends.ts`, `components/admin/BarChart.tsx` | F1, F2, F3 | 14 |  |
| A3 | W2 fan-out (A) | Admin library editor | `app/admin/biblioteka/page.tsx`, `app/admin/biblioteka/[id]/page.tsx`, `app/admin/biblioteka/actions.ts` | L1 | 12 |  |
| A4 | W2 fan-out (B) | Admin: nabory, poczta, testy | `app/admin/nabory/page.tsx`, `app/admin/nabory/actions.ts`, `app/admin/poczta/page.tsx`, `app/admin/testy/page.tsx` | F1, F2, F3 | 12 |  |
| A5 | W2 fan-out (B) | Admin AI cost & audit | `app/admin/koszty-ai/page.tsx`, `lib/ai/pricing.ts` | F1, F2, F3 | 8 |  |
| X1 | W2 fan-out (C) | Landing page / | `app/(public)/page.tsx`, `components/landing/` | F1 | 12 |  |
| X2 | W2 fan-out (C) | Deklaracja dostępności /dostepnosc | `app/(public)/dostepnosc/page.tsx` | F1 | 8 |  |
| X3 | W2 fan-out (C) | O projekcie, ETR, PJM pages | `app/(public)/o-projekcie/page.tsx`, `app/(public)/etr/page.tsx`, `app/(public)/pjm/page.tsx` | F1, F3 | 10 |  |
| X4 | W3 integrate | Seed script (demo data) | `scripts/seed-db.ts` | M5, E1, K2, C2 | 12 |  |
| E2 | W3 integrate | Matchmaking eval hit@3 | `scripts/eval-match.ts`, `docs/eval.md` | M5, E1 | 10 |  |
| Q1 | W3 integrate | A11y scan + Lighthouse report | `scripts/a11y-scan.ts`, `e2e/a11y.spec.ts`, `docs/a11y-report.md` | U1, U4, L2, K4, W2, A2, X1 | 12 |  |
| Q2 | W3 integrate | Production smoke test | `scripts/smoke-prod.ts` | X4 | 8 |  |
| D1 | W2 fan-out (C) | README + AI_WORKFLOW + dependency list | `README.md`, `AI_WORKFLOW.md`, `docs/dependencies.md` | F0 | 10 |  |
| G1 | W2 fan-out (C) | Pitch deck HTML (10 slides, PL) | `docs/deck/` | F0 | 15 |  |
| G2 | W2 fan-out (C) | Cost estimate table (PL) | `docs/koszty.md`, `docs/koszty.json` | F0 | 10 |  |
| G3 | W2 fan-out (C) | Video script + captions (PL, ≤3:00) | `docs/video/` | F0 | 12 |  |
| G4 | W2 fan-out (C) | HackTribe submission text (PL) | `docs/hacktribe.md` | F0 | 10 |  |
| G5 | W3 integrate | Screenshots / UX-UI mockups board | `scripts/shots.ts`, `docs/mockups/` | X4 | 10 |  |
