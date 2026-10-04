# 01: ROPS Kraków and the Małopolska social-innovation ecosystem

Research date: 2026-10-04, ~06:30–06:55 CEST. Sources are public web pages fetched today. **(verify)** marks anything not confirmed from a primary source.
Companion seed data: `research/hubmi/rops-biblioteka-innowacji.json`, a scrape of all 115 Biblioteka entries with structured fields. Personal author names were removed and only organisation authors were kept.

## TL;DR

- **The Biblioteka Innowacji Społecznych is public and scrapeable.** It has **115 entries in 9 categories** ("Dla seniorów", "Dla dzieci, młodzieży i rodziny", etc.). Every entry uses the same 5-question template: *Na czym polega rozwiązanie? / Jakich problemów dotyczy innowacja? / Grupa docelowa / Kto może skorzystać z innowacji? / Czy to działa?* plus *Autorzy*. Each entry also has action buttons: *dowiedz się więcej* (PDF folder), *zobacz film* (YouTube), *pobierz materiały* (ZIP), *sprawdź zasady wykorzystania* (CC BY 4.0) and *otwórz w telefonie* (QR). 26 entries have a video, and 27 are flagged "INNOWACJA WYBRANA DO UPOWSZECHNIANIA". This is our matchmaking corpus. [1][2]
- **The Mapa Wyzwań Społecznych** is a 44-slide PDF published in Nov 2024 by the Dział Innowacji Społecznych. It covers **8 areas**: Rodzina i piecza zastępcza, Bezdomność, Niepełnosprawność, Ubóstwo, Integracja cudzoziemców, Zdrowie, Zdrowie psychiczne and Seniorzy. Each area has the same blocks: *Definicja obszaru → Analiza danych zastanych → Kluczowe wyzwania → PERSONA (Cele i potrzeby / Wyzwania / Motywacje) → Dowiedz się więcej*. ⚠️ Its data is **national, not Małopolska-specific** (the PDF says so). [3]
- **We can use the official grant form as the generator template.** It is the IWS 2.0 "Formularz aplikacyjny" (zał. 3), with 11 sections. Section 5 explicitly asks how the idea fits the Mapa Wyzwań. The **Karta oceny merytorycznej** scores 5 criteria from 0 to 10: innowacyjność, adekwatność do potrzeb, efektywność kosztowa, uniwersalność and wizja rozwoju. The maximum is 50, the pass mark is 21, innowacyjność needs at least 5 and every other criterion needs at least 4. We can implement this as an AI "pre-ocena" of an idea. [4][5][6]
- **The incubator lineage gives the "10 years" in the brief.** Małopolski Inkubator Innowacji Społecznych (MIIS) → Inkubator Dostępności (ended 31.12.2022) → Inkubator Włączenia Społecznego (POWER 4.1, 2020–2023, 6.18 mln zł; 251 applications, 60 grants, 9 innovations selected for dissemination) → **Inkubator Włączenia Społecznego 2.0** (FERS 5.1, 2024–06.2028, partner INNOAGH; 32 innovations to test, 12 to accelerate, 9 to disseminate; grants average 70k and max 120k zł). [7][8][9]
- **"Usługa Wrażliwa" is the real-world version of our "Middleman".** It is a FEM 2021–27 action 6.23 project that implements tested innovations in Małopolska communities. It has two tracks: **Ścieżka A**, grants up to 600 000 zł, and **Ścieżka B**, instruction and advisory support. It aims to implement at least 10 innovations through 2 grant calls. [10]
- **CUS in Małopolska.** The project "Małopolskie Centra Usług Społecznych" (FEM 6.23, 35.9 mln zł, 09.2024–10.2028) has ROPS as lead with **11 partner gminas**: Dobczyce, Grybów (miasto), Kęty, Korzenna, Liszki, Mogilany, Niepołomice, Oświęcim (miasto), Ryglice, Skrzyszów and Stary Sącz. It uses the "Kooperacje 3D" model. A separate **Małopolska Sieć Centrów Usług Społecznych** network was founded on 19.06.2024 by the CUS in Myślenice, Klucze, Skawina, Tarnów and Alwernia. [11][12]
- **Regional statistics for each gmina** are available in the **Internetowy Obserwator Statystyk Społecznych** (obserwator.rops.krakow.pl). It covers ageing (indeks starości, wskaźnik podwójnego starzenia, potencjał pielęgnacyjny), poverty-risk rates, reasons for receiving pomoc społeczna, DPS and more. We can use it to aggregate "trends" for each JST. [13]
- **No official "HubMI" announcement was found online. (verify)** The only public "HubMI" references are other HackYeah 2026 teams' GitHub repos. One competitor README cites jury weights of challenge fulfilment 40%, deployment potential 20%, WCAG 2.1 AA 20%, UI 10% and materials 10%. That is third-party information, so check it against the brief. [14][15]

---

## 1. ROPS Kraków and its social-innovation work

**Organisation.** Regionalny Ośrodek Polityki Społecznej w Krakowie is a regional unit of Województwo Małopolskie at ul. Piastowska 32, Kraków. The site is https://rops.krakow.pl/ [16]. Social innovation is run by the **Dział Innowacji Społecznych** (contact: iws@rops.krakow.pl, +48 12 422 06 36 ext. 34 or 27) [17]. The Mapa Wyzwań was prepared with a "konsultacja merytoryczna" from the **Dział Badań i Analiz** [3].

**Site sections relevant to us** (taken from the site menu [1]):
- *Innowacje społeczne* → **Biblioteka innowacji społecznych** (Kategorie + 9 categories), **Innowacje w małopolskich modelach**, **Publikacje ze świata innowacji**, **REGIOSTARS Awards 2025** (PL/EN pages about the Inkubator Włączenia Społecznego; whether it was a finalist or a winner is **(verify)**).
- *NABORY*: GRANTY NA INNOWACJE SPOŁECZNE, DORADZTWO dla JST, WIZYTY STUDYJNE, MENTORING ("mentorES", business mentors for przedsiębiorstwa społeczne; mentor and mentee calls are open until mid-Nov 2026) [18], SPOTKANIA SIECIUJĄCE, among others.
- *Programy i modele*: Strategia Rozwoju Województwa „Małopolska 2030”, Regionalny Plan Rozwoju Usług Społecznych i Deinstytucjonalizacji Województwa Małopolskiego, Program Wsparcia Rodziny „Rodzinna Małopolska 2030”, Regionalny Program Rozwoju Ekonomii Społecznej w Województwie Małopolskim do 2030 r., and **Małopolskie modele usług społecznych** [1].

**Incubator programmes:**

| Programme | Funding | Period | Key numbers | Partners |
|---|---|---|---|---|
| Małopolski Inkubator Innowacji Społecznych (MIIS) | POWER **(verify)** | ~2016–2019 **(verify)** | the source of many Biblioteka entries; the usage-rules PDF is named `Zasady_wykorzystania_innowacji_MIIS.pdf` [2] | – |
| Inkubator Dostępności | POWER **(verify)** | ended 31.12.2022 [1] | – | – |
| Inkubator Włączenia Społecznego (IWS) | POWER 2014–2020, Oś IV, Działanie 4.1 | 01.10.2020–31.12.2023 | 6 176 022 zł; **251** applications assessed, **60** grants, **9** innovations disseminated, 3 "Maratony Kreowania Innowacji", 28 focus meetings, >1000 people reached. Innovators: 13 individuals, 28 NGOs, 10 informal groups, 4 OPS/JST, 5 enterprises [8] | **Fundacja Rozwoju Demokracji Lokalnej im. Jerzego Regulskiego**, **Uniwersytet Jagielloński** [8] |
| **Inkubator Włączenia Społecznego 2.0** (the "fourth incubator") | FERS 2021–2027, Oś V, **Działanie 5.1 Innowacje społeczne**, EFS+ | 01.01.2024–30.06.2028 | **32** innovations to test, **12** to accelerate, **9** recommended for national dissemination; grant average 70 000 zł, max 120 000 zł, 100% funded with no own contribution and simplified settlement; nationwide; call ran 13.11–13.12.2024 [7][9] | **Krakowskie Centrum Innowacyjnych Technologii INNOAGH sp. z o.o.** [7] |
| Usługa Wrażliwa – upowszechnianie innowacji społecznych w środowiskach lokalnych | FEM 2021–2027, Działanie 6.23 | ongoing | at least 10 innovations implemented through 2 grant calls (Tura I and Tura II have been decided); grants up to **600 000 zł**; draws on innovations from MIIS, Inkubator Dostępności and IWS [10] | – |

**Who can be an innovator:** an individual, an NGO, a public or private entity including companies and social-economy entities, or an informal group [7][9].

**Support offered before applying** (vocabulary we can reuse): *konsultacje indywidualne*, *konsultacje specjalistyczne* and *spacery poznawcze* (meeting the target group), available on site or online [9]. Innovations for dissemination are chosen by the **Rada Innowacji Społecznych** [8].

**What counts as a social innovation (official wording, IWS 2.0)** [9]: a new solution on the scale of Poland; a method that works better than current ones; an improvement to an existing form of support; or an optimisation following the principle "więcej za mniej".

### Biblioteka Innowacji Społecznych

- URL: https://rops.krakow.pl/innowacje-spoleczne/biblioteka-innowacji-spolecznych/kategorie [1]
- **Size: 115 entries** (scraped 2026-10-04; one title, "Dialog ponad kulturami", appears twice for two different innovations). That is fewer than the ~200 in the brief, so the rest of the portfolio is not published here. **(verify on site)**

| Category (PL, exact) | URL slug | # |
|---|---|---|
| Dla dzieci, młodzieży i rodziny | dla-dzieci-mlodziezy-i-rodziny | 21 |
| Dla osób z niepełnosprawnością sensoryczną | dla-osob-z-niepelnosprawnoscia-sensoryczna | 20 |
| Dla seniorów | dla-seniorow | 20 |
| Dla osób o ograniczonej mobilności | dla-osob-o-ograniczonej-mobilnosci | 18 |
| Dla osób z niepełnosprawnością intelektualną | dla-osob-z-niepelnosprawnoscia-intelektualna | 14 |
| Dla zdrowia i medycyny | dla-zdrowia-i-medycyny | 9 |
| Dla cudzoziemców | dla-cudzoziemcow | 6 |
| Dla rynku pracy | dla-rynku-pracy | 5 |
| Dla osób w kryzysie bezdomności | dla-osob-w-kryzysie-bezdomnosci | 2 |

- **Entry URL pattern:** `/innowacje-spoleczne/biblioteka-innowacji-spolecznych/{kategoria},{slug}`
- **Entry structure** (consistent across all 115) [2]:
  1. *Na czym polega rozwiązanie?* (what it is)
  2. *Jakich problemów dotyczy innowacja?* (the problem)
  3. *Grupa docelowa* (end beneficiaries)
  4. *Kto może skorzystać z innowacji?* (**the implementing institutions**, such as DPS, ŚDS, OPS, JST, NGOs and schools; this is the key field for the JST and Middleman use cases)
  5. *Czy to działa?* (test results; present in 111 of 115)
  6. *Autorzy* (individuals, NGOs or gminas)
  - Action buttons: *dowiedz się więcej* (a PDF folder, for the 27 disseminated entries), *zobacz film* (YouTube, 26 entries), *pobierz materiały* (a ZIP on every entry, at `rops.krakow.pl/pliki/IS/bibloteka/{slug}.zip`), *sprawdź zasady wykorzystania* (CC BY 4.0 or the MIIS usage-rules PDF), *otwórz w telefonie* (QR).
- **Videos:** yes, 26 YouTube links, mostly on the "wybrana do upowszechniania" entries [2].
- **Innowacje w małopolskich modelach** lists 9 senior innovations embedded in the Małopolskie Modele Usług Społecznych: Senior CUDER, Ścieżka motosensoryczna, Organizator kompleksowej opieki w miejscu zamieszkania, BaWita, Mobilne centrum pomocy, Centrum antydepresyjne, Terapeuta przestrzeni, Ścieżka treningu umysłu and Talerze zdrowia [19]. These are good demo cases for the brief's ageing and loneliness themes.

**15 example innovations** (all from [2]; individual entry URLs are in the JSON):

| Innowacja | Kategoria | One-line description | Grupa docelowa |
|---|---|---|---|
| **Centrum antydepresyjne** (Gmina Miechów) | Seniorzy | home-based work with depressed seniors using dog and cat therapy, to reduce depression and suicide risk in rural areas | lonely older people needing care at home, and their carers |
| **Mobilne centrum pomocy dla osób starszych** | Seniorzy | mobile support for seniors in remote rural areas with poor transport | dependent seniors in villages |
| **Organizator kompleksowej opieki w miejscu zamieszkania** ★ | Seniorzy | a programme coordinating comprehensive care at home for multimorbid elderly people | older people with multiple conditions |
| **Merkury** ★🎬 | Seniorzy | web simulator of an ATM, parking meter, parcel locker and self-checkout, plus instructional films | seniors afraid of self-service machines (**digital exclusion**) |
| **E-rzecznik konsumenta seniora** | Seniorzy | app giving seniors simple legal advice on consumer issues | older people |
| **Kody QR na pomoc seniorom** | Seniorzy | unique QR codes with key information for seniors with memory disorders | seniors, including people with dementia |
| **BaWita** ★🎬 | Seniorzy | wooden manipulation board for memory and manual skills | people with early dementia and stroke survivors |
| **Senior CUDER** ★🎬 | Seniorzy | card game strengthening seniors' motivation and skills | older people |
| **Edu gra HaHaHa** | Seniorzy | board game teaching laughter yoga for seniors' mental wellbeing | seniors with limited mobility or perception |
| **Gra o zdrowie** ★🎬 | Zdrowie | therapeutic board game for returning to the labour market | people in **mental-health crisis** |
| **Inteligentny organizer do leków** | Zdrowie | pill organiser with sensors and signalling | seniors managing their own medication (polypharmacy) |
| **Telerehabilitacja oddechowa** | Zdrowie | remote respiratory rehabilitation | seniors with limited mobility and people with respiratory dysfunction |
| **Mobilna giełda pracy** (Gmina Charsznica) | Rynek pracy | support model for economically inactive women in rural areas | rural women |
| **Wiejski program pomocy osobom w kryzysie bezdomności – Ścieżka Feniksa** | Bezdomność | holistic rural homelessness support model | people experiencing homelessness |
| **Strażnik** ★🎬 | Niepełnosprawność sensoryczna | app detecting sound alarms (CO, fire) and passing them on to Deaf users | Deaf and hard-of-hearing people |
| **Hear IT** ★🎬 | Niepełnosprawność sensoryczna | e-learning in PJM for Deaf people entering IT | Deaf adults |
| **koMIX życiowy** ★🎬 | Dzieci/młodzież | therapeutic board game for teenagers in placówki opiekuńczo-wychowawcze | care-home teens |

★ = "wybrana do upowszechniania", 🎬 = has a video.

## 2. Mapa Wyzwań Społecznych, "Kondycja Małopolski" and the Obserwatorium

**Mapa Wyzwań Społecznych** [3]
- URL: https://rops.krakow.pl/mpliki/IS/IWS_20/za._nr_2._Mapa_Wyzwa_Spoecznych.pdf (zał. 2 to the IWS 2.0 call notice). The file is a PowerPoint-exported PDF with 44 slides, dated 6 Nov 2024 and tagged as accessible.
- It explicitly states that the **data is national (ogólnopolskie)** and that the map was prepared for IWS 2.0.
- **8 areas (exact):** 1. Rodzina i piecza zastępcza · 2. Bezdomność · 3. Niepełnosprawność · 4. Ubóstwo · 5. Integracja cudzoziemców · 6. Zdrowie · 7. Zdrowie psychiczne · 8. Seniorzy.
- **Structure of each area:** *Definicja obszaru*, *Analiza danych zastanych* (with sources), *Kluczowe wyzwania* (bullets), a fictional **PERSONA** (*Cele i potrzeby / Wyzwania / Motywacje*), and *Dowiedz się więcej!* (report list).
- Personas: Ania i Staś (foster care), Kuba, 22 (youth homelessness), Krystian, 38 (tetraplegia, lonely), Tomek, 60 (rural poverty), Swietłana, 37 (Ukrainian refugee), Stanisław, 56 (carer, health), Mateusz, 17, and Karina, 41 (mental health), and **Janina, 73** (a widow living alone in a small town, lonely, with polypharmacy). Janina is an ideal demo persona for the brief's loneliness, ageing and digital-exclusion themes.
- **Key data points** (national, as cited in the Mapa):
  - Seniors: their biggest problems are "zdrowie, samotność, finanse i potrzeba cyfryzacji". Loneliness is correlated with material situation. Polypharmacy and architectural barriers are flagged. Challenges include developing seniors' digital competences and access to usługi opiekuńcze in gminas.
  - Zdrowie psychiczne: rising suicide attempts among youth; mental-health care is ~3% of NFZ spending; the challenge is the shift "z opieki instytucjonalnej na środowiskową".
  - Niepełnosprawność: 5.4 mln people (14.3%, NSP 2021); employment rate for ages 16–64 was 30.1% at the end of 2023.
  - Ubóstwo: extreme poverty affected 6.6% of households in 2023 (+2 pp).
  - Piecza zastępcza: +3.5% children in foster care in 2023 compared with 2022.
  - Zdrowie: loneliness was intensified by the pandemic, mostly among seniors living alone.

**"Kondycja Małopolski" and Małopolskie Obserwatorium Polityki Społecznej**
- **Internetowy Obserwator Statystyk Społecznych** (https://obserwator.rops.krakow.pl/) came out of ROPS's Małopolskie Obserwatorium Polityki Społecznej (2008–2015) [13][20]. It offers a "PORTRET GMINY I POWIATU" with indicators in these groups: LUDNOŚĆ (60+, wskaźnik podwójnego starzenia, potencjał pielęgnacyjny, indeks starości, ...), GOSPODARSTWA DOMOWE (poverty-risk rates), RODZINA, POMOC SPOŁECZNA – KADRA, POWODY KORZYSTANIA (ubóstwo, bezdomność, niepełnosprawność, ...), BENEFICJENCI and DPS. It also has a "differenceanalysis" view. The export format is HTML tables or charts; whether there is CSV export is **(verify)**.
- Obserwatorium reports live under `rops.krakow.pl/pliki/raporty_Obserwatorium/`, for example "Opiekunowie rodzinni osób starszych" (report and presentation) and "Kondycja małopolskiej rodziny" [20]. A secondary source gives Małopolska's population aged 65+ as 473 819, or 14.1%. That is an old figure **(verify; likely outdated)** [20].
- I did **not** find a page literally titled "Kondycja Małopolski". It is probably on-site material or a report series name **(verify)**. Another team's repo also uses that label [14].
- The separate **Małopolskie Obserwatorium Rozwoju Regionalnego** (obserwatorium.malopolska.pl) belongs to the Urząd Marszałkowski and covers demography and settlement topics such as suburbanisation around Kraków [20].

## 3. Kanwa innowacji społecznych

- **No public ROPS Kraków "Kanwa innowacji społecznych" template was found. (verify; it is likely handed out on site.)**
- The closest official structure is the IWS 2.0 **Formularz aplikacyjny** (zał. 3) [4]. Its sections are:
  1. Tytuł innowacji
  2. Dane pomysłodawcy (osoba fizyczna / podmiot / grupa nieformalna)
  3. **Opis innowacji** (what it is: produkt, aplikacja, model pracy or rozwiązanie technologiczne; how it supports włączenie społeczne; how it fits **deinstytucjonalizacja**)
  4. **Innowacyjność rozwiązania** (similar solutions in Poland or the world, and what is new)
  5. **Diagnoza problemu** (statistics, reports, *fit with the Mapa Wyzwań Społecznych*)
  6. **Opis odbiorców innowacji** (needs, and why they are excluded)
  7. **Zmiana jaką wprowadza innowacja**
  8. **Wizja przyszłości innowacji** (scaling, other groups, ease of use, wdrażalność)
  9. **Plan działania i koszty**, split into an *Okres przygotowawczy* of at most 3 months and an *Okres testowania* of at most 9 months (Faza I and Faza II), with each action given a timing and a cost
  10. **Wnioskowana kwota grantu**
  11. **Zespół projektowy i jego doświadczenie**
  12. Oświadczenia
- **Karta oceny merytorycznej** (zał. 5) [5]: *Innowacyjność rozwiązania*, *Adekwatność do potrzeb odbiorców i użytkowników* (including "Czy pomysł odpowiada na wyzwanie zgodne z Mapą Wyzwań Społecznych?"), *Efektywność kosztowa*, *Uniwersalność* and *Wizja rozwoju pomysłu w przyszłości*. Each is scored 0–10. The maximum is 50 and the minimum is 21, with innowacyjność at least 5 and the rest at least 4 each. Other documents in the call: Ogłoszenie o naborze (zał. 1), Procedury (zał. 1 do ogłoszenia), Karta oceny formalnej (zał. 4) and Karta oceny prezentacji wnioskodawcy (zał. 6) [6].
- Suggestion: build the in-app "Kanwa" from the form's sections 3–8 (problem → odbiorcy → rozwiązanie → zmiana → innowacyjność → skala/wdrożenie → zasoby/koszty → zespół). This mirrors generic social-innovation canvases. Label it as "inspirowana formularzem IWS 2.0" rather than claiming it is the official ROPS kanwa.

## 4. HubMI, strategy documents and CUS

- **HubMI / "Małopolski Hub Innowacji Społecznych":** no official public announcement or strategy document was found on rops.krakow.pl or in web search. **(verify)** Only HackYeah 2026 competitor repos mention it [14][15].
- **Strategy and programme documents** listed on the ROPS site (contents not reviewed, so **verify** before citing details) [1]:
  - Strategia Rozwoju Województwa „Małopolska 2030”
  - Regionalny Plan Rozwoju Usług Społecznych i Deinstytucjonalizacji Województwa Małopolskiego (relevant to the deinstitutionalisation framing used in the grant form)
  - Program Wsparcia Rodziny „Rodzinna Małopolska 2030”
  - Regionalny Program Rozwoju Ekonomii Społecznej w Województwie Małopolskim do 2030 r. (Uchwała ZWM nr 701/22) [21]
  - Małopolskie Ramowe Programy and Małopolskie modele usług społecznych
- **Centra Usług Społecznych:**
  - *Projekt „Małopolskie Centra Usług Społecznych”* [11]: FEM 2021–2027 Działanie 6.23, 01.09.2024–31.10.2028, budget 35 917 986,98 zł. ROPS is lead with 11 partner gminas: **Dobczyce, Miasto Grybów, Kęty, Korzenna, Liszki, Mogilany, Niepołomice, Gmina Miasto Oświęcim, Ryglice, Skrzyszów and Stary Sącz**. The phases are diagnosis (09.2024–05.2025), local service programmes and CUS launch (06–08.2025), and service delivery (09.2025–10.2028) [22]. It is based on the **"Kooperacje 3D"** model and publishes the guide "ABC Diagnozy. Badanie podaży i popytu na usługi społeczne w gminie".
  - *Małopolska Sieć Centrów Usług Społecznych (MSCUS)* [12]: founded on 19.06.2024 by the directors of the CUS in **Myślenice, Klucze, Skawina, Tarnów and Alwernia**. It is a voluntary network supported by ROPS.
  - The total count of CUS in Małopolska is not confirmed. It is at least 5 existing plus 11 in the project, with possible overlap. Krajowe Forum CUS has a national database at forumcus.pl/baza-cus **(verify)**.

## 5. Partners and departments

- **ROPS departments:** Dział Innowacji Społecznych (incubators and Biblioteka) and Dział Badań i Analiz (data and Obserwatorium) [3][17]. Owner: Województwo Małopolskie / Urząd Marszałkowski Województwa Małopolskiego.
- **Project partners:** Fundacja Rozwoju Demokracji Lokalnej im. Jerzego Regulskiego and Uniwersytet Jagielloński (IWS 2020–2023) [8]; Krakowskie Centrum Innowacyjnych Technologii **INNOAGH** sp. z o.o., the AGH tech-transfer company (IWS 2.0) [7]; and 11 gminas (Małopolskie CUS) [11].
- **Funders:** Ministerstwo Funduszy i Polityki Regionalnej (IWS commissioned under POWER and FERS), EFS+, and FEM 2021–2027 (the Małopolska regional programme) [7][10].
- **Innovation authors** in the Biblioteka include NGOs (e.g. Stowarzyszenie Edukacji Pozaformalnej „Meritum”, Fundacja HumanDoc, Stowarzyszenie Ku Dobrej Nadziei), gminas (Gmina Miechów, Gmina Charsznica), OPS, social enterprises and universities [2].
- **Governance term:** "Rada Innowacji Społecznych" selects innovations for dissemination [8].

## 6. HackYeah: previous ROPS/Małopolska tasks and the 2026 jury

- The hackyeah.pl pages "Winners 2024" and "Winners 2025" exist in search results, but the 2025 page returned 404 to our fetcher. **Previous ROPS or Małopolska social-policy tasks and their winners were not confirmed. (verify)** [23]
- The HubMI jury and mentors are **not public online. (verify on site)**
- **Competitor signals** (public GitHub repos, which are third-party):
  - "Drop-the-Base/malopolski-hub-2026": 7 modules plus a "Rejestr wyzwań gminnych", TF-IDF matching, SUS tester and ETR mode [15].
  - "Flychuban/juz-dziala": "Już Działa", with answers drawn only from ROPS cards with citations and an honest "nie wiem"; its README cites the jury weights quoted in the TL;DR [14].
  - "imflawlezz/hackyeah-2026" and "JaQubus/Spolecznik".
  - Expect most teams to have the same seven modules. Differentiation needs to come from real data, citations, accessibility and deployability.

---

## Implications for our MVP

**Vocabulary for the Polish UI** (official ROPS terms):
- *innowacja społeczna*, *innowator / innowatorka*, *pomysłodawca*, *grupa nieformalna*, *grantobiorca*
- *Biblioteka Innowacji Społecznych*, *Mapa Wyzwań Społecznych*, *obszar*, *kluczowe wyzwania*, *persona*, *analiza danych zastanych*
- Entry headings used verbatim: *Na czym polega rozwiązanie?*, *Jakich problemów dotyczy innowacja?*, *Grupa docelowa*, *Kto może skorzystać z innowacji?*, *Czy to działa?*
- Actions: *zobacz film*, *pobierz materiały*, *sprawdź zasady wykorzystania*, *otwórz w telefonie*
- Programme stages: *inkubacja → testowanie → akceleracja → upowszechnianie → wdrożenie*; *innowacja wybrana do upowszechniania*
- Grant terms: *nabór*, *formularz aplikacyjny*, *karta oceny merytorycznej*, *okres przygotowawczy / okres testowania*, *wnioskowana kwota grantu*
- Pre-application support: *konsultacje indywidualne / specjalistyczne*, *spacery poznawcze*
- Policy terms: *włączenie społeczne*, *wykluczenie społeczne*, *deinstytucjonalizacja*, *usługi społeczne*, *CUS*, *JST*, *OPS*, *DPS*, *ŚDS*, *Kooperacje 3D*, *Usługa Wrażliwa*, *ETR (tekst łatwy do czytania)*, *PJM*

**Data we can seed now:**
1. `research/hubmi/rops-biblioteka-innowacji.json` has 115 real innovations with category, title, URL, the 5 structured fields, video URLs, PDF folder, ZIP, the "wybrana do upowszechniania" flag and organisation authors. This is a ready-made matchmaking corpus. Embed *Jakich problemów dotyczy* together with *Grupa docelowa*, and use *Kto może skorzystać* for JST and institution matching. Always link back to the ROPS entry URL.
2. The Mapa Wyzwań's 8 areas, their key challenges and 9 personas give the taxonomy for tagging needs and trends. Map problems to areas, and areas to Biblioteka categories. The Mapa areas and Biblioteka categories differ, so define a crosswalk: e.g. Seniorzy→Dla seniorów, Zdrowie / Zdrowie psychiczne→Dla zdrowia i medycyny, Niepełnosprawność→the 3 disability categories, Integracja cudzoziemców→Dla cudzoziemców, Bezdomność→Dla osób w kryzysie bezdomności, Ubóstwo→Dla rynku pracy and others, Rodzina i piecza→Dla dzieci, młodzieży i rodziny.
3. The grant-form sections and scoring card can drive the grant-application generator and an AI "pre-ocena" against the 5 criteria (0–10, pass at 21 or more).
4. The list of CUS gminas (the 11 project gminas and the 5 MSCUS founders) can serve as demo JST users for the Middleman module. Gmina-level indicators can come from obserwator.rops.krakow.pl, for example to show an ageing index next to a recommended innovation. Mark these as illustrative if they are typed in by hand.

**What the jury will probably care about:**
- Grounding in **ROPS's own assets**: real Biblioteka entries with links, Mapa Wyzwań areas, and the IWS form and scoring. Do not invent innovations; label demo data clearly.
- The **pipeline from incubation to implementation in JST**, which is ROPS's actual current mission via Usługa Wrażliwa and CUS. The Middleman should output something like an "implementation plan for a CUS/OPS" built from *Kto może skorzystać* and *Czy to działa?*.
- **WCAG 2.1 AA and simple language (ETR):** ROPS publishes its own accessibility standards ("Standardy tworzenia dostępnych dokumentów, treści, multimediów i wydarzeń on-line w ROPS w Krakowie", 2022) and the Biblioteka itself contains ETR innovations [2].
- The **brief's themes** of loneliness, ageing, mental health and digital exclusion are best demoed with the persona *Janina, 73* matched to Merkury, Centrum antydepresyjne, Mobilne centrum pomocy, Kody QR and Organizator kompleksowej opieki.
- **Ease of updating by ROPS staff** (an admin panel, CSV/JSON import) and **trend aggregation** (needs by Mapa area and by gmina).
- **Transparency** about what is AI-generated and which source was cited, with a "nie wiem" fallback.

## Sources

1. ROPS Kraków, Biblioteka – Dla seniorów (category page and site menu): https://rops.krakow.pl/innowacje-spoleczne/biblioteka-innowacji-spolecznych/dla-seniorow
2. ROPS, Biblioteka entries, e.g. BaWita https://rops.krakow.pl/innowacje-spoleczne/biblioteka-innowacji-spolecznych/dla-seniorow,bawita and Centrum antydepresyjne https://rops.krakow.pl/innowacje-spoleczne/biblioteka-innowacji-spolecznych/dla-seniorow,centrum-antydepresyjne (all 115 scraped; URLs in the JSON). Category index: https://rops.krakow.pl/innowacje-spoleczne/biblioteka-innowacji-spolecznych/kategorie
3. Mapa Wyzwań Społecznych (PDF, Nov 2024): https://rops.krakow.pl/mpliki/IS/IWS_20/za._nr_2._Mapa_Wyzwa_Spoecznych.pdf
4. Formularz aplikacyjny IWS 2.0 (wzór): https://rops.krakow.pl/mpliki/IS/IWS_20/za._3._Formularz_aplikacyjny_wzor.pdf
5. Karta oceny merytorycznej (wzór): https://rops.krakow.pl/mpliki/IS/IWS_20/za._5._Karta_Oceny_merytorycznej_wzor.pdf
6. IWS 2.0 call page: https://rops.krakow.pl/nabory-szkolenia-granty-dotacje-wizyty-studyjne-studia-specjalizacje-superwizje/granty-na-innowacje-spoleczne,nabor-aplikacji-wnioskow-na-innowacje-spoleczne-w-ramach-projektu-pn-inkubator-wlaczenia-spolecznego-20
7. IWS 2.0, "O projekcie": https://rops.krakow.pl/realizowane-projekty-i-zadania/inkubator-wlaczenia-spolecznego-20,o-projekcie
8. IWS (2020–2023) summary: https://rops.krakow.pl/aktualnosci/zakonczylismy-projekt-inkubator-wlaczenia-spolecznego-co-za-nami
9. IWS 2.0 project index: https://rops.krakow.pl/realizowane-projekty-i-zadania/inkubator-wlaczenia-spolecznego-20 and the call page [6]
10. Usługa Wrażliwa, "O projekcie": https://rops.krakow.pl/realizowane-projekty-i-zadania/usluga-wrazliwa-upowszechnianie-innowacji-spolecznych-w-srodowiskach-lokalnych,o-projekcie
11. Małopolskie Centra Usług Społecznych, "O projekcie": https://rops.krakow.pl/realizowane-projekty-i-zadania/projekt-malopolskie-centra-uslug-spolecznych,o-projekcie
12. Małopolska Sieć CUS: https://rops.krakow.pl/gremia-i-zespoly/malopolska-siec-centrow-uslug-spolecznych
13. Internetowy Obserwator Statystyk Społecznych: https://obserwator.rops.krakow.pl/
14. Competitor repo "Już Działa": https://github.com/Flychuban/juz-dziala
15. Competitor repo: https://github.com/Drop-the-Base/malopolski-hub-2026
16. ROPS home page: https://rops.krakow.pl/
17. Dział Innowacji Społecznych contact: https://rops.krakow.pl/kontakt/dzial-innowacji-spolecznych
18. Mentoring (mentorES): https://rops.krakow.pl/nabory-szkolenia-granty-dotacje-wizyty-studyjne-studia-specjalizacje-superwizje/mentoring
19. Innowacje w małopolskich modelach: https://rops.krakow.pl/innowacje-spoleczne/innowacje-w-malopolskich-modelach
20. Obserwatorium reports: https://rops.krakow.pl/pliki/raporty_Obserwatorium/Opiekunowie_rodzinni_os__b_starszych_raport.pdf, https://rops.krakow.pl/pliki/raporty_Obserwatorium/do_wrzycenia_na_www/kondycja_malopolskiej_rodziny.pdf, https://www.obserwatorium.malopolska.pl/
21. Regionalny Program Rozwoju Ekonomii Społecznej do 2030: https://rops.krakow.pl/mpliki/DES/Regionalny_Program_Rozwoju_Ekonomii_Spoecznej_w_Wojewodztwie_Maopolskim_do_2030_r..pdf
22. Gmina Korzenna on the CUS project timeline: https://www.korzenna.pl/blog/2025/01/02/projekt-malopolskie-centra-uslug-spolecznych/
23. HackYeah winners pages: https://hackyeah.pl/winners-2024/ and https://hackyeah.pl/winners-2025/ (404 when fetched)
