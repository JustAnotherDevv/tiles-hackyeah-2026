# AI Workflow

This project uses AI-assisted development. Keep this document current and public-safe. Do not include credentials, tokens, personal data, private endpoints, or confidential prompts.

> **Our setup:** this team develops with **Claude Code** (CLI agent) running **Claude Opus 5.5** (`claude-opus-5-5`).
> The lead session splits independent work into self-contained briefs and runs them as **parallel sub-agents**
> (for example toolchain install, repository/docs setup, research). The lead session integrates their reports,
> and a human reviews the result before it is committed.
>
> This file follows the organizers' "Hackathon Template" scaffold
> ([onirodeveloper/hackyeah2026-challenge](https://github.com/onirodeveloper/hackyeah2026-challenge), `default_template/project scaffolds/AI_WORKFLOW.md`).

## Tools used

| Model, agent, MCP server, or Agent Skill | Version or source | Role in the project |
| --- | --- | --- |
| Claude Code (CLI agent) | Anthropic Claude Code, model Claude Opus 5.5 (`claude-opus-5-5`) | Main coding agent: research, setup, scaffolding, implementation, docs, debugging |
| Claude Code sub-agents | Claude Opus 5.5, launched in parallel by the lead session | Parallel, self-contained tasks (toolchain/SDK/emulator install, repository setup, research); each returns a short report |
| Agent Skills: `ohos-app-scaffold`, `ohos-app-dev`, `ohos-system-app-dev`, `ohos-system-dev`, `conductor-dev`, `hmos-arkts-knowledge-retriever`, `hmos-arkui-scenario-development`, `hmos-arkui-develop-skill`, `hmos-arkui-mvvm-pattern` | Organizers' repo [`skills/`](https://github.com/onirodeveloper/hackyeah2026-challenge/tree/main/skills), commit `f698853`; installed project-locally in `.claude/skills/` (git-ignored) | ArkTS/ArkUI knowledge, build/run/lint/log loop, API lookups. `conductor-dev` is installed but not used with this template (see `AGENTS.md`) |
| DevEco CLI (`devecocli`) | `@deveco/deveco-cli` 1.3.4 from npm, with the organizers' two 1.3.4 patches | Build, run, device/emulator, logs, lint, UI inspection and docs search for the agent |
| `deveco-cli` Agent Skill | Bundled with DevEco CLI 1.3.4 (`devecocli init --skill`) | Pending: needs DevEco Studio installed first (see README, Setup) |
| DevEco Studio toolchain (hvigor, ohpm, hdc, HarmonyOS SDK 6.1.1(24), CodeLinter) | DevEco Studio 6.1.1.280 for macOS ARM | Driven from the command line by `devecocli` / hvigor: build, lint, local unit tests. The SDK's `.d.ts` files were the ground truth for API signatures |
| Claude Code "Aegis Pocket implementer" sub-agent | Claude Opus 5.5, launched by the lead session | Implemented the Aegis Pocket app (data layer, UI, Notification Kit, Form Kit widgets, on-device redactor), unit tests, README and this log |
| Claude Code "platform depth" sub-agent (POCKET2) | Claude Opus 5.5, launched by the lead session in parallel with other agents | Added User Authentication Kit step-up, Sensor Service Kit haptics, Background Tasks Kit WorkScheduler refresh, accessibility labels, the on-device risk explainer, tests, README / HackTribe docs |
| Claude Code "device verification" sub-agent (POCKET-DEVICE) | Claude Opus 5.5, launched by the lead session | Ran the app on the DevEco HarmonyOS 6.1.1 emulator via `hdc` / `uitest`, fixed a Detail refresh bug found there, captured screenshots and the demo video, updated docs |
| `oniro-app` CLI + OpenHarmony 6.1 public SDK (API 23) | Installed locally in `.toolchain/` (git-ignored), see `.toolchain/README.md` | No-Huawei-ID build and debug signing of the `.hap` (`scripts/build-ohos-signed.sh`) |
| DevEco local documentation (`devecocli docs search` / `docs read`) | Bundled with DevEco Studio 6.1.1 (mostly Chinese-language pages, translated by the agent) | Grounding for the User Authentication Kit and WorkScheduler development guides and their constraints |

## Important prompts and instructions

- `AGENTS.md` — repository-wide hackathon constraints and working agreement (`CLAUDE.md` and `GEMINI.md` import it).
- Standing project context given to agents: *"Project: HackYeah 2026, Huawei partner task. App for an OpenHarmony-based device (HarmonyOS / OpenHarmony / Oniro). ArkTS + ArkUI, Stage model, minimum API 20, deliverable is a .hap. Machine: Apple Silicon Mac, 8 GB RAM. No sudo."*
- Aegis Pocket implementation brief (lead session to the implementer sub-agent, summarized): *"Build Aegis Pocket, a native
  HarmonyOS app (ArkTS/ArkUI, API 20+) in `entry/` + `AppScope/`. Must, in order, keeping it buildable: (1) data layer with an
  `ApprovalsRepository` interface, a MockRepository (default, seeded approvals and stats, a simulated new request every
  20-30 s, clearly labelled 'Mock mode') and a LiveRepository (Network Kit HTTP polling of the Aegis gateway), persona switcher
  setting `X-Aegis-View-As`; (2) approvals inbox + detail with approve/deny, buttons locked with a reason when the role is
  insufficient, optimistic update + error toast; (3) Notification Kit local notification for new requests with proper
  permission request and tap-to-open; (4) Form Kit home-screen widget with posture and pending count; (5) on-device 'What data
  leaves' preview (email, phone, PESEL with checksum, IBAN, card with Luhn, `[EMAIL_1]` placeholders); (6) polished dark ArkUI.
  Use the organizers' skills and grounded docs, do not invent APIs, build the .hap from the command line, keep signing configs
  empty, update README and AI_WORKFLOW.md."* The gateway API shapes came from the Aegis project's own contract document.

## AI-assisted work log

| Date | Tool/model | Request or task | Generated or changed | Human review and validation |
| --- | --- | --- | --- | --- |
| 2026-10-03 | Claude Code sub-agent (Claude Opus 5.5) | Check prerequisites; init git and `.gitignore`; scaffold an idea-agnostic ArkTS Stage-model skeleton matching DevEco's "Empty Ability" template for API 20; write README and AI_WORKFLOW drafts | Commit "Initial project skeleton": `AppScope/`, `entry/`, build profiles, `.gitignore`, `README.md`, `AI_WORKFLOW.md`. Template contents cross-checked against public DevEco-generated API 20 projects; placeholder icons generated by a script, not copied | Reviewed in `git diff` by the team. Not yet built (DevEco Studio not installed at that point) |
| 2026-10-03 | Claude Code sub-agent (Claude Opus 5.5) | macOS equivalent of the organizers' Windows-only `INSTALLATION_PROMPT.md`, scoped to this project | Installed the 9 organizers' skills into `.claude/skills/`; installed and patched DevEco CLI 1.3.4; added the Hackathon Template files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `HACKATHON_BRIEF.md`, this file, `hackathon-resources/`); set SDK versions (compatible API 20, compile API 23, target API 24); added `scripts/set-deveco-region-cn.sh` and `scripts/install-deveco-templates.sh`; updated README setup | Skill copies and template files diffed byte-for-byte against the organizers' repo; patcher reported the patches applied and `devecocli -V` = 1.3.4. Scripts not run yet (DevEco Studio not installed) |
| 2026-10-03/04 | Claude Code sub-agent (Claude Opus 5.5) + skills `ohos-app-dev`, `hmos-arkui-develop-skill`, `hmos-arkts-knowledge-retriever`, `hmos-arkui-mvvm-pattern`; `devecocli` | Implement Aegis Pocket (brief above) | `entry/src/main/ets/**` (EntryAbility, Index page, 5 views, shared components, mock/live repositories, eligibility rules, store, NotificationService, WidgetBridge, SettingsStore, FormExtensionAbility, two widget cards, redactor), `module.json5` (form extension, INTERNET permission), `form_config.json`, strings/colors, bundle name `com.hackyeah.aegispocket`, `compileSdkVersion` to the installed `6.1.1(24)`, 10 local unit tests, README rewrite | `devecocli build --modules entry --build-mode debug`: exit 0, unsigned `.hap`. `devecocli check lint`: 0 errors, 7 performance warnings (justified in README). hvigor `test`: 10/10 pass. Redactor regexes also cross-checked in Node. **Not yet run on an emulator/device** (none available); human review of the diff pending |
| 2026-10-04 | Claude Code sub-agent POCKET2 (Claude Opus 5.5) + skills `ohos-app-dev`, `hmos-arkui-develop-skill`, `hmos-arkts-knowledge-retriever`; `devecocli` | Strengthen platform-capability depth (brief below) | `platform/StepUpAuth.ets`, `platform/Haptics.ets`, `platform/BackgroundRefresh.ets`, `workscheduler/RefreshWorkAbility.ets`, `data/RiskExplainer.ets`, step-up rule in `data/Eligibility.ets`, DetailView risk card + step-up flow + fallback dialog, accessibility attributes across views, Settings "Security & background" section, `module.json5` (ACCESS_BIOMETRIC, VIBRATE, workScheduler extension), 7 new unit tests, README (two-submission note, capability table, demo shot list), `docs/HACKTRIBE_POCKET.md` | Every new API checked against the installed SDK `.d.ts` (`@since`, permissions, error codes) and DevEco's local guides; permissions checked in the SDK's `PermissionDefinitions.json` (all `system_grant`, normal APL). `devecocli build`: exit 0. Lint: 0 errors, the same 7 pre-existing performance hints. Unit tests: 17/17 pass. **Not run on an emulator/device** (none attached); human review of the diff pending |
| 2026-10-04 | Claude Code sub-agent POCKET-DEVICE (Claude Opus 5.5); `hdc`, `uitest`, `oniro-app` | Verify Aegis Pocket on the DevEco HarmonyOS 6.1.1 (API 24) emulator; screenshots, deck, demo video, docs | Drove the app with `uitest` (dumpLayout + click/swipe) and `snapshot_display`: notification permission, Home, Inbox, Detail risk card, Approve on admin-level requests (User Authentication Kit returned 12500010 = not enrolled for face/fingerprint/PIN, so the labelled manual fallback appeared; confirmed it approves only after the explicit tap), Deny, simulated request + system notification + tap-to-open, Preview with the built-in synthetic sample (email, PESEL, IBAN, card), Settings, widget added via long-press > Widgets. Found and fixed a real bug: the Detail page kept showing "pending" and the Approve/Deny buttons after a successful vote (`@Builder` by-value parameter is not reactive) - now keyed `ForEach` in `views/DetailView.ets`; fallback button label shortened to "Confirm" (was truncated). Saved 8 screenshots to `docs/screenshots/`, rebuilt the deck, recorded the video with `scripts/pocket-video/record.sh` (driver updated to the real labels; typing skipped because the emulator keyboard opens its own terms dialog, which the agent must not accept). Added `scripts/build-ohos-signed.sh` (no-Huawei-ID OpenHarmony debug signing) | Each screen checked by the agent in the pulled screenshots and layout dumps; rebuilt + reinstalled after the fix and re-verified the approve path on the device. Live mode also verified: local gateway, app at `http://10.0.2.2:8787`, the trading copilot's $50 request approved on the phone and the agent completed (gateway recorded the manual step-up marker). Real biometric sheet, haptics and WorkScheduler remain unverified |

### Platform-depth brief (lead session to POCKET2, summarized)

*"Strengthen use of platform capabilities, highest value first, keeping the build green: (1) step-up authentication
with User Authentication Kit before approving admin/owner-level or high-value requests, with a clearly labelled
fallback when the emulator has no authenticator, and ACCESS_BIOMETRIC declared; (2) vibrator haptics on approve / deny /
new request and accessibility labels with large-font friendliness; (3) background-friendly widget updates (WorkScheduler
or similar, only if available to ordinary apps); (4) optionally an on-device, rule-based risk explanation. Then lint,
unit tests, rebuild the .hap, update README, a HackTribe text with a 60-second video script, and this file. Use the
organizers' skills and grounded docs; never invent APIs; never touch the separate gateway project."*

## Workflow

### Ideation and architecture

The concept (Aegis Pocket as the human-approval companion of the team's Aegis AI gateway) was chosen by the team; the lead
Claude Code session wrote the brief. The implementer sub-agent chose the internal architecture within that brief: an
MVVM-style split (UI models and views, a `PocketStore` service publishing to `AppStorage`, a repository interface with mock
and live implementations), Form Kit + Notification Kit as the showcased platform capabilities, and a rule-based on-device
redactor that mirrors the gateway's entity names and placeholders.

### Implementation

The agent read the project rules (`AGENTS.md`), the challenge statement, the organizers' skills and the gateway contract,
then verified every non-trivial HarmonyOS API against the installed SDK's `.d.ts` files (for example
`notificationManager.requestEnableNotification(context)`, `wantAgent.WantAgentInfo.actionType`,
`formProvider.getPublishedRunningFormInfos` (API 20), `preferences.removePreferencesFromCacheSync`) and DevEco's local docs
(`devecocli docs search`, for example to confirm cleartext HTTP is allowed by default). It built after each step (data layer,
platform services, UI) and fixed compiler errors at once.

Parallel sub-agents: the lead Claude Code session gives each sub-agent a self-contained brief, the sub-agents run concurrently, and the lead session integrates their reports. Humans review every change before it is committed.

### Testing and debugging

- Builds: `devecocli build --modules entry --build-mode debug` (exit code checked every time).
- Lint: `devecocli check lint --format json <project>`; one state-in-loop warning fixed, the custom-component performance
  hints kept on purpose.
- Tests: hvigor `test` task, results in `entry/.test/default/intermediates/test/coverage_data/test_result.txt` (10 pass).
- Device/emulator: not available during implementation. Later (2026-10-04) verified on the DevEco HarmonyOS 6.1.1
  emulator with `hdc`/`uitest` and screenshots (see the work log); the OpenHarmony-SDK build signed with the SDK debug
  keystore installs there without a Huawei ID.

## Unsuccessful approaches

- `compileSdkVersion "6.1.0(23)"` failed with "SDK component missing": DevEco Studio 6.1.1 only bundles the 6.1.1(24) SDK.
  Changed the compile SDK to `6.1.1(24)`; the minimum (`compatibleSdkVersion`) stays API 20.
- The grounded-docs retriever skill returned only language-guide hits for Kit API queries, so the SDK `.d.ts` files and
  `devecocli docs` were used instead.
- A custom component property named `size` clashed with ArkUI's built-in `size` attribute (compile error); renamed.
- The grounded-docs retriever skill had no User Authentication Kit, vibrator or WorkScheduler entries; the SDK `.d.ts`
  files and DevEco's local guides (`devecocli docs read`) were used instead.
- The first phone-number pattern also matched invalid 11-digit PESEL candidates; the validator now accepts a bare digit run
  only when it has exactly 9 digits.

## Known limitations

- Verified on the DevEco HarmonyOS emulator except a real biometric/PIN sheet, haptics and the WorkScheduler background
  task (see README "Known limitations").
- The DevEco emulator cannot simulate biometrics or vibration; the app falls back to the lock-screen PIN or a labelled
  manual confirmation, and skips haptics.
- The background task runs at most about every 2 hours, as scheduled by the system; it is a safety net, not real-time.
- Mock mode data is simulated on the device and clearly labelled; live mode needs the separate Aegis gateway.
- Background polling stops when HarmonyOS freezes the app; no push channel yet.

## Lessons learned

- Check `PermissionDefinitions.json` in the SDK before declaring a permission: `ACCESS_BIOMETRIC`, `VIBRATE` and
  `INTERNET` are all `system_grant` with normal APL, so no runtime prompt and no system-app identity are needed.
- Design hardware-dependent features (biometrics, vibration) with an explicit, labelled fallback from the start: the
  emulator used for judging cannot simulate them.

- Check which SDK DevEco actually bundles before pinning `compileSdkVersion`.
- For HarmonyOS Kit APIs, the installed SDK's `.d.ts` files are the fastest reliable source (signatures, `@since`, deprecations).
- ArkUI `@Builder` parameters passed by value do not re-render when the state they came from changes; key the subtree
  (for example a one-element `ForEach` with a key of the mutable fields) or read state directly. Only an on-device run showed it.
- Keep view code free of class methods on objects that pass through `AppStorage` / `@Prop` copies; use free helper functions.

## AI feature disclosure

Not applicable. Aegis Pocket contains no AI model and calls no AI service (the "Why a human is asked" risk card is a
deterministic, rule-based explanation computed on the device); it is the human approval front end for AI agents
governed by the separate Aegis gateway. Its "What data leaves" preview is rule-based (patterns plus checksums) and runs on
the device.
