# powiaty_indicators.csv – wskaźniki dla 22 powiatów Małopolski

Źródło: GUS, Bank Danych Lokalnych (BDL), API `https://bdl.stat.gov.pl/api/v1/` (bez klucza; limit anonimowy ok. 100 zapytań / 15 min – w trakcie pobierania raz go przekroczono, przy ponownej próbie działało). Pobrano 2026-10-04.
Zapytanie: `GET /data/by-variable/{id}?unit-parent-id=011200000000&unit-level=5&year=2022..2025&format=json` (011200000000 = woj. małopolskie, poziom 5 = powiaty).
Licencja: dane GUS są publiczne, ponowne wykorzystanie z podaniem źródła („Źródło: GUS, BDL”), zob. https://stat.gov.pl/copyright (verify).

Kolumny identyfikacyjne:
- `teryt_powiat` – 4-cyfrowy kod TERYT (12xx); 1261–1263 to miasta na prawach powiatu (Kraków, Nowy Sącz, Tarnów).
- `bdl_unit_id` – 12-znakowy identyfikator jednostki w BDL.
- `typ` – powiat ziemski albo miasto na prawach powiatu.

| kolumna | ID zmiennej BDL | temat BDL | jednostka | rok |
|---|---|---|---|---|
| ludnosc_ogolem | 72305 | P2137 Ludność wg grup wieku i płci (stan 31 XII) | osoby | 2025 |
| ludnosc_2022 | 72305 | jw. | osoby | 2022 |
| zmiana_ludnosci_2022_2025_proc | obliczone z 72305 | – | % | 2022→2025 |
| zmiana_ludnosci_na_1000 | 458603 | P2425 Gęstość zaludnienia oraz wskaźniki | ‰ (na 1000 mieszk.) | 2025 |
| przyrost_naturalny_na_1000 | 450551 | P3428 Urodzenia, zgony, przyrost naturalny na 1000 ludności | ‰ | 2025 |
| odsetek_65plus | 634989 | P2426 Wskaźniki obciążenia demograficznego | % ludności | 2025 |
| wsp_obciazenia_osobami_starszymi | 634067 | P2426 | osoby 65+ na 100 osób 15–64 | 2025 |
| poprodukcyjni_na_100_produkcyjnych | 60562 | P2426 | osoby | 2025 |
| nieprodukcyjni_na_100_produkcyjnych | 60563 | P2426 (współczynnik obciążenia demograficznego) | osoby | 2025 |
| poprodukcyjni_na_100_przedprodukcyjnych | 60564 | P2426 (≈ indeks starości wg wieku ekonomicznego) | osoby | 2025 |
| beneficjenci_pomocy_spol_na_10tys | 1548717 | P3870 Beneficjenci środowiskowej pomocy społecznej – wskaźniki | osoby na 10 tys. ludności | **2024** (2025 jeszcze niedostępny) |
| stopa_bezrobocia_rejestrowanego | 60270 | P2392 Stopa bezrobocia rejestrowanego | % | 2025 |
| gestosc_zaludnienia | 60559 | P2425 | osoby / km² | 2025 |
| wskaznik_urbanizacji | 1725015 | P2425 | % ludności w miastach | 2025 |

Uwagi:
- Lata: większość zmiennych ma już wartości za 2025 r.; wskaźnik pomocy społecznej kończy się na 2024 r. Kolumny `rok_danych_*` podają rok użyty w wierszu.
- Wiek produkcyjny/poprodukcyjny wg definicji GUS (poprodukcyjny: K 60+, M 65+); `odsetek_65plus` to próg 65+ dla obu płci.
- Surowe odpowiedzi API (2022–2025) dla każdej zmiennej można pobrać ponownie tym samym zapytaniem (≈12 wywołań).
- `teryt_malopolska.csv`: 299 jednostek BDL poziomu 6 (gminy oraz ich części: miasto i obszar wiejski gmin miejsko-wiejskich). Ma kolumny `ludnosc_2025` (72305) i `odsetek_65plus_2025` (634989). 16 jednostek bez danych za 2025 r. oznaczono jako historyczne: to dawne gminy wiejskie, które otrzymały prawa miejskie, oraz sztuczna jednostka „Miejska strefa usług publicznych”. Bieżących gmin wyszło 183, a oficjalnie jest ich 182 (verify).
