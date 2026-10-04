# Prompt for the Claude Code design session: Iskra clickable prototype

> Copy everything below the line into a fresh Claude Code session. It is self-contained.

---

You are a senior product designer and design engineer. Build a **premium, production-grade, interactive clickable prototype**
for **Iskra**, a Polish-language civic web platform. It must look and feel like a top-tier product (think the polish of Linear,
Stripe, Vercel or Arc) while being as clear and accessible as GOV.UK. The jury is a regional government, so the result should feel
trustworthy, calm, modern and expensive, and never like a hackathon toy.

## 1. Context (why this exists)

- **Event:** HackYeah 2026 (Kraków). Task **"HubMI.pl"** by **Województwo Małopolskie / ROPS Kraków** (Regionalny Ośrodek Polityki
  Społecznej). It is due today; this prototype is the UX/UI foundation that the build agents will implement, and its screenshots are the
  required **"makiety UX/UI"** deliverable.
- **The brief:** design, name and prototype the "digital heart" of the **Małopolski Hub Innowacji Społecznych**, an AI platform
  that connects residents' and institutions' social problems with **proven social innovations**, and supports idea creation,
  testing, communication and implementation across the region.
- **ROPS Kraków** has run social-innovation incubators for 10 years. Its public **Biblioteka Innowacji Społecznych** has **115
  innovations** in 9 categories. Each innovation answers 5 questions: *Na czym polega rozwiązanie? · Jakich problemów dotyczy? ·
  Grupa docelowa · Kto może skorzystać z innowacji? · Czy to działa?* Some have videos, and some are "wybrana do upowszechniania"
  (recommended for scaling).
- **How the jury scores (it drives the design):**
  - **Challenge fulfilment, 40%:** the mandatory matchmaking module (10%) plus 6 extra modules (+5% each). **All 7 modules must
    exist and be clickable.**
  - **Accessibility and intuitiveness, 20%:** seniors and people with disabilities; WCAG 2.1 AA; "can a resident of any age and
    any digital skill level use it without help?"
  - **Implementation potential, 20%.**
  - **UI attractiveness and originality, 10%.**
  - **Quality of materials, 10%.**
- **Everything the user sees is in Polish.** Plain language: sentences of ≤15 words, concrete verbs on buttons, no jargon without
  explanation.

## 2. The product: Iskra

**Name:** *Iskra* ("spark"): the spark that turns a local need into a working solution.
**Tagline:** **„Od potrzeby do wdrożenia w Twojej gminie."**
**The loop (the core idea; show it visually on the landing page):**
1. **Opisz potrzebę.** A resident, NGO or gmina describes a problem in their own words, by typing or **by voice**.
2. **Dopasujemy sprawdzone rozwiązania.** AI matches the problem to real innovations from the ROPS library and explains
   *why* each fits.
3. **Wdróż u siebie.** An institution turns an innovation into a ready **service card** and checks whether it qualifies for
   **„Usługa Wrażliwa"**, ROPS's real programme for implementing tested innovations in local communities: **Ścieżka A**, a grant of
   up to 600 000 zł, or **Ścieżka B**, advisory support.
4. **Luki stają się naborami.** Needs that nothing in the library answers become *gaps* that ROPS sees, and they turn into topics
   for the next grant call. Ideas are pre-scored against ROPS's **official IWS 2.0 evaluation card**.

**Differentiators to make visible in the UI:**
- **A voice-first, senior-friendly intake:** a big microphone, one question at a time, results read aloud, a **„Pomagam komuś"**
  mode (a carer, relative or social worker reports for someone else), and a printable one-page **„kartka"**.
- **Real data with sources:** every innovation card shows its source, licence (CC BY 4.0), a link to ROPS, and an evidence badge.
- **„Dlaczego to ważne u Ciebie":** local statistics for the user's gmina against the Małopolska average (GUS data).
- **The Middleman → Usługa Wrażliwa readiness check:** a checklist of *macie / brakuje / do ustalenia* and a recommended path.
- **Kreator → IWS 2.0 pre-score:** 5 criteria scored 0–10, with the official pass thresholds applied, and the verdict
  „Przeszłoby / Nie przeszłoby – popraw: …".
- **Transparent AI:** every AI output is labelled, explains itself, and offers a human fallback („Zapytaj pracownika ROPS").

## 3. Users and roles (the prototype has a "Tryb demo – rola" switcher in the header)

| Role | Needs | Main screens |
|---|---|---|
| **Mieszkaniec** (resident, often a senior or a carer) | Describe a problem easily and get understandable help | Landing, Zgłoś potrzebę, Wyniki, Biblioteka, Wiadomości |
| **NGO** | Find proven methods, propose ideas, get grants | Biblioteka, Zgłoś pomysł (Kreator), Testuj |
| **JST / instytucja** (gmina, OPS, CUS, DPS, school) | A catalogue of ready innovations and how to implement them | Wdrożenie (Middleman), Biblioteka, Wyzwania |
| **Ekspert / mentor** | Give feedback quickly | Wiadomości, Kreator review |
| **ROPS (admin)** | Triage, respond, publish knowledge, see trends and gaps | Admin: Skrzynka, Trendy, Luki, Biblioteka, Nabory, Poczta, Testy, Koszty AI |

**Hero persona for the demo journey (synthetic):** **Anna, 48**, works in Kraków. Her mother **Pani Krystyna, 82**, lives alone in
**gmina Szczurowa** (powiat brzeski, a rural gmina of 8 983 residents). Anna writes, or says:
> „Moja mama ma 82 lata i mieszka sama na wsi, 6 km od najbliższego sklepu i przychodni. Autobus jeździ dwa razy dziennie. Ostatnio
> coraz częściej zapomina o lekach i nie chce wychodzić z domu. Ja pracuję w Krakowie i nie mam jak codziennie przyjeżdżać. Czy jest
> jakaś forma pomocy na miejscu?"

## 4. Information architecture (use EXACTLY these routes; the build reuses them)

Public:
`/` landing · `/zglos` intake wizard · `/zglos/wyniki/[id]` results · `/zglos/wyniki/[id]/kartka` print view ·
`/biblioteka` library · `/biblioteka/[id]` innovation detail (includes the tester widget) · `/wyzwania` regional challenges ·
`/wiedza` knowledge · `/pomysl` Kreator step 1 (fiszka) · `/pomysl/[id]/kanwa` · `/pomysl/[id]/ocena` (IWS 2.0) ·
`/pomysl/[id]/wniosek` (grant draft) · `/wdrozenie` Middleman profile · `/wdrozenie/[id]` service card + Usługa Wrażliwa ·
`/testuj` · `/wiadomosci` · `/wiadomosci/[id]` · `/dostepnosc` deklaracja dostępności · `/o-projekcie` AI and data
transparency · `/etr` easy-read page · `/pjm` sign-language placeholder.

Admin (role ROPS): `/admin` inbox · `/admin/trendy` · `/admin/luki` · `/admin/biblioteka` + `/admin/biblioteka/[id]` ·
`/admin/nabory` · `/admin/poczta` (simulated e-mail log) · `/admin/testy` · `/admin/koszty-ai`.

**Module map (show it in `/o-projekcie` too):**

| Module | Where |
|---|---|
| I Matchmaking | `/zglos` → `/zglos/wyniki/[id]` |
| II Zasobnik wiedzy | `/biblioteka`, `/wyzwania`, `/wiedza`, `/admin/trendy` |
| III Kreator pomysłów | `/pomysl` → kanwa → ocena → wniosek |
| IV Tester | widget on `/biblioteka/[id]` and `/testuj` |
| V Komunikacja | `/wiadomosci`, the notification bell |
| VI Panel administratora | `/admin/*` |
| VII Middleman Innowacji | `/wdrozenie` → `/wdrozenie/[id]` |

## 5. Screens: content, states and interactions

Design **every** state: default, loading, AI "thinking", success, empty, error, and the role-gated view.

1. **Landing `/`**
   - h1 „Iskra – od potrzeby do wdrożenia w Twojej gminie"; a 1–2 sentence lead.
   - A dominant CTA **„Opisz problem"**, with a secondary hint „Możesz też powiedzieć – kliknij mikrofon".
   - Three role tiles:
     - „Mieszkaniec / organizacja: zgłoś potrzebę";
     - „Gmina / instytucja: znajdź i wdróż rozwiązanie";
     - „Masz pomysł? Zgłoś innowację".
   - **The 4-step loop** as an elegant diagram.
   - A trust strip: „115 innowacji z Biblioteki ROPS Kraków" · „WCAG 2.1 AA" · „AI pod nadzorem człowieka".
   - A non-digital channel: „Wolisz zadzwonić? ROPS Kraków", with an institutional contact.
   - A subtle demo-mode notice.

2. **Intake `/zglos`** (the most important screen; senior-first)
   - „Krok 1 z 2" as text.
   - h1 „Opisz problem własnymi słowami". A large textarea labelled „Co się dzieje? Kogo to dotyczy?", with a hint example.
   - A **big microphone button** „Powiedz zamiast pisać". Recording state: „Słucham… kliknij, aby zakończyć", with a live
     waveform. The transcript appears in the textarea, editable, and is **never auto-submitted**.
   - Topic chips that prefill: Samotność, Opieka nad bliskim, Dojazd, Praca, Niepełnosprawność, Młodzież.
   - An optional gmina autocomplete. A **„Pomagam komuś"** checkbox that reveals „Kim jesteś dla tej osoby?" (opiekun, rodzina,
     pracownik socjalny, sąsiad) and switches the copy to third person.
   - A notice „Nie podawaj danych osobowych (PESEL, telefon)". The button **„Znajdź rozwiązania"**.
   - **Loading:** a calm, branded "spark" progress with steps („Rozumiem problem… Szukam w bibliotece ROPS… Sprawdzam dopasowanie…").
   - An optional **„Tryb głosowy"** toggle that reads the questions aloud.

3. **Results `/zglos/wyniki/[id]`**
   - The header „Znaleźliśmy 3 rozwiązania".
   - A summary of how Iskra understood the problem (podsumowanie plus chips: obszar *Seniorzy*, grupa *seniorzy, opiekunowie*),
     with „Coś się nie zgadza? Opisz inaczej".
   - Optional clarifying questions as **one-at-a-time radio cards**, with „Nie wiem / Pomiń".
   - A **„Dlaczego to ważne u Ciebie"** strip: Szczurowa 65+ **19,7%** vs Małopolska **19,2%**; powiat brzeski old-age dependency
     **27,9** vs **29,4**; social-assistance beneficiaries **270** vs **273** per 10 000; „Źródło: GUS BDL, 2025/2024". Show it as an
     elegant comparison plus an accessible table.
   - **Result cards** contain:
     - the title;
     - one sentence of what it is;
     - a match label in words: **Bardzo pasuje / Pasuje / Może pasować** (never percentages);
     - an evidence badge, „Rekomendowana do upowszechniania" or „Przetestowana w inkubatorze ROPS";
     - **„Dlaczego to pasuje?"** (2 bullets, with matched words highlighted);
     - „Co trzeba dostosować";
     - the source and licence.

     Actions: **Przeczytaj na głos**, **Wyjaśnij prościej** (expands into a simplified AI version), **Wdróż u siebie**, **Zapytaj
     pracownika ROPS**, Szczegóły.
   - The AI disclosure: „Wyniki przygotowała sztuczna inteligencja na podstawie Biblioteki ROPS – może się mylić."
   - **Gap state (luka):** „Nie znaleźliśmy dobrze pasującego rozwiązania. Twoja potrzeba trafi do ROPS jako sygnał." plus
     **„Zgłoś pomysł"**.
   - **„Wydrukuj kartkę"** → the print view: an A4 one-pager in large type.

4. **Library `/biblioteka`:** filters in a form (obszar, typ, dowód skuteczności, „z filmem") with **„Pokaż wyniki"**, a result
   count, and a beautiful card grid/list toggle. **Detail `/biblioteka/[id]`:** a hero, the 5 ROPS sections as readable long-form,
   a video with captions and a „Opis filmu" expander, a materials download, attribution, the actions (read aloud, simplify, Wdróż
   u siebie), and the **tester widget** „Przetestuj i oceń": „Zgłoś się do testów" plus an accessible 1–5 rating in words
   (1 – słabo … 5 – bardzo dobrze), „Co działa? / Co poprawić?", and the aggregate „Średnia 4,3/5 (12 ocen)".

5. **Wyzwania `/wyzwania`:** the 8 areas from ROPS's *Mapa Wyzwań Społecznych* (Rodzina i piecza zastępcza, Bezdomność,
   Niepełnosprawność, Ubóstwo, Integracja cudzoziemców, Zdrowie, Zdrowie psychiczne, Seniorzy) as rich expandable panels, then
   **„Małopolska w liczbach"** as a sortable table of 22 powiaty with a tasteful choropleth-style visual that **always has a table
   equivalent**.

6. **Wiedza `/wiedza`:** an editorial layout with these sections: Czym jest innowacja społeczna · Jak ROPS testuje innowacje
   (pomysł → test → upowszechnienie) · Usługa Wrażliwa · Jak zgłosić pomysł · Słowniczek (JST, OPS, CUS, DPS, ETR, PJM).

7. **Kreator `/pomysl` (4 steps with a step nav: Fiszka → Kanwa → Ocena IWS 2.0 → Wniosek)**
   - **Fiszka:** tytuł, na czym polega, dla kogo, jaki problem, etap.
   - **Kanwa** („inspirowana formularzem IWS 2.0"): problem, odbiorcy, rozwiązanie, zmiana, innowacyjność, skala i wdrożenie,
     zasoby i koszty, zespół. An **AI assistant side panel** suggests up to 3 improvements per field; nothing is auto-overwritten.
   - **Ocena IWS 2.0:** a premium scorecard of 5 criteria (Innowacyjność rozwiązania, Adekwatność do potrzeb odbiorców i
     użytkowników, Efektywność kosztowa, Uniwersalność, Wizja rozwoju pomysłu w przyszłości), each scored 0–10 against its
     threshold, plus a sum against **21/50**. Thresholds: sum ≥21, innowacyjność ≥5, the others ≥4. A big verdict „Przeszłoby ocenę
     merytoryczną" or „Nie przeszłoby – popraw: Efektywność kosztowa". Disclaimer: „Symulacja AI, nie jest oceną ROPS".
   - **Wniosek:** available only during an active call („Nabór DEMO – Inkubator IWS 2.0"). Editable AI-drafted sections and
     „Pobierz szkic". Outside a call, show a locked state.

8. **Middleman `/wdrozenie`:** the chosen innovation summary plus an institution profile (typ: OPS/CUS/gmina/NGO/szkoła/DPS; gmina;
   wielkość; budżet; kadra; partnerzy). **The service card `/wdrozenie/[id]`** („Karta usługi: Mobilne centrum pomocy dla osób
   starszych w gminie Szczurowa") has these sections:
   - **Rdzeń (nie zmieniać)**;
   - **Do dostosowania**;
   - a **timeline of steps by month**;
   - Role;
   - Koszty orientacyjne (a range with assumptions);
   - Partnerzy, Ryzyka, Wskaźniki, Źródła finansowania;
   - the **„Czy to może być Usługa Wrażliwa?"** panel: a path badge (Ścieżka A – grant / Ścieżka B – doradztwo), a checklist with
     *macie / brakuje / do ustalenia* (as text plus icon), the next step, and the caveat „uproszczone zasady – sprawdź regulamin".

   The CTA **„Wyślij do ROPS"** creates a conversation.

9. **Wiadomości `/wiadomosci`:** „Twoje sprawy" with statuses. **The thread view** shows a clean conversation (Ty / ROPS Kraków /
   Mentor), a reply box, and the expectation „ROPS zwykle odpowiada w ciągu 7 dni roboczych". **The notification bell** in the
   header shows a count, with an aria-label like „Powiadomienia, 2 nowe".

10. **Admin.**
    - **Skrzynka:** KPI tiles (nowe zgłoszenia, luki, nowe pomysły, nieprzeczytane), a dense but elegant data table of reports,
      ideas and implementations with status selects (nowe / w weryfikacji / opublikowane / zamknięte), and „Odpowiedz".
    - **Trendy:** a chart by obszar and by powiat **plus** a „Pokaż dane w tabeli" table and a 2–3 sentence auto-summary.
    - **Luki:** gaps grouped by obszar with sample (anonymised) texts and **„Przekaż jako temat naboru"**.
    - **Biblioteka:** an editor (title, summary, obszar, keywords, published/hidden, „szukamy testerów") with „Zapisano – zmiany
      widoczne od razu".
    - **Nabory:** toggle the DEMO call.
    - **Poczta:** a simulated outgoing e-mail log, clearly labelled „symulacja".
    - **Testy:** signups and ratings.
    - **Koszty AI:** calls, tokens, estimated PLN cost, and cost per report.

11. **Trust pages.**
    - `/dostepnosc`: a deklaracja dostępności, a structured, official-looking document.
    - `/o-projekcie`: which AI models do what, human oversight, an AI Act transparency note, data sources and licences, the
      synthetic-data notice, and the roadmap.
    - `/etr`: an easy-read page about the service, labelled „Tekst prosty (nie jest to certyfikowany ETR)".
    - `/pjm`: an honest placeholder „Tłumaczenie PJM – w przygotowaniu".

**Global header:**
- the Iskra wordmark;
- the main nav: Zgłoś potrzebę, Biblioteka, Wyzwania, Wiedza, Zgłoś pomysł, Wdrożenie, Testuj, Wiadomości;
- ETR and PJM entry icons with text;
- **„Ustawienia wyświetlania"**: text size A / A+ / A++ and high contrast, a native panel rather than an overlay widget;
- the bell;
- the role switcher.

**Footer:** Deklaracja dostępności, O projekcie i AI, Źródła danych, ROPS Kraków contact, and the line „Prototyp HackYeah 2026".

## 6. The demo journey that MUST be fully clickable

1. On the landing page, Anna clicks „Opisz problem", ticks „Pomagam komuś" (rodzina), and **dictates** the text above (simulate
   speech: an animated waveform, then the transcript appears). She picks the gmina Szczurowa and clicks „Znajdź rozwiązania".
2. AI loading steps → results: **3 matches**:
   - **„Mobilne centrum pomocy dla osób starszych"** (Bardzo pasuje): services delivered to the homes of dependent rural seniors;
   - **„Centrum antydepresyjne"** (Pasuje): home-based work with a lonely senior in depression;
   - **„Kody QR na pomoc seniorom"** (Może pasować).

   Plus the local-statistics strip. She clicks „Wyjaśnij prościej" and „Przeczytaj na głos" on card 1.
3. She switches the role to **JST (GOPS Szczurowa)** → **„Wdróż u siebie"** on card 1 → fills in the profile → **the service card**
   → **Usługa Wrażliwa: Ścieżka A** with a checklist → **„Wyślij do ROPS"**.
4. She switches the role to **ROPS** → the bell shows 2 → Skrzynka → opens the thread → replies → **Trendy** and **Luki**: a gap in
   „Depopulacja / dojazd" → „Przekaż jako temat naboru".
5. Kreator: a fiszka prefilled from a gap → kanwa with AI tips → **IWS 2.0 verdict „Nie przeszłoby – popraw: Efektywność
   kosztowa"** → improve → „Przeszłoby" → Wniosek (DEMO call active).
6. Accessibility flash: A++ plus high contrast, a keyboard-only pass, and the 320 px mobile layout.

## 7. Visual direction: "premium civic"

- **Mood:** calm authority with warmth. Swiss precision meets Scandinavian public design. Generous whitespace, a strict 12-column
  grid, an 8 px spacing system, and refined typographic hierarchy. It should feel expensive because of **restraint, alignment,
  rhythm and detail**, not gradients and glassmorphism.
- **Brand idea:** a deep **ink navy** base with a single **ember/spark** accent used sparingly (the CTA, active states, the spark
  glyph, key data highlights). The background is a **warm paper** tone, not stark white. A subtle spark motif can appear in empty
  states and the loading animation.
- **Typography:** a modern grotesk with full Polish diacritics (e.g. **Inter / Inter Display** or **Geist**) for the UI. An optional
  refined serif for large editorial headings (e.g. **Fraunces** or **Source Serif 4**, if Polish glyphs render well). Body text is
  **18 px**, line-height 1.5, max ~70ch. Check that ą ć ę ł ń ó ś ź ż render perfectly in every weight.
- **Components:** crisp 1 px hairlines that are still ≥3:1 where they define an input; 10–14 px radii; soft, layered elevation for
  cards; precise focus rings. **Iconography:** Lucide at 1.5 px stroke, always paired with text.
- **Motion:** 150–250 ms ease-out micro-interactions, the AI "thinking" sequence and a waveform. **Respect
  `prefers-reduced-motion`.**
- **Data viz:** minimal, direct labels, no legends where avoidable, and no colour-only encodings. Every chart has a table.
- **Imagery:** no stock photos of smiling seniors. Use abstract warm geometric illustration or the spark motif, and real ROPS video
  thumbnails where relevant.
- **Don'ts:**
  - no gov.pl branding, national emblem (godło) or official logos;
  - no names of other hackathon teams;
  - no "certified ETR" claims, no percentages for match quality;
  - no dark patterns, no autoplay, no tiny grey text.

**Starting tokens** (contrast verified on the given backgrounds; adjust only if you keep ≥4.5:1 for text and ≥3:1 for UI borders
and focus rings):

| Token | Hex | Contrast |
|---|---|---|
| `ink` (text, primary dark surfaces) | `#0B1F33` | 16.7:1 on white, 15.6:1 on paper |
| `paper` (app background) | `#FAF7F2` | — |
| `surface` (cards) | `#FFFFFF` | — |
| `ember` (primary CTA, accent text) | `#C2410C` | 5.18:1 on white; white on ember 5.18:1 |
| `ember-strong` (hover, pressed) | `#9A3412` | 7.31:1 |
| `spark` (**decorative only on dark ink**, never text on light) | `#FBBF24` | 10.0:1 on ink |
| `muted` (secondary text) | `#475467` | 7.69:1 on white. `#667085` is the floor at 4.97:1 |
| `border` (input outlines) | `#667085` | ≥3:1. Purely decorative dividers may be lighter |
| `info` | `#155E75` | 7.27:1 |
| `success` | `#15803D` | 5.02:1 |
| `danger` | `#B42318` | 6.57:1 |
| `focus` | 3 px `#0B1F33` outline + 2 px paper offset; in high contrast, `#FBBF24` on black | — |
| high-contrast theme | `#FFFF00` / `#FFFFFF` text on `#000000` | — |

## 8. Accessibility non-negotiables (20% of the score; design them in, not on)

- `lang="pl"`, a skip link „Przejdź do treści głównej", landmarks, one h1 per page, visible labels plus hints (never placeholder-only),
  an error summary starting „Błąd:" plus inline errors, ≥44×44 px targets, a fully keyboard-operable UI with visible focus, and no
  keyboard traps.
- Reflow at **320 px**, and zoom to 200% without loss. A++ text size and high-contrast themes must look *designed*, not broken.
- AI streaming is announced through one polite status region („Asystent przygotowuje odpowiedź…" → „Gotowe. Znaleźliśmy 3
  rozwiązania."). Never use colour alone. Charts and maps have tables. Videos have captions and a text description.
- Voice features appear only when the browser supports them, and the text path is always equivalent.
- Show „Krok X z Y" as text. „Wstecz" never loses input. There are no time limits.

## 9. AI UX patterns

- Every AI block carries a small label „Odpowiedź przygotowała sztuczna inteligencja – może zawierać błędy", plus a human fallback
  link.
- Matches show *why* they fit (matched words highlighted) and *where the data comes from*. Iskra recommends **only innovations from
  the library**, so say this in a subtle "jak to działa" popover.
- Scores and verdicts that come from fixed rules (IWS thresholds, Usługa Wrażliwa paths) are labelled „reguły ROPS, nie AI".

## 10. Mock data to use (real ROPS innovations, credited „Źródło: ROPS Kraków, Biblioteka Innowacji Społecznych, CC BY 4.0")

| ID | Title | Area | One-line description |
|---|---|---|---|
| rops-008 | Mobilne centrum pomocy dla osób starszych | Seniorzy | Services for dependent seniors from villages, delivered to their homes: coaching, plus advice from a lawyer, dietitian, physiotherapist and financial adviser |
| rops-002 | Centrum antydepresyjne | Seniorzy | A method of working with a lonely senior in depression at home, using dog and cat therapy, with support for the closest family |
| rops-005 | Kody QR na pomoc seniorom | Seniorzy | Unique QR codes on patches or stickers; scanning one shows a helper the key information |
| rops-007 | Merkury | Seniorzy | An online simulator of an ATM, parking meter, parcel locker and self-checkout so seniors can practise at home |
| rops-010 | Organizator kompleksowej opieki w miejscu zamieszkania | Seniorzy | Quickly organises home care for dependent people discharged from hospital, and for their carers |
| rops-001 | BaWita | Seniorzy | A wooden board with 7 movable elements to train memory, manual dexterity and day planning (dementia, after a stroke). **Wybrana do upowszechniania** |
| rops-024 | Czas na aktywność! | Dzieci, młodzież i rodzina | A platform with a simplified picture-and-sound interface that helps adults with Down syndrome plan cultural life with volunteers |
| rops-048 | Innotextil | Osoby o ograniczonej mobilności | Smart leggings plus an app that monitor movement and suggest how to correct gait, for home rehabilitation |
| rops-065 | Głuchy czytelnik w bibliotece | Osoby z niepełnosprawnością sensoryczną | A publication in Polish Sign Language and easy-read text about using a library |
| rops-082 | Gra o zdrowie | Zdrowie i medycyna | A therapeutic board game rehearsing job-market roles before returning to work |

The 9 library categories are: Dzieci, młodzież i rodzina · Seniorzy · Osoby z niepełnosprawnością sensoryczną · Osoby o ograniczonej
mobilności · Osoby z niepełnosprawnością intelektualną · Zdrowie i medycyna · Cudzoziemcy · Rynek pracy · Osoby w kryzysie
bezdomności.
Regional facts for the landing and Wyzwania pages:
- the share of people of post-working age in Małopolska rose from **18,6% (2015) to 21,8% (2024)**;
- **93,8 tys.** people used social assistance in 2024 (2,7% of residents);
- the highest 65+ share is in powiat m. Tarnów (**25,5%**).

Sources: the ROPS Raport OZPS 2024 and GUS BDL.
Admin demo data: 25 synthetic reports (label them „dane syntetyczne"). The mix: Seniorzy 9, Dzieci/młodzież 5, Niepełnosprawność 5,
Zdrowie psychiczne 3, Rynek pracy 2, Bezdomność 1. There are 4 gaps (luki): depopulacja/dojazd ×2, ubóstwo energetyczne, młodzi
bezdomni.

## 11. Build the prototype like this

- **Stack:** **Next.js (App Router) + TypeScript + Tailwind**, with **Radix primitives** (or shadcn/ui, fully restyled to the
  tokens above) and **lucide-react** icons. Use subtle motion with CSS or framer-motion. Fonts come from Google Fonts with the
  `latin-ext` subset.
- **All data is mock, in `/mocks/*.ts`.** All AI is **simulated**: scripted responses with realistic delays and the step-by-step
  loading sequence. Use a simple React context for role, display settings, notifications and created items, so the full demo
  journey (§6) works end to end in one session.
- Use the **exact routes** from §4. Build a shared component kit in `components/ui` (Button, Field, Textarea, Select, RadioCards,
  Checkbox, Card, Badge, StatusRegion, AiLabel, Notice, ErrorSummary, PageHeader, StepIndicator, DataTable with caption,
  ScoreCard, Timeline, Checklist, KPI tile, Bell, RoleSwitcher, DisplaySettings, MicButton with waveform, ReadAloudButton). The
  build agents will lift these into production, so keep them clean and typed.
- It must be **responsive** (390 px phone, 768 px tablet, 1440 px desktop) and work with a keyboard only.
- **Deliver:**
  1. the running prototype (`pnpm dev`);
  2. a `/prototyp` index page linking every screen and state, including the loading, empty, error, luka, locked-call and
     high-contrast/A++ variants;
  3. `DESIGN.md` covering the tokens, type scale, components, and the do's and don'ts;
  4. a Playwright script that screenshots every screen at 1440 and 390 px into `docs/mockups/`. These screenshots are the
     submission's UX/UI mockups.

## 12. Quality bar (self-check before you finish)

- [ ] All 7 modules are reachable and clickable, and the §6 journey works with no dead ends.
- [ ] Every page has one h1, labels, focus states, and no colour-only meaning. axe on 6 key pages shows 0 serious/critical issues.
- [ ] Polish copy is everywhere, with no lorem ipsum and no English leftovers. Diacritics render correctly.
- [ ] The A++ and high-contrast themes and the 320 px layout look intentional.
- [ ] AI outputs are labelled. Rule-based results are labelled „reguły ROPS". Simulated things (e-mail, demo call) are labelled.
- [ ] It looks like a product a regional government would proudly launch tomorrow.
