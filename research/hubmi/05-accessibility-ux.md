# 05: Accessibility, inclusive UX and Polish public-sector requirements (HubMI.pl)

> Research track 5 of the HubMI.pl entry (Województwo Małopolskie / ROPS Kraków task). Written Sun 4 Oct 2026, ~06:30–06:55
> CEST, for a team that will build for about 3 hours. This is guidance only: no app code was written. **(verify)** marks items
> I could not confirm against a primary source in the time available.
> Scoring context: **Accessibility & intuitiveness = 20%**, UI attractiveness/originality = 10%, materials/MVP quality = 10%.
> The stated target is **WCAG 2.1 AA**. The pitch, UI copy and materials must be in Polish.

---

## TL;DR: the top 10 must-dos for the MVP

1. **`<html lang="pl">`, real HTML semantics, one `<h1>` per view, landmarks** (`header`/`nav`/`main`/`footer`), and a
   first-tab **„Przejdź do treści głównej”** skip link. In a SPA, update `document.title` and move focus to the new `<h1>`
   on every route change.
2. **Every form field has a visible `<label>`** (a placeholder is not a label), a hint text with an example, and
   `autocomplete` on personal fields. Errors appear inline **and** in an error summary at the top that starts with „Błąd:”.
   Never rely on colour alone.
3. **Full keyboard path with a thick, visible focus ring** (≥3px, ≥3:1 contrast, for example `outline: 3px solid #1B1B1B;
   outline-offset: 2px`, or yellow `#FFD400` on dark backgrounds). No keyboard traps. Modals trap focus and return it on
   close. A sticky header must not hide the focused element (`scroll-padding-top`).
4. **Contrast ≥4.5:1 for text and ≥3:1 for UI borders, focus rings and chart marks.** The shadcn default border
   `#E4E4E7` is **1.27:1** on white, which fails 1.4.11 for input outlines. Use `#767676` (4.54:1) or darker. The palette
   in §3.8 has pre-computed ratios.
5. **Reflow at 320 CSS px and text zoom to 200%** without horizontal scroll or clipped text. Use `rem` units, no fixed
   heights on text containers, and test at 400% browser zoom on a 1280 px window.
6. **Accessible AI output.** Do **not** put the streaming token container in `aria-live`. Use one visually hidden
   `role="status"` region that announces „Asystent przygotowuje odpowiedź…” and then „Odpowiedź gotowa. Znaleziono 3
   rozwiązania.”, and set `aria-busy="true"` on the message while it streams. Label every AI answer as AI („Odpowiedź
   przygotowała sztuczna inteligencja – może zawierać błędy”) and give a human fallback („Zapytaj pracownika ROPS”).
7. **Every map and chart has an equivalent table or list.** The challenge map gets a „Widok listy” (filterable by
   powiat/gmina), and every admin trend chart gets a „Pokaż dane w tabeli” `<table>` with a `<caption>` plus a 2–3-sentence
   text summary. Never use colour alone (add direct labels and patterns).
8. **Video in the innovation library** gets Polish captions (`<track kind="captions" srclang="pl">` or YouTube CC with
   `cc_lang_pref=pl`), a „Transkrypcja” expander, a descriptive `title` on any `<iframe>`, and no autoplay. Optional: a
   „Wersja w PJM” slot.
9. **Senior/low-skill mode**: a native (not overlay) „Ustawienia wyświetlania” control with text size A / A+ / A++ and
   high contrast, a 18px+ base font, ≥44×44 px targets, buttons that say what they do („Znajdź rozwiązania”, not „OK”),
   a **microphone button for voice input (pl-PL)** and a **„Przeczytaj na głos”** button. Plain Polish everywhere
   (≤15 words per sentence) and a **„Wyjaśnij prościej”** AI rewrite of any innovation description.
10. **Prove it.** Publish a **„Deklaracja dostępności”** page linked from the footer (template in §4), run
    **axe-core via Playwright + Lighthouse** on the five key screens, show **„0 naruszeń / Lighthouse Dostępność 100”** on
    one slide, and include a 20-second keyboard-plus-screen-reader clip in the demo video.

---

## 1. The legal and standards frame (what a regional-government jury has in mind)

### 1.1 Ustawa z dnia 4 kwietnia 2019 r. o dostępności cyfrowej stron internetowych i aplikacji mobilnych podmiotów publicznych

- **Who it covers.** Public bodies, which includes the Urząd Marszałkowski and **ROPS** (a regional budgetary unit). A
  platform operated for ROPS falls under this law.
- **Standard (art. 4–5).** Digital accessibility means *postrzegalność, funkcjonalność, zrozumiałość, kompatybilność*,
  met by the requirements in the annex to the act, which are **WCAG 2.1 levels A and AA**. EU presumption of conformity
  runs through **EN 301 549 V3.2.1 (2021)**.
  The original act referenced EN 301 549 V2.1.2. (verify which version the current consolidated text names)
- **Exclusions (art. 3 ust. 2)** relevant to us:
  - live multimedia;
  - multimedia published **before 23 Sept 2020**;
  - online maps/map services, **provided key information is accessible another way**, which is why the challenge map
    needs a list view;
  - third-party content the body did not fund or control.
- **„Nadmierne koszty” (art. 8).** Accessibility may be waived only after a documented cost assessment. Don't plan to rely on it.
- **Deklaracja dostępności (art. 10).**
  - It is mandatory, must follow the EU model from **Implementing Decision (EU) 2018/1523**, and must be published in
    **accessible HTML**.
  - The link has to be reachable while navigating, and the footer is the convention.
  - Review it **annually by 31 March** and after any significant change.
  - The Ministry of Digital Affairs' **„Warunki techniczne publikacji oraz struktura dokumentu elektronicznego deklaracji
    dostępności”** (the 2.0 version) adds **mandatory HTML `id`s** such as `a11y-wstep`, `a11y-podmiot`, `a11y-status` and
    `a11y-kontakt`, plus `<time datetime="YYYY-MM-DD">` dates. The template is in §4. Bodies had to update to the new
    pattern by **31 Mar 2025**.
- **The right to request accessibility (art. 18–19).**
  - Anyone can request that a page or element be made accessible, or ask for an alternative format.
  - The body must deliver **without delay, ≤7 days**. If that isn't possible, it must say why and set a new date
    **≤2 months** out.
  - If refused, the person can file a complaint, and then go to the **Rzecznik Praw Obywatelskich**.
  - **Penalties:** up to 10 000 zł, and up to 5 000 zł for a missing declaration. (verify the exact amounts and article)

### 1.2 Ustawa z dnia 19 lipca 2019 r. o zapewnianiu dostępności osobom ze szczególnymi potrzebami

- **Art. 6 pkt 2** points back to digital accessibility (the 2019 act above).
- **Art. 6 pkt 3 lit. d** requires the public body's website to carry information about **the scope of its activity** in
  three forms:
  1. a machine-readable text file;
  2. **a recording in Polish Sign Language (PJM)**;
  3. **text that is easy to read and understand (ETR)**.
- **This is why every Polish public site has the two header icons, „PJM” and „ETR”.** A jury from the Urząd Marszałkowski
  or ROPS will look for them.
- **Also required:** a **koordynator do spraw dostępności** (art. 14), periodic accessibility reports (art. 11), and
  communication options such as e-mail, SMS/MMS, video interpreter and PJM contact.

### 1.3 European Accessibility Act (Directive 2019/882) and its Polish implementation

- **Polish law.** *Ustawa z dnia 26 kwietnia 2024 r. o zapewnianiu spełniania wymagań dostępności niektórych produktów i
  usług przez podmioty gospodarcze*, **in force since 28 June 2025**.
- **Scope.** It targets **economic operators** (e-commerce, banking, e-books, transport, telecoms and so on), so it does
  not directly cover ROPS. ROPS stays under the 2019 acts.
- **Pitch angle.** A future HubMI integration with NGOs and companies (for example, the „pośrednik innowacji” offering
  services) means partners may fall under EAA. Being built for WCAG AA from day one keeps that path open.
- **Transition periods** for some existing services run to 28 June 2030. (verify per service type)

### 1.4 WCAG 2.2 and EN 301 549 status (as of Oct 2026)

- **WCAG 2.2** has been a W3C Recommendation since 5 Oct 2023 (editorial update 12 Dec 2024). On 21 Oct 2025 it was
  approved as **ISO/IEC 40500:2025**.
- **EN 301 549 V4.1.1** was **published in Sept 2026** and adopts **WCAG 2.2 AA**. It is **not yet cited in the EU
  Official Journal**, so V3.2.1 (WCAG 2.1 AA) is still the legal benchmark. Citation is expected soon. (verify)
- **Recommendation.** Claim **„WCAG 2.1 AA (zgodnie z ustawą) + kryteria WCAG 2.2 AA”**. The six new A/AA criteria are
  cheap, help seniors, and are a visible differentiator:

| WCAG 2.2 criterion | What to do in HubMI |
|---|---|
| 2.4.11 Focus Not Obscured (AA) | `scroll-padding-top` equal to the sticky header height. Cookie/AI banners must not cover the focused element. |
| 2.5.7 Dragging Movements (AA) | Admin kanban/sorting must also work through „Przenieś do…” select or buttons. Map pan also needs ± buttons. |
| 2.5.8 Target Size (Minimum, AA) | ≥24×24 px. We target **44×44** for seniors, which is the 2.5.5 AAA size. |
| 3.2.6 Consistent Help (A) | A „Pomoc / Kontakt z ROPS” link in the same place (header, right side) on every page. |
| 3.3.7 Redundant Entry (A) | Wizard and grant generator never ask for the same data twice: pre-fill from earlier steps or the profile. |
| 3.3.8 Accessible Authentication (AA) | No CAPTCHA puzzles or cognitive tests. Allow password managers and paste. Prefer e-mail magic link or a demo login. |

### 1.5 EU-funds angle: „Standardy dostępności dla polityki spójności 2021–2027”

- If HubMI is co-financed from **Fundusze Europejskie dla Małopolski 2021–2027 / EFS+**, which is likely for a ROPS
  social-innovation hub (verify), the project must also meet **Załącznik nr 2 do Wytycznych dotyczących realizacji zasad
  równościowych**.
- That annex has five standards: szkoleniowy, informacyjno-promocyjny, **cyfrowy**, transportowy and architektoniczny.
- The **standard cyfrowy** covers websites, web apps, documents and multimedia (WCAG 2.1 AA, captions, audio description
  where visuals matter, PJM for events).
- Mentioning this one line in the pitch signals that the team understands how the region actually procures.
- Małopolska's EU-funds portal has a guide, „Realizacja w praktyce zasady dostępności”.

### 1.6 AI Act transparency (relevant because the product is AI)

- **Art. 50(1) of Regulation (EU) 2024/1689** says people must be informed that they are interacting with an AI system.
  It applies from **2 Aug 2026**. (verify whether the „digital omnibus” changed any Art. 50 dates)
- **Implementation:** a permanent „Asystent AI” label on chat/matching output and a one-line explanation of what the AI
  does and does not do.
- **Keep matching advisory.** AI that assesses eligibility for public benefits is high-risk under Annex III pt 5(a). Our
  matchmaking only *suggests innovations*, with a human (ROPS) in the loop. Say so explicitly. (verify the classification
  with the AI/legal track)

### 1.7 What the jury will expect to *see* (visible signals)

| Signal | Where | Effort |
|---|---|---|
| „Deklaracja dostępności” link in the footer, opening a proper HTML page (template in §4) | footer | 15 min |
| **ETR** and **PJM** entry points in the header (icons with text), pointing to „O platformie w tekście łatwym” and a PJM placeholder page | header | 20 min |
| „Ustawienia wyświetlania”: A / A+ / A++ and „Wysoki kontrast” (native CSS variables, **not an overlay widget**) | header | 30 min |
| Skip link, keyboard-only demo, focus ring | everywhere | 20 min |
| Voice input + read-aloud on the matchmaking screen | main flow | 40 min |
| „Wyjaśnij prościej” (AI rewrite in simple Polish) | innovation cards | 20 min, reusing the LLM |
| Map/chart alternatives (list/table) | knowledge store, admin | 30 min |
| Captions + transcript on 1–2 library videos | library | 20 min |
| Automated report (axe/Lighthouse) in the PDF | pitch | 15 min |

> **Do not use accessibility overlays** (UserWay, accessiBe and similar). Polish and EU experts criticise them, and they
> don't fix the underlying issues. A small native settings panel is fine and is a common pattern on Polish BIP/JST sites
> that seniors recognise.

---

## 2. App-specific WCAG 2.1 AA checklist

Legend for the test column:
- **K**: keyboard-only pass
- **SR**: screen reader (NVDA + Chrome/Firefox on Windows, the most common in PL; or VoiceOver + Safari on macOS, Cmd+F5)
- **axe**: axe-core / Playwright
- **LH**: Lighthouse
- **Z**: browser zoom / 320 px viewport
- **CC**: contrast checker (e.g. WebAIM)

### 2.1 Global layout and navigation

| Criterion | Where in our app | How to implement | How to test |
|---|---|---|---|
| 3.1.1 Language of page (A) | every page | `<html lang="pl">` | axe (`html-has-lang`, `html-lang-valid`) |
| 3.1.2 Language of parts (AA) | English terms, Ukrainian content (Małopolska has many UA residents) | `<span lang="en">`, `<section lang="uk">` | SR pronunciation; manual |
| 2.4.1 Bypass blocks (A) | every page | First focusable element: `<a href="#main" class="skip-link">Przejdź do treści głównej</a>`, visible on focus. `<main id="main" tabindex="-1">` | K: Tab once on load |
| 1.3.1 Info & relationships (A) | all | Landmarks (`header`, `nav aria-label="Menu główne"`, `main`, `footer`), real `<h1>`–`<h3>` hierarchy, `<ul>` for card lists, `<table>` for data | axe; SR landmarks list (NVDA Insert+F7) |
| 2.4.2 Page titled (A) | every route | `„Wyniki dopasowania – HubMI.pl”`, `„Krok 2 z 4: Opisz problem – HubMI.pl”` | Check the tab title; SR |
| 2.4.3 Focus order (A) + SPA routing | route changes, wizard steps | On navigation: set the title and move focus to the `<h1 tabindex="-1">`. In the wizard: focus the step heading | K + SR |
| 2.4.4 Link purpose (A) | cards | „Zobacz szczegóły: Seniorzy w sieci”, not a bare „Więcej” (use visually hidden text) | SR links list |
| 2.4.5 Multiple ways (AA) | site | Main menu + search + „Mapa strony” page | manual |
| 2.4.6 Headings & labels (AA) | all | Descriptive Polish headings, question-style where useful („Jakiego wsparcia szukasz?”) | manual |
| 3.2.3 / 3.2.4 Consistent navigation & identification (AA) | all | The same header/footer everywhere. The same icon and text for the same action | manual |
| 1.4.10 Reflow (AA) | all, especially the admin dashboard | Mobile-first CSS grid. At 320 px, no horizontal scroll except data tables and the map (which may scroll inside their own container) | Z: DevTools 320×800, or 400% zoom on a 1280 px window |
| 1.4.4 Resize text (AA) | all | `rem`, no `px` font sizes, no fixed heights on text boxes. The A/A+/A++ toggle scales the `html` font-size (100/125/150%) | Z: 200% text-only zoom (Firefox „Powiększ tylko tekst”) |
| 1.4.12 Text spacing (AA) | all | No clipping when line-height is 1.5, paragraph spacing 2×, letter spacing 0.12em, word spacing 0.16em | Text-spacing bookmarklet |
| 1.3.4 Orientation (AA) | mobile | No orientation lock | rotate device |

### 2.2 Forms: matchmaking input, idea-submission card, grant generator, tester sign-up, ROPS contact

| Criterion | Where | How to implement | How to test |
|---|---|---|---|
| 3.3.2 Labels or instructions (A), 2.5.3 Label in name (A) | all fields | Visible `<label for>` above the field. Hint in `<p id="x-hint">` linked by `aria-describedby`. Mark required fields in words: „(wymagane)”, or mark optional ones as „(opcjonalnie)” (GOV.UK style). Visible button text = accessible name | axe `label`; SR; voice control („kliknij Znajdź rozwiązania”) |
| 1.3.5 Identify input purpose (AA) | contact, tester sign-up, idea author | `autocomplete="name"`, `"email"`, `"tel"`, `"organization"`, `"address-level2"` (city), `"postal-code"` (hint „np. 30-001”) | inspect; autofill works |
| 3.3.1 Error identification (A) | submit | Inline error under the field (`id="x-error"`, appended to `aria-describedby`), `aria-invalid="true"`, plus an **error summary** box at the top with `role="alert"` and links to each field. Text: „Błąd: Wpisz adres e-mail w formacie nazwa@domena.pl” | SR; axe |
| 3.3.3 Error suggestion (AA) | all validation | Say how to fix it, not just that it's wrong | manual |
| 3.3.4 Error prevention (legal, financial, data) (AA) | **grant-application generator**, idea submission | A „Sprawdź przed wysłaniem” review step with „Zmień” links per section, explicit confirmation, and the ability to edit after submitting (or withdraw) | manual |
| 1.4.1 Use of colour (A) | errors, statuses | Icon + text („Błąd”, „Wysłano”), not red/green alone | grayscale screenshot |
| 2.2.1 Timing adjustable (A) | grant generator (the *call* has a deadline, not the UI), sessions | **No UI timeouts.** If a session expires: warn ≥20 s before, offer „Przedłuż sesję”, and autosave drafts (localStorage or server) | manual |
| 3.3.7 Redundant entry (2.2, A) | wizard → grant generator | Carry the problem description, gmina and target group forward. Never re-ask | manual |
| 4.1.2 Name, role, value (A) | custom selects, toggles, chips | Native `<select>`, `<input type=radio>`, `<button aria-pressed>`, or React Aria / Radix primitives | axe; SR |
| Radio/checkbox groups | clarifying questions, target groups | `<fieldset><legend>Kogo dotyczy problem?</legend>…` | SR |
| 1.4.11 Non-text contrast (AA) | input borders, checkboxes, focus | Borders ≥3:1 (`#767676` or darker). Focus ring ≥3:1 | CC |

### 2.3 Keyboard and focus

| Criterion | Where | How to implement | How to test |
|---|---|---|---|
| 2.1.1 Keyboard (A) | everything, including the map, chart toggles, video player, chat, drag-n-drop in admin | Native elements. Map markers reachable by Tab **or** via the list view. Drag replaced by buttons | K: unplug the mouse |
| 2.1.2 No keyboard trap (A) | modals, video embeds, map | Esc closes. Focus returns to the trigger | K |
| 2.4.7 Focus visible (AA) | all | `:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }`. Never `outline: none` without a replacement | K + CC |
| 2.4.11 Focus not obscured (2.2, AA) | sticky header, cookie bar | `html { scroll-padding-top: 5rem }` | K |
| 1.4.13 Content on hover/focus (AA) | tooltips, AI „Dlaczego to pasuje?” popovers | Dismissible with Esc, hoverable, persistent. Prefer disclosure buttons over tooltips | K + mouse |
| 2.1.4 Character key shortcuts (A) | if any single-letter shortcuts | Avoid them, or make them toggleable | manual |
| 2.5.1 / 2.5.7 Pointer gestures, dragging | map pinch-zoom, admin kanban | Zoom ± buttons. „Przenieś do kolumny…” menu | manual |

### 2.4 AI matchmaking, chat and „pośrednik” (dynamic content)

| Criterion | Where | How to implement | How to test |
|---|---|---|---|
| 4.1.3 Status messages (AA) | „Szukam…”, „Znaleziono 3 rozwiązania”, „Zapisano szkic” | One persistent, visually hidden `<div role="status" aria-live="polite" aria-atomic="true">` that exists in the DOM before content changes. Write short messages into it | SR (NVDA speech viewer) |
| **Streaming LLM output** | chat, „Wyjaśnij prościej”, grant generator | **Don't** mark the streaming bubble `aria-live` (SRs read fragments or re-read everything). While streaming: `aria-busy="true"` on the bubble, status = „Asystent pisze odpowiedź…”. When done: `aria-busy="false"`, status = „Odpowiedź gotowa”. Offer „Przeczytaj odpowiedź” (TTS). Don't steal focus | SR: verify one clean announcement |
| Chat transcript | chat | Container `role="log"` with `aria-label="Rozmowa z asystentem"`. Each message is an `<article>` with a visually hidden author heading („Ty napisałeś:”, „Asystent AI odpowiada:”). Input is a labelled `<textarea>` + „Wyślij” button. Enter sends, Shift+Enter adds a new line (documented in the hint) | SR + K |
| 2.2.2 Pause, stop, hide (A) | typing animation, carousels | Respect `prefers-reduced-motion` (show the full text immediately). Provide a „Zatrzymaj generowanie” button. No auto-rotating carousels | manual |
| 3.1.5-ish plain language (AAA, but scored here) | AI output | System prompt: „Pisz prostym językiem polskim, zdania do 15 słów, bez żargonu, zwracaj się na «Ty»…” plus a „Wyjaśnij prościej” button | Jasnopis score (§5) |
| Result cards | matchmaking results | `<h2>Znaleźliśmy 3 rozwiązania</h2>` + `<ol>` of `<article>`, each with an `<h3>`. The match reason is **text**, not just a % bar („Bardzo pasuje: dotyczy samotności seniorów na wsi”) | SR headings nav (H key) |
| AI transparency (AI Act Art. 50) | chat/results | Visible „Odpowiedź przygotowała sztuczna inteligencja. Może zawierać błędy. Sprawdź szczegóły lub zapytaj pracownika ROPS.” | manual |

### 2.5 Knowledge store: challenges map and innovation library

| Criterion | Where | How to implement | How to test |
|---|---|---|---|
| 1.1.1 Non-text content (A) | map, icons, images | Map container `role="region" aria-label="Mapa wyzwań społecznych Małopolski"`, plus a visible link „Pokaż wyzwania jako listę”. Decorative icons get `aria-hidden="true"`. Images get meaningful `alt` in Polish | axe; SR |
| Map alternative (law art. 3 ust. 2 + 1.3.1) | challenge map | **A „Widok listy” tab**: a table or list grouped by powiat, with filters (powiat, kategoria). The same data and the same filters as the map. Use two tabs („Mapa” / „Lista”) and put the list first in DOM order | K + SR |
| 1.4.1 / 1.4.11 | map markers, chart lines | Shapes and labels as well as colour. Marker contrast ≥3:1. Avoid red/green pairs | grayscale + CC |
| 1.2.2 Captions (prerecorded, A) | library videos | `<video>` + `<track kind="captions" srclang="pl" label="Polski" default>`, or YouTube with `cc_load_policy=1&cc_lang_pref=pl&hl=pl`. AI-generated captions (e.g. Whisper) **must be human-reviewed**. Unreviewed auto-captions are not considered conformant | play with CC |
| 1.2.3 / 1.2.5 Audio description (A/AA) | library videos | For „talking head” videos, a full **transcript** with visual descriptions is the pragmatic route (1.2.3). For AA (1.2.5), add audio description, or state in the deklaracja that visuals carry no extra information (verify that this exemption reasoning is acceptable) | manual |
| 1.2.1 Audio-only (A) | podcasts, if any | Transcript | manual |
| 1.4.2 Audio control / no autoplay | library | No autoplay | manual |
| 4.1.2 for embeds | YouTube iframe | `title="Film: Seniorzy w sieci – jak to działa (z napisami)"` | axe `frame-title` |
| Documents (PDF downloads) | library | Prefer HTML pages. Any PDF must be tagged. Add „PDF, 1,2 MB” to the link text | PAC 2024 / Acrobat check |

### 2.6 Admin panel (ROPS): trend dashboard, moderation

| Criterion | Where | How to implement | How to test |
|---|---|---|---|
| 1.1.1 / 1.3.1 Chart alternatives | need-trend charts | Each chart sits in a `<figure>` with a `<figcaption>` (a 1–2-sentence takeaway, which can be AI-generated: „Najczęściej zgłaszany problem w październiku: samotność seniorów (+34%)”) and a **„Pokaż dane w tabeli”** toggle that renders a `<table>` with `<caption>`, `<th scope>`. The chart SVG gets `role="img" aria-label="…"` (Recharts: `accessibilityLayer`) | SR + axe |
| 1.4.11 | chart lines/bars | ≥3:1 against the background. Direct labels instead of legend-only | CC |
| 1.4.10 reflow | dashboard | Cards stack at 320 px. Tables scroll horizontally inside `<div role="region" aria-label="Tabela: …" tabindex="0">` | Z |
| 2.5.7 | kanban moderation | Status `<select>` per item | K |
| Data tables | submissions list | Sortable column buttons inside `<th>` with `aria-sort` | SR |

### 2.7 Polish accessible-name glossary (use consistently)

| Element | Polish label |
|---|---|
| Skip link | „Przejdź do treści głównej” |
| Main nav | `aria-label="Menu główne"` |
| Mobile menu button | „Menu” (`aria-expanded`) |
| Search | label „Szukaj w serwisie”, button „Szukaj” |
| Close | „Zamknij” (visible text or `aria-label`) |
| Voice input | „Powiedz zamiast pisać”. While active: „Zatrzymaj nagrywanie” (`aria-pressed="true"`) |
| Read aloud | „Przeczytaj na głos” / „Zatrzymaj czytanie” |
| Simplify | „Wyjaśnij prościej” |
| Text size | „Rozmiar tekstu: standardowy / duży / bardzo duży” |
| Contrast | „Wysoki kontrast” (switch, `role="switch" aria-checked`) |
| New window | append „(otwiera się w nowym oknie)” |
| Required | „(wymagane)” |
| Error prefix | „Błąd:” |
| Status while generating | „Asystent przygotowuje odpowiedź…” |
| Human fallback | „Zapytaj pracownika ROPS” / „Porozmawiaj z człowiekiem” |
| Pagination | `nav aria-label="Stronicowanie"`, „Następna strona”, „Poprzednia strona”, `aria-current="page"` |

---

## 3. Inclusive UX for seniors and people with low digital skills

### 3.1 Prosty język (plain Polish)

- **Sources:**
  - the gov.pl Redakcyjne ABC page „Najważniejsze zasady prostego języka”;
  - the Służba Cywilna page „Prosty język” (the Head of the Civil Service's 17 Dec 2020 recommendation to promote plain
    language);
  - the Ministry of Digital Affairs' plain-language pages.
- **Write for a reader with 8–9 years of schooling:**
  - sentences of **10–15 words**, active voice;
  - address the reader as **„Ty”**, and the institution as **„my”**;
  - put the key information first;
  - one paragraph = one idea;
  - bullet lists, and headings phrased as **questions**;
  - no left-right justified text;
  - expand abbreviations („JST” → „samorząd (gmina, powiat, województwo)”, „ROPS” → „Regionalny Ośrodek Polityki
    Społecznej”).
- **Microcopy examples:**

| Instead of | Write |
|---|---|
| „Zgłoś zapotrzebowanie na innowację społeczną” | „Opisz problem, z którym się mierzysz” |
| „Weryfikacja zgłoszenia” | „Sprawdzamy Twoje zgłoszenie” |
| „Nie znaleziono rekordów” | „Nie znaleźliśmy pasujących rozwiązań. Spróbuj opisać problem innymi słowami albo zapytaj pracownika ROPS.” |

- **Measure** text difficulty with **Jasnopis** (SWPS). The gov.pl Gov UI guide even has a „Jasnopis” section. Aim for
  class ≤3–4 on its 1–7 scale. (verify the scale and target)
- **Ask the LLM** for plain Polish in the system prompt. Run 3–4 key texts through Jasnopis and quote the score in the PDF.

### 3.2 ETR: tekst łatwy do czytania i zrozumienia

- **What it is.** An easy-to-read standard aimed mainly at people with intellectual disabilities:
  - very short sentences with one idea per sentence;
  - left-aligned, large sans-serif text;
  - supporting pictograms;
  - and (this is the key point) **texts are tested by people with intellectual disabilities**.
- **Polish practice:** the PSONI instruction *„Tekst łatwy do czytania i zrozumienia. Instrukcja tworzenia i stosowania”*,
  the ZPE.gov.pl course, and Dostępna Małopolska's own ETR page and webinar materials.
- **The European easy-to-read logo (Inclusion Europe)** may only be used on texts made to the European standards and tested
  with users. **Do not put the ETR logo on AI-generated text.** (verify the logo-licence conditions)
- **What's realistic for the MVP:**
  1. **One static ETR page** „HubMI w tekście łatwym” (6–10 short sections, each with a pictogram: Co to jest? Co możesz
     tu zrobić? Jak opisać problem? Kto Ci pomoże? Jak się z nami skontaktować?). Link it from the header with an „ETR”
     icon plus text. Mark it „wersja robocza – do przetestowania z odbiorcami”.
  2. A **„Wyjaśnij prościej”** button on every innovation card and AI answer. It produces a *plain-language* version,
     labelled „Wersja uproszczona (przygotowana przez AI)”. Pitch it as a step towards ETR, not as certified ETR.
- **Sample ETR-style copy** (for the static page):
  > **Co to jest HubMI?**
  > HubMI to strona internetowa.
  > Możesz tu opisać swój problem.
  > Na przykład: jesteś samotny. Albo nie masz jak dojechać do lekarza.
  > Pokażemy Ci, kto już rozwiązał podobny problem.

### 3.3 Guided wizard vs free-text chat: recommendation for the mandatory matchmaking flow

Use a **hybrid** layout: **one big free-text field with strong scaffolding**, and AI follow-up questions shown as **buttons,
not open chat**. Open chat is hard for low-skill users because of the blank-page problem and because they don't know what to
ask. A pure form wizard can't capture the problem in the resident's own words, which the brief explicitly requires.

```
Krok 1 z 3: Opisz problem
  <h1>Opisz problem własnymi słowami</h1>
  [label] Co się dzieje? Kogo to dotyczy?
  [hint]  Na przykład: „Moja mama mieszka sama na wsi i nie ma z kim porozmawiać.”
  [textarea, 6 rows, large font]
  [🎤 Powiedz zamiast pisać]   (shown only if voice input is supported)
  Albo wybierz temat:  [Samotność] [Opieka nad bliskim] [Dojazd] [Praca] [Niepełnosprawność] [Młodzież]  (chips prefill the text)
  [label] Gdzie mieszkasz? (opcjonalnie)   [select/autocomplete: gmina/powiat]
  [ Znajdź rozwiązania ]        Masz pytania? Zadzwoń / napisz do ROPS

Krok 2 z 3: Doprecyzuj (max 2 questions, AI-chosen, radio buttons + „Nie wiem / Pomiń”)
  <fieldset><legend>Kogo najbardziej dotyczy problem?</legend> ( ) Osoby starsze ( ) Dzieci i młodzież ( ) Osoby z niepełnosprawnością ( ) Nie wiem

Krok 3 z 3: Wyniki
  <h1>Znaleźliśmy 3 rozwiązania</h1>  (role=status announces it)
  Card: <h3>Tytuł innowacji</h3> · 1-sentence summary · „Dlaczego to pasuje?” (2 bullets, plain words)
        · Gdzie to już działa · [Przeczytaj na głos] [Wyjaśnij prościej] [Zobacz szczegóły] [Zapytaj pracownika ROPS]
  Footer note: „Wyniki przygotowała sztuczna inteligencja…”  + [Nie pasuje? Opisz inaczej] [Zgłoś pomysł]
```

**Rules for seniors and low-skill users:**
- Show **„Krok X z 3”** progress as text, not a bar alone.
- **„Wstecz”** must always be visible and must not lose input.
- **One question per screen** in the wizard.
- No hidden menus on desktop. Use a hamburger only below ~768 px, and label it „Menu”.
- **Never auto-submit** after voice input: show the transcribed text so the user can correct it.
- No time limits. Autosave drafts.
- A confirmation page lists what happens next and when („Pracownik ROPS odpowie w ciągu 7 dni roboczych”).
- Offer a **non-digital channel** everywhere (phone, office address). Seniors trust that.
- Avoid percentages for match quality. Use words such as „Bardzo pasuje / Pasuje / Może pasować”.

### 3.4 „Ustawienia wyświetlania” (native, not an overlay)

- **Where:** a header button „Ustawienia wyświetlania” that opens a small panel.
- **Controls:**
  - text size (standard 100% / large 125% / very large 150%), applied by setting `html { font-size }` so everything
    in `rem` scales;
  - „Wysoki kontrast”: a `data-theme="contrast"` attribute that swaps CSS variables (yellow `#FFFF00` on black
    `#000000` = 19.56:1, white on black = 21:1, links underlined);
  - optional „Większe odstępy” (line-height 1.8, letter-spacing 0.05em);
  - optional „Ogranicz animacje”.
- **Persistence:** save to `localStorage` wrapped in try/catch. Also respect `prefers-contrast: more`,
  `prefers-reduced-motion` and `prefers-color-scheme`.

### 3.5 Voice input: Web Speech API `SpeechRecognition`, `lang = "pl-PL"`

| Browser | Support | Notes |
|---|---|---|
| Chrome (desktop + Android) | Yes (`webkitSpeechRecognition`) | Audio goes to **Google's cloud** by default. Chrome 139+ (Aug 2025) adds on-device mode (`processLocally`) once a language pack is installed. Polish on-device availability: (verify) |
| Edge | Yes (verify that pl-PL works; Edge uses Microsoft's service) | |
| Safari macOS 14.1+ / iOS 14.5+ | Yes (`webkitSpeechRecognition`) | Uses Apple's recognizer and may require Siri/Dictation to be enabled. Prompts for the microphone |
| Firefox | **No** (behind a flag only) | Hide the mic button |

**Implementation rules:**
- **Detect the feature** (`'SpeechRecognition' in window || 'webkitSpeechRecognition' in window`) and render the button
  only if it exists.
- **HTTPS is required** for the microphone (fine on Vercel and on localhost).
- **Settings:** `rec.lang='pl-PL'; rec.interimResults=true; rec.continuous=false`. Append the final transcript to the
  textarea; don't replace what the user already typed.
- **Button state:** `aria-pressed="true"` plus a visible „Słucham… mów teraz” label and a red dot with text. The status
  region announces „Nagrywanie rozpoczęte / zakończone”.
- **Privacy notice under the button (public-sector GDPR):** „Rozpoznawanie mowy wykonuje przeglądarka (np. Google lub
  Apple). Nie zapisujemy nagrania.”
- **Fallback if it fails** (`onerror`, e.g. `not-allowed`): „Nie mamy dostępu do mikrofonu. Możesz wpisać tekst.”
- **Server-side STT** (Whisper, Azure Speech) is a post-MVP option for Firefox and for privacy. Mention it in the pitch;
  don't build it now.

### 3.6 Read aloud: `speechSynthesis`, `lang = "pl-PL"`

- **Supported** in Chrome, Edge, Safari and Firefox. The voice depends on the operating system:
  - Chrome: „Google polski”;
  - macOS/iOS: „Zosia”;
  - Windows: „Microsoft Paulina”;
  - Edge also offers online natural voices for pl-PL. (verify the exact voice names)
- **Pick a voice** with `voices.find(v => v.lang.startsWith('pl'))`, and handle the `voiceschanged` event (Chrome loads
  voices asynchronously). If there is no Polish voice, hide the button.
- **Chunk long text into sentences.** Chrome is known to cut off long utterances. (verify that this still happens)
- **Controls:** „Przeczytaj na głos” / „Zatrzymaj czytanie”, plus an optional speed control (0.8× suits seniors).
- **Never autoplay.**
- **Use it on** result cards, AI answers and the ETR page.
- **Pitch framing:** TTS is a convenience for low-literacy and low-vision users, not a replacement for screen-reader
  compatibility.

### 3.7 PJM (Polish Sign Language) conventions and MVP realism

- **Convention on public sites:** a header link/icon „PJM” (sign-language hands icon + text „Polski Język Migowy”) that
  goes to a page with a **video of a deaf or CODA interpreter** explaining what the institution does. The video has
  captions and a short text summary.
- **Interpreter framing:**
  - the interpreter should take up at least **1/12 of the frame**, with **1/8 or more** recommended;
  - plain contrasting background and dark clothing;
  - captions on as well.
- **Deaf-first translation is preferred** (deaf translators). PJM and SJM are different: PJM is the natural language of the
  Deaf community.
- **Contact options for Deaf users:** e-mail, SMS, and an online video-interpreter service. Many public bodies link a
  remote PJM interpreter.
- **MVP: be honest.**
  - Build the PJM page as a **placeholder with the correct structure**: heading, video slot, captions, text summary, and
    contact via an online PJM interpreter, labelled „Nagranie w przygotowaniu”.
  - Add a **„Wersja w PJM” slot in the innovation-library data model** (`pjmVideoUrl`) so ROPS can add translations later.
  - **Do not use AI-generated sign-language avatars** as a claim of PJM accessibility. The Deaf community criticises them
    and their quality is unproven.
  - Cost line for the maintenance estimate: a professional PJM translation of a few minutes of video typically costs a
    few hundred złoty per minute. (verify with a quote, e.g. migam.org or Towarzystwo GEST)

### 3.8 Visual tokens: gov.pl-inspired, contrast pre-computed

The **gov.pl „Przewodnik Gov UI”** (aplikacje.gov.pl/app/govpl-front-styleguide) has sections for:
- typography;
- colour palettes;
- contrast;
- components: accordion, breadcrumbs, checkbox, radio, stepper, uploader, progress bar, datepicker, tab menu, tables,
  messages, footer;
- a licence section.

From its stylesheet: font **Open Sans**, primary blue **#0052A5**, text **#1B1B1B**, red **#D5233F**, grey **#F1F1F1**.
Use these as *inspiration* for a familiar public-sector look. **Do not use the national emblem (godło/„Herb”) or gov.pl
branding.** HubMI is a regional service, so use neutral or Małopolska-style branding. (verify the guide's licence before
copying any CSS)

| Token | Hex | Contrast (on white unless noted) | Use |
|---|---|---|---|
| text | #1B1B1B | 17.22:1 | body text |
| primary | #0052A5 | 7.64:1 (white on it: 7.64:1) | buttons, links (AAA) |
| primary-hover | #006CD7 | 5.09:1 | hover only |
| danger | #A7162D | 7.51:1 | error text (#D5233F = 5.07:1 is OK for icons and large text) |
| success | #16692C | 6.79:1 | success text |
| muted text | #656565 | 5.83:1 | hints (avoid lighter greys; `#71717A` = 4.83:1 is the floor) |
| border / input | #767676 | 4.54:1 | input outlines (shadcn `#E4E4E7` = 1.27:1, **fails**) |
| surface | #F1F1F1 | text on it 15.25:1 | panels |
| focus (light) | #1B1B1B outline + white offset | high | focus ring |
| focus (dark/contrast) | #FFD400 | 12.03:1 on #1B1B1B, 5.33:1 on #0052A5 | focus ring in contrast mode |
| contrast mode | #FFFF00 on #000000 | 19.56:1 | high-contrast theme |

**Typography:**
- base body size **18px** (1.125rem), line-height 1.5, max line length ~70ch;
- headings bold;
- links underlined;
- buttons ≥44 px tall with text labels (icons only alongside text).

### 3.9 Trust patterns for older and low-skill users

- **Say who runs the platform** on every page: „Serwis prowadzi Regionalny Ośrodek Polityki Społecznej w Krakowie”
  (prototype wording).
- **Explain what happens to their data** in one sentence before they type.
- **Never ask for PESEL** or real personal data. The brief also says no real personal data.
- **Show human contact options.**
- **Visibly label AI.** Let users **correct the AI** („To nie mój problem – opisz jeszcze raz”).

### 3.10 Good Polish public-sector reference UIs (for the mockup mood board)

- **gov.pl service pages:**
  - one H1 question;
  - a „Usługa w skrócie” box;
  - a step list;
  - a big primary button „Załatw sprawę”;
  - ETR/PJM icons in the header.
- **mObywatel (COI):**
  - large tiles with icon + label;
  - plain-language service names;
  - step-by-step flows with one action per screen;
  - the team ran user research with seniors (see the COI behind-the-scenes article).
- **Dostępna Małopolska (dostepna.malopolska.pl):** the region's own accessibility portal, covering WCAG, the deklaracja,
  ETR, PJM, accessible video and audits. **Cite it in the pitch** to show we know the client's own standards.
- **GOV.UK Design System patterns:** these are the best-documented accessible patterns and transfer directly:
  - „Question pages”;
  - „Check answers”;
  - „Error summary”;
  - „Confirmation page”;
  - „Step by step navigation”.

---

## 4. Template: „Deklaracja dostępności” (Polish, prototype)

Follows the EU model (Decision 2018/1523), the gov.pl example and the Ministry of Digital Affairs' technical conditions
(mandatory `id`s, `<time>` dates). Replace the `[…]` placeholders. **Use no real personal data.** In the prototype, use a
role address such as `dostepnosc@[domena]`, and don't invent real phone numbers. Link it from the footer as „Deklaracja
dostępności”.

```html
<h1>Deklaracja dostępności</h1>

<p id="a11y-wstep">
  <span id="a11y-podmiot">Regionalny Ośrodek Polityki Społecznej w Krakowie</span>
  zobowiązuje się zapewnić dostępność swojej <span id="a11y-zakres">strony internetowej</span>
  zgodnie z ustawą z dnia 4 kwietnia 2019 r. o dostępności cyfrowej stron internetowych i aplikacji mobilnych
  podmiotów publicznych. Deklaracja dostępności dotyczy strony internetowej
  <a id="a11y-url" href="https://[adres-prototypu]">HubMI.pl – Małopolski Hub Innowacji Społecznych</a>.
</p>
<p><strong>To jest prototyp przygotowany podczas HackYeah 2026.</strong></p>

<ul>
  <li>Data publikacji strony internetowej: <time id="a11y-data-publikacja" datetime="2026-10-04">4 października 2026 r.</time></li>
  <li>Data ostatniej istotnej aktualizacji: <time id="a11y-data-aktualizacja" datetime="2026-10-04">4 października 2026 r.</time></li>
</ul>

<h2>Stan dostępności cyfrowej</h2>
<p id="a11y-status">Strona internetowa jest częściowo zgodna z ustawą o dostępności cyfrowej stron internetowych
i aplikacji mobilnych podmiotów publicznych z powodu niezgodności lub wyłączeń wymienionych poniżej.</p>

<h2>Niedostępne treści</h2>
<h3>Niezgodność z załącznikiem</h3>
<ul>
  <li>Część filmów w Bibliotece Innowacji nie ma jeszcze audiodeskrypcji. Dla każdego filmu udostępniamy napisy i transkrypcję.</li>
  <li>Strona „Polski Język Migowy” nie zawiera jeszcze nagrania w PJM – nagranie jest w przygotowaniu.</li>
  <li>Odpowiedzi asystenta AI są generowane automatycznie i mogą nie spełniać wymagań prostego języka.</li>
</ul>
<h3>Treści nieobjęte przepisami</h3>
<ul>
  <li>Mapa wyzwań społecznych – wszystkie informacje z mapy są dostępne w widoku listy.</li>
</ul>

<h2>Przygotowanie deklaracji dostępności</h2>
<ul>
  <li>Data sporządzenia deklaracji: <time id="a11y-data-sporzadzenie" datetime="2026-10-04">4 października 2026 r.</time></li>
  <li>Deklarację sporządzono na podstawie samooceny przeprowadzonej przez zespół projektowy
      (testy automatyczne axe-core i Lighthouse, testy z klawiaturą i czytnikami ekranu NVDA i VoiceOver).</li>
</ul>

<h2>Udogodnienia</h2>
<ul>
  <li>Zmiana wielkości tekstu i tryb wysokiego kontrastu – przycisk „Ustawienia wyświetlania”.</li>
  <li>Wprowadzanie tekstu głosem i czytanie treści na głos (w obsługiwanych przeglądarkach).</li>
  <li>Przycisk „Wyjaśnij prościej” – uproszczona wersja opisów przygotowana przez AI.</li>
  <li>Informacje o serwisie w tekście łatwym do czytania (ETR).</li>
</ul>

<h2>Skróty klawiszowe</h2>
<p>Na stronie można korzystać ze standardowych skrótów klawiaturowych przeglądarki. Pierwszy klawisz Tab
wyświetla link „Przejdź do treści głównej”.</p>

<h2>Informacje zwrotne i dane kontaktowe</h2>
<p>Wszystkie problemy z dostępnością cyfrową tej strony możesz zgłosić do:
  <span id="a11y-kontakt">[koordynator do spraw dostępności / nazwa komórki]</span>,
  e-mail: <a id="a11y-email" href="mailto:[dostepnosc@domena]">[dostepnosc@domena]</a>,
  telefon: <a id="a11y-telefon" href="tel:[numer]">[numer]</a>.</p>
<p>Każdy ma prawo wystąpić z żądaniem zapewnienia dostępności cyfrowej tej strony internetowej lub jej elementów.
Możesz także zażądać udostępnienia informacji za pomocą alternatywnego sposobu dostępu.</p>

<h2 id="a11y-procedura">Obsługa wniosków i skarg związanych z dostępnością</h2>
<p>Żądanie musi zawierać: dane kontaktowe osoby zgłaszającej, wskazanie strony lub elementu strony, którego
dotyczy żądanie, oraz wskazanie dogodnej formy udostępnienia informacji, jeśli żądanie dotyczy udostępnienia
w formie alternatywnej.</p>
<p>Na Twoje zgłoszenie odpowiemy najszybciej jak to możliwe, nie później niż w ciągu 7 dni od jego otrzymania.
Jeżeli ten termin będzie dla nas zbyt krótki, poinformujemy Cię o tym. W tej informacji podamy nowy termin,
do którego poprawimy zgłoszone przez Ciebie błędy lub przygotujemy informacje w alternatywny sposób.
Ten nowy termin nie będzie dłuższy niż 2 miesiące.</p>
<p>Jeżeli nie będziemy w stanie zapewnić dostępności cyfrowej strony internetowej lub treści, zaproponujemy Ci
dostęp do nich w alternatywny sposób.</p>
<p>Jeżeli odmówimy realizacji żądania, możesz złożyć skargę [adres / e-mail do złożenia skargi].
Po wyczerpaniu tej procedury możesz złożyć wniosek do
<a href="https://bip.brpo.gov.pl/">Rzecznika Praw Obywatelskich</a>.</p>

<h2>Dostępność architektoniczna</h2>
<div id="a11y-architektura">
  <p>[Opis dostępności siedziby ROPS w Krakowie: wejście, windy, toalety, miejsca parkingowe, pętla indukcyjna,
  pies asystujący – do uzupełnienia przez ROPS.]</p>
</div>

<h2>Dostępność komunikacyjno-informacyjna</h2>
<div id="a11y-komunikacja">
  <p>[Możliwość kontaktu: e-mail, SMS, wideotłumacz PJM online – do uzupełnienia przez ROPS.]</p>
</div>

<h2>Aplikacje mobilne</h2>
<p id="a11y-aplikacje">Serwis nie ma aplikacji mobilnej. Strona działa w przeglądarce na telefonie.</p>
```

**Tools:**
- The Ministry of Digital Affairs' generator/validator at **deklaracja-dostepnosci.info** (generator + „walidator
  deklaracji”). Run our page through the validator and screenshot the result for the PDF. (verify that the validator
  accepts non-gov URLs)
- **Optional id:** `a11y-data-przeglad` (review date). Add it after the first review.

---

## 5. Tooling to prove compliance fast

### 5.1 Automated checks: pick two, and run them on the 5 key routes

Key routes:
1. `/`
2. `/dopasuj` (matchmaking)
3. `/wyniki`
4. `/biblioteka/[id]` (video)
5. `/admin` (dashboard)

| Tool | Use | Command / setup (~10 min) |
|---|---|---|
| **@axe-core/playwright** | CI gate + JSON/HTML report. Best signal-to-noise | `npm i -D @playwright/test @axe-core/playwright`. In a test: `const r = await new AxeBuilder({ page }).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']).analyze(); expect(r.violations).toEqual([]);`. For a pretty HTML report: `axe-html-reporter` (verify the package is maintained) |
| **Lighthouse** (built into Chrome DevTools) | **Pitch screenshot**: the „Dostępność 100” gauge | `npx lighthouse https://<url>/dopasuj --only-categories=accessibility --locale=pl --output=html --output-path=./a11y-lh.html`. CI: `npx @lhci/cli autorun` |
| **pa11y-ci** | Quick multi-URL CLI, axe + HTML_CodeSniffer runners | `npx pa11y-ci --sitemap https://<url>/sitemap.xml`, or a `.pa11yci` file with `{"defaults":{"standard":"WCAG2AA","runners":["axe","htmlcs"]},"urls":[…]}` |
| **WAVE** (browser extension, WebAIM) | Visual overlay of issues, good for a 3-second clip in the video | Install the extension and click it on each page |
| **axe DevTools** / **Accessibility Insights for Web** (MS) | Guided manual checks (tab stops visualisation) | Extensions. Accessibility Insights' „Tab stops” view makes a great keyboard-order screenshot |
| **Jasnopis** (jasnopis.pl, SWPS) | Polish readability score of our copy and AI output | Paste the text and screenshot the class score |
| **Contrast** | WebAIM Contrast Checker / Chrome DevTools colour picker | Values pre-computed in §3.8 |
| **Screen readers** | **NVDA** (free, most popular in PL, Polish voice) on Windows. **VoiceOver** on Mac (Cmd+F5) | 5-minute manual pass on the matchmaking flow |

**Automated tools catch only an estimated ~30–40% of WCAG issues**, so the manual keyboard and screen-reader pass is what
proves AA. State this in the pitch, because it shows maturity.

### 5.2 Component libraries with good accessibility

| Library | Verdict for HubMI |
|---|---|
| **React Aria / React Aria Components** (Adobe) | Best-in-class ARIA, keyboard and i18n, with **built-in Polish strings for pl-PL** (verify the coverage). Ideal for combobox (gmina autocomplete), date picker and table |
| **Radix UI / shadcn/ui** | Solid focus management and ARIA (Dialog, Tabs, Popover, Switch). Fastest to style. **Fix the default tokens**: `--border` (#E4E4E7 fails 1.4.11 for inputs), small `text-sm` sizes, and missing visible error summaries. Add our own focus ring |
| **GOV.UK Frontend** | Use for **patterns and copy structure** (error summary, check answers, question pages, fieldsets), not necessarily the package |
| **Headless UI** | Fine too |
| **Charts: Recharts** | Set `accessibilityLayer` (keyboard and ARIA on the chart, Recharts ≥2.x) **plus** the table toggle |
| **Maps: Leaflet / MapLibre** | Neither is fully accessible on its own. **The list view is the accessible path**. Keep the map as a supplement with a `role="region"` label |

### 5.3 Getting the accessibility report into the pitch PDF

1. Run Lighthouse (accessibility only, `--locale=pl`) on the 3–5 key routes and screenshot the **„Ułatwienia dostępu 100”**
   gauges (the Polish UI label may be „Ułatwienia dostępu” (verify)).
2. Run the Playwright + axe test and screenshot the terminal or HTML report: **„0 naruszeń WCAG 2.1 AA / 2.2 AA na 5
   ekranach”**.
3. Screenshot the Accessibility Insights tab-stops view of the matchmaking page (numbered focus order), which is visually
   striking.
4. Screenshot the deklaracja-dostepnosci.info validator result.
5. Put all of these on **one slide** („Dostępność – 20% oceny”) as a 2×2 grid with captions in Polish.
6. Keep the HTML reports in the repo (`docs/a11y/`) and link them from the README.

---

## 6. Mockups: fast tooling for the required UX/UI mockups

The brief requires mockups as well as a working demo link. The fastest credible path is to **build the real screens first,
then export them as mockups**:

| Option | Time | How |
|---|---|---|
| **Export real app screens** (recommended) | 10 min | Write a Playwright script that visits each route at **1440×900 and 390×844 (mobile)** and saves `page.screenshot({fullPage:true})`. Then frame them with a device mockup (e.g. shots.so or mockuphone) or put them on a single Figma/Penpot board with arrows. Include **one „senior mode” screenshot** (A++ + high contrast) beside the normal one. |
| **html.to.design** (Figma plugin) | 15 min | Import the live URL into editable Figma layers, then annotate the flow and a11y notes (focus order, landmarks) on the canvas. (verify that the free-tier limits are enough for ~5 pages) |
| **Penpot** (open source, browser) | 20 min | Figma alternative. Fine for annotated flow boards |
| **Excalidraw / tldraw** | 10 min | Hand-drawn low-fi wireframes of modules we *didn't* build (grant generator, tester, admin), labelled „makieta koncepcyjna” |
| **v0 / Figma Make / Uizard / Visily** | 15–30 min | AI-generated screens for unbuilt modules. Restyle them to our tokens so they don't look generic. Label them „koncepcja” |

**Accessibility annotation layer:** one board showing heading levels (H1/H2/H3 tags), landmarks, tab order numbers and
the live region. Juries rarely see this, and it directly supports the 20% criterion and the 10% for materials.

**Required mockup set (suggestion):**
1. Home („Opisz problem”)
2. Clarifying question
3. Results with „Wyjaśnij prościej” open
4. Innovation detail with video + captions + transcript
5. Idea card / grant generator step
6. Admin dashboard with table view
7. Senior mode (A++ / contrast) side-by-side
8. Mobile 390 px

---

## 7. Demonstrating accessibility in the 3-minute video and the 10-slide PDF

### 7.1 Video (≤3 min, mp4, Polish narration): an accessibility segment of about 35–45 s inside the main story

Suggested story: a senior in a small gmina looks for help for a lonely mother.

| Time | Shot | Narration (PL, plain) |
|---|---|---|
| 0:00–0:15 | Problem + persona | „Pani Krystyna, 68 lat, z gminy pod Nowym Sączem…” |
| 0:15–0:45 | **Voice input**: click 🎤 „Powiedz zamiast pisać”, speak, see the transcript, press „Znajdź rozwiązania” | „Nie musi pisać. Wystarczy powiedzieć.” |
| 0:45–1:15 | Results → „Wyjaśnij prościej” → „Przeczytaj na głos” (audio audible) | „Prosty język i czytanie na głos.” |
| 1:15–1:35 | **Keyboard only**: Tab from the skip link through the form with a visible focus ring; **NVDA or VoiceOver** announces „Odpowiedź gotowa. Znaleźliśmy 3 rozwiązania.” | „Działa bez myszy i z czytnikiem ekranu.” |
| 1:35–1:45 | Toggle A++ + high contrast; resize to mobile 320 px (layout reflows) | „Duży tekst, wysoki kontrast, telefon.” |
| 1:45–2:30 | Other modules (library with captions + transcript, idea card, admin trend chart → „Pokaż dane w tabeli”) | |
| 2:30–2:50 | Flash: Lighthouse 100 + axe „0 naruszeń” + Deklaracja dostępności page | „WCAG 2.1 AA, sprawdzone automatycznie i ręcznie.” |
| 2:50–3:00 | Close | |

**Rules for the video itself:**
- **Burn in Polish captions** (or ship an `.srt` file). It would be ironic to submit an inaccessible video about
  accessibility.
- Keep it readable: zoom the browser to 125–150% while recording.

### 7.2 10-slide PDF: where accessibility appears

1. Title + one-line value proposition
2. Problem (residents can't find existing social innovations)
3. Solution + user journey (matchmaking)
4. **Demo screens** (mockups)
5. Modules covered (matrix: built / mocked)
6. **„Dostępność dla każdego” (the 20% criterion):**
   - checklist ticks: WCAG 2.1 AA + 2.2, ETR/PJM entry points, voice, TTS, plain language with the Jasnopis score,
     senior mode, deklaracja;
   - the report screenshot grid (§5.3);
   - one sentence on the law (ustawa 2019 + Standardy dostępności polityki spójności).
7. AI architecture + transparency (AI Act Art. 50 label, human-in-the-loop)
8. Implementation potential: integrations, security, **running cost estimate** (add line items for **PJM translation and
   an external WCAG audit**: an audit by a certified auditor plus testers with disabilities; (verify the price range))
9. Roadmap: server-side STT, real ETR testing with PSONI, PJM videos, an audit with Dostępna Małopolska
10. Team + links (demo, repo, video)

---

## Sources

**Law and standards:**
- Ustawa o dostępności cyfrowej (text, with commentary): https://deklaracja-dostepnosci.info/prawo/udc
- Act text (Sejm print): https://orka.sejm.gov.pl/proc8.nsf/ustawy/3119_u.htm
- gov.pl, „Omówienie wymogów dostępności cyfrowej dla podmiotów publicznych”: https://www.gov.pl/web/dostepnosc-cyfrowa/omowienie-wymogow-dostepnosci-cyfrowej-dla-podmiotow-publicznych
- gov.pl, „Deklaracja dostępności [przykład]”: https://www.gov.pl/web/dostepnosc-cyfrowa/deklaracja-dostepnosci-przyklad
- Technical conditions and structure of the deklaracja (ids, `<time>`): https://www.deklaracja-dostepnosci.info/index.php/prawo/wtsd
- Dostępna Małopolska, deklaracja requirements: https://dostepna.malopolska.pl/dostepnosc-cyfrowa/deklaracja-dostepnosci/deklaracja-dostepnosci-wymagania
- Dostępna Małopolska portal (Urząd Marszałkowski Województwa Małopolskiego): https://dostepna.malopolska.pl/
- Dostępna Małopolska, ETR: https://dostepna.malopolska.pl/dostepnosc-informacyjno-komunikacyjna/tekst-latwy-do-czytania-i-zrozumienia
- PZN on the new declaration template: https://pzn.org.pl/wprowadzono-nowy-wzorzec-deklaracji-dostepnosci/
- MFiPR, complaint procedure: https://www.funduszeeuropejskie.gov.pl/strony/o-funduszach/fundusze-europejskie-bez-barier/dostepnosc/ustawa/skarga/brak-dostepnosci-cyfrowej/
- Polish EAA implementation act (26 Apr 2024): https://orka.sejm.gov.pl/proc10.nsf/ustawy/241_u.htm
- EAA overview (PL): https://www.sages.pl/blog/wcag-eaa-i-polska-ustawa-o-dostepnosci-obowiazkowe-standardy-ktore-nalezy-wdrozyc-przed-28-czerwca-2025-roku
- AccessibleEU, EN 301 549 v4.1.1 published (WCAG 2.2): https://accessible-eu-centre.ec.europa.eu/content-corner/news/european-accessibility-standard-en-301-549-has-been-updated-2026-09-07_en
- EN 301 549 (overview): https://en.wikipedia.org/wiki/EN_301_549
- WCAG 2.2 as ISO/IEC 40500:2025: https://www.pivotalaccessibility.com/2025/11/wcag-2-2-as-an-iso-standard-and-its-implications-for-accessibility-strategy-in-2026/
- Standardy dostępności dla polityki spójności 2021–2027 (Załącznik nr 2): https://funduszeue.kujawsko-pomorskie.pl/wp-content/uploads/2025/12/Standardy-dostepnosci-dla-polityki-spojnosci-2021-2027.pdf
- FEM (Małopolska), „Realizacja w praktyce zasady dostępności”: https://www.fundusze.malopolska.pl/sites/default/files/2025/02/10716/Realizacja%20w%20praktyce%20zasady%20dostepnosci.pdf

**Plain language, ETR, PJM:**
- gov.pl Redakcyjne ABC, plain-language rules: https://www.gov.pl/web/redakcyjne-abc/najwazniejsze-zasady-prostego-jezyka
- Służba Cywilna, „Prosty język”: https://www.gov.pl/web/sluzbacywilna/prosty-jezyk
- Ministry of Digital Affairs, „Prosty język”: https://www.gov.pl/web/cyfryzacja/prosty-jezyk
- PSONI, ETR instruction: https://psoni.org.pl/wp-content/uploads/2024/10/Czytam-i-wiem_INSTRUKCJA_z-okladka.pdf
- ZPE, ETR course: https://zpe.gov.pl/a/odbiorcy-tekstu-latwego-do-czytania-i-zrozumienia/DWDHDLff5
- PJM video practice: https://dostepnastrona.pl/tlumaczenie-na-pjm-polski-jezyk-migowy
- „Jak dobrze zamówić tłumaczenie na PJM”: https://kulturawrazliwa.pl/wp-content/uploads/2022/01/Jak-dobrze-zamowic-tlumaczenie-na-PJM-2.pdf

**Design systems and UI references:**
- gov.pl „Przewodnik Gov UI” (the styleguide's stylesheet was inspected for its font and colours): https://aplikacje.gov.pl/app/govpl-front-styleguide/
- COI, mObywatel 2.0: https://www.coi.gov.pl/realizacje/mobywatel-2-0
- COI, behind the scenes of mObywatel: https://www.coi.gov.pl/strefa-wiedzy/wpis/kulisy-pracy-nad-najpopularniejsza-publiczna-aplikacja-w-polsce
- Government design systems list: https://github.com/ctrimm/Government-Design-Systems-List
- GOV.UK Design System: https://design-system.service.gov.uk/

**Speech APIs:**
- MDN, Using the Web Speech API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API/Using_the_Web_Speech_API
- MDN, SpeechSynthesis: https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis
- Chrome 139, on-device speech recognition: https://developer.chrome.com/blog/new-in-chrome-139
- On-device explainer: https://github.com/WebAudio/web-speech-api/blob/main/explainers/on-device-speech-recognition.md
- Browser-support notes: https://www.assemblyai.com/blog/speech-recognition-javascript-web-speech-api
- Polish voices ("Google polski", "Zosia"): https://gist.github.com/PingNote/a9c4d0cf95690fa9eb6e3d06318ae8f1

**Tools (not fetched in this session; standard docs):**
- axe-core Playwright: https://github.com/dequelabs/axe-core-npm/tree/develop/packages/playwright
- pa11y-ci: https://github.com/pa11y/pa11y-ci
- Lighthouse CI: https://github.com/GoogleChrome/lighthouse-ci
- WAVE: https://wave.webaim.org/
- Accessibility Insights: https://accessibilityinsights.io/
- React Aria: https://react-spectrum.adobe.com/react-aria/
- Jasnopis: https://jasnopis.pl/
- deklaracja generator/validator: https://deklaracja-dostepnosci.info/
