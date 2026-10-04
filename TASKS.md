# HackYeah 2026 — Tasks

Source: official "HackYeah 2026 - Rules for Participants" Google Drive folder
https://drive.google.com/drive/folders/1cLA74vS54-eFeMUtox4MtCCuza-DLZrz
(hackyeah.pl/tasks-prizes was down on 2026-10-03 — its CMS backend was timing out.)

Polish-language briefs (Kraków, HubMi) are summarised in English below.

## At a glance

| Task | Type | Prize pool | Judging (top weights) | IP to sponsor? |
|---|---|---|---|---|
| Artificial Intelligence | Open | 8,000 PLN | Idea 30 / Category 20 / Usability 20 / Design 20 / Completeness 10 | — (not checked) |
| Defence | Open | 8,000 PLN | same as above | — |
| ImpactHer: Technology for Real Change | Open | 8,000 PLN | same as above | — |
| Smart City | Open | 8,000 PLN | same as above | — |
| Sport & Healthcare | Open | 8,000 PLN | same as above | — |
| Huawei — Imagine What's Next | Partner | 25,000 PLN (12k / 8k / 5k) | Originality 20 / Usefulness 20 / Tech execution 20 / Platform use 20 / Demo 10 / Reproducibility 10 | No — you keep IP; Huawei gets a 3-yr non-exclusive, non-commercial licence |
| Goldman Sachs — AI Control Layer | Partner | 15,000 PLN (6k / 5k / 4k) | Guardrail robustness 30 / Architecture & perf 20 / Security reporting 20 / Test suite 15 / Implementability 15 | No |
| UMWM (Małopolska region) — HubMi.pl | Partner | 15,000 PLN (6k / 5k / 4k, before tax) | Challenge fulfilment 40 / Deployability 20 / Accessibility 20 / Bonus 20 | **Yes** — copyright transfers to organiser on payout |
| Miasto Kraków — Cracow without barriers | Partner | 5,000 PLN (single prize) | Usefulness 25 / Prototype 20 / Data trust 15 / Scalability 20 / Business model 20 | **Yes** — copyright transfers on accepting the prize |
| SuperTeam — Finance without Intermediaries | Partner | USD 3,000 (1,500 / 1,000 / 500)* | Relevance 30 / Completeness 25 / Idea 20 / Potential 15 / Originality 10 | No |

\* SuperTeam rules say "USD 3,000" total but list the places in PLN — likely a typo; ask at their booth.

Note: the homepage says 25,000 PLN for open tasks, but the five open briefs each say 8,000 PLN (40,000 total). The per-task PDFs are probably the authoritative source.

## Common submission requirements (open tasks)

Required: project title, team name, team members, project description, **PDF presentation, max 10 slides**.
Optional: snapshots, code repo, demo links, graphics, other materials.
Upload to **Challenge Rocket**; Polish or English.

AI policy (all tasks unless a partner overrides): AI tools are allowed. Disclose significant use of AI tools/models/APIs/datasets. The team must be able to explain and defend everything, including AI-generated parts. Separate pre-existing work from hackathon work.

---

## Open tasks

### Artificial Intelligence — 8,000 PLN
Build something where AI plays a meaningful role in addressing a specific user need. You can use existing models/APIs or your own.
Directions: making complex info findable/understandable; adaptive learning; accessibility; creative assistance; workflow automation; helping users analyse situations and compare options.
Show: the role AI plays, how the components fit together, technical decisions, capabilities **and limitations**, and **how users can verify outputs and stay in control**. Demo a concrete use case.

### Defence — 8,000 PLN
Strengthen security and resilience: pick a specific problem and the people who face it, then build something that prevents threats, detects them earlier, or reduces their impact.
Directions: helping small orgs find weaknesses and prioritise protections; verifying suspicious messages/content/sources; emergency coordination and info-sharing; mapping service dependencies and single points of failure; making security procedures easier to follow.
Consider incomplete info, limited resources, and services going down. Demo how it improves preparedness, response or continuity.

### ImpactHer: Technology for Real Change — 8,000 PLN
A tech solution to a real challenge that affects women (safety, health, education, career development, access to services, digital participation). Open domain. Start from a well-identified need; show the barriers removed and the real-world impact.

### Smart City — 8,000 PLN
Solve a specific problem for a city or its residents. Scale can be one street up to a whole city.
Directions: transport and journey planning; accessibility; energy/water/waste/shared infrastructure; resident↔institution communication; urban data for decisions; handling failures and emergencies.
Consider how accurate and up to date the info is, ease of use, and whether it could be tested in real urban conditions.

### Sport & Healthcare — 8,000 PLN
Help people take an informed, active role in their health, activity or wellbeing. Pick a specific user group and need.
Directions: patterns in activity/recovery/routines; sustainable exercise habits for different abilities; preparing for appointments and communicating with professionals; organising health info and sharing it with caregivers; access to activity and wellbeing support.
Focus on a clear user journey, accessibility, motivation and the effort needed for regular use.

---

## Partner tasks

### Huawei — Imagine What's Next — 25,000 PLN (12k / 8k / 5k)
Build an innovative **system feature or mobile app for an OpenHarmony-based device** (HarmonyOS / OpenHarmony / Oniro).
Themes (combining them is a plus): **Intelligent Experiences** (agents, on-device AI, personalisation), **Spatial Experiences** (spatial UI, 3D, sensing, positioning), **Human-Centric Tech** (accessibility, wellbeing, inclusion, education).
Tech: ArkTS + ArkUI or C/C++ native, or a cross-platform framework (e.g. React Native for OpenHarmony) **with a real OpenHarmony target** — an Android/iOS/web build alone doesn't count. **API 20+**. Must run on an OpenHarmony/HarmonyOS emulator or device. Recommended tooling: DevEco Studio, hvigor, HDC. Mentors have real devices on site.
Deliverables: public repo; reproducible setup/build/install/launch instructions; working **.hap**; short recorded demo; architecture description; **AI_WORKFLOW.md** (required if any AI tools were used — models, agents, MCP servers, main prompts, workflow, how output was validated, lessons learned); extra docs if the app has AI features.
Judging notes: they prefer a narrow working solution to a broad concept; real use of platform APIs (an app that would run unchanged on any OS scores lower); error handling, tests, no secrets in the repo; commit history should show progress.

### Goldman Sachs — AI Control Layer — 15,000 PLN (6k / 5k / 4k)
Build a lightweight **AI control layer** (gateway / proxy / middleware / SDK wrapper) that intercepts and governs traffic to and from AI systems (agent↔agent, app↔agent, agent↔MCP, agent↔model).
Required:
1. **Centralised policy engine** — one config source for controls, thresholds (block vs redact / adherence %), allowed models, and budgets.
2. **Hybrid guardrails** — deterministic (PII/secret regex, authn/authz checks) **plus** semantic/AI-based.
3. **Budget and resource governance** — token spend, compute time, resource access; covers both commercial APIs and local models.
4. **Historical attack mitigation** — signatures fed from an external source (malicious code execution, unsafe deserialisation, model-repo supply-chain attacks).
5. **Security reporting** — real-time metrics dashboard and exportable audit logs.
6. **Automated test suite** — positive (allowed) and negative (blocked/redacted) cases.
Deliverables: the layer and an architecture diagram; a documented sample policy file with strictness levels and budget rules; a simple dashboard; a runnable test suite. You can use an existing agent for the demo (agents aren't judged).
Judging: judges **run your test suite**, send ad-hoc prompts live, and **edit your config live** to watch how it adapts. Have performance telemetry ready.
Resources: none provided and no paid API keys. Expect to use local models (e.g. Ollama) and open-source tools; check licences. See OWASP (e.g. LLM Top 10) for threats.

### UMWM (Małopolska Regional Government / ROPS Kraków) — HubMi.pl — 15,000 PLN (6k / 5k / 4k, before tax)
Design, name and prototype an **AI-powered platform for the Małopolska Social Innovation Hub**. It should connect reported social problems with existing social innovations and support collaboration between residents, NGOs, local governments, ROPS staff and experts.
Modules (I is mandatory; each extra module scores more):
- **I. Social matchmaking (mandatory)** — a user describes a problem; the system finds similar cases and suggests existing solutions/innovations.
- II. Knowledge bank — regional social challenges (reports, Social Challenges Map), the Social Innovation Library (incl. videos), educational material; easy to update; admin-only trend aggregation of reported needs.
- III. Idea creator — short idea cards; a seasonal grant-application generator; Social Innovation Canvas; an AI assistant that helps develop and visualise ideas (nice to have).
- IV. Innovation tester — sign up to test, rate solutions, give feedback.
- V. Communication platform — dialogue with ROPS, mentor support, building partnerships.
- VI. Admin panel.
- VII. "Innovation Middleman" — an AI assistant that adapts an innovation into a service for a requesting institution.
Requirements: working MVP plus at least UX/UI mockups; **WCAG 2.1 AA** (seniors, people with disabilities); scalable; integration-ready; data security; **no real personal data**.
Submit: name and description; PDF (max 10 slides) **or** video (max 3 min); link to a working demo and the mockups; estimated running/maintenance cost.
Judging: fulfilment 40% (mandatory module 10%, each extra +5%), deployability 20%, accessibility and intuitiveness 20%, bonus 20% (UI originality/attractiveness 10%, quality of materials/MVP 10%).
Resources on site: Social Challenges Map, innovation library link, ROPS materials, canvases, sample data, mentors at the ROPS booth.
⚠ Winners transfer copyright to the organiser.

### Miasto Kraków — Cracow without barriers — 5,000 PLN (single prize)
A tool for residents and tourists to assess **how accessible places and routes are for their individual needs**, going beyond "accessible / not accessible". Pick a target group (e.g. wheelchair users, parents with prams).
Must:
- show specific barriers and facilities (stairs, thresholds, ramps, lifts, entrance width, surface, toilets, rest spots);
- show the **source, last-updated date and reliability level** of every piece of info, and clearly separate user reports from verified data;
- use public data (no manual database run by the city, no access to internal city systems); have a way to correct wrong data;
- handle **conflicting, missing or unavailable data** without ever implying "accessible" when info is missing;
- separate data ingestion from presentation; document how to add sources, place categories and cities;
- target **WCAG 2.2 AA**: keyboard, screen reader, contrast, and a text alternative to the map;
- avoid asking for disability info — preferences about barriers are enough;
- include a hosting/maintenance model outside city infrastructure, plus privacy and security basics.
Submit: description, prototype/demo, target group, data sources and how freshness/reliability is assessed, **business model**, PDF (max 10 slides), **video (max 3 min)**.
Judging: usefulness 25%, prototype quality 20%, data reliability/presentation 15%, scalability 20%, **business model/commercialisation 20%**.
Data: otwartedane.um.krakow.pl (JSON/CSV/XLSX/API), msip.krakow.pl (WMS/WFS), dane.gov.pl, OpenStreetMap (attribution required).
Contacts (mentor zone and Discord): Bartłomiej Węglarz, Karolina Grzanka, Michał Janaś.
⚠ Winners transfer copyright to the prize sponsor.

### SuperTeam Poland — Finance without Intermediaries — USD 3,000 (1,500 / 1,000 / 500)
On **Solana**, take a financial relationship that currently needs a trusted intermediary and redesign it so that **on-chain program logic enforces the terms** (escrow, freelancer settlements, conditional-refund fundraisers, revenue sharing, parametric insurance, loyalty programs, B2B settlements…).
Must: be a working app (not a mockup) with at least one full flow from user input to a confirmed transaction; show the moment the intermediary disappears; **demo live** (keep a backup recording). **Devnet is fine.** The enforcement logic must live on-chain, not in your backend. Name the target user explicitly. Include a short design rationale.
Stack: Anchor / native Rust / Pinocchio / Steel; any frontend with @solana/kit or web3.js and Wallet Adapter; SPL Token / Token-2022, Pyth / Switchboard oracles. They provide a dev container (VS Code / Codespaces); Solana Playground works in the browser.
Submit: title and description with design rationale; PDF (max 10 slides); video (max 3 min, public link); code repo.
Questions they'll ask: where in the code the intermediary disappears; what happens if one party vanishes mid-transaction; who has which permissions and whether you can change anything after deploy; **why blockchain and not a database**; what you'd do next.
They don't judge attack resistance, test coverage or polish.
Resources: matzayonc.github.io/stpl-bootcamp, github.com/matzayonc/solana-live-course-2026, solana.com/pl/docs, anchor-lang.com. Booth on site; Telegram @matzayonc / @matjanisz; pl@superteam.fun.
