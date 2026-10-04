# HackYeah 2026: all tasks (digest)

Read on Sun 4 Oct 2026 from <https://hackyeah.pl/tasks-prizes> and every RULES/DETAILS file linked there, plus the Huawei
organizer repo (`onirodeveloper/hackyeah2026-challenge`, last commit 1 Oct) and prelint.com. This is a digest, not a
copy. The linked PDFs are authoritative.

## Overview

| # | Task | Sponsor | Pool | Language | Deadline (as written) | Video | IP |
|---|---|---|---|---|---|---|---|
| 1 | Defence | Proidea (open) | 8 000 PLN | PL/EN | "11:00PM Oct 4" | optional | kept |
| 2 | Sport & Healthcare | Proidea (open) | 8 000 PLN | PL/EN | "11:00PM Oct 4" | optional | kept |
| 3 | Smart City | Proidea (open) | 8 000 PLN | PL/EN | "11:00PM Oct 4" | optional | kept |
| 4 | Artificial Intelligence | Proidea (open) | 8 000 PLN | PL/EN (rules; no note on site) | "11:00PM Oct 4" | optional | kept |
| 5 | ImpactHer: Technology for Real Change | Proidea (open) | 8 000 PLN | PL/EN | "11:00PM Oct 4" | optional | kept |
| 6 | REENTRY CTF | UNSHADE | 5 000 PLN + 5× IDA Pro Expert-4 | PL rules | **12:00 Oct 4** (runs 3 Oct 12:00 → 4 Oct 12:00) | n/a | n/a |
| 7 | Prelint Challenge | Prelint | USD 5 000 in Prelint credits | – | – | – | no rules file published |
| 8 | HubMI.pl | Woj. Małopolskie / ROPS Kraków | 15 000 PLN (6k/5k/4k) | **PL only** | **11:00 Oct 4** | **required, ≤3 min mp4** | **transferred to Proidea, then to the region** |
| 9 | Imagine What's Next | Huawei | 25 000 PLN (12k/8k/5k) | **EN only** | official HackYeah deadline | demo recording required | kept (3-yr non-exclusive promo licence) |
| 10 | Finance Without Intermediaries | Superteam Poland (Solana) | 11 300 PLN | PL/EN | "11:00PM Oct 4" | **required, ≤3 min, public link** | kept |
| 11 | Cracow Without Barriers | Gmina Miejska Kraków | 5 000 PLN | **PL only** | **11:00 Oct 4** | **required, ≤3 min mp4** | **transferred to the city** |
| 12 | AI Control Layer | Goldman Sachs (via Proidea) | 15 000 PLN (6k/5k/4k) | EN (site) / PL+EN (rules) | "11:00PM Oct 4" | optional | kept |

Notes that apply across tasks:
- **Deadline.** The Proidea-template rules say "11:00PM on October 4th" (and a start of "11:00 PM on October 3rd"). The
  HubMI and Kraków rules, the CTF and the general rules all say **11:00**. Treat **11:00 CEST** as the deadline (see
  [06-rules-and-huawei-integration.md](goldman/06-rules-and-huawei-integration.md) §2.4).
- **Platform.** HackTribe: <https://hackyeah2026.hacktribe.co/>. The open-task DETAILS PDFs still say "Challenge Rocket", which
  is a leftover. The rules say HackTribe.
- **Common package.** Title, team name, members (1–6), description, PDF ≤10 slides. Optional: screenshots, repo, demo link, graphics.
- **Judging.** Most tasks score in two phases: (1) a mentor commission reviews the HackTribe entry, then (2) finalists pitch
  live. A project needs **≥50%** to win. Jury lists go on Discord by Oct 4. Proidea prizes are paid within 90 days.
- **AI policy (open tasks, boilerplate).** AI is allowed. Disclose significant AI use, models, APIs and datasets. Separate
  pre-existing work from hackathon work. The team must be able to explain and defend everything, including AI-generated parts.
  A partner's own rules take precedence.
- **Website bug.** For Sport & Healthcare and Smart City, the DETAILS link serves the RULES PDF (the files are byte-identical),
  so neither task has a published brief beyond the paragraph on the site.

## 1–5. Open tasks (Defence, Sport & Healthcare, Smart City, AI, ImpactHer)

All five use the same rules template. Weights: **Idea & Innovation 30, Relation to Category 20, Practical Applicability /
Usability 20, Design (visual/UI) 20, Completeness & Implementation Value 10.**

- **Defence.** Build something that strengthens security and resilience: prevent, detect earlier or reduce consequences.
  Example directions: weakness triage for small organisations, verifying suspicious messages or sources, coordination during
  emergencies, mapping service dependencies and single points of failure, making security procedures easier to follow. The
  scenario should be realistic and degraded (incomplete info, limited resources, services down), and the demo should show
  better preparedness, response or continuity.
- **Sport & Healthcare.** The site says: holistically combine sport, physical health, mental wellbeing and access to care.
  Turn scattered health data into better decisions, not just monitoring. No DETAILS brief (see the bug above).
- **Smart City.** The site says: help cities work better day to day, covering mobility, energy, urban data, public services,
  quality of life and crisis response. No DETAILS brief.
- **Artificial Intelligence.** AI must play a *meaningful* role for a specific user need. Example directions: finding and
  understanding complex info, adaptive learning, accessibility, creative assistance, workflow automation, comparing options.
  Explain the AI's role, how the components fit, technical decisions, capabilities and limitations, and **how users verify
  outputs and stay in control**. Show one concrete use case. The site warns of "unexpected twists, themes or extra challenges".
- **ImpactHer.** A technology solution for a real challenge that disproportionately affects women (safety, health, education,
  career, access to services, digital participation). Start from a well-identified need and show practical, measurable impact.

## 6. REENTRY CTF (UNSHADE)

A story-driven CTF covering web, crypto, RE, pwn, forensics, AI challenges, real hardware and an on-site team game. Runs
**3 Oct 12:00 → 4 Oct 12:00**. Teams of **1–4**. Players must be adults, on site and registered through the Google Form plus
the platform. The flag format is `flag{…}`. Ranking is by points, with ties going to whoever made the earlier last correct
submission. **Only 1st place** gets the 5 000 PLN, paid by Proidea within 90 days. Sharing solutions gets a team
disqualified, and the organizer may ask for write-ups.

## 7. Prelint Challenge

Build your HackYeah project *using* Prelint, a PR "decision review" tool with a decision ledger that agents can query
through MCP or CLI. Show how it helped the team move fast without drifting. The best project gets USD 5 000 in Prelint
credits. **No rules or details document is published.** The website offers a free tier with $10 credits.

## 8. HubMI.pl (Małopolska Social Innovation Hub, ROPS Kraków)

Design, name and prototype the "digital heart" of the hub, an **AI-based platform**. Modules:
1. **Social matchmaking (mandatory).** The user describes a problem, and the system finds similar cases and proposes existing
   innovations.
2. Knowledge store: regional challenges map, Library of Social Innovations, educational content, and need-trend
   aggregation for admins.
3. Idea creator: idea "flashcards", a time-limited grant-application generator, innovation canvases, an optional AI
   assistant with visualisation.
4. Innovation tester: sign up to test, rate, give feedback.
5. Active communication: dialogue with ROPS, mentors, partnerships.
6. Admin panel.
7. "Innovation middleman": an AI assistant that adapts an innovation into a service for an institution.

Required: a working MVP (matchmaking mandatory, each extra module scores more), UX/UI mockups, **WCAG 2.1 AA** as the target,
scalable and integration-ready, data security, a **demo link + mockups**, and an **estimated running/maintenance cost**. No
real personal data.
Scoring is 1–10 per criterion, weighted: **Challenge fulfilment 40** (mandatory module 10, each extra module +5);
**Implementation potential 20**; **Accessibility & intuitiveness 20**; **Bonus 20** (UI attractiveness and originality 10,
quality of materials/MVP 10). Pitch in Polish. Results come at the closing ceremony, ~17:45. Prize money is split equally
across the team. **Winning requires signing a full copyright-assignment contract** (Proidea, then on to the region) and
handing over the source.

## 9. Imagine What's Next (Huawei): our entry B, Aegis Pocket

The PDF matches `hackathon_challenge.md` in the organizer repo word for word. Build an innovative system feature or app for an
OpenHarmony-based mobile device. Lead with **one** of: Intelligent Experiences / Spatial Experiences / Human-Centric
Technology (combining them is a plus if it serves a purpose).
- **Tech:** ArkTS/ArkUI or C/C++, or cross-platform (e.g. RNOH) *with* an OHOS target, or system frameworks. Target
  HarmonyOS/OpenHarmony/Oniro, **API ≥20, declared as the minimum**. It must run on an emulator or device, have reproducible
  setup/build/launch, and use or improve ≥1 platform capability. An "improvement" means an installable app or component that
  doesn't modify the system.
- **FAQ guidance:** in DevEco, keep Compatible SDK at 6.0.0 (API 20) and set `targetSdkVersion` to 24. For the Oniro
  Emulator, use API 23. The Previewer is not enough. Never commit the keystore. Account-backed signing is needed for a
  shareable `.hap`.
- **Deliverables:** public repo; setup/build/install/launch instructions; working `.hap`; short recorded demo; concise
  architecture/implementation description; `AI_WORKFLOW.md` (models, agents, MCP servers, skills, main prompts, workflow,
  review/validation, limitations, lessons); extra AI integration docs if the product has AI features (model, inference flow,
  data handling, limitations, validation, privacy).
- **Weights:** Originality 20, Demonstrated usefulness 20, Technical execution 20 (works as claimed, sensible architecture,
  error handling, **some tests**, no secrets, minimal permissions), Platform capabilities 20 (an app that would run unchanged on
  another OS scores lower), Demo quality 10 (real emulator, not mockups; say what was built during the hackathon), Reproducibility
  & transparency 10 (README alone suffices, versions documented, commit history shows progress). There may be an automated
  repo pre-review.
- **Rules:** EN only. Must be "created or substantially developed during the Challenge". Pre-existing and third-party parts and
  AI use must be identified. Teams keep their IP. Winners grant Huawei a 3-year non-exclusive non-commercial promo licence.

## 10. Finance Without Intermediaries (Superteam Poland / Solana)

Remove the need for trust from one financial transaction on **Solana** (devnet is fine). **The trust-replacing logic must
live on-chain.** If your backend enforces it, "the intermediary has become you." Name the target user explicitly. You need
≥1 full flow from user input to a confirmed transaction, and you must show the moment the intermediary disappears. **The demo
must be live**, with a recording kept as backup. Keep an explorer open and have two funded wallets ready.
Deliverables: title + description **with design rationale** (which relationship, who the intermediary was, what changes);
PDF ≤10; **public video ≤3 min**; repo with a clear README. Expect these judge questions: where in code the intermediary
disappears; what happens if a party vanishes mid-way; who holds which permissions and whether the author can change anything
post-deploy; why blockchain rather than a DB; what you'd do with another week. They don't audit or grade design or test coverage.
Weights: **Relevance 30, Completeness & functionality 25, Idea & problem 20, Implementation potential 15, Originality 10.**
Resources: github.com/matzayonc/solana-live-course-2026 (devcontainer), matzayonc.github.io/stpl-bootcamp, solana.com/pl/docs,
Anchor docs, Solana Playground. The code stays yours, but the repo must be public during judging.

## 11. Cracow Without Barriers (Kraków city)

A tool for residents and tourists to assess the accessibility of places and routes **for individual needs**, scoped to one
group (e.g. wheelchair users and parents with prams). It must give detailed barrier and facility info (steps, thresholds,
ramps, lifts, door width, surface, toilet, rest spots), not just accessible/not. **Every datum carries a source, date and
reliability status.** Unverified or user reports must be visually distinct. A gap in data must never be shown as "accessible".
The demo must include a conflicting, incomplete or source-down case. Use open data only (Kraków open data, MSIP WMS/WFS,
dane.gov.pl, OSM with attribution), with no access to city-internal systems and no city-maintained DB. Separate ingestion from
presentation. Target **WCAG 2.2 AA**: keyboard, screen reader, contrast, and a text alternative to the map. Don't require
disability disclosure. Include hosting and maintenance outside the city, privacy/security basics, and how to add a new city.
Deliverables: description and problem, prototype or demo, target group, data sources and how freshness and reliability are
judged, **business model**, PDF ≤10, **video ≤3 min**, everything in **Polish**.
**Weights conflict.** DETAILS: relation & usability 25, prototype quality 20, data reliability 15, scalability 20, business model
20. RULES: Idea 30, Technical 30, Design 20, Relation 10, WOW 10. Prize paid within **180 days**. **Copyright transfers to the
city** (the contract template still names a prior-year project, "Krakowskie cyfrowe centrum wolontariatu").

## 12. AI Control Layer (Goldman Sachs): our entry A, Aegis

Build a lightweight gateway, proxy, middleware or SDK wrapper that governs agent↔model, agent↔MCP, app↔agent and similar
traffic, driven by a **central policy/config** (controls, block-vs-redact thresholds, allowed models, budgets). It needs a
**hybrid** of deterministic controls (PII and secret patterns, authN/authZ) and semantic AI-based controls. It must also handle
budget and resource governance for paid APIs *and* local models; historical-attack mitigation with externally fed signatures
(code execution, unsafe deserialization, model-repo supply chain); real-time metrics plus exportable audit logs for security
teams and management; and an automated test suite with positive and negative cases.
Deliverables: the control layer plus an architecture diagram; a documented sample policy showing strictness levels and budget
rules; a simple dashboard (controls, posture, blocked threats, cost); a runnable test suite.
**How judges test it:** they run your test suite, fire ad-hoc prompts at the running layer, **edit config and feeds live**
(change rules, remove controls, adjust thresholds) to see if changes apply in real time, ask for **performance telemetry**, and
review the architecture, dashboards and logs. No datasets or paid subscriptions are provided, so it should run on local
models (e.g. Ollama).
**Weights conflict.** DETAILS: Robustness/guardrails 30, Architecture & performance 20, Security reporting 20, Test suite 15,
Implementability & scalability 15. RULES: 30/20/20/**20**/**10**. Judging has two phases (HackTribe review, then live pitch
for finalists). IP stays with the team.
