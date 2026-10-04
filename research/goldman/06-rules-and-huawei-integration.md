# 06: HackYeah 2026 rules check (plus an optional Huawei tie-in)

Researched Sat 3 Oct 2026, around 16:30 CEST. Research and planning only.

**Scope note.** Mid-task, the scope changed. The Goldman Sachs "AI Control Layer" is now a standalone
project with its own repo and web UI, and it is not integrated with the Huawei app. Part A (rules) is
therefore the main deliverable. Part B is cut down to one short optional section (§5).

---

## TL;DR

| Question | Answer | Source |
|---|---|---|
| Can one team submit to more than one task? | **Yes.** The FAQ says there is no limit on the number of tasks a team can work on. | hackyeah.pl/faq › Tasks Q4, Q6 |
| Limit on tasks per team? | **No limit on tasks.** The limit is **one project per category (task)**. | hackyeah.pl/faq › Tasks Q4 |
| Same project/codebase to two tasks? | **Technically possible, but the organizers say they "strongly discourage submitting one project to more than one category".** No rule forbids it. Their copyright-transfer reason does not apply to Goldman or Huawei, because neither one transfers IP. | hackyeah.pl/faq › Tasks Q5; GS rules pt 14; Huawei rules §7 |
| Final deadline | **Sun 4 Oct 2026, 11:00 CEST.** Some English texts say "11:00 PM" or "11 PM". That is almost certainly a mistranslation (see §2.4). | General Rules 4.3 (Polish text: "godz. 11:00"); hackyeah.pl agenda |
| Intermediate deadline | **Sat 3 Oct, 20:00: "Project checkpoint deadline: submit your first project draft".** This is in the agenda only, not in the rules. Do it anyway. | hackyeah.pl agenda |
| Platform | **HackTribe**, not Challenge Rocket. The team leader signs up, joins the "HackYeah 2026" event, creates the team and fills in the project page. A Discord account is needed first. | FAQ › Uploading Q7–Q9, Tasks Q9; GS rules pt 5, 8a; Huawei rules §4 |
| Required fields (HackTribe) | Category; title (English, ≤5 words); description (English, ≤500 words, including names, surnames and emails of all members); ≥1 image; PDF presentation (English, ≤10 slides). Optional: video URL, demo link, repo URL, opening instructions. | FAQ › Uploading Q8 |
| Video limit | **≤60 seconds, in English** (an optional field in general). For Huawei, a recorded demo is a required deliverable, so plan a ≤60 s cut. | FAQ › Uploading Q8; Huawei deliverable 4 |
| Team size | **1–6** (General FAQ, GS rules pt 5c, Huawei rules §3). One person may be in more than one team. | FAQ › Teams Q1, Q4 |
| Submission language | **English** for both tasks. The Goldman rules allow Polish, but the task page says English is required. Huawei requires English. | hackyeah.pl/tasks-prizes; Huawei rules §4 |

---

## 1. Sources found, and where I looked

**Found (primary):**

1. **HackYeah 2026 general Rules (Regulamin / Rules)**: <https://hackyeah.pl/rules> serves a 15-page PDF
   titled "HackYeah_2026_Regulamin_Rules". It is in Polish (pp. 1–8) and English (pp. 9–15), was last updated 7 July 2026,
   and has been in force since 21 April 2026. Local text extract:
   `/private/tmp/claude-501/-Users-nevvdevv-Development-hackathons--october-2026-hackyeah/f9181857-ae21-42c3-91ac-8e07ff31b75d/scratchpad/hackyeah2026_rules.txt`.
2. **HackYeah 2026 FAQ**: <https://hackyeah.pl/faq>. This is a single-page app, and the answers sit in accordions that load from the CMS.
   I rendered it in a browser and opened every accordion to read the answers. A plain fetch shows only the questions.
3. **Agenda**: the homepage <https://hackyeah.pl/> (agenda section, rendered in a browser).
4. **Tasks page**: <https://hackyeah.pl/tasks-prizes>. It gives a language note for each task and links to each task's RULES and DETAILS PDFs.
5. **Goldman Sachs task**: Drive folder `Partner Task [Goldman Sachs] - AI Control Layer`
   (<https://drive.google.com/drive/folders/1iNbiAxQjeHfU1onSlfy_9-2ECR1iiCVD>):
   - `RULES AI Control Layer.pdf` (file id `1n8Crzx4HjyQFZFudeF5QnEcpY2OZt4LP`, 3 pp., created 3 Oct 10:47).
     It is byte-identical (sha1 `89dd2528…`) to the RULES link on hackyeah.pl/tasks-prizes.
   - `CRIETRIA AI Control Layer` (sic; id `1oGwpQ5sD-x5I9ERwCQJvz-gfbHJ5aGYG`): the full task brief and criteria.
6. **Huawei task**: Drive folder `Partner Task [Huawei] - Imagine what's next`
   (<https://drive.google.com/drive/folders/1SRQXvpaRorZLMEMgExC60bPP-t7lLv-P>):
   - `RULES Imagine What's Next` (id `10WcJMWOLPcJA4RqDeyyr3ZsMFfi1UJ3L`, 5 pp.). It is byte-identical (sha1 `da534130…`) to the
     hackyeah.pl RULES link.
   - `CRITERIA Imagine What's Next` (id `1S5V-x4RW3NK3YgI4TLxIsmiS8LF7_-zN`). Its content is identical to `hackathon_challenge.md` in
     the organizers' repo.
7. The organizers' Huawei repo (local clone `…/scratchpad/hy-challenge`): `hackathon_challenge.md` (Required Deliverables),
   `FAQ.md` (§Submission, §Signing), and `README.md` (emulator capability comparison).

**Looked, but not useful or not applicable:**
- `challengerocket.com/hackyeah-2026` returns 404. Challenge Rocket was HackYeah's platform in 2024 (a 2024 page links
  `challengerocket.com/hackyeah-2024/participant-manual-`). For 2026, every source names **HackTribe**.
- Web searches for "HackYeah 2026 regulamin" and "HackTribe HackYeah 2026" found no public HackTribe event URL. HackTribe is a
  hackathon SaaS from Riga. I did not find a direct link to the HackYeah 2026 event page on HackTribe. Ask on Discord, or check
  the email or Discord announcements.
- crossweb.pl returns 403. Search snippets from listing sites (crossweb, infosec-conferences) say 11:00 AM Sat to 11:00 AM Sun.
- Note: in the general Rules, "Platforma" means **eventory.cc** (ticket registration), not the submission site.

---

## 2. Answers in detail

### 2.1 Can one team submit to more than one task? Yes.
- **FAQ › Tasks Q4 ("Can my team do more than one task?")**: there is no limit on how many tasks a team solves, but only
  **one project may be submitted per category**.
- **FAQ › Tasks Q6**: after finishing, teams are encouraged to start another task, and there is no limit on how many they complete.
- **General Rules 4.2**: Competitions are *independent of each other* ("niezależne od siebie Konkursy"), and each one is
  organized and funded by the Organizer or a Partner. **4.9**: submitting a solution to a Competition counts as accepting *that*
  Competition's rules. Each submission is therefore governed by its own task rules.
- The general Rules have **no clause** that limits or forbids multiple submissions. This was checked against the full PL and EN text.

### 2.2 Can the same project or codebase go to two tasks? Discouraged, not forbidden.
- **FAQ › Tasks Q5 ("Can I submit one project to more than one category?")**: the organizers give two reasons. Tasks have
  different requirements, and some tasks transfer copyright to winners, which cannot be done for two tasks at once. Their
  conclusion is that it is technically possible, but they "strongly discourage submitting one project to more than one category".
- **The copyright reason does not bite for our pair.** Under GS rules pt 14, the authors' economic copyrights are *not*
  transferred to the sponsor. Under Huawei rules §7, the team keeps ownership, and winners grant Huawei only a 3-year,
  non-exclusive, non-commercial licence for demo and promo use. (UMWM HubMi and Miasto Kraków *do* transfer copyright, so never
  combine with those.)
- **Huawei-specific:** §4 requires the solution to be created or substantially developed during the Challenge. Pre-existing
  or third-party components are allowed but must be identified in the docs. If the Goldman gateway were reused inside a Huawei
  submission, it would have to be declared as a component, and the Huawei jury would only credit the HarmonyOS part.
- **Now moot.** With the scope change (Goldman is standalone and not integrated), we would submit **two different projects**
  to two categories. That is explicitly allowed (FAQ Tasks Q4) and does not trigger the Q5 discouragement.

### 2.3 Limit on the number of tasks per team
- None (FAQ › Tasks Q4, Q6). The only limit is **one project per category per team**.
- A person may also be in several teams (FAQ › Teams Q4). Membership is fixed by the team leader on HackTribe at upload time
  (Teams Q5, Q6). Team details (name, project name, members, attachments) are locked once voting rounds start (Teams Q7).

### 2.4 Deadline: Sunday 4 Oct 2026, 11:00 CEST (treat as binding)
- **General Rules 4.3, Polish text (authoritative original)**: the submission site is open from **11:00 on 3 Oct to 11:00 on 4 Oct 2026**.
- **Agenda (hackyeah.pl)**: Sat 11:00 tasks unlocked and coding starts. Sat **20:00 "Project checkpoint deadline"** (submit a
  first draft). **Sun 11:00 "Final submission deadline"**. Sun 11:00 jury evaluation begins. 15:00 finalists announced.
  16:00 final pitching. 17:45 winners announced.
- **Conflict:** the English Rules 4.3, the GS rules pt 5 ("no earlier than 11:00 PM on October 3rd … no later than 11:00PM on
  October 4th") and FAQ › Uploading Q1 ("11 PM on Sunday") all say **PM**. This is almost certainly a translation error:
  - The Polish original uses the 24-hour "11:00".
  - Coding starts at 11:00 AM on Saturday.
  - An 11 PM Sunday deadline would fall *after* the 17:45 winners announcement.
  
  **Plan for 11:00 Sunday.** Confirm on Discord.
- **Huawei rules §4** follow the official HackYeah schedule. Late submissions are not considered. Results come on 4 Oct at the closing ceremony (§6).
- **No edits after the deadline**: General Rules 5.8 and GS rules pt 13. FAQ › Tasks Q10 says to upload an unfinished
  project early and keep editing it until the deadline.
- **GS rules pt 5** also require that work on the task **started no earlier than** the task start (11:00 on 3 Oct).

### 2.5 Platform: HackTribe
- **FAQ › Uploading Q7**: the team leader signs up and logs in to **HackTribe**, joins the **HackYeah 2026** event, creates a
  team, adds members by email or invite link, and fills in all project details before the deadline. The project stays editable
  until then.
- **FAQ › Uploading Q1 and Tasks Q9**: you must have a **Discord account before uploading**, because Discord IDs are required.
- **GS rules pt 5(e)**: submissions go to the HackTribe platform. **Pt 8(a)**: phase-1 evaluation happens on HackTribe.
- **Huawei rules §4**: submit through the platform specified by HackYeah, which is HackTribe.
- FAQ › Tasks Q6 notes that a Partner *may* choose another platform. Neither GS nor Huawei does.

### 2.6 Required submission fields

**Generic HackTribe form (FAQ › Uploading Q8):**

| Field | Status | Constraints |
|---|---|---|
| Category | Mandatory | Which task the project goes to |
| Project title | Mandatory | English, **max 5 words** |
| Description | Mandatory | English, **≤500 words**; must include **names, surnames and emails of all team members** |
| Image gallery | Mandatory | **≥1 image** (screenshots, UI and so on) |
| Presentation | Mandatory | English; PDF, or PDF + PPTX; **≤10 slides** |
| Video URL | Optional | **≤60 s**, English; a project video or a member explaining it |
| Demo link | Optional | Include login info if needed |
| Repository URL | Optional* | One repo, with modules in separate folders; must be viewable online |
| How to open the project | Optional | Instructions for judges |

\*The FAQ says a partner may make optional fields mandatory.

**Goldman overlay (GS rules pt 5 and the CRITERIA brief §3, §6):**
- Rules pt 5 requires (a) title, (b) team name, (c) member list (1–6), (d) description, and (e) a PDF of ≤10 slides. The PDF may
  include snapshots, a code repo, demo links and graphics.
- The brief's expected outcomes are: the control layer; an architecture diagram; a documented sample policy file with
  strictness levels and budget rules; a simple interactive dashboard; and an executable test suite. Judges will run the test
  suite, send ad-hoc prompts, and edit config or feeds live. Have performance telemetry ready.
  → The **repo URL is effectively mandatory** for us, and so are **"how to open the project"** instructions.
- Evaluation has two phases. Phase 1 is on HackTribe, by a commission of at least 3 mentors. Phase 2 is a live pitch by
  finalists to the jury (pt 8). A prize needs **≥50% of points in phase 1** (pt 12).
- ⚠ **Criteria weights differ between the GS documents.** RULES pt 11 gives Robustness 30 / Architecture & perf 20 /
  Security reporting 20 / **Self-testing suite 20 / Implementability & scalability 10**. The CRITERIA brief §8 gives
  30/20/20/**15/15**. The brief matches what we were told. Ask at the GS booth which one applies. Either way, tests are worth
  15–20%.

**Huawei overlay (Huawei rules §4 and hackathon_challenge.md › Required Deliverables):**
- A public source repo; reproducible setup, build, install and launch instructions; a **working `.hap`**; a **brief recorded
  demo**; a concise architecture and implementation description; `AI_WORKFLOW.md` (mandatory if any AI was used); and extra AI
  docs if the app has AI features.
- Everything must be in English. Material pre-existing or third-party components, and AI tool use, must be identified (§4).

### 2.7 Video length
- **≤60 seconds, English** (FAQ › Uploading Q8, the HackTribe "Video URL" field). Neither the GS nor the Huawei rules
  override this. Other tasks such as Kraków and SuperTeam allow up to 3 min, but that is task-specific.
- Goldman: video optional. The live demo and the pitch matter more.
- Huawei: a "brief recorded demonstration" is required, so make a **≤60 s** video for the field. A longer walkthrough could
  be linked from the README, but it is unverified whether judges will watch it. Ask a Huawei mentor.

### 2.8 Team size
- **1–6 people**: FAQ › Teams Q1, GS rules pt 5 and 5(c), Huawei rules §3. Only registered HackYeah 2026 participants may be
  members (Huawei §3). People related to the jury or sponsor are excluded (GS pt 6, Huawei §3).

### 2.9 Other rules worth knowing
- **Pre-existing work** (FAQ › Tasks Q13, Q14): prior or external resources, tools and repos must be fairly cited. Paid assets
  give no advantage. Huawei §4 allows pre-existing code, templates and AI tools if declared. The GS rules (pt 5) require starting
  the task no earlier than the task start.
- **Prizes**: GS gives 6k / 5k / 4k PLN including tax (pt 7), paid within 90 days (pt 4). Huawei gives 12k / 8k / 5k PLN,
  split equally among the members listed in the submission and paid within 60 days (§6).
- **Jury lists**: published on Discord by 4 Oct (GS pt 15; General Rules 5.3).
- **Pitch**: only finalists pitch, and only one team member presents (FAQ › Tasks Q11). Finalists are announced on Discord and HackTribe (Q12).

---

## 3. What this means for us (checklist)

1. **Before 20:00 tonight (Sat):** the team leader creates the HackTribe account, joins "HackYeah 2026", creates the team,
   adds all members (name, surname, email; Discord IDs needed), and saves a **draft project in the Goldman "AI Control
   Layer" category**. If the Huawei app is still alive, save a second draft in "Imagine What's Next". Drafts are editable
   until the deadline.
2. **Two categories means two separate projects** on HackTribe, each with its own title, description, images, PDF and repo.
   This is allowed (FAQ Tasks Q4). Goldman is now standalone, so the Q5 discouragement does not apply.
3. **Fallback is clean.** If Huawei isn't finished, simply don't submit to that category. Uploading is not mandatory (FAQ › Tasks Q7).
4. **Freeze for 11:00 Sun.** Aim to have everything uploaded by about 10:00. The FAQ warns about the last-minute crush.
5. **Goldman pack:** a ≤5-word English title; a ≤500-word description with member details; ≥1 screenshot of the dashboard; a
   ≤10-slide PDF (architecture diagram, policy file, test results, telemetry); a public repo with a one-command test run and
   "how to open" instructions; an optional ≤60 s video.
6. **Huawei pack (only if submitted):** a public repo, `.hap`, README build steps, `AI_WORKFLOW.md`, a ≤60 s demo video, and
   architecture notes, all in English.

## 4. To confirm (Discord or booths)
- Is the deadline 11:00 or 23:00 on Sunday? (Expect 11:00.)
- Is the 20:00 checkpoint draft mandatory or only advisory?
- Goldman criteria weights: RULES (20/10) or brief (15/15)?
- Huawei: is a demo video longer than 60 s acceptable outside the HackTribe field (for example, linked from the README)?
- The direct HackTribe URL for the HackYeah 2026 event.

---

## 5. Optional: if we later want a Huawei tie-in

The lightest tie-in would be a **separate HarmonyOS "approval companion" app**. It would be a small ArkTS client of the
standalone gateway's existing HTTP API: posture and audit read endpoints, plus a pending-approvals endpoint.

**What it would do:**
- Show a **Form Kit home-screen widget** with the security posture: blocked count, budget burn, last incident.
- Raise **local Notification Kit notifications** when an agent action is held for human-in-the-loop review.
- Let the user approve or deny from the phone, and optionally from a **wearable emulator profile**.

**Emulator support:** notifications, widgets and wearable profiles all work on the DevEco emulator, according to the organizers'
emulator capability table. Avoid Push Kit and Live View. They need AppGallery Connect / HUAWEI ID setup, which is unverified
here. Poll or use a WebSocket and post local notifications instead.

**How it would score:** it fits **Intelligent Experiences / responsible technology**. Platform use is moderate, from the widget,
the notifications and the wearable profile.

**Boundary:** a separate public repo, README, `.hap`, ≤60 s video and HackTribe entry. The Goldman project never depends on it.
Declare the gateway as a pre-existing or third-party component in the Huawei docs (Huawei §4), so the two are clearly two
projects and not one project submitted twice.
