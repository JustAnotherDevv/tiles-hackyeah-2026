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
- Device/emulator: not available during implementation, so install, launch, notifications and widgets are unverified.

## Unsuccessful approaches

- `compileSdkVersion "6.1.0(23)"` failed with "SDK component missing": DevEco Studio 6.1.1 only bundles the 6.1.1(24) SDK.
  Changed the compile SDK to `6.1.1(24)`; the minimum (`compatibleSdkVersion`) stays API 20.
- The grounded-docs retriever skill returned only language-guide hits for Kit API queries, so the SDK `.d.ts` files and
  `devecocli docs` were used instead.
- A custom component property named `size` clashed with ArkUI's built-in `size` attribute (compile error); renamed.
- The first phone-number pattern also matched invalid 11-digit PESEL candidates; the validator now accepts a bare digit run
  only when it has exactly 9 digits.

## Known limitations

- Not yet verified on an emulator or device (see README "Known limitations").
- Mock mode data is simulated on the device and clearly labelled; live mode needs the separate Aegis gateway.
- Background polling stops when HarmonyOS freezes the app; no push channel yet.

## Lessons learned

- Check which SDK DevEco actually bundles before pinning `compileSdkVersion`.
- For HarmonyOS Kit APIs, the installed SDK's `.d.ts` files are the fastest reliable source (signatures, `@since`, deprecations).
- Keep view code free of class methods on objects that pass through `AppStorage` / `@Prop` copies; use free helper functions.

## AI feature disclosure

Not applicable. Aegis Pocket contains no AI model and calls no AI service; it is the human approval front end for AI agents
governed by the separate Aegis gateway. Its "What data leaves" preview is rule-based (patterns plus checksums) and runs on
the device.
