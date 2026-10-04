# 06: HubMI.pl rules, scoring maths and submission pack

Sources: the HubMI RULES PDF (26 pp., PL + EN + copyright-assignment contract template) and the DETAILS PDF (8 pp., PL),
both linked from <https://hackyeah.pl/tasks-prizes>, read on Sun 4 Oct 2026. Digest of all tasks:
[../hackyeah-2026-all-tasks.md](../hackyeah-2026-all-tasks.md). HackTribe's task page needs a login and was not read.

## TL;DR

1. **Deadline: Sun 4 Oct, 11:00 CEST, on HackTribe** (RULES §2.1 and §4.8 say 11:00 explicitly, so this one is unambiguous).
   Late files are not judged.
2. **Everything must be in Polish**: the submission, the materials and the live pitch (§4.9, §5.5).
3. **Scoring rewards breadth.** "Challenge fulfilment" is 40%: the mandatory matchmaking is worth 10%, and **each additional
   module is worth +5%**. There are 6 optional modules, so **all 7 modules = the full 40%**. A thin but working version of every
   module beats a polished matchmaking alone, but matchmaking quality is still judged ("jakość działania kluczowych elementów").
4. **The other 60%** is implementation potential 20 (scalable, flexible, cheap and simple to maintain), accessibility and
   intuitiveness 20 (WCAG 2.1 AA, all ages and skill levels), UI attractiveness and originality 10, and quality of materials and
   MVP 10.
5. **Copyright transfers if you win.** A laureate must sign a full economic-copyright assignment to Proidea, which then passes to
   Województwo Małopolskie, and hand over the source code. A public MIT/Apache repo would conflict with an *exclusive* transfer.
   **Decision for the user:** keep the HubMI code in a **separate repo** and decide its licence or visibility deliberately.
6. **Build it in a separate repo, not this one.** This repository *is* the public Huawei submission. A web app at the root would
   muddy the Huawei README, commit history and automated pre-review, and would mix IP regimes.

## 1. Rules that matter (RULES, EN part, with § refs)

| Topic | Rule |
|---|---|
| Window | Starts 3 Oct 11:00 and ends 4 Oct **11:00**. Max 24 h. On site only (Tauron Arena). §2, §4.3–4.4 |
| Team | 1–6 people, adults with full legal capacity. §3.1, §3.4 |
| Required in the submission | **Project title, team ID, project description, PDF ≤10 slides, mp4 video ≤3 min.** Optional: screenshots, repo, demo links, graphics. **Polish.** §4.9 |
| DETAILS adds | Name and description of the solution. PDF **or** film (RULES says PDF **and** mp4, so do both). **Link to a working demo and UX/UI mockups.** **Estimated operating/maintenance cost and the resources it needs.** DETAILS §4 |
| Jury | Mostly Województwo Małopolskie representatives. Simple majority, chair breaks ties. §5.1–5.2 |
| Scoring | Each criterion 1–10, weighted average. **≥50% of max** needed to be a laureate. §5.3–5.4 |
| Pitch | **In Polish.** §5.5 |
| Results | 4 Oct at the closing ceremony (~17:45). Up to 3 laureates: **6 000 / 5 000 / 4 000 PLN**, gross, split equally per member. §6 |
| Payout conditions | Sign the copyright-assignment contract and provide tax data. Paid within 60 days of the contract. §6.6–6.7 |
| IP | Economic copyright to the awarded work (incl. **source code** and docs) passes to Proidea when the prize is paid. Very broad fields of exploitation. Further transfer to the region. Authors waive their moral rights against them. Refusing to sign means giving up the prize. §7 |
| Data | Do **not** use real personal or sensitive data from ROPS materials. DETAILS §9 |
| Contract warranties | The authors warrant the work is **made personally**, is **not a derivative of someone else's work**, is unencumbered, and is **unpublished** apart from being shown for judging. Code is delivered as a zip with a full toolchain list. Contract §1 |

**Implications of the contract warranties (not legal advice, verify with the organiser if we place):**
- "Unpublished except for evaluation" plus an *exclusive* transfer suggests **not** releasing the HubMI code under an open licence
  before results. A private repo shared with the jury, or a public repo marked "all rights reserved", is the safer default.
  **This is the user's call.**
- Third-party OSS dependencies are fine as dependencies (they remain under their own licences). Keep a dependency list ready,
  since the contract asks for "a complete list of tools, libraries and other elements".
- AI-generated code: the HackYeah AI policy allows it, but the team must be able to explain everything. Disclose AI use in the
  description (good practice, and consistent with the AI policy in the open-task briefs).

## 2. Scoring maths: where the points are

| Criterion | Weight | What earns it (from DETAILS §6/§8) | Our lever |
|---|---|---|---|
| Challenge fulfilment | 40 | Quality of key elements and **number of extra modules**: mandatory 10 + 6 × 5 | Ship **all 7 modules**, with matchmaking deep and the others thin but working |
| Implementation potential | 20 | Practical use, scalability, flexibility, optimisation, **cost efficiency, simple maintenance** | Managed EU hosting, one DB, a swappable LLM provider, a cost table, an integration story (grant DB, notifications) |
| Accessibility and intuitiveness | 20 | Any age or skill level fills the modules and finds info. WCAG 2.1 AA | Plain Polish, big targets, a step-by-step flow, voice input, an axe report in the PDF, a draft "deklaracja dostępności" |
| UI attractiveness and originality | 10 | Novel approach, attractive mockups | A distinctive visual identity and a "new quality" feature (see 03-prior-art) |
| Materials and MVP quality | 10 | How the concept is communicated, quality of submitted materials | A tight 10-slide PDF, a 3-minute video, a clean demo link |

The DETAILS §6 validation questions, each of which needs a visible answer in the demo:
1. **Intuitiveness:** can a resident of any age fill in the modules without technical prep?
2. **Communication speed:** *how does the system notify the admin about a new idea, and what is the reply path to the author?*
   This needs an explicit notification and reply loop in the demo.
3. **Match relevance:** does it suggest existing innovations from the keywords in a need description? Show a match explanation.
4. **Ingenuity:** does it just re-integrate other portals, or create a "new quality"?

The "focus on" list: ingenuity and attractiveness, ease of reporting a problem, relevance of the proposed solutions, intuitive
interface, quality of communication between users, and growth potential.

## 3. Submission checklist (all in Polish)

- [ ] **Name** of the solution. Naming is an explicit part of the brief ("zaprojektowanie, nazwanie…").
- [ ] Project title and team ID on HackTribe, project description (Polish).
- [ ] **PDF, ≤10 slides** (Polish).
- [ ] **mp4 video, ≤3 min** (Polish narration or captions), uploaded as required by HackTribe.
- [ ] **Link to the working demo** (publicly reachable, seeded with sample data, no login wall for judges or a demo account).
- [ ] **UX/UI mockups.** Annotated screenshots of the real app count, and a short Figma-like board is a plus.
- [ ] **Operating/maintenance cost estimate and the resources needed** (a table, pilot vs region scale).
- [ ] Optional: repo link (see the IP decision), screenshots, accessibility report.
- [ ] A clear mark on **synthetic or sample data** (no real personal data).

## 4. Time budget (it was 06:30 when this was written; deadline 11:00)

| Window | Work |
|---|---|
| 06:30–07:15 | Research (parallel tracks 01–05) and the plan. **User decisions** (name, stack, repo, scope) |
| 07:15–09:30 | Build: seed data, matchmaking, then thin modules II–VII, then a11y pass, then deploy |
| 09:30–10:15 | Polish materials: screenshots as mockups, 10-slide PDF, cost table, 3-min video (the user records) |
| 10:15–10:40 | HackTribe upload and buffer. **The Aegis and Aegis Pocket uploads (target 10:00) must not slip because of HubMI** |

## 5. Open questions for the organisers (ROPS booth / Discord)

- PDF **and** video, or either? RULES says both, DETAILS says either. Default: both.
- Is a demo account or seeded login acceptable, or must the demo be open?
- May we use the sample data handed out on site, and under what terms? Where are the on-site materials (challenges map, library
  link, canvases)?
- Does the jury expect the repo to be private given the copyright transfer?
