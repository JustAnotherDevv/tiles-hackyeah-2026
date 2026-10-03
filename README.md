# HackYeah App (working title)

> **Status:** project skeleton. The app idea is not decided yet. The current app is the DevEco Studio
> "Empty Ability" template showing a bold **Hello HarmonyOS** screen, plus the files the organizers'
> **Hackathon Template** adds on top (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `HACKATHON_BRIEF.md`,
> `AI_WORKFLOW.md`, `hackathon-resources/`).
> Replace every `TODO` below once the idea and toolchain are settled.

Organizers' setup repository (challenge statement, FAQ, skills, templates):
<https://github.com/onirodeveloper/hackyeah2026-challenge>

Submission for **HackYeah 2026, Huawei partner task "Imagine What's Next"**: an app for an
OpenHarmony-based device (HarmonyOS / OpenHarmony / Oniro).

| | |
|---|---|
| Language / UI | ArkTS + ArkUI (declarative) |
| App model | Stage model (`UIAbility`) |
| SDK levels (`build-profile.json5`) | compatible **API 20** `6.0.0(20)` (minimum), compile **API 23** `6.1.0(23)`, target **API 24** `6.1.1(24)`. These are the organizers' defaults |
| Runtime | `runtimeOS: "HarmonyOS"` |
| Deliverable | `.hap` (module `entry`) |
| Bundle name | `com.hackyeah.huawei.app` (placeholder) |
| Build system | hvigor + ohpm |

---

## 1. Repository layout

```
.
├── AppScope/                       # App-wide config: app.json5 (bundleName, version, icon, label) + resources
├── entry/                          # The single HAP module (type: entry)
│   ├── src/main/
│   │   ├── module.json5            # Module config: abilities, pages, device types, permissions
│   │   ├── ets/entryability/       # EntryAbility (UIAbility lifecycle, loads pages/Index)
│   │   ├── ets/entrybackupability/ # Backup/restore extension (template default)
│   │   ├── ets/pages/Index.ets     # Main page
│   │   └── resources/              # Strings, colors, floats, media, profile/main_pages.json
│   ├── src/test/                   # Local unit tests (hypium, run on host)
│   ├── src/ohosTest/               # Instrumented tests (hypium, run on emulator/device)
│   ├── build-profile.json5         # Module build options and targets
│   └── oh-package.json5
├── hvigor/hvigor-config.json5      # hvigor version model and execution options
├── build-profile.json5             # App build profile: SDK versions, products, signing, modules
├── oh-package.json5                # ohpm root manifest (dev deps: hypium, hamock)
├── code-linter.json5               # ArkTS linter rules (DevEco Code Linter)
├── AGENTS.md                       # Agent guidance from the organizers' Hackathon Template (canonical)
├── CLAUDE.md, GEMINI.md            # Shims that import AGENTS.md
├── HACKATHON_BRIEF.md              # Our submission brief (pitch, target, user flow, acceptance checks)
├── AI_WORKFLOW.md                  # Required by the Huawei brief: AI tools, prompts, work log, validation
├── hackathon-resources/            # Organizers' bundled reference: devecocli matrix, emulator capabilities
├── scripts/                        # macOS helpers: DevEco region switch, DevEco template install
├── .claude/skills/                 # Agent skills, installed per machine (git-ignored, see Setup)
└── README.md
```

## 2. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| macOS (Apple Silicon) | 27 | Development machine. The DevEco Studio emulator needs Apple Silicon |
| DevEco Studio | 6.1.x (data directory `DevEcoStudio6.1`) | Bundles the HarmonyOS SDK, hvigor, ohpm, hdc and the emulator. Install into `/Applications` |
| HarmonyOS SDK | 6.0.0(20), 6.1.0(23), 6.1.1(24) | Installed through the DevEco SDK Manager |
| Node.js | 22 or later (tested with 24.10) | Required by `devecocli`. Keep your own Node first on `PATH`, not DevEco's bundled `tools/node` |
| Python 3 | any 3.x | Some agent skills call the `python` command |
| Java | 17 | TODO: confirm whether the CLI toolchain needs it |
| Git | any recent | |

> Local machine-specific toolchain files go in `.toolchain/`, which is git-ignored.

## 3. Setup

The organizers' automated installer ([`INSTALLATION_PROMPT.md`](https://github.com/onirodeveloper/hackyeah2026-challenge/blob/main/INSTALLATION_PROMPT.md))
supports Windows only. On macOS their README and FAQ say to do the same steps by hand. The steps below are that
macOS path. The two scripts in `scripts/` automate the manual parts. Neither script uses sudo.

```bash
git clone TODO-public-repo-url
cd TODO-repo-dir
# The organizers' repository provides the skills, the DevEco CLI patches and the templates:
git clone --depth 1 https://github.com/onirodeveloper/hackyeah2026-challenge /tmp/hy-challenge
```

### 3.1 DevEco Studio and the emulator

1. **Install DevEco Studio 6.1** into `/Applications`. See the
   [Oniro DevEco Studio installation guide](https://docs.oniroproject.org/application-development/environment-setup-guide/deveco-studio/installation/).
2. **First launch.** Start DevEco Studio once, finish the first-launch setup (including the SDK download), then
   quit it (Cmd+Q). This step creates `~/Library/Application Support/Huawei/DevEcoStudio6.1/options/country.region.xml`.
3. **Switch the region to China.** Outside China, Device Manager only offers smart-watch emulators. With the
   region set to CN it also offers phone, tablet, 2-in-1 and TV emulators.
   ```bash
   scripts/set-deveco-region-cn.sh --dry-run   # shows the change
   scripts/set-deveco-region-cn.sh             # backs up the file, sets <countryregion name="CN"/>
   ```
   The script reads `dataDirectoryName` from the app's `product-info.json`. It refuses to run while DevEco Studio is
   running and never creates the file. This follows the organizers' [FAQ](https://github.com/onirodeveloper/hackyeah2026-challenge/blob/main/FAQ.md#how-do-i-switch-the-deveco-studio-region-to-china-manually).
4. **Create and start an emulator** (GUI only; the agent cannot do this). Start DevEco Studio, open Device Manager,
   create a **Phone** device, download its system image (newest available, API 24; several GB) and start it. With
   8 GB RAM, close other heavy apps first. See the [Oniro emulator guide](https://docs.oniroproject.org/application-development/environment-setup-guide/deveco-studio/emulator/).
5. *(Optional)* **Install the organizers' project templates** (`Hackathon Template`, `Conductor Hackathon Template`)
   into DevEco's Create Project wizard. This repository already contains the Hackathon Template files, so you only
   need the templates to create new projects.
   ```bash
   scripts/install-deveco-templates.sh --source /tmp/hy-challenge --dry-run
   scripts/install-deveco-templates.sh --source /tmp/hy-challenge
   ```
   Target directory: `<DevEco Studio>.app/Contents/plugins/openharmony/lib/templates/project`. This is the macOS
   equivalent of the organizers' Windows path `<DevEcoStudioRoot>\plugins\openharmony\lib\templates\project`.
   The script does not overwrite or merge an existing template that differs. If macOS reports
   "Operation not permitted", allow your terminal under System Settings > Privacy & Security > App Management.
   Restart DevEco Studio afterwards.
6. **Open this project.** In DevEco Studio choose File > Open and select this folder. Let it sync and accept the SDK
   prompts. DevEco creates `local.properties` (git-ignored), which points at your SDK. Then restore dependencies:
   ```bash
   ohpm install            # restores oh_modules/ (hypium, hamock)
   ```
   TODO: verify the CLI paths after the install. DevEco puts its tools under
   `<DevEco Studio>.app/Contents/tools/{ohpm,hvigor}/bin` and `hdc` under
   `<DevEco Studio>.app/Contents/sdk/default/openharmony/toolchains`. You can add these directories to `PATH`, but
   do not add `Contents/tools/node`.

### 3.2 Agent tooling (Claude Code)

We use **Claude Code** (model Claude Opus 5.5) with **parallel sub-agents** (see [AI_WORKFLOW.md](AI_WORKFLOW.md)).
The tooling is installed **for this project**, not in the user-level agent configuration.

**Agent skills.** The organizers' nine skills are copied unmodified into `.claude/skills/`, where Claude Code loads
project skills. The folder is git-ignored because it holds about 26 MB of third-party content. To restore it:

```bash
mkdir -p .claude/skills && cp -R /tmp/hy-challenge/skills/* .claude/skills/
```

| Skill | Purpose |
|---|---|
| `ohos-app-scaffold` | Creates a new, untouched project skeleton and stops |
| `ohos-app-dev` | Inner dev loop for an existing app: lint, build, run, logs, UI checks |
| `ohos-system-app-dev` | Privilege preflight and dev loop for apps that may need system-app identity |
| `ohos-system-dev` | Platform components built inside the OpenHarmony source tree |
| `conductor-dev` | Conductor orchestration. Not used with this template (see `AGENTS.md`) |
| `hmos-arkts-knowledge-retriever` | Grounded ArkTS and API references |
| `hmos-arkui-scenario-development` | Scenario-based ArkUI development (REQ, DEV, FIX, VAL) |
| `hmos-arkui-develop-skill` | ArkUI pages, components, layout and state |
| `hmos-arkui-mvvm-pattern` | MVVM layering and refactoring |

**DevEco CLI.** Install `@deveco/deveco-cli` **exactly 1.3.4**, because the organizers' patches are verified only
against that version. The package pins its companion `@deveco/deveco-cli-common` to 1.3.4. Then apply the patches.
They fix the linter wording and disable a Windows memory sampler.

```bash
npm install -g @deveco/deveco-cli@1.3.4
node /tmp/hy-challenge/scripts/apply-devecocli-patches.mjs   # "Applied DevEco CLI 1.3.4 patches at ..."
node /tmp/hy-challenge/scripts/apply-devecocli-patches.mjs   # must say "patches are already applied"
devecocli -V                                                 # 1.3.4
```

`devecocli` is installed into `$(npm config get prefix)/bin`, which must be on `PATH`. To opt out of the CLI's
telemetry, set `export DEVECO_CLI_DISABLE_TELEMETRY=1`.

**DevEco CLI skill** (after DevEco Studio is installed, because the CLI refuses to run without it). Install it into
this project only:

```bash
devecocli init --skill --agent claude-code --project .   # writes .claude/skills/deveco-cli/SKILL.md
```

Without `--agent`/`--project`, `init` writes into the global configuration of every agent it detects.

Restart Claude Code after installing skills so that it loads them.

## 4. Signing

Installing a `.hap` on the emulator or a device needs a debug signature. An unsigned `.hap` builds but will not install.

1. DevEco Studio > File > Project Structure > Signing Configs > tick **Automatically generate signature**.
   For a HarmonyOS (`runtimeOS: "HarmonyOS"`) project this needs a Huawei ID sign-in.
2. DevEco writes the keys and certificates to `~/.ohos/config/` (outside the repo). It also fills
   `app.signingConfigs` in `build-profile.json5` with **absolute local paths and encrypted passwords**.
3. **Do not commit that block.** Before committing, check `git diff build-profile.json5` and revert
   `signingConfigs` to `[]` (or use `git add -p`). `*.p12`, `*.cer`, `*.p7b` and similar files are git-ignored.

TODO: describe how judges should sign (their own auto-sign), and attach a signed debug `.hap` to the GitHub Release.

## 5. Build

**DevEco Studio:** Build > Build Hap(s)/APP(s) > Build Hap(s).

**CLI** (TODO: verify against the installed toolchain):

```bash
hvigorw clean
hvigorw assembleHap --mode module -p module=entry@default -p product=default -p buildMode=debug --no-daemon
```

Expected output: `entry/build/default/outputs/default/entry-default-signed.hap`.
Without signing, the file is `entry-default-unsigned.hap`. TODO: confirm the path.

## 6. Install

```bash
hdc list targets                      # emulator/device must be listed
hdc install -r entry/build/default/outputs/default/entry-default-signed.hap
```

The emulator must be created and running first (see [3.1 step 4](#31-deveco-studio-and-the-emulator)).

## 7. Launch

```bash
hdc shell aa start -a EntryAbility -b com.hackyeah.huawei.app
hdc hilog | grep testTag              # follow app logs (TODO: switch to the app's own log tag)
```

Or tap **HackYeah App** on the launcher. In DevEco, select the device and press Run.

## 8. Tests

TODO: verify the commands.

```bash
hvigorw test --no-daemon              # local unit tests: entry/src/test
hvigorw onDeviceTest --no-daemon      # instrumented tests: entry/src/ohosTest (needs emulator/device)
```

In DevEco: right-click `entry/src/test` or `entry/src/ohosTest` > Run.

## 9. Architecture

TODO: one diagram plus a short description: modules, pages, data flow, platform APIs/Kits used,
on-device AI and agent components, persistence, permissions and error handling.

## 10. AI features

TODO: if the app ships AI features, document the model/service, inference flow, data handling,
limitations, validation and privacy here (or in `docs/AI_FEATURES.md`). See also [AI_WORKFLOW.md](AI_WORKFLOW.md).

## 11. Switching runtime: HarmonyOS vs OpenHarmony

The skeleton targets the **HarmonyOS** SDK. That is DevEco's default, and the DevEco emulator on macOS only
runs HarmonyOS projects. To build against the **OpenHarmony** SDK instead (for example for an OpenHarmony or Oniro
board), change the product in `build-profile.json5`:

```json5
"compileSdkVersion": 23,
"compatibleSdkVersion": 20,
"targetSdkVersion": 23,
"runtimeOS": "OpenHarmony",
```

The OpenHarmony runtime uses integer API levels. The HarmonyOS runtime uses release labels:
`"6.0.0(20)"`, `"6.1.0(23)"`, `"6.1.1(24)"`. The Oniro emulator runs OpenHarmony 6.1 (API 23), so do not rely on
API 24 behaviour there.
Only `@ohos.*` / OpenHarmony APIs are available there. HarmonyOS-only Kits are not.

---

## Huawei judging checklist

Judging weights: Originality 20, Usefulness 20, Technical execution 20, Platform use 20, Demo 10, Reproducibility 10.
They prefer a **narrow, working** solution over a broad concept.

- [ ] **Public repository**, with commit history that shows progress (small, frequent commits)
- [ ] **Reproducible instructions** for setup, build, install and launch (sections 3 to 7, all `TODO`s resolved and tested on a clean machine)
- [ ] **Working `.hap`**, API 20+, running on an OpenHarmony/HarmonyOS emulator or device (attach it to a GitHub Release)
- [ ] **Short recorded demo** of the app running on an emulator/device (link here: TODO)
- [ ] **Architecture description** (section 9)
- [ ] **`AI_WORKFLOW.md`**: models, agents, MCP servers, main prompts, workflow, validation, lessons learned
- [ ] **AI feature docs**, if the app has AI features (section 10)
- [ ] Real use of **platform APIs/Kits**. An app that would run unchanged on any OS scores lower.
- [ ] Theme fit: Intelligent / Spatial / Human-Centric experiences (combining themes is a plus)
- [ ] Error handling and **tests** (`entry/src/test`, `entry/src/ohosTest`)
- [ ] **No secrets in the repo**: no signing material, API keys or `signingConfigs` with local paths
- [ ] Pre-existing work separated from hackathon work. Significant AI use disclosed.
