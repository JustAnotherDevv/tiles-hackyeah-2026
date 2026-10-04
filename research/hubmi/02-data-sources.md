# HubMI: public seed data for the MVP (02-data-sources)

Collected 2026-10-04, 06:30–06:45 CEST. All files are in `research/hubmi/data/` (432 KB total).

## TL;DR

- **We have the real target corpus.** ROPS Kraków's own **Biblioteka Innowacji Społecznych** is public at `rops.krakow.pl/innowacje-spoleczne/biblioteka-innowacji-spolecznych/`. I scraped all **115 innovations** across 9 categories. Each innovation page follows the same structure: what it is, the problem it addresses, the target group, who can use it, whether it works, and the authors. **100 of the 115 pages are marked CC BY 4.0.** The brief mentions "~200 innovations"; the public library shows 115, and the rest probably sit in incubator archives (verify on site).
- **The "Mapa Wyzwań Społecznych" is a public ROPS PDF** (Nov 2024, prepared for IWS 2.0). It covers 8 thematic areas with key data points and challenges. I condensed it into `challenges.json` and added Małopolska-specific numbers from the OZPS 2024 report and from GUS BDL. Note that its data are **national, not regional**.
- **GUS BDL API works without a key.** It returned 12 indicators for all 22 powiats (2025 for most; social assistance only up to 2024) and a TERYT list of 299 gmina-level units with population and 65+ share.
- `synthetic_problems.json` holds 25 **SYNTHETIC** Polish problem reports with expected tags for matchmaking evals. A naive keyword-overlap test already returns sensible top hits for about 20 of the 25 reports.
- **Corpus gaps:** poverty and energy poverty, depopulation, long-term unemployment 50+ (the library has only 5 labour-market innovations) and homelessness (2). Matchmaking will be weak for these. Either the on-site sample data fills them, or we use the national base (innowacjespoleczne.pl) as a backup.

## Datasets saved

| File | Rows | Source | Licence / terms | Freshness | Caveats |
|---|---|---|---|---|---|
| `data/innovations.json` | 115 | [ROPS Biblioteka Innowacji Społecznych](https://rops.krakow.pl/innowacje-spoleczne/biblioteka-innowacji-spolecznych/kategorie) (9 category pages and 115 detail pages) | CC BY 4.0 on 100 pages, attribution "ROPS Kraków" + link. The other 15 have no licence badge, so treat them as all rights reserved **(verify)** | scraped 2026-10-04; innovations from roughly 2016–2025 | `short_description`, `problem_addressed`, `target_groups`, `type` and `keywords` are **AI paraphrases and tags (Claude), not checked by a human yet**. `thematic_area` is the ROPS category. `stage` comes from the "wybrana do upowszechniania" banner (27 items); the rest are "tested in incubator" **(verify)**. Author personal names are removed and only organisation names are kept, using a heuristic (2 leaked names were fixed by hand). Innovators also come from outside Małopolska (Dębica, Stalowa Wola, Siedlce, Poznań), so `region`/gmina is unknown. Links to the folder PDF, YouTube video and materials ZIP are kept. |
| `data/innovations_rops_sections.json` | 100 | same | CC BY 4.0 only (the 15 unlicensed pages are excluded) | same | Full original text of sections 1–4 for RAG and embeddings. Authors section dropped. Show attribution in the UI. |
| `data/challenges.json` | 9 (8 areas + 1 regional context) | [Mapa Wyzwań Społecznych, ROPS (PDF, 7.8 MB)](https://rops.krakow.pl/mpliki/IS/IWS_20/za._nr_2._Mapa_Wyzwa_Spoecznych.pdf); [Raport OZPS za 2024 (PDF, 206 pp.)](https://rops.krakow.pl/mpliki/PS/BA/Raport_OZPS_za_rok_2024.pdf); BDL | No licence marked on the PDFs; I paraphrase and cite them **(verify)** | Mapa: XI 2024; OZPS: 2025 edition (data for 2024) | The 8 areas are family/foster care, homelessness, disability, poverty, integration of foreigners, health, mental health and seniors. The Mapa's numbers are national. The fictional personas were omitted. The regional record has the OZPS numbers plus top-3 powiats by indicator. |
| `data/powiaty_indicators.csv` (+ `.md`) | 22 | [GUS BDL API](https://bdl.stat.gov.pl/api/v1/) | GUS public data, cite "Źródło: GUS BDL" **(verify terms)** | 2025 (social-assistance beneficiaries: 2024) | Variable IDs, units and years are in `powiaty_indicators.md`. The anonymous rate limit (~100 req/15 min) was hit once. |
| `data/teryt_malopolska.csv` | 299 | GUS BDL `/units?level=6` + variables 72305 and 634989 | as above | 2025 | Includes the city and rural parts of urban-rural gminas, plus 16 historical units (flagged `aktualna_2025=nie`). That leaves 183 current gminas against the official 182 **(verify)**. The TERYT code is derived from the BDL id (woj+powiat+gmina+kind). |
| `data/institutions.json` | 19 institutions + 6 directory sources | [Małopolska Sieć CUS (ROPS)](https://rops.krakow.pl/gremia-i-zespoly/malopolska-siec-centrow-uslug-spolecznych); partner list of the "Małopolskie Centra Usług Społecznych" project ([CUS Niepołomice](https://niepolomice.naszops.pl/projekt-malopolskie-centra-uslug-spolecznych), [CUS Oświęcim](https://cus-oswiecim.pl/malopolskie-centra-uslug-spolecznych/)) | Names only; no personal contacts | 2024–2025 | Incomplete: 5 MSCUS founders and 11 MCUS partner gminas. Whether each partner already runs a CUS is **(verify)**. The CUS in Tarnów could be the city or the rural gmina **(verify)**. |
| `data/synthetic_problems.json` | 25 | Written by AI from the Mapa areas and BDL hotspots | **SYNTHETIC**, no real persons | 2026-10-04 | Fields: `id`, `synthetic`, `author_type` (mieszkaniec/NGO/gmina), `gmina`, `teryt_gminy`, `powiat`, `text`, `expected_tags`. They cover ageing, loneliness, youth mental health, digital exclusion, rural access, depopulation, disability, caregivers, foreigners, foster care, homelessness, poverty and grants. |

## Sources found but not downloaded

| Source | URL | Access | Notes |
|---|---|---|---|
| National social-innovation base (FERS/POWER incubators, ~1,200 micro-innovations) | https://innowacjespoleczne.pl/lista-innowacji/ | HTML list (`?on_page=`), detail pages `/innowacja/{slug}`, and an "Eksportuj do Excela" button in the UI. The WP REST API does **not** expose the `innowacja` type (404). | Best backup corpus. Its fields (problem, how it works, who it serves, who can implement, effectiveness rating, grant amount) map well onto our schema. It also has a profile for "Małopolski Inkubator Innowacji Społecznych [2016-2019]". Licence: **(verify)**. |
| innowatorzyspoleczni.pl | https://innowatorzyspoleczni.pl/inkubatory/ | HTML | List of active incubators only. |
| EU Social Innovation Match (SIM) | https://european-social-fund-plus.ec.europa.eu/en/social-innovation-match | HTML case studies (~177 projects EU-wide, a few from Poland) | Mostly English; low relevance for Polish matchmaking. |
| Poznań ROPS "Włącznik Innowacji Społecznych" | https://innowacje.rops.poznan.pl/wlacznik/ | HTML | Another regional library, Wielkopolska. |
| Inkubator Włączenia Społecznego 2.0: accelerated innovations | https://rops.krakow.pl/realizowane-projekty-i-zadania/inkubator-wlaczenia-spolecznego-20,lista-akcelerowanych-innowacji | HTML | Current (2024–2027) cohort, probably not yet in the library **(verify)**. |
| ROPS research reports (Obserwatorium) | https://rops.krakow.pl/badania-analizy-raporty/raporty-z-badan | PDFs | 2025 reports on DPS and deinstitutionalisation, and on social services (deficits and needs). Good for the knowledge store and RAG. |
| OZPS: powiat/gmina tables | https://rops.krakow.pl/badania-analizy-raporty/ocena-zasobow-pomocy-spolecznej-w-woj-malopolskim/biezaca-ocena | PDF (206 pp.) | Has the main reasons for granting social assistance and service-gap data. Parsing the tables would take more than 30 minutes. |
| Krajowe Forum CUS: CUS/OPS base | https://www.forumcus.pl/baza-cus/ | HTML | Full national CUS list, filterable to Małopolska. |
| bazy.ngo.pl | https://bazy.ngo.pl/ | HTML search | NGO directory. Contains contact data, so only names and gminas should be taken. |
| KRS open API | https://api-krs.ms.gov.pl/ | REST by KRS number | No regional search. |
| GUS BDL (more variables) | https://bdl.stat.gov.pl/api/v1/ | REST JSON | Gmina-level data (`unit-level=6`, ~3 pages per variable) is available for heatmaps. Disability (NSP 2021, P4323, powiat level) is also there. |

## Quality issues

1. **Only 115 innovations, not ~200.** Coverage is skewed toward disability, seniors and families. Poverty, homelessness (2), labour market (5) and foreigners (6) are thin.
2. **AI-generated summaries and tags.** They are paraphrases and need a quick human pass. `type` labels are subjective (product 47, tech 35, method 24, service 8, organisational 1).
3. **Licences are mixed.** 15 innovations have no CC badge. The Mapa Wyzwań and OZPS PDFs have no stated licence. We use them only as short paraphrases with citations.
4. **The Mapa Wyzwań is not geographic.** Its statistics are national. For the regional "map" layer, combine its areas with BDL powiat indicators (and our synthetic or real reports).
5. **No geolocation for innovations.** Innovator organisations come from several voivodeships, so gmina-based matching has to rely on the problem's gmina, not the innovation's.
6. **BDL quirks.** There are historical units at level 6, and gmina count is 183 against the official 182 **(verify)**. The social-assistance variable stops at 2024. The anonymous rate limit is easy to hit when several teammates share one IP.
7. **Author-name stripping is heuristic.** Section 6 was removed. Organisation names were kept by keyword regex and reviewed by eye once, but a final grep before publishing is advised.

## Recommended seed-data plan for the demo

1. **Matchmaking corpus:** `innovations.json` (115). Embed `title + short_description + problem_addressed + target_groups + keywords`, optionally adding the CC BY full text from `innovations_rops_sections.json`. Show the source link and "CC BY 4.0 – ROPS Kraków" on every result card.
2. **Eval set:** run the 25 `synthetic_problems.json` reports through matchmaking and check that the top 3 hits overlap `expected_tags`. Pick 3–4 demo stories where it clearly works: digital exclusion (syn-002), youth mental health (syn-005), caregiver respite (syn-007) and hearing-impaired access (syn-012). Also show one "gap" case, poverty (syn-022), to demo the idea creator: "no existing innovation, generate a new idea and a grant application".
3. **Knowledge store and challenges:** load `challenges.json` (8 areas + regional context) as challenge cards and tag the innovations with `related_library_areas`.
4. **Admin trend dashboard:** aggregate synthetic reports by `powiat`/`teryt_gminy` and overlay `powiaty_indicators.csv` (65+ share, beneficiaries per 10k, population change, unemployment). Join gminas on `teryt_malopolska.csv`. Label all report counts **SYNTHETIC**.
5. **On site:** if organisers hand out the official library export or sample data, swap it in under the same schema (`id, title, short_description, problem_addressed, target_groups[], thematic_area, type, stage, source_url, licence`). If time allows, add the national base (innowacjespoleczne.pl) to fill the poverty and labour-market gaps.
