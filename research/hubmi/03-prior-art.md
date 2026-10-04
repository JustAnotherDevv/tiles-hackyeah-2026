# HubMI.pl: prior art and competitive landscape

Research only. Compiled Sun 4 Oct 2026, about 06:30–06:55 CEST, from web searches, page fetches and public GitHub metadata.
Items marked **(verify)** come from search snippets, are inferences, or come from memory and were not confirmed on a primary page.
Statements about competitor repos describe what their READMEs claim. We did not run any of them.

---

## TL;DR

1. **The arena is crowded and converging.** At least 9 public GitHub repos target this exact HubMI.pl / ROPS task at HackYeah 2026.
   Most claim **all 7 modules**, RAG or embedding matchmaking, voice input, WCAG toggles, a "Middleman" implementation-plan generator and a trends view.
   "Seven modules plus a chat" no longer stands out; it is the baseline. See §6.
2. **The strongest rival, "Już Działa"** (<https://github.com/Flychuban/juz-dziala>, live at <https://juz-dziala.vercel.app>), sets the bar.
   It grounds answers only in ROPS sources (114-item Biblioteka Innowacji Społecznych, Mapa Wyzwań Społecznych, IWS 2.0 docs, GUS BDL) and gives verbatim citations.
   It refuses when unsure and hands over to a ROPS expert, publishes a frozen 20-case eval (94% top-3), reports 0 axe-core violations on 19 screens, and uses Claude.
3. **EU prior art: the Social Innovation Match (SIM) database** (ESF+ Social Innovation+, run by the European Competence Centre for Social Innovation, ECCSI).
   It is a validated case-study catalogue with filters, partner search and a national-validator workflow (about 15 working days).
   It is **catalogue-first, English-only and has no problem-first or AI matching**, which is exactly the gap module I fills.
   <https://european-social-fund-plus.ec.europa.eu/en/social-innovation-match>
4. **Transfer methodology exists, and almost nobody productises it.** SI+ frames transfer as separating **elements that travel** (methods, tools, business model, principles, technology) from **elements to adapt**, with **originator** and **adopter** roles.
   A Middleman that outputs a "rdzeń vs. elementy do dostosowania" (core vs. adaptable) card is grounded in EU guidance. Rivals output generic implementation plans.
   <https://www.socialinnovationplus.eu/how-can-social-innovations-be-transferred-to-different-contexts/>
5. **The Polish innovation stock is fragmented.** Sources: innowacjespoleczne.pl (150+ innovations from PO WER and FERS 5.1, tag search), ROPS Kraków's Biblioteka, ROPS Poznań "Włącznik", INNOES, dobrepraktyki.pl (500+ JST practices with a map), and dead EQUAL/PO KL databases.
   None of them takes a resident's problem as input. A cross-source "one problem → all Polish evidence" match is a credible "new quality".
6. **Grant generators in Polish JST are form-fillers, not writers.** Witkac.pl (300+ institutions, 21k+ calls, 355k+ offers) and eNGO run the call → offer → evaluation → contract → report pipeline.
   SOWA EFS covers ESF+ applications. **No public API was found (verify).** The realistic "integration" is export in the official *wzór oferty* structure (copy-ready sections, DOCX/JSON), not a push to Witkac.
   AI writers (Grantbot.pl, rozliczNGO.pl) are generic and know nothing of ROPS innovations.
7. **Civic platforms supply proven flows to borrow.** From Decidim (AGPL): proposal states and an *Accountability* tracker. From CONSUL (AGPL): support thresholds before escalation. From Go Vocal: voice/video input and AI "Sensemaking" clustering. From FixMyStreet/NaprawmyTo.pl: a public report, a status, alerts and "already reported?" de-duplication.
8. **Sovereign AI is now politically salient in Poland.** mObywatel's Wirtualny Asystent runs on **PLLuM** (since 31 Dec 2025, anonymous, RAG). The Ministry of Digital Affairs (MC) strategy names PLLuM and Bielik for samorządy. CUI Wrocław deployed Bielik. MC's *Przewodnik po AI dla administracji* requires human oversight and verification.
   A PLLuM/Bielik-ready architecture with a human in the loop reads well to a regional-government jury.
9. **ROPS Kraków's own process is the best spec.** IWS 2.0 tests 32 innovations, accelerates 12 and recommends 9 for national dissemination. Grants average 70k and reach up to 120k PLN, are settled in a simplified way, and the partner is INNOAGH.
   Mirroring that *evidence ladder* (pomysł → test → akceleracja → rekomendacja → transfer) inside the platform makes it feel built for ROPS.
10. **No previous HubMI-style hackathon task was found** in 2023–2025 HackYeah records. Małopolska's 2025 HackYeah task was "Journey Radar", a transport task **(verify)**, so HackYeah 2026 is the first iteration of this brief.

---

## Comparison table

| Platform | Type | Key features | Open source? | What to borrow | Gap we can fill |
|---|---|---|---|---|---|
| **SIM database** (EU, ESF+ SI+) | Validated SI case-study catalogue | Org-only and org+case entries; filters (type, level of action, country, theme, status, funding source); partner search; national validators; EU Login or EUSurvey submission | No (EC Drupal site) **(verify)** | Validator workflow; "organisation-only" entries for newcomers seeking partners; transferability as an explicit field | English-only, catalogue-first, no problem-first entry, no AI matching, no local adaptation |
| **ECCSI / socialinnovationplus.eu** | EU competence centre | €197m SI+ grants (2021–27), Communities of Practice, transfer and scaling guidance | n/a | Transfer framing (originator/adopter, travelling vs. adapted elements) | Guidance only, nothing operational for a gmina |
| **European Social Innovation Competition** (EC DG GROW, run by Nesta and partners) | Challenge prize | Annual themed calls, academy, finalists | n/a | Themed "wyzwanie" calls with a mentoring academy | One-off prize; no regional matching |
| **Ashoka / Changemakers** | Network and idea competitions | 3,200+ fellows in 84 countries; online idea competitions | No | Online challenge/competition mechanics | Global; not tied to public services |
| **OECD SSE & SI Recommendation + Toolkit** | Policy framework | 9 building blocks (finance, markets, skills, impact measurement, SI) | n/a | Impact-measurement vocabulary for the admin view | Policy-level only |
| **ESID** (European Social Innovation Database, research) | ML-built SI database | NLP/ML classification of SI projects from the web | Research code **(verify)** | Automatic classification and scoring of SI-ness | Research prototype, not a service |
| **innowacjespoleczne.pl** | PL national SI database and portal | 150+ innovations (PO WER + FERS 5.1), text and tag search, profiles, incubator links, panel app | No **(verify)** | Standard innovation profile; tag taxonomy | No problem-first search, no AI, no adaptation help |
| **ROPS Kraków: IWS 2.0 + Biblioteka Innowacji Społecznych** | Regional incubator and library | 32 tested, 12 accelerated, 9 recommended nationally; library of about 114 innovations in 9 categories **(verify count)** | No | Evidence ladder; library card sections (problem, target group, who can use it) | Static library; no matching, no trends, no adopter workflow |
| **ROPS Poznań "Włącznik"** | Regional incubator | Calls for exclusion-related innovations; ROPS Szczecin partner | No | Incubator call structure | Same as above |
| **dobrepraktyki.pl** (ZGWRP, ZMP, ZPP) | JST good-practice base | 500+ standardised practices since 2007, categories, **Mapa Dobrych Praktyk** | No | Map of where a practice runs; JST-to-JST contact | Not social-innovation specific; no matching |
| **ngo.pl** | NGO news, knowledge and guides | Guides, events, AI-for-NGO articles | No | Plain-language guide style | Not a matching tool |
| **Witkac.pl** | JST ↔ NGO grant-call system | Calls, offer generator, evaluation, contracts, reports; 300+ institutions, 21k+ calls, 355k+ offers, 10bn+ PLN | No (commercial) | Field structure of the statutory offer; call-window logic | No AI drafting, no link to innovation evidence |
| **Generator eNGO** (engo.org.pl) | JST ↔ NGO grant-call system | Per-JST subdomains, offers and reports online, free for NGOs | No (commercial) | Same | Same |
| **SOWA EFS** | ESF+ application generator | Correspondence, version comparison; successor of SOWA (PO WER) | No (state) | Versioning and correspondence in the application | Form-filler only |
| **Grantbot.pl / rozliczNGO.pl** | AI grant writers (PL) | AI drafting for ESF+, FIO, Erasmus+; settlement | No | Section-by-section drafting UX | Generic; no regional innovation knowledge |
| **Grantable / Instrumentl** | AI grant writing (US) | Content library in the organisation's voice; funder matching | No | Reusable "fiszka → wniosek" content library | US-centric |
| **Decidim** | Participatory democracy | Processes, assemblies, proposals, meetings, budgets, **accountability**, surveys | **Yes, AGPL-3.0**, Ruby on Rails | Proposal state machine; public accountability of outcomes | Heavy; no AI matching to existing solutions |
| **CONSUL Democracy** | Participatory democracy | Proposals with support thresholds, debates, PB, polls, legislation | **Yes, AGPL-3.0**, Rails **(verify licence)** | Threshold mechanics (e.g. N similar needs → ROPS action) | No knowledge base |
| **Go Vocal** (ex-CitizenLab) | Engagement SaaS | Voice/video ideas, AI recommendations, translation, toxicity scoring, **Sensemaking** clustering (about 50% faster analysis) | Partly; core published as AGPL in the past **(verify)** | AI clustering for the admin trend view; voice input | Consultation-centric; no solution matching |
| **FixMyStreet** (mySociety) | Issue reporting | Map pin, auto-routing to authority (Open311), public reports, updates, alerts | **Yes, AGPL-3.0** | "Has this been reported?" view; status + alert subscription | Physical faults only |
| **NaprawmyTo.pl** | Issue reporting (PL) | Photo + description, about 30 cities; Katowice had 8k reports and 4.5k fixes in year 1 | No **(verify)** | Polish public-trust precedent; visible fix rate | Physical faults only |
| **bo.malopolska.pl / budzet.krakow.pl** | Participatory budgets | Submit → formal/substantive review → vote (online, app, paper) | No **(verify)** | Multichannel participation (online + paper + points) | Annual, money-allocation only |
| **mObywatel Wirtualny Asystent** (PLLuM) | Gov AI assistant | Plain-language explanation, guides to forms, anonymous, RAG | No | Anonymous-by-default chat; "translate officialese" | Not about social innovation |

---

## 1. Social-innovation databases and matchmaking (EU and international)

### 1.1 Social Innovation Match (SIM)
- **What it does.** An EU database meant to promote the **transfer and scaling-up** of social innovation. Users can showcase projects, search projects tested in other countries, find inspiring organisations and find partners for transnational calls.
  <https://european-social-fund-plus.ec.europa.eu/en/social-innovation-match>, <https://www.esf.lt/en/social-innovation-match-database-a-new-possibility-of-visibility-and-recognition-for-you-and-your-organization/>
- **Data model** (from the factsheet). There are two entry types:
  - **Organisation-only**, for newcomers seeking partners.
  - **Organisation + case study.**

  A case study must describe **objectives, methods, target groups, outcomes, impacts**, must fit ESF+ areas, and must be **in English**.
  Moderation state goes Draft → "Awaiting validation" → published. National validators handle local, regional and national projects; ECCSI handles transnational ones. The average is 15 working days.
  <https://socialinnovationplus.eu/app/uploads/2025/04/Social-Innovation-Match-Database-Factsheet.pdf>
- **Filters.** Initiatives filter by country, type, theme, level of action, status and funding source. Organisations filter by country, level, theme and type.
  Validators check problem scope, approach, results, and **potential for scaling and transfer**.
  <https://socialinnovationplus.eu/the-social-innovation-market-exploring-promising-practices-from-the-social-innovation-match-database/>
- **Tutorials.** An ALMA tutorial for SIM was published in June 2026 (<https://socialinnovationplus.eu/app/uploads/2026/06/ALMA-Tutorial_-Social-Innovation-Match-SIM-Database_2026-1.pdf>). A video intro is at <https://european-social-fund-plus.ec.europa.eu/en/videos/introducing-social-innovation-match-sim-database>.
- **Borrow.** Use a validator role (ROPS expert = "walidator") before a library entry goes public, and treat "transferability" as a first-class field. Allow organisations to register *without* an innovation, as "szukam partnera".
- **Gap.** Search assumes you already know what you're looking for. Its language and audience are institutional. It has no *problem-first* entry, no plain-language Polish and no adaptation step.

### 1.2 European Competence Centre for Social Innovation (ECCSI) / ESF+ Social Innovation+
- Set up by the Lithuanian ESF Agency. It has a **€197m** budget for 2021–2027 and two pillars: SI grants (transnational calls to transfer and scale tested approaches) and knowledge sharing (ALMA, EUROMA, and 5 Communities of Practice).
  <https://european-social-fund-plus.ec.europa.eu/en/esf-social-innovation-initiative>, <https://socialinnovationplus.eu/about/>
- **Transfer guidance**, which matters most for our Middleman:
  - Transfer is "rarely exact replication".
  - Separate what travels from what must adapt. What travels: **methodologies, tools/resources, business models, principles, technology**, plus a *portfolio approach* in which elements transfer independently.
  - Name the roles: **originators** (document methods, build reusable resources) and **adopters** (tailor to target group and context).
  - Use "a clear methodological structure and flexibility for contextual adaptation".

  <https://www.socialinnovationplus.eu/how-can-social-innovations-be-transferred-to-different-contexts/>
- Scaling literature distinguishes **scaling out** (replicate elsewhere), **scaling up** (change policy and institutions) and **scaling deep** (change norms), and balances **fidelity vs. adaptation**.
  <https://www.redalyc.org/journal/5375/537567402001/html/>, <https://delftdesignlabs.org/news/how-to-scale-social-innovations-from-one-context-to-another/>, <https://socialinnovationacademy.org/wp-content/uploads/2022/09/Scaling-Social-Innovation_SINA.pdf>
  The out/up/deep typology comes from Moore, Riddell & Vocisano (2015) **(verify)**. The idea of "core components vs. adaptable periphery" comes from implementation science (CFIR) **(verify)**.
- Polish-language guide: *Skalowanie innowacji społecznych. Siedem kroków do wykorzystania EFS* (<https://innowacjespoleczne.pl/wp-content/uploads/2023/03/Skalowanieinnowacjispolecznych.SiedemkrokowdowykorzystaniaEFS.pdf>). Worth citing in the pitch as the Polish anchor for the Middleman's method **(verify the 7 steps' content)**.

### 1.3 European Social Innovation Competition (EUSIC) and Nesta
- An annual EC challenge prize run by DG GROW with a consortium of Nesta, Kennisland, the European Network of Living Labs, Ashoka and Scholz & Friends. It includes a semi-finalist academy.
  <https://www.nesta.org.uk/project/european-social-innovation-competition/>
- **Borrow.** Themed challenge calls with a short mentoring "academy". This maps onto module V (mentors) and onto ROPS calls.

### 1.4 Social Innovation Community (SIC)
- A Horizon 2020 network (about 2016–2019) that produced SI learning resources **(verify; we did not re-check this in this session)**. It has mainly historical value. Cite it only as background.

### 1.5 Ashoka / Changemakers
- The largest network of social entrepreneurs: **3,200+ fellows in 84 countries**. Changemakers ran online idea competitions to source solutions.
  <https://www.changemakers.com/en>, <https://en.wikipedia.org/wiki/Ashoka_(non-profit_organization)>
- **Borrow.** "Open challenge" mechanics: when no existing innovation matches, the need becomes a public call for ideas.

### 1.6 OECD
- *Recommendation on the Social and Solidarity Economy and Social Innovation* plus the **Toolkit for the Social Economy**, which has 9 building blocks, including impact measurement and "encouraging social innovation".
  <https://www.oecd.org/en/about/programmes/oecd-toolkit-for-the-social-economy.html>, <https://emes.net/news/oecd-recommendation-of-the-council-on-the-social-and-solidarity-economy-and-social-innovation/>
- *Starting, Scaling and Sustaining Social Innovation* covers levers for future ESF support.
  <https://www.oecd.org/en/publications/starting-scaling-and-sustaining-social-innovation_ec1dfb67-en/full-report/component-8.html>
- OECD on AI in civic participation: <https://www.oecd.org/en/publications/governing-with-artificial-intelligence_795de142-en/full-report/ai-in-civic-participation-and-open-government_51227ce7.html>
- **Borrow.** OECD impact-measurement vocabulary for the admin dashboard, so it reads as policy-grade.

### 1.7 ESID (European Social Innovation Database, research)
- Built with NLP and ML to identify and classify SI projects from web data.
  <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9653489/>
- It scores projects on SI criteria (objectives, actor interactions, outputs, innovativeness) **(verify the exact criteria)**.
- **Borrow.** The AI can *classify and score incoming idea cards* against explicit SI criteria. Show the score and its reasons rather than a black-box rank.

---

## 2. Polish equivalents

### 2.1 ROPS Kraków: Inkubator Włączenia Społecznego (IWS 1.0 → 2.0) and Biblioteka
- **IWS 2.0.** The goal is wider use of social innovations for inclusion. It will **develop, fund and test 32 innovations**, put **12 on an acceleration path** (refined for accessibility) and **recommend the best 9 nationally**.
  Grants average **70k PLN** (max **120k**), cover 100% of costs with no own contribution, and are settled in a simplified way without financial documents. The project runs 54 months with partner **INNOAGH**.
  <https://rops.krakow.pl/realizowane-projekty-i-zadania/inkubator-wlaczenia-spolecznego-20,o-projekcie>, <https://mapadotacji.gov.pl/projekty/1677388/?lang=en>
- **IWS 1.0** ended on 31 Dec 2023: <https://rops.krakow.pl/zakonczone-projekty-i-zadania/inkubator-wlaczenia-spolecznego-projekt-zakonczony-31122023>.
  Its procedures are documented at <https://rops.krakow.pl/pliki-do-pobrania/wpis,procedury-realizacji-projektu-inkubator-wlaczenia-spolecznego,189>.
  ROPS describes itself as a social-innovation incubator for 10+ years, with a RegioStars 2025 entry: <https://rops.krakow.pl/innowacje-spoleczne/regiostars-awards-2025/pl-inkubator-wlaczenia-spolecznego> (the fetch returned 403; content is from a search snippet, **verify**).
- There is an open call "zgłoś pomysł i zostań innowatorem": <https://rops.krakow.pl/aktualnosci/ruszyl-nabor-na-innowacje-spoleczne-zglos-pomysl-i-zostan-innowatorem>
- **Biblioteka Innowacji Społecznych** has about **114** innovations from Małopolska in 9 categories (seniors; children, youth and families; people with limited mobility; and others). Each card has sections: what it is, which problems it addresses, target group, and who can use it.
  These figures come from a rival README and search snippets **(verify the canonical URL and count on rops.krakow.pl)**. <https://github.com/Flychuban/juz-dziala>
- **Mapa Wyzwań Społecznych** (ROPS, Nov 2024) covers 8 areas: family and substitute care, homelessness, disability, poverty, integration of foreigners, health, mental health, and seniors **(verify, from a rival README)**.
- A ROPS-adjacent concept, "Usługa Wrażliwa", and **5 IWS 2.0 assessment criteria** are used by Już Działa for idea self-assessment **(verify the source documents)**.
- **Implication.** The jury knows its own process intimately. Using its vocabulary (inkubacja, testowanie, akceleracja, upowszechnienie; the IWS criteria; Ramowy Plan Wdrożenia) is a strong signal.

### 2.2 Other ROPS incubators
- **ROPS Poznań, "Włącznik Innowacji Społecznych"** (2019–2023, with partners). It looks for ideas against social exclusion and has current calls.
  <https://innowacje.rops.poznan.pl/wlacznik/>, <https://innowacje.rops.poznan.pl/aktualne-nabory/>, profile at <https://innowacjespoleczne.pl/profil/9efae06a-fdea-40d4-8a22-4bb772bd3a29/>
- The list of incubators is at innowatorzyspoleczni.pl/inkubatory, which redirects to innowacjespoleczne.org.pl. That site was **down (HTTP 522)** when we checked, so the FERS 5.1 incubator list is still to be **(verify)**.

### 2.3 innowacjespoleczne.pl (national)
- A portal plus a database-management app (panel.innowacjespoleczne.pl). It holds **150+ innovations** from PO WER and those tested under **FERS action 5.1**, with text search, simple tag search and advanced tag search, plus "Ludzie innowacji" profiles.
  <https://innowacjespoleczne.pl/o-co-chodzi/>, <https://ngostacja.pl/poznaj-3-najwazniejsze-i-najciekawsze-bazy-innowacji-spolecznych/>, list at <https://innowacjespoleczne.pl/innowacje-spoleczne/lista-innowacji/>
- **Note on naming.** The brief mentions *innowacjespoleczne.org.pl*. The working database we found is **innowacjespoleczne.pl**, and *innowatorzyspoleczni.pl* redirects to *.org.pl* **(verify which one the organisers mean)**.
- **Gap.** It is a catalogue with tags. It has no problem-first search, no "where can I adopt this" and no adoption contacts.

### 2.4 Other Polish bases
- **INNOES, Baza innowacji społecznych**: <https://innoes.pl/baza-innowacji-spolecznych/> (content not checked, **verify**).
- **EQUAL (2001–2011)** and **PO KL (2007–2013)** solution databases are outdated or partly dead (<https://ngostacja.pl/poznaj-3-najwazniejsze-i-najciekawsze-bazy-innowacji-spolecznych/>). They show that Polish SI knowledge has been lost before when programmes ended. **Pitch angle:** HubMI should be the *persistent regional memory* across funding periods.
- **Baza Dobrych Praktyk** (<https://www.dobrepraktyki.pl/>). Run jointly by ZGWRP, ZMP and ZPP since 2007, it has **500+ standardised practice descriptions**. Categories include social services and JST–NGO cooperation, and the **Mapa Dobrych Praktyk** searches by area and location.
  <https://www.miasta.pl/strony/baza-dobrych-praktyk>, <https://zpp.pl/artykul/70-baza-dobrych-praktyk>
  **Borrow** "where does this already run" on a map, plus JST-to-JST peer contact.
- **ngo.pl** is the main NGO knowledge and news portal. Its articles on AI for NGOs and on writing grant applications with AI show demand.
  <https://publicystyka.ngo.pl/ai-dla-ngo-jak-organizacje-pozarzadowe-moga-korzystac-ze-sztucznej-inteligencji>, <https://publicystyka.ngo.pl/napisz-wniosek-o-grant-lub-dotacje-z-ai>
  TechSoup Polska runs an AI-for-NGO programme: <https://ai.techsoup.pl/>

### 2.5 Grant-application generators (what "integration" can mean)
- **Witkac.pl.** A complete JST↔NGO system covering calls, offer and application generation, evaluation, contracts, reports and online correspondence. It claims **300+ institutions, 21,000+ calls, 355,000+ offers and 10bn+ PLN**, and also serves Citizens' Initiative Fund (FIO) operators. It is said to reduce formal and accounting errors.
  <https://witkac.pl/strona>, <https://warszawa.ngo.pl/scwo/generator-wnioskow-witkac-pl>
- **Generator eNGO** (<https://engo.org.pl/>). An e-service for JST calls under the public-benefit act. Each JST gets a subdomain (e.g. leszno.engo.org.pl) listing current calls. It is free for NGOs, and support is paid by the JST.
  <https://ngo.leszno.pl/Generator_wnioskow_eNGO.html>
- **SOWA EFS** (sowa2021.efs.gov.pl). The ESF+ 2021–27 generator and successor of SOWA (PO WER). It has more functions than WOD2021 (correspondence, version comparison). Which generator a call uses is set by its rules (CST2021, WOD2021, Witkac or eNGO).
  <https://poradnikprzedsiebiorcy.pl/-generator-sowa-efs-jak-przygotowac-czesc-opisowa-wniosku>, <https://ktoiledostaje.pl/poradniki/generatory-wnioskow-o-dotacje-ue>
  FERS calls likely use SOWA EFS. FEM 2021–27 (Fundusze Europejskie dla Małopolski) has its own system **(verify both)**.
- **No public API** for Witkac, eNGO or SOWA turned up **(verify)**. The realistic integration is:
  - mirror the **statutory offer template** (*wzór oferty realizacji zadania publicznego* under the public-benefit act, 2018 regulation **(verify)**) section by section;
  - export copy-ready text, DOCX or JSON;
  - add deep links to the call on Witkac or eNGO;
  - keep a time window tied to the call ("generator aktywny w trakcie naboru", as the brief requires).
- **AI writers already on the market:**
  - Polish: **Grantbot.pl** (ESF+, FIO, Erasmus+) at <https://grantbot.pl/>; **rozliczNGO.pl** (AI drafting plus settlement) at <https://rozliczngo.pl/>.
  - US: **Grantable** (content library in the organisation's own voice; claims 40h → 10h) at <https://grantable.co/for/nonprofits>; **Instrumentl** (prospecting + "Apply" AI) at <https://www.eesel.ai/blog/ai-grant-writing-software>.
  - **Gap:** none of them knows the regional innovation evidence or links an application to a tested ROPS innovation.

---

## 3. Civic participation and issue-reporting platforms

| Platform | Proposal / feedback / testing flow worth copying | Source |
|---|---|---|
| **Decidim** (AGPL-3.0, Rails) | Participatory *processes* with phases; *proposals* with states (evaluating → accepted/rejected/withdrawn) **(verify state names)**; *meetings*; *budgets*; **accountability** (public progress of accepted proposals); surveys; assemblies | <https://decidim.org/blog/2019-01-14-consul-comparison/>, <https://democracy-technologies.org/tool/decidim/> |
| **CONSUL Democracy** (AGPL-3.0 **(verify)**, Rails) | Citizen proposals collect **supports**; crossing a threshold triggers escalation; moderated debates; PB; e-voting and local referenda | <https://decidim.org/blog/2019-01-14-consul-comparison/>, <https://www.gov.scot/publications/market-research-existing-civic-technologies-participation/pages/4/> |
| **Go Vocal** (ex-CitizenLab) | Ideas as **audio or video**; AI recommendations, machine translation, voice-to-text, toxicity score; **Sensemaking** clusters and summarises input and flags significant demographic links. Cambridge City Council analysed input about 50% faster; Lejre (DK) reached 1 in 7 residents. Newer "Perspectives" shows conversation structure. | <https://www.govocal.com/en-uk/platform-features/sensemaking>, <https://www.govocal.com/case-studies/cambridge-city-council-analyzes-input-50-faster-with-go-vocals-ai-assistant>, <https://www.govocal.com/blog/rethinking-public-deliberation-ai> |
| **FixMyStreet** (AGPL-3.0, mySociety) | Map pin with no need to know the competent authority (auto-routed via **Open311**); public reports; updates; **email/RSS alerts per area**; users see whether an issue is already reported | <https://github.com/mysociety/fixmystreet>, <https://fixmystreet.org/overview/> |
| **NaprawmyTo.pl** | Photo plus short description; about 30 cities. Initiated by Fundacja im. Stefana Batorego and coordinated by Pracownia Stocznia (pilot 2012). Katowice had 8k+ reports and 4.5k+ fixes in year 1. | <https://pdm.irmir.pl/narzedziownik/inne/serwis-%22naprawmyto.pl%22>, <https://samorzad.pap.pl/kategoria/jak-robia-inni/naprawmy-aplikacja-naprawmytopl-w-katowicach-mieszkancy-zglaszaja-miasto> |
| **Budżet Obywatelski Województwa Małopolskiego** (bo.malopolska.pl) and **Kraków BO** (budzet.krakow.pl) | Submit → formal and substantive assessment → vote. **Multichannel**: web, mKraków app, paper ballots at points or by post. Browsing needs no login; voting needs registration. | <https://bo.malopolska.pl/>, <https://msip.krakow.pl/polecamy/337226,2224,komunikat,glosowanie_w_budzecie_obywatelskim_2026.html> |

**Takeaways.**
- Every mature civic platform makes **status visible** (FixMyStreet, Decidim accountability). Each report should get a public lifecycle and a case code.
- **Thresholds** (CONSUL) are a fair, explainable rule for when aggregated needs force a ROPS action.
- **AI clustering** (Go Vocal) is now expected for the admin trend view, so it is not novel by itself.
- **Multichannel and paper** (BO Małopolska) is the Polish precedent for digitally excluded users.

---

## 4. AI in the public and social sector (PL focus)

- **mObywatel Wirtualny Asystent.** Based on **PLLuM** and live since **31 Dec 2025**. It explains officialese in plain language and guides users to the right form. It is **anonymous**, with no access to the user's mObywatel data, and uses RAG.
  <https://ccnews.pl/2025/12/30/mobywatel-wdraza-wirtualnego-asystenta-opartego-na-modelu-pllum>, <https://www.purepc.pl/mobywatel-asystent-ai-pllum-rag-chatbot-sprawy-urzedowe-ulatwienie>, <https://imagazine.pl/2026/01/02/mobywatel-wchodzi-w-2026-rok-z-polskim-ai/>
- **Government AI strategy for administration.** AI in samorządy should use Polish models (**PLLuM, Bielik**). An AI legal assistant for officials on PLLuM is planned.
  <https://samorzad.pap.pl/kategoria/e-urzad/tak-bedzie-wygladac-wdrazanie-ai-w-administracji-publicznej-mc-ujawnia-strategie>, <https://www.rp.pl/w-sadzie-i-w-urzedzie/art45043341-urzednicy-dostana-asystenta-prawnego-opartego-na-sztucznej-inteligencji-pllum>
- **PLLuM.** MC released **11 new PLLuM models** in May 2026: <https://ai.gov.pl/aktualnosci/nowe-modele-pllum>, <https://itwiz.pl/polski-rzad-udostepnia-polski-model-jezykowy-pllum/>
- **Bielik** (SpeakLeash, grassroots). The **first JST deployment was at CUI Wrocław**: <https://pfr.pl/artykul/start-z-polskim-ai-od-pomyslu-do-wdrozenia-cui-wroclaw>, <https://www.parkiet.com/technologie/art43128951-bielik-chce-wejsc-do-szkol-a-pllum-podbija-samorzady-polska-ai-rosnie-w-sile>
- **MC, *Przewodnik po sztucznej inteligencji dla administracji publicznej*.** Covers AI Act + RODO obligations, **real human oversight**, hallucination risk, and verifying outputs before using them in official documents.
  <https://ai.gov.pl/aktualnosci/przewodnik-dla-administracji-publicznej>, <https://samorzad.pap.pl/kategoria/e-urzad/mc-opublikowalo-pierwszy-przewodnik-po-ai-dla-urzedow-dokument>
  Warsaw city published a review of GenAI guidelines: <https://um.warszawa.pl/documents/114265126/0/Przegl%C4%85d+wytycznych+dotycz%C4%85cych+korzystania+z+generatywnej+sztucznej+inteligencji+w+administracji+publicznej+(1)+(1).pdf/aaabca32-2be5-56d4-60ca-5592ba144f4b?t=1742998386678>
- **AI for NGOs (PL).** Grantbot.pl, rozliczNGO.pl, TechSoup Polska's AI programme and ngo.pl guidance (§2.5).
- **AI matchmaking of needs to solutions.** Within social innovation, the only operational examples found are this weekend's hackathon repos (§6) and generic funder matching (Instrumentl, Grantable). SIM has no AI matching **(verify that SIM has no semantic search)**.
- **Implications for us.**
  - Make the LLM provider swappable, with a PLLuM or Bielik path documented even if the demo uses a hosted model.
  - Keep chat anonymous by default (mirroring mObywatel) and mask PII before any model call.
  - Show "AI suggests, a ROPS person approves" checkpoints. This matches the MC guide and the AI Act transparency duty: disclose that the user is talking to AI.

---

## 5. Previous hackathon solutions for similar briefs

- **HackYeah 2025** (4–5 Oct 2025). The Małopolska task was **"Journey Radar"** (won by "Solvrownicy w piaskownicy (KN Solvro)", with a distinction for "MIKOxC(offe)++"). It was a mobility task, not social innovation **(verify; from a search snippet, and the winners page returned 404)**.
  <https://hackyeah.pl/winners-2025/>, <https://hackyeah.pl/hackyeah-2025-a-hackathon-that-turns-ideas-into-reality/>
- **HackYeah 2023 winners** (<https://2023.hackyeah.pl/winners-2023/>, <https://www.gov.pl/web/govtech-en/hackyeah-powered-by-govtech-2023-winners>) and **2022 GovTech** (<https://fintek.pl/8-edycja-hackathonu-hackyeah-juz-za-nami-ponad-700-tys-zl-w-puli-nagrod/>) had no ROPS or social-innovation task in the snippets we reviewed **(verify)**.
- **"Hackathon dla Małopolski"** (Innowacyjna Małopolska) is a separate regional hackathon. It could be precedent for the region taking over hackathon IP **(verify the content)**.
  <https://innowacyjna.malopolska.pl/pl/projekty/hackathon-dla-malopolski>
- **Narodowy Hackathon** (NASK) is public-service themed: <https://www.nask.pl/aktualnosci/hakerzy-w-sluzbie-publicznej-co-pokazal-pierwszy-narodowy-hackathon>
- **Conclusion.** We found no prior winning solution for a "social-innovation matchmaking hub" brief. The real comparison set is the **concurrent 2026 entries** below.

---

## 6. Concurrent HackYeah 2026 entries for the same task (public GitHub)

Metadata comes from the GitHub API at about 06:40 CEST. Claims come from READMEs and were **not executed or verified**.

| Repo | Last push (UTC) | Stack | Notable claims | Read |
|---|---|---|---|---|
| **Flychuban/juz-dziala** "Już Działa", live <https://juz-dziala.vercel.app> | 4 Oct 00:16 | Next.js 15, tRPC, Drizzle/Postgres (Neon), Claude | All 7 modules. Answers **only from ROPS sources** with verbatim quotes (server rejects quotes not in the card) and says "nie wiem", then hands over to ROPS. Case code + two-way thread. Trends and "białe plamy". IWS 2.0 five-criteria self-check. Ramowy Plan Wdrożenia with GUS data. Eval: top-3 94%, top-1 85%, 0 PII leaks. axe-core 0 violations on 19 screens. PJM page, easy-read, no resident accounts. Open API `/api/v1/innovations`. Per-call cost logging. | **Strongest rival.** Sets the bar for trust, grounding and accessibility. |
| **imflawlezz/hackyeah-2026**, live <https://hubml-hackyeah2026-ab.vercel.app> | 4 Oct 03:28 | Next.js, pgvector, Vercel (dub1), Supabase-style Realtime **(verify)** | All 7 modules. Embeddings + keyword rerank with Polish reasons. Trends by category and week. Social Innovation Canvas wizard. Grant generator while a call is open. Tester slots enforced in the DB. Middleman: institution profile → candidates → plan with costs, risks and KPIs. Server-side Polish voice transcription. CI. | Polished, full-stack |
| **Drop-the-Base/malopolski-hub-2026** | 3 Oct 18:39 | FastAPI, SQLAlchemy, React, Groq optional | 7 modules + a JST challenge registry. TF-IDF + LLM hybrid. PII masking. **SUS** questionnaire in the tester. Middleman package (timeline, budget, staff, risks, **draft gmina resolution**). Easy-read summaries. Costs 170–200 PLN/month. 10-slide deck. | Finished early |
| **nikiwiii/hubmi** "MiNNO" | 4 Oct 04:26 | JS, Groq RAG | 115 innovations. Middleman. **Cartograms of 22 powiats with GUS/ROPS 2014–2024 data**. AI prototype generator. Chat with ROPS experts. "WCAG 2.2 AAA lab". Mobile app. | Breadth-heavy |
| **hubertmalkowski/hubmi** "Zaczyn" | 4 Oct 04:20 | TS, Postgres, Elasticsearch, Docker | All 7. **No match → the report becomes an open challenge** for NGOs, gminy and residents. PL/EN/**UA** UI. Accessibility footer (TTS, easy-read). | Open-challenge idea |
| **Wojciech151218/HUBMI-confidence-team** | 3 Oct 23:16 | Next.js, TypeORM, pgvector, OpenAI | Initiatives with votes. Local hashed embeddings fallback. Search eval script. Admin has no auth (README admits it). | Early |
| **TomaszWu14/hugme** "HugMe" | 3 Oct 23:12 | n/a | "Twój problem nie zostaje sam" | Not inspected |
| **Majkelll/hubmi** | 4 Oct 00:56 | C# | Description only | Not inspected |
| **JaQubus/Spolecznik** "Społecznik" | n/a | n/a | PR "Zasobnik wiedzy: Biblioteka…, panel admina i mapa Małopolski" | Not inspected (<https://github.com/JaQubus/Spolecznik/pull/41>) |

**Convergence.** Nearly everyone has:
- RAG/embedding matching over the ~114-card ROPS library;
- voice input, a contrast/font/TTS bar and easy-read text;
- an AI canvas;
- a grant draft;
- a Middleman "plan with budget, risks and KPIs";
- trends by category.

These are table stakes. Do not pitch them as innovation.

**Ideas not yet claimed** (from READMEs we read, so absence is not proven):
- an explicit **core-vs-adaptable transfer card** (SI+ method) with an **adopter readiness check**;
- **originator ↔ adopter connection** with a peer "who already adopted it in Małopolska";
- an **evidence ladder** mirroring IWS stages;
- **proxy reporting** by a social worker or relative for digitally excluded people, plus paper/phone intake;
- turning aggregated needs into a **draft call (nabór) brief** for ROPS;
- the grant draft in the **statutory *wzór oferty* structure** with Witkac/eNGO-ready export;
- tester results flowing back into the **library card as evidence**.

---

## 7. Differentiation opportunities for our MVP

These are ideas for the team to choose from. None of them is a decision. Each is grounded in prior art above and, where checked, absent from the rival READMEs.

1. **"Karta Transferu" Middleman (core vs. adaptable).** For a chosen innovation and a requesting institution (e.g. a small-gmina OPS), output three lists:
   - **Rdzeń**, elements that must stay for it to work;
   - **Do dostosowania**, elements to localise (staff, channel, partner, schedule);
   - **Warunki brzegowe**, preconditions.

   Add a short **readiness checklist** for the adopter. This follows SI+ guidance (<https://www.socialinnovationplus.eu/how-can-social-innovations-be-transferred-to-different-contexts/>) and the PL *Skalowanie… 7 kroków* guide.
   It reads as *methodology*, not "LLM writes a plan". Rivals produce generic plans with budget and risks.
2. **Originator ↔ adopter bridge.** Every match shows who created and tested the innovation and **where in Małopolska it already runs**, on a map (borrowing Mapa Dobrych Praktyk, <https://www.dobrepraktyki.pl/>). It ends with one CTA: "Poproś o rozmowę z autorem" or "z gminą, która już wdrożyła", routed through ROPS.
   This turns a library into a **network** and is ROPS's real job.
3. **Evidence ladder on every card** (*poziom dowodu*): pomysł → przetestowana (IWS) → akcelerowana → rekomendowana do upowszechnienia → wdrożona w N gminach. It mirrors IWS 2.0's 32 → 12 → 9 funnel (<https://rops.krakow.pl/realizowane-projekty-i-zadania/inkubator-wlaczenia-spolecznego-20,o-projekcie>) and SIM's validation step.
   Matching ranks on relevance **and** shows evidence, so a jury from the Województwo sees its own process.
4. **Closed loop: needs → nabór.** When the same unmet need appears ≥ N times in an area, a CONSUL-style threshold (<https://decidim.org/blog/2019-01-14-consul-comparison/>) generates a **draft challenge brief for the next ROPS incubator call**: the problem, the affected powiats, and why the existing innovations don't fit.
   Admin trends then become *actionable policy input*, not just charts. This answers "new quality vs. re-integrating portals" directly.
5. **Assisted and proxy reporting** ("zgłoś w czyimś imieniu"). A social worker, OPS staff member, librarian or family member can file a need on behalf of a senior or excluded person, with consent. Add a printable paper form or phone script whose content is re-entered by staff, following BO Małopolska's multichannel model (<https://bo.malopolska.pl/>).
   This targets the "all ages and digital-skill levels" criterion better than a font slider does.
6. **Grant draft in the official structure.** Map the idea card (*fiszka*) to sections of the statutory *wzór oferty realizacji zadania publicznego* **(verify the template edition)**. Activate the generator only during an open call, and export copy-ready blocks, DOCX or JSON with a deep link to the call on Witkac or eNGO.
   Be honest that there is no public API **(verify)**. Mention that 300+ JST already run calls on Witkac (<https://witkac.pl/strona>). This is concrete "integration readiness" that judges can believe.
7. **Tester → evidence feedback.** Structure tester feedback, using SUS (as Drop-the-Base does) or a short accessible questionnaire, so the aggregated results **update the innovation card's evidence section**. The tester module then feeds the library instead of being a dead end.
8. **Sovereign and transparent AI.** Use a provider-agnostic LLM layer with a documented **PLLuM or Bielik** path (as in mObywatel and CUI Wrocław), anonymous by default, with PII masking before model calls. Show AI-disclosure labels and a "człowiek zatwierdza" step for anything published or sent, per the MC *Przewodnik* (<https://ai.gov.pl/aktualnosci/przewodnik-dla-administracji-publicznej>).
   Add a visible *per-request cost* figure for the required running-cost estimate.
9. **Cross-source Polish evidence.** Beyond the ROPS library, also show "related in Poland" (innowacjespoleczne.pl, dobrepraktyki.pl) and "related in Europe" (SIM). Label clearly when an item is outside Małopolska or unvalidated. This positions HubMI as the **regional memory that survives funding periods**, unlike the dead EQUAL and PO KL databases.
10. **Trust patterns as table stakes, not headline.** Grounded citations, honest "nie wiem → ekspert ROPS", case code + status (as in FixMyStreet and Decidim accountability) and axe-checked WCAG 2.1 AA are now expected (Już Działa has them). If we lack them, that is a weakness. Having them is not a differentiator.

**Pitch framing.** The rivals sell "a portal with 7 modules and a chatbot". A stronger story is **"HubMI closes the innovation-transfer loop"**: need → proven innovation → adapted for *your* institution (core vs. adaptable) → funded (call-ready draft) → tested → evidence back into the library → unmet needs become the next ROPS call.

---

## Sources

EU and international
- <https://european-social-fund-plus.ec.europa.eu/en/social-innovation-match>
- <https://european-social-fund-plus.ec.europa.eu/en/videos/introducing-social-innovation-match-sim-database>
- <https://www.esf.lt/en/social-innovation-match-database-a-new-possibility-of-visibility-and-recognition-for-you-and-your-organization/>
- <https://socialinnovationplus.eu/app/uploads/2025/04/Social-Innovation-Match-Database-Factsheet.pdf>
- <https://socialinnovationplus.eu/app/uploads/2026/06/ALMA-Tutorial_-Social-Innovation-Match-SIM-Database_2026-1.pdf>
- <https://socialinnovationplus.eu/the-social-innovation-market-exploring-promising-practices-from-the-social-innovation-match-database/>
- <https://european-social-fund-plus.ec.europa.eu/en/esf-social-innovation-initiative>
- <https://socialinnovationplus.eu/about/>
- <https://www.socialinnovationplus.eu/how-can-social-innovations-be-transferred-to-different-contexts/>
- <https://www.redalyc.org/journal/5375/537567402001/html/>
- <https://delftdesignlabs.org/news/how-to-scale-social-innovations-from-one-context-to-another/>
- <https://socialinnovationacademy.org/wp-content/uploads/2022/09/Scaling-Social-Innovation_SINA.pdf>
- <https://www.nesta.org.uk/project/european-social-innovation-competition/>
- <https://www.changemakers.com/en>
- <https://en.wikipedia.org/wiki/Ashoka_(non-profit_organization)>
- <https://www.oecd.org/en/about/programmes/oecd-toolkit-for-the-social-economy.html>
- <https://emes.net/news/oecd-recommendation-of-the-council-on-the-social-and-solidarity-economy-and-social-innovation/>
- <https://www.oecd.org/en/publications/starting-scaling-and-sustaining-social-innovation_ec1dfb67-en/full-report/component-8.html>
- <https://www.oecd.org/en/publications/governing-with-artificial-intelligence_795de142-en/full-report/ai-in-civic-participation-and-open-government_51227ce7.html>
- <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9653489/>

Poland: social innovation
- <https://rops.krakow.pl/realizowane-projekty-i-zadania/inkubator-wlaczenia-spolecznego-20,o-projekcie>
- <https://mapadotacji.gov.pl/projekty/1677388/?lang=en>
- <https://rops.krakow.pl/zakonczone-projekty-i-zadania/inkubator-wlaczenia-spolecznego-projekt-zakonczony-31122023>
- <https://rops.krakow.pl/pliki-do-pobrania/wpis,procedury-realizacji-projektu-inkubator-wlaczenia-spolecznego,189>
- <https://rops.krakow.pl/aktualnosci/ruszyl-nabor-na-innowacje-spoleczne-zglos-pomysl-i-zostan-innowatorem>
- <https://rops.krakow.pl/innowacje-spoleczne/regiostars-awards-2025/pl-inkubator-wlaczenia-spolecznego>
- <https://innowacje.rops.poznan.pl/wlacznik/>
- <https://innowacjespoleczne.pl/o-co-chodzi/>
- <https://innowacjespoleczne.pl/wp-content/uploads/2023/03/Skalowanieinnowacjispolecznych.SiedemkrokowdowykorzystaniaEFS.pdf>
- <https://ngostacja.pl/poznaj-3-najwazniejsze-i-najciekawsze-bazy-innowacji-spolecznych/>
- <https://innoes.pl/baza-innowacji-spolecznych/>
- <https://www.dobrepraktyki.pl/>
- <https://www.miasta.pl/strony/baza-dobrych-praktyk>
- <https://zpp.pl/artykul/70-baza-dobrych-praktyk>

Poland: grants and AI for NGOs
- <https://witkac.pl/strona>
- <https://warszawa.ngo.pl/scwo/generator-wnioskow-witkac-pl>
- <https://engo.org.pl/>
- <https://ngo.leszno.pl/Generator_wnioskow_eNGO.html>
- <https://poradnikprzedsiebiorcy.pl/-generator-sowa-efs-jak-przygotowac-czesc-opisowa-wniosku>
- <https://ktoiledostaje.pl/poradniki/generatory-wnioskow-o-dotacje-ue>
- <https://grantbot.pl/>
- <https://rozliczngo.pl/>
- <https://ai.techsoup.pl/>
- <https://publicystyka.ngo.pl/ai-dla-ngo-jak-organizacje-pozarzadowe-moga-korzystac-ze-sztucznej-inteligencji>
- <https://publicystyka.ngo.pl/napisz-wniosek-o-grant-lub-dotacje-z-ai>
- <https://grantable.co/for/nonprofits>
- <https://www.eesel.ai/blog/ai-grant-writing-software>

Civic platforms
- <https://decidim.org/blog/2019-01-14-consul-comparison/>
- <https://democracy-technologies.org/tool/decidim/>
- <https://www.gov.scot/publications/market-research-existing-civic-technologies-participation/pages/4/>
- <https://www.govocal.com/en-uk/platform-features/sensemaking>
- <https://www.govocal.com/case-studies/cambridge-city-council-analyzes-input-50-faster-with-go-vocals-ai-assistant>
- <https://www.govocal.com/blog/rethinking-public-deliberation-ai>
- <https://github.com/mysociety/fixmystreet>
- <https://fixmystreet.org/overview/>
- <https://pdm.irmir.pl/narzedziownik/inne/serwis-%22naprawmyto.pl%22>
- <https://samorzad.pap.pl/kategoria/jak-robia-inni/naprawmy-aplikacja-naprawmytopl-w-katowicach-mieszkancy-zglaszaja-miasto>
- <https://bo.malopolska.pl/>
- <https://msip.krakow.pl/polecamy/337226,2224,komunikat,glosowanie_w_budzecie_obywatelskim_2026.html>

Public-sector AI (PL)
- <https://ccnews.pl/2025/12/30/mobywatel-wdraza-wirtualnego-asystenta-opartego-na-modelu-pllum>
- <https://www.purepc.pl/mobywatel-asystent-ai-pllum-rag-chatbot-sprawy-urzedowe-ulatwienie>
- <https://imagazine.pl/2026/01/02/mobywatel-wchodzi-w-2026-rok-z-polskim-ai/>
- <https://samorzad.pap.pl/kategoria/e-urzad/tak-bedzie-wygladac-wdrazanie-ai-w-administracji-publicznej-mc-ujawnia-strategie>
- <https://www.rp.pl/w-sadzie-i-w-urzedzie/art45043341-urzednicy-dostana-asystenta-prawnego-opartego-na-sztucznej-inteligencji-pllum>
- <https://ai.gov.pl/aktualnosci/nowe-modele-pllum>
- <https://pfr.pl/artykul/start-z-polskim-ai-od-pomyslu-do-wdrozenia-cui-wroclaw>
- <https://www.parkiet.com/technologie/art43128951-bielik-chce-wejsc-do-szkol-a-pllum-podbija-samorzady-polska-ai-rosnie-w-sile>
- <https://ai.gov.pl/aktualnosci/przewodnik-dla-administracji-publicznej>
- <https://samorzad.pap.pl/kategoria/e-urzad/mc-opublikowalo-pierwszy-przewodnik-po-ai-dla-urzedow-dokument>

Hackathons and concurrent entries
- <https://hackyeah.pl/hackyeah-2025-a-hackathon-that-turns-ideas-into-reality/>
- <https://2023.hackyeah.pl/winners-2023/>
- <https://www.gov.pl/web/govtech-en/hackyeah-powered-by-govtech-2023-winners>
- <https://innowacyjna.malopolska.pl/pl/projekty/hackathon-dla-malopolski>
- <https://github.com/Flychuban/juz-dziala>
- <https://github.com/imflawlezz/hackyeah-2026>
- <https://github.com/Drop-the-Base/malopolski-hub-2026>
- <https://github.com/nikiwiii/hubmi>
- <https://github.com/hubertmalkowski/hubmi>
- <https://github.com/Wojciech151218/HUBMI-confidence-team>
- <https://github.com/TomaszWu14/hugme>
- <https://github.com/Majkelll/hubmi>
- <https://github.com/JaQubus/Spolecznik>
