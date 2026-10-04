# HackYeah 2026: final HackTribe submission pack (two entries)

This repository holds **two separate HackTribe entries**:

| # | Entry | Category on HackTribe | Code |
|---|---|---|---|
| A | **Aegis: Local-First AI Guardrails** | Goldman Sachs: *AI Control Layer* | [`aegis/`](aegis/) |
| B | **Aegis Pocket: Approve AI Agents** | Huawei: *Imagine What's Next* | repository root |

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
| B: Aegis Pocket | 5 | 486 |

Each extra team member adds about 4 words. Entry A then has 491 + 4 per member; entry B has 486 + 4 per member.

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

## B. Aegis Pocket: Huawei "Imagine What's Next"

### B1. Category

```text
Huawei: Imagine What's Next
```

### B2. Title (5 words)

```text
Aegis Pocket: Approve AI Agents
```

### B3. Description (486 words incl. placeholder team line)

Based on `docs/HACKTRIBE_POCKET.md`, with these changes:

- The team line is a placeholder.
- The repo link and the "verified" line are added.
- The claims that are not yet verified on a device are softened:
  - The "stolen phone cannot approve" sentence now names the labelled manual fallback.
  - "usable for everyone" is gone.
  - The risk score is described as deterministic rules, which matches the AI disclosure in `AI_WORKFLOW.md`.

```text
AI agents are starting to act for us: they buy subscriptions, read company databases, deploy code and email customers. When one of them wants to do something risky, someone has to say yes or no, usually away from a desk. Aegis Pocket puts that human back in the loop, on a HarmonyOS phone.

When an agent governed by our Aegis gateway asks for a risky action ("Research agent wants to spend $50 on a SaaS subscription"), the request appears as a notification. Tapping it shows everything needed to decide: who asked, which agent sponsor is responsible, the amount, the policy checks that passed or failed, and an expiry countdown. A "Why a human is asked" card explains the risk in plain words and scores it from 0 to 100. The score is computed on the device by deterministic rules over the gateway's policy data: which control fired, how much money moves, whether production or personal data is involved. The agent's own justification is labelled untrusted and never scored, since agents can be prompt-injected.

Approval rules follow the person's role: members approve small actions for agents they sponsor, admins approve mid-size spend and sensitive data access, and owners approve large spend and budget raises, sometimes with a second approver (two-person rule). A sponsor can never approve their own agent's request. When a request is risky, Approve first asks for the user's face, fingerprint or PIN through HarmonyOS User Authentication Kit; on a device with no authenticator (such as the emulator) a clearly labelled manual fallback is shown instead. Denying never needs it: saying no is always the safe direction. Approve and deny give distinct haptic confirmations.

A home-screen service widget (Form Kit, 2x2 and 2x4) shows the AI security posture at a glance: pending approvals, blocked threats, redacted personal data and budget left. A WorkScheduler background task refreshes the widget and raises notifications for new live requests while the app is closed. The "What data leaves" preview shows which personal data (emails, phone numbers, PESEL, IBAN, card numbers, validated by checksum) would be replaced with placeholders before a prompt goes to an AI model. It runs entirely on the device.

Aegis Pocket is native ArkTS/ArkUI for HarmonyOS (minimum API 20, compiled against API 24). It uses User Authentication Kit, Notification Kit, Form Kit, Background Tasks Kit, Sensor Service Kit, Network Kit and ArkData, with screen-reader labels and system font scaling. Two clearly labelled modes: MOCK simulates the gateway on the device for demos; LIVE talks to the real Aegis gateway over HTTP. The same source also builds unchanged against the OpenHarmony 6.1 SDK. Verified: .hap builds, 17/17 unit tests, lint 0 errors.

Themes: Human-Centric Technology (human oversight of AI agents, privacy, accessibility), with an Intelligent Experiences angle.

Code, build and launch steps: https://github.com/JustAnotherDevv/tiles-hackyeah-2026 (repository root; the aegis/ folder is our separate Goldman Sachs entry). AI-assisted development is documented in AI_WORKFLOW.md.

Team: [YOUR FIRST NAME SURNAME — EMAIL]
```

### B4. Image gallery (≥ 1 required)

| Upload | File | Status |
|---|---|---|
| 1 (cover) | `docs/cover.png` (1600×900) | ⏳ exists locally (regenerated 04:06), **not yet committed or pushed** |
| optional | emulator screenshots (Home, Detail with the risk card, step-up sheet, widget) | ⏳ none yet. The app has not run on an emulator or device |

### B5. Presentation (PDF, ≤ 10 slides)

`docs/deck/AegisPocket_HackYeah2026_Huawei.pdf`: ⏳ exists locally, 10 pages (regenerated 04:05). **Not yet committed or pushed.** Open it and check it before uploading.

### B6. Video URL (≤ 60 s; the Huawei rules require a recorded demo)

`docs/video/aegis-pocket-demo-60s.mp4`: ⏳ **does not exist yet**. It needs the emulator (shot list: `docs/HACKTRIBE_POCKET.md`
"Demo video script"). Upload it to YouTube as Unlisted and paste the URL. Raw-file fallback, once it is pushed:

```text
https://github.com/JustAnotherDevv/tiles-hackyeah-2026/raw/main/docs/video/aegis-pocket-demo-60s.mp4
```

### B7. Demo link

Leave empty. You could paste the GitHub Release URL that holds the `.hap` here, once it exists (see B10).

### B8. Repository URL

```text
https://github.com/JustAnotherDevv/tiles-hackyeah-2026
```

### B9. How to open the project (judge instructions)

```text
Requirements: macOS on Apple Silicon, DevEco Studio 6.1.1 (bundles HarmonyOS SDK 6.1.1(24), hvigor, ohpm, hdc and the phone emulator), Node 22+, devecocli 1.3.4. Full steps: README.md sections 2-8.
1. git clone https://github.com/JustAnotherDevv/tiles-hackyeah-2026 && cd tiles-hackyeah-2026   (Aegis Pocket is the repository root; aegis/ is a separate entry)
2. Build: DEVECO_CLI_DISABLE_TELEMETRY=1 devecocli build --modules entry --build-mode debug   -> entry/build/default/outputs/default/entry-default-unsigned.hap
3. Sign with your own Huawei ID (DevEco: File > Project Structure > Signing Configs > Automatically generate signature), rebuild, then install on a running phone emulator (API 20+): hdc install -r entry/build/default/outputs/default/entry-default-signed.hap
4. Launch: hdc shell aa start -a EntryAbility -b com.hackyeah.aegispocket   (allow notifications on first start)
5. Try it: the app starts in MOCK mode (labelled; a new simulated agent request every 20-30 s). Open a request, switch persona in the Inbox (Piotr member / Emily admin / Katarzyna owner) to see role rules, Approve to trigger the face/fingerprint/PIN step-up (labelled manual fallback on the emulator), and paste text with an email or PESEL into the Preview tab. Add the "AI posture" service widget from the home screen.
Optional LIVE mode: run the Aegis gateway (cd aegis && make setup && make up), then Settings > gateway URL http://10.0.2.2:8787 > Live gateway.
```

### B10. Huawei deliverables checklist (organizers' `hackathon_challenge.md`, "Required Deliverables")

Status as of Sun 4 Oct ~04:15: ✅ = done and pushed (`origin/main` = `6cb94c8`); ⏳ = missing, local-only or unverified.

| # | Deliverable | Status | Evidence / what is missing |
|---|---|---|---|
| 1 | Public source repository | ✅ | `github.com/JustAnotherDevv/tiles-hackyeah-2026` is PUBLIC; local `HEAD` = `origin/main` |
| 2 | Setup, build, install and launch instructions | ✅ written / ⏳ install+launch not yet exercised | `README.md` §2–8. The build is verified (devecocli exit 0, lint 0 errors, 17/17 unit tests). `hdc install` / `aa start` have never run (no target) |
| 3 | Working `.hap` | ⏳ | Built locally: `entry/build/default/outputs/default/entry-default-unsigned.hap` (HarmonyOS, unsigned, gitignored). Also `.toolchain/oniro-build/aegis-pocket/entry/build/default/outputs/default/entry-default-signed.hap` (OpenHarmony SDK debug key, gitignored). **No GitHub Release exists** (`gh release list` is empty), but README §4 says one does. **To do:** sign with a Huawei ID, install on an emulator, then attach the `.hap`(s) to a GitHub Release |
| 4 | Recorded demonstration | ⏳ | `docs/video/aegis-pocket-demo-60s.mp4` is missing (needs the emulator) |
| 5 | Architecture and implementation description | ✅ | `README.md` §9 (mermaid diagram plus data-flow notes) and the "Platform capabilities used" table |
| 6 | `AI_WORKFLOW.md` | ✅ | `AI_WORKFLOW.md` (tools, prompts, work log, limitations), pushed |
| 7 | Extra AI documentation for AI-integrated features | ✅ (N/A, declared) | `AI_WORKFLOW.md` "AI feature disclosure": no AI model in the app, and the risk card is rule-based |
| – | API 20+ minimum | ✅ | `build-profile.json5`: compatible 6.0.0(20), compile/target 6.1.1(24). OpenHarmony build: minAPIVersion 20 (`docs/ONIRO_RUN.md`) |
| – | Runs on an emulator or device | ⏳ **blocker** | Not yet. README "Known limitations" and `docs/ONIRO_RUN.md` (the Oniro emulator did not finish booting) |
| – | Demonstrates platform capabilities | ✅ in code / ⏳ on device | User Authentication, Notification, Form, Background Tasks, Sensor, Network Kits and ArkData (README table). None has been exercised on a target yet |

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

**B: Aegis Pocket.** The described behaviour is implemented in code, but **none of it has been seen running on a
device or emulator**: the notification, widget, step-up sheet, haptics, WorkScheduler and LIVE mode
(`HUAWEI_HANDOFF.md` 00:10 / 02:33 / 03:15; README "Known limitations"). The B3 text already avoids the strongest
claims.

| Claim | Status | Suggestion |
|---|---|---|
| Notification, widget, step-up, haptics, background task "work" | Unverified on a target | Top priority: get one emulator run with screenshots and the video. If that is impossible, add to the description: "Verified by build and unit tests; not yet run on a device." |
| "a stolen or unlocked phone cannot approve a $480 purchase" (original draft) | **Contradicted** by the labelled manual fallback when no authenticator is enrolled | Already replaced in B3 |
| "Screen-reader labels and font scaling make it usable for everyone" (original draft) | Code only, never tested with a screen reader | Softened in B3 |
| README §4: "A signed debug build … is attached to the GitHub Release" | **False right now.** No release exists | Create the release (see checklist) or edit the README |
| "LIVE talks to the real Aegis gateway over HTTP" | Implemented (`LiveRepository.ets`). Emulator-to-host networking has never run | OK as a design statement; do not claim a live demo |
| `HUAWEI_HANDOFF.md` line 3: "`aegis/` is gitignored here (own git repo)" | Stale: it is now a monorepo | Internal note only, not pasted |

---

## Before you click submit: user-only actions

- [ ] **Discord account** for every member (HackTribe requires Discord IDs). Log in to **HackTribe**, join the
      **HackYeah 2026** event and create the team. The GS rules also ask for a **team name**, which you set on the team.
- [ ] Create **two projects** under the same team, one per category. Each team may submit only one project per
      category.
- [ ] In both descriptions, replace `[YOUR FIRST NAME SURNAME — EMAIL]` with the real name, surname and email of
      every member (1–6 members, one per line). Do this **only on HackTribe**. Re-check that each description is still ≤ 500 words.
- [ ] **Videos:** upload `aegis/docs/submission/video/aegis-demo-60s.mp4` (and the Pocket video once it exists) to
      YouTube as **Unlisted**. Paste the URLs and confirm they play while logged out.
- [ ] **Aegis repo hygiene:** commit (after `make web` and `make test` pass) or discard the ~100 modified `aegis/web/` files, then push. Do **not** commit `aegis/config/policy.yaml`; restore it with `cp aegis/config/policy.golden.yaml aegis/config/policy.yaml`.
- [ ] **Pocket artifacts:** commit and push `docs/cover.png` and `docs/deck/AegisPocket_HackYeah2026_Huawei.pdf` (after
      checking them).
- [ ] **Pocket `.hap`:** sign with your Huawei ID (README §4; DevEco GUI step). Install and launch on the emulator. Then publish a
      **GitHub Release** (e.g. `v1.0-hackyeah`) and attach the signed `.hap`, plus optionally the unsigned `.hap` and the
      OpenHarmony-signed `.hap` from `.toolchain/oniro-build/…`. Never attach keys or `.p12`/`.p7b` files.
- [ ] **Pocket demo:** record ≤ 60 s on the emulator in MOCK mode (shot list in `docs/HACKTRIBE_POCKET.md`) and save it as
      `docs/video/aegis-pocket-demo-60s.mp4`. Upload it unlisted.
- [ ] Open **every link** in a private or incognito window: both repo URLs, the release, both video URLs, and the README
      anchors.
- [ ] Upload the PDFs and images listed in A4/A5 and B4/B5. Click submit **before 10:00**. After 11:00 nothing can change.

### Why these are two projects, not one project in two categories

The organizers "strongly discourage submitting one project to more than one category" (FAQ, Tasks Q5). These are two
different deliverables:

| | A: Aegis (Goldman Sachs) | B: Aegis Pocket (Huawei) |
|---|---|---|
| What it is | Local-first **AI gateway / control layer**: policy engine, redaction, budgets, threat feed, dashboard, self-test suite | **Native HarmonyOS phone app**: the human-approval front end |
| Code | Python 3.13 / FastAPI / React in `aegis/` | ArkTS / ArkUI in `entry/`, `AppScope/` |
| Judged on | Robustness, architecture, reporting, self-testing (GS criteria) | Platform capabilities: User Auth, Notification, Form, Background Tasks and Sensor Kits (Huawei criteria) |
| Runs | macOS/Linux laptop, `make up` | HarmonyOS emulator or device, `.hap` |
| Relationship | Stand-alone; needs nothing from B | Stand-alone in MOCK mode. Optional LIVE mode talks to A's REST API; the README names A as the separate GS submission |

If HackTribe asks, say it in one line: "Separate codebases and deliverables; the phone app optionally connects
to the gateway's API."
