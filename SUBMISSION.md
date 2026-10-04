# HackYeah 2026: final HackTribe submission pack (two entries)

This repository holds **two separate HackTribe entries**:

| # | Entry | Category on HackTribe | Code |
|---|---|---|---|
| A | **Aegis: Local-First AI Guardrails** | Goldman Sachs: *AI Control Layer* | [`aegis/`](aegis/) |
| B | **Tiles: A Phone That Adapts** | Huawei: *Imagine What's Next* | repository root |

**Deadline:** upload by **Sun 4 Oct 10:00** (hard limit **11:00 CEST**; read the "11 PM" in the English rules as
11:00, see `research/goldman/06-rules-and-huawei-integration.md` §2.4). You cannot edit after the deadline. Upload
early and keep editing until then.

**How to paste:** copy only what is **inside** the `text` blocks. HackTribe fields are listed in form order
(organizers' FAQ, "Uploading" Q8). The **only** edit to make on HackTribe is the `Team:` line. Replace
`[YOUR FIRST NAME SURNAME — EMAIL]` with the real first name, surname and email of every member, one per line.
**Never commit those details to this public repo.**

Word counts use whitespace split, the same as `aegis/docs/submission/build.py`. They include the placeholder team line.

| | Title words (≤ 5) | Description words (≤ 500) |
|---|---|---|
| A: Aegis | 4 | 491 |
| B: Tiles | 5 | 479 |

Each extra team member adds about 4 words. Entry A then has 491 + 4 per member; entry B has 479 + 4 per member.

---

## A. Aegis: Goldman Sachs "AI Control Layer"

### A1. Category

```text
Goldman Sachs: AI Control Layer
```

(Pick the Goldman Sachs task in the HackTribe category list. The name on the form may differ slightly.)

### A2. Title (4 words)

```text
Aegis: Local-First AI Guardrails
```

### A3. Description (491 words incl. placeholder team line)

Source: `aegis/docs/submission/out/HACKTRIBE.md` (rendered numbers). The only change is the team line.

```text
Problem. Every agent call can leak customer data to a remote model, run a poisoned tool, burn budget in a loop, or take an action nobody approved.

Solution. Aegis is one lightweight local gateway on every hop: agent to model (Anthropic, OpenAI-compatible and Ollama APIs), agent to MCP tools, agent to third-party HTTP, and Claude Code's own tool calls. Each request passes one policy pipeline and ends in allow, redact, block, require approval or log.

Local-first redaction (headline). PII, payment cards, Polish IDs (PESEL, NIP, REGON, IBAN), secrets and metadata are detected on the device and replaced with reversible placeholders before anything leaves. Checksum validators keep false positives low; a multilingual NER model catches names. Real values are restored only for the local user. CVVs are dropped, never stored.

Goldman Sachs requirements:
1. Centralized policy: one YAML file (controls, block/redact thresholds, adherence %, allowed models, budgets, approval rules, four strictness profiles), hot-reloaded with validation, a self-test gate, atomic swap and last-known-good fallback.
2. Hybrid guardrails: deterministic detectors first (validators, secret patterns, command and SSRF guards, MCP tool pinning), then small local models (injection classifier, Qwen3Guard, NER).
3. Budgets: org, team, agent and session limits on tokens, USD and local compute-seconds; loop detection; downgrade to a local model; kill switch.
4. Historical attacks: a separate threat-intel service publishes Ed25519-signed signature bundles (malicious pickles, compromised packages, MCP tool poisoning, EchoLeak-style exfiltration) that the gateway verifies and hot-swaps; tampered or rolled-back bundles are refused.
5. Reporting: live management, security and performance dashboard; Prometheus metrics; hash-chained audit log with JSONL, CSV and OCSF export.
6. Self-testing: one command runs allowed and blocked cases for every control, including budgets, approvals and exploit replays.

Organization governance. Owners, admins, members, and agents as service identities. Approval rules route actions by type and amount: an agent's $12 purchase is confirmed by its sponsor, a $50 subscription goes to an admin, $480 to the owner, above $1,000 to the owner plus a second admin. Reading a PII table needs an admin, a production write the owner. Budget raises and disabling controls are governed too. Approvals are bound to exact parameters, expire and are audited.

Claude Code. Model traffic via ANTHROPIC_BASE_URL, tool calls via a fail-closed PreToolUse hook, MCP servers via our proxy, all from one demo settings profile with no machine-wide changes.

Tech. Python 3.13, FastAPI, SQLite, RE2, ONNX Runtime, Ollama; React dashboard. Runs offline on an 8 GB laptop; all models optional.

Measured on 1,234 labelled prompts (make eval): with the optional local models 92.4 % attack detection (89.6 % held-out) at 5.1 % false positives; deterministic only (default) 66.6 % at 0.4 %. make test: 2,006 tests pass. Overhead p50 2.40 ms.

How judges test it. Code: https://github.com/JustAnotherDevv/tiles-hackyeah-2026/tree/main/aegis. In aegis/: make setup, make up, open http://127.0.0.1:8787/ui, then make test. Try the Playground, edit config/policy.yaml and watch the next decision change, or publish a feed signature and replay the exploit. Guide: aegis/docs/JUDGES.md.

Team: [YOUR FIRST NAME SURNAME — EMAIL]
```

### A4. Image gallery (≥ 1 required)

| Upload | File | Status |
|---|---|---|
| 1 (cover) | `aegis/docs/submission/video/cover.png` (1920×1080, title card) | ✅ exists, pushed |
| 2 | `aegis/docs/assets/architecture.png` (1920×1080) | ✅ exists, pushed |
| optional 3–5 | product screenshots `aegis/docs/assets/screens/*.png` (list in `aegis/docs/submission/out/HACKTRIBE.md` §4) | ⏳ not captured. Optional. Frames can be grabbed from the video, e.g. `ffmpeg -ss 12 -i aegis/docs/submission/video/aegis-demo-60s.mp4 -frames:v 1 shot.png` |

### A5. Presentation (PDF, ≤ 10 slides)

`aegis/docs/submission/out/Aegis_HackYeah2026_GS_AIControlLayer.pdf`: ✅ 10 pages, pushed.

### A6. Video URL (optional, ≤ 60 s)

File: `aegis/docs/submission/video/aegis-demo-60s.mp4`. ✅ 57.45 s, 1920×1080, 14.9 MB, silent, burned-in captions, pushed.

- **Recommended:** upload it to YouTube as **Unlisted** and paste the YouTube URL. It then plays in the browser.
- Fallback (downloads rather than streams):

```text
https://github.com/JustAnotherDevv/tiles-hackyeah-2026/raw/main/aegis/docs/submission/video/aegis-demo-60s.mp4
```

### A7. Demo link

Leave empty. There is no hosted instance, and the gateway must not be exposed publicly.

### A8. Repository URL

```text
https://github.com/JustAnotherDevv/tiles-hackyeah-2026/tree/main/aegis
```

### A9. How to open the project (judge instructions)

```text
Requirements: macOS or Linux, uv (installs Python 3.13), Node 20.19+ or 22.12+ to build the dashboard. Models are optional: without them the demo runs deterministic-only (the default); make models + Ollama add the semantic controls.
1. git clone https://github.com/JustAnotherDevv/tiles-hackyeah-2026 && cd tiles-hackyeah-2026/aegis
2. make setup && make web && make up     # gateway :8787, threat feed :8790, mocks :8791-8794
3. Open http://127.0.0.1:8787/ui and use the view-as switcher (owner u_katarzyna / admin u_emily / member u_piotr)
4. make test                             # deterministic suite, no model needed (2,006 tests + 1,045-case control matrix)
5. Try to break it: Playground page; edit config/policy.yaml and resend; publish a signature in the feed editor at http://127.0.0.1:8790. Full guide: aegis/docs/JUDGES.md
Optional: make claude (Claude Code routed through Aegis with a demo settings profile; nothing machine-wide)
```

---

## B. Tiles: Huawei "Imagine What's Next"

> Pivot (Sun 4 Oct ~06:45): entry B was "Aegis Pocket: Approve AI Agents". It is now **Tiles**. The old Pocket
> texts are superseded (`docs/HACKTRIBE_POCKET.md`); do not paste them.

### B1. Category

```text
Huawei: Imagine What's Next
```

### B2. Title (5 words)

```text
Tiles: A Phone That Adapts
```

### B3. Description (479 words incl. placeholder team line)

Source: `docs/HACKTRIBE_TILES.md` (copy of the same text). On HackTribe, replace the `Team:` line with each
member's real first name, surname and email. The platform-capabilities sentence matches the README table "Platform
capabilities used" (no background-reminder or TTS-engine claim).

```text
Phones are designed for one average person. Halina, 78, squints at tiny icons, misses taps and nearly fell for a "your grandson needs money" call. Zosia, 8, needs fewer, friendlier choices. Michał, with low vision, needs everything read aloud. Daniel, 29, wants Friday's dinner with friends settled. Same phone, four different people.

Tiles is a native HarmonyOS app that reshapes the phone around the person using it. The home screen is a grid of big, colourful tiles. Each tile is a small, live, actionable card: "Pills 8:00, tap when taken", "Call Kasia", "14° and rain, take the umbrella", "Homework: 3 of 5 done", "Dinner Fri 19:30 at Veganda, vote".

Ask Tiles. Type a request ("Remind me to take Euthyrox at 8 every morning", "Dinner Friday with Ola and Kuba, vegan, near Kazimierz, under 80 zł") and the assistant answers with new tiles. This is generative UI: the assistant returns not text but a structured TileSpec (size, colour, content blocks such as checklist, progress, timer, chips and buttons, and actions such as call, remind, speak and vote) that the app renders natively in ArkUI. Today the generator is an on-device, deterministic intent planner for English and Polish (it extracts time, day, person, place, food, budget and medicine). No cloud model, and no personal data leaves the phone; a language model behind guardrails could fill the same schema later.

One app, four homes. A profile switcher regenerates the home for each person: very large, high-contrast tiles with read-aloud and an SOS tile for Halina; a playful homework checklist, focus timer and screen-time meter for Zosia; a voice-first two-column layout for Michał; a dense, colourful grid with plans and commute for Daniel.

It adapts, but asks first. Tiles turns usage signals (missed taps, unused tiles, time of day) into plain suggestions such as "11 missed taps today: make text 40% bigger?". For seniors and kids, every adaptation and every tile the assistant proposes waits for a caregiver or parent to approve it on the Caregiver screen (shown as a "Kasia's phone" simulation in the demo).

Guardian. A scam-shield tile for seniors explains red flags in a suspicious call or SMS ("asks for money", "pressure: right now") and turns the screen into one calm instruction: "This looks like a scam. Hang up. Kasia already knows." In the demo the call is simulated and labelled "Demo call".

Native ArkTS/ArkUI for HarmonyOS (minimum API 20, compiled against API 24), running on the HarmonyOS 6.1 phone emulator. Platform capabilities: Form Kit home-screen widgets (2x2, 2x4, 4x4), Notification Kit pill notifications and caregiver alerts, calls handed to the system dial screen, read-aloud through the system screen reader, vibrator haptics, ArkData persistence, high-contrast text scaling and dark mode.

Themes: Human-Centric Technology (accessibility, seniors, kids, digital wellbeing) with Intelligent Experiences (generative UI, on-device personalisation).

Code and build steps: https://github.com/JustAnotherDevv/tiles-hackyeah-2026 (repository root). AI-assisted development is documented in AI_WORKFLOW.md.

Team: JustAnotherDevv
```

### B4. Image gallery (≥ 1 required)

| Upload | File | Status |
|---|---|---|
| 1 (cover) | `docs/cover.png` (1600×900, Tiles title card; the phone is a labelled illustration) | ✅ regenerated by `docs/deck/build.sh`; not yet committed |
| optional 2–10 | `docs/screenshots/tiles/*.jpeg` (real DevEco HarmonyOS 6.1.1 emulator screenshots) | ⏳ to be copied from the build fleet's device checks |

Do **not** upload `docs/screenshots/0*.jpeg`: they show the superseded Aegis Pocket.

### B5. Presentation (PDF, ≤ 10 slides)

`docs/deck/Tiles_HackYeah2026_Huawei.pdf`: 10 pages, built by `docs/deck/build.sh`. Slide 9 shows a placeholder
until real screenshots are in `docs/screenshots/tiles/`; then rebuild and check the PDF before uploading. (The
old `docs/deck/AegisPocket_HackYeah2026_Huawei.pdf` is superseded.)

### B6. Video URL (≤ 60 s; the Huawei rules require a recorded demo)

⏳ Not recorded yet. The shot list and voice-over are in `docs/HACKTRIBE_TILES.md`. Record on the emulator, then
upload it to YouTube as **Unlisted** and paste the URL. (`docs/video/aegis-pocket-demo-60s.mp4` shows the
superseded concept, so do not use it.)

### B7. Demo link

Leave empty, or paste the GitHub Release URL that holds the `.hap` once it exists.

### B8. Repository URL

```text
https://github.com/JustAnotherDevv/tiles-hackyeah-2026
```

### B9. How to open the project (judge instructions)

```text
Requirements: macOS on Apple Silicon, DevEco Studio 6.1.1 (HarmonyOS SDK 6.1.1(24), hdc and the phone emulator). Full steps: README.md sections 2-7.
1. git clone https://github.com/JustAnotherDevv/tiles-hackyeah-2026 && cd tiles-hackyeah-2026   (Tiles is the repository root; aegis/ is a separate entry)
2. Start a DevEco phone emulator (HarmonyOS 6.1.1, API 24).
3. Fastest: install the prebuilt debug-signed .hap from the GitHub Release: hdc install -r <file>.hap  (built with the OpenHarmony SDK and its debug keystore, no Huawei ID). Rebuild it yourself: source .toolchain/env.sh && scripts/build-ohos-signed.sh (README section 4). Or build with DevEco: devecocli build --modules entry --build-mode debug, sign with your own Huawei ID (README 4.1).
4. Launch: hdc shell aa start -a EntryAbility -b com.hackyeah.tiles   (allow notifications on first start)
5. Try it: pick a profile ("Who is this phone for?"), tap tiles, type in "Ask Tiles..." (e.g. "Remind me to take Euthyrox at 8 every morning"), approve the proposal on the Caregiver screen, open Guardian (labelled demo call), switch profiles in Settings, add the "Tiles" service widget from the home screen.
The assistant is an on-device rule-based generator (no LLM); the Guardian call and "Kasia's phone" are simulated and labelled.
```

### B10. Huawei deliverables checklist (organizers' `hackathon_challenge.md`, "Required Deliverables")

| # | Deliverable | Status | Evidence / what is missing |
|---|---|---|---|
| 1 | Public source repository | ✅ / ⏳ | `github.com/JustAnotherDevv/tiles-hackyeah-2026` is public; the Tiles code must be committed and pushed |
| 2 | Setup, build, install and launch instructions | ✅ | `README.md` sections 2-7 (no-Huawei-ID signed build, emulator, `hdc install`, `aa start -b com.hackyeah.tiles`) |
| 3 | Working `.hap` | ⏳ | `scripts/build-ohos-signed.sh` → `release/tiles-debug-signed.hap` (file name kept from the earlier concept; contents are Tiles). `*.hap` is git-ignored: attach it to a GitHub Release |
| 4 | Recorded demonstration | ⏳ | Not recorded yet (script in `docs/HACKTRIBE_TILES.md`) |
| 5 | Architecture and implementation description | ✅ | `README.md` section 9 (mermaid + notes), "Generative UI: the TileSpec contract", capabilities table |
| 6 | `AI_WORKFLOW.md` | ✅ | Tools, prompts, the pivot and the build fleet, validation |
| 7 | Extra AI documentation for AI-integrated features | ✅ | `README.md` section 10 + `AI_WORKFLOW.md` "AI feature disclosure": the assistant is an on-device rule-based generator, not an LLM |
| – | API 20+ minimum | ✅ | `build-profile.json5`: compatible 6.0.0(20), compile/target 6.1.1(24); OpenHarmony build: min API 20 |
| – | Runs on an emulator or device | see README "Verification status" | DevEco HarmonyOS 6.1.1 (API 24) phone emulator `AegisPhone` |
| – | Demonstrates platform capabilities | see README table | Status per capability ("verified on emulator" / "implemented") |

---

## Claims to fix or confirm before pasting

Checked against `aegis/docs/status/{LIVE,CAL,FIX,VIDEO,PUB,INT-A,B*}.md`, `reports/` numbers (`aegis/docs/submission/numbers.json`),
the root `README.md`, `HUAWEI_HANDOFF.md` and `docs/ONIRO_RUN.md`.

**A: Aegis.** Most claims are backed:

- LIVE: F1–F10 PASS and the dress rehearsal 9/9.
- CAL: 92.4 % / 89.6 % / 5.1 %, and 2.40 ms p50.
- `make test` 2,006 passed, 0 failed, 20 xfailed (refreshed in commit `6cb94c8`).

Weak or unbacked claims:

| Claim in A3 | Status | Suggestion |
|---|---|---|
| "a multilingual NER model catches names" | Weak. NER is wired in (SEM-07, RED-12 borrows it), but every live run (LIVE, VIDEO) used `AEGIS_SEMANTIC=off`. No status file shows a live DLP-07/NER pass | Keep it, but do not demo it without models. Or write "an optional multilingual NER model" |
| "Anthropic, OpenAI-compatible and Ollama APIs" | Partial. Anthropic (real `claude -p`) and the OpenAI wire were live-verified. The Ollama proxy route exists (INT-A), but no live pass is recorded | Fine to keep. Test `/ollama/*` once if time allows |
| "92.4 % attack detection … 5.1 % false positives" | Backed (CAL, `reports/bench.json`), but **only with all local models loaded**, and the run was memory-limited. Deterministic-only: 66.6 % (38.9 % held-out) at 0.4 % FP. Judges who skip `make models` will not reproduce 92.4 % | Consider "Measured with local models (make eval, …)" (+3 words) |
| "a production write the owner" | Not found in any status file. ACT-02 prod-write labels exist (B11), but no owner-routing test is recorded | Run once or drop the clause |
| "tokens, USD and local compute-seconds" | Weak. `compute_s` exists (B23), but compute-seconds enforcement is not verified | Low risk. Keep or drop "local compute-seconds" |
| "Approvals … expire" | Backed by unit tests only (APR-05 lazy expiry, APR-V11 `test_background.py`) | OK |
| "$12 … $50 … $480 … above $1,000" | Backed. TASKS INT-07 F4 was ticked by LIVE; B23 DEMO-V12 | OK |
| Repo state | **~100 modified, uncommitted files under `aegis/web/`** (including `package.json` and `package-lock.json`), plus `aegis/config/policy.yaml`, where a leftover demo raise changed `team:platform` from usd 50 to 60.0 (see `git status`). The public repo is what judges clone | Commit (and rebuild `web/dist` if it is tracked) or discard them before submitting |
| Eval/bench freshness | The numbers come from the CAL run (~01:55). LIVE/FIX code fixes landed afterwards, so INT-12 ("numbers on the final build") is left unticked | Acceptable. Re-run `make eval` only on a quiet machine |

**B: Tiles.** Checked against the build fleet's device reports (`HUAWEI_HANDOFF.md` log, README capability table):

| Claim | Status | Suggestion |
|---|---|---|
| Form Kit widgets (2x2, 2x4, 4x4) | ✅ verified on the emulator: all three on the home screen with live data | OK |
| Notification Kit pill notifications and caregiver alerts | ✅ verified: permission dialog, caregiver and Guardian alerts in the shade | OK |
| Calls handed to the system dial screen | ✅ verified: dial screen with a fictional number | OK |
| Guardian red flags, caregiver alert | ✅ verified on labelled demo call/SMS samples | Keep "simulated, labelled Demo call" |
| Generative UI assistant | ✅ verified (plan tile with votes added; senior pills sent for approval). Rule-based, **not an LLM** | Keep the sentence that says so |
| Reminders | ⚠️ `reminderAgentManager` returns 1700002 without an AppGallery entitlement; the in-app timer + notification fallback fires only while Tiles runs | The description does not claim background reminders; keep it that way |
| Read-aloud | ⚠️ Core Speech Kit is not in the OpenHarmony SDK; read-aloud goes through the system screen reader when it is on, otherwise a visible "Speaking…" state | Description says "read-aloud through the system screen reader" |
| Haptics | ⚠️ implemented; the emulator has no vibrator | Do not claim it was felt on the emulator |
| `.hap` name `release/tiles-debug-signed.hap` | Name kept from the earlier concept | Rename the asset on the GitHub Release (e.g. `tiles-debug-signed.hap`) |

---

## Before you click submit: user-only actions

- [ ] **Discord account** for every member (HackTribe requires Discord IDs). Log in to **HackTribe**, join the
      **HackYeah 2026** event and create the team. The GS rules also ask for a **team name**, which you set on the team.
- [ ] Create **two projects** under the same team, one per category. Each team may submit only one project per
      category.
- [ ] In both descriptions, replace `[YOUR FIRST NAME SURNAME — EMAIL]` with the real name, surname and email of
      every member (1–6 members, one per line). Do this **only on HackTribe**. Re-check that each description is still ≤ 500 words.
- [ ] **Videos:** upload `aegis/docs/submission/video/aegis-demo-60s.mp4` (and the Tiles video once it exists) to
      YouTube as **Unlisted**. Paste the URLs and confirm they play while logged out.
- [ ] **Aegis repo hygiene:** commit (after `make web` and `make test` pass) or discard the ~100 modified `aegis/web/` files, then push. Do **not** commit `aegis/config/policy.yaml`; restore it with `cp aegis/config/policy.golden.yaml aegis/config/policy.yaml`.
- [ ] **Tiles artifacts:** copy the final emulator screenshots to `docs/screenshots/tiles/`, run `docs/deck/build.sh`,
      check `docs/deck/Tiles_HackYeah2026_Huawei.pdf` and `docs/cover.png`, then commit and push them.
- [ ] **Tiles `.hap`:** `source .toolchain/env.sh && scripts/build-ohos-signed.sh` (README §4, no Huawei ID). Install and launch
      on the emulator. Then publish a **GitHub Release** (e.g. `v1.0-hackyeah`) and attach the signed `.hap` (renamed to
      `tiles-debug-signed.hap`). Never attach keys or `.p12`/`.p7b` files.
- [ ] **Tiles demo:** record ≤ 60 s on the emulator (shot list in `docs/HACKTRIBE_TILES.md`). Upload it unlisted.
- [ ] Open **every link** in a private or incognito window: both repo URLs, the release, both video URLs, and the README
      anchors.
- [ ] Upload the PDFs and images listed in A4/A5 and B4/B5. Click submit **before 10:00**. After 11:00 nothing can change.

### Why these are two projects, not one project in two categories

The organizers "strongly discourage submitting one project to more than one category" (FAQ, Tasks Q5). These are two
different deliverables:

| | A: Aegis (Goldman Sachs) | B: Tiles (Huawei) |
|---|---|---|
| What it is | Local-first **AI gateway / control layer**: policy engine, redaction, budgets, threat feed, dashboard, self-test suite | **Native HarmonyOS phone app**: an adaptive, generative-UI home for seniors, kids, low-vision and everyday users |
| Code | Python 3.13 / FastAPI / React in `aegis/` | ArkTS / ArkUI in `entry/`, `AppScope/` |
| Judged on | Robustness, architecture, reporting, self-testing (GS criteria) | Originality, usefulness, platform capabilities: Form, Notification, Background Tasks (reminders), Sensor, Accessibility Kits (Huawei criteria) |
| Runs | macOS/Linux laptop, `make up` | HarmonyOS emulator or device, `.hap` |
| Relationship | Stand-alone; needs nothing from B | Stand-alone and fully on-device; no dependency on A |

If HackTribe asks, say it in one line: "Separate codebases, products and deliverables."
