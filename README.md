# HackYeah App (working title)

> **Status:** project skeleton. The app idea is not decided yet. The current app is the DevEco Studio
> "Empty Ability" template showing a bold **Hello HarmonyOS** screen.
> Replace every `TODO` below once the idea and toolchain are settled.

Submission for **HackYeah 2026, Huawei partner task "Imagine What's Next"**: an app for an
OpenHarmony-based device (HarmonyOS / OpenHarmony / Oniro).

| | |
|---|---|
| Language / UI | ArkTS + ArkUI (declarative) |
| App model | Stage model (`UIAbility`) |
| Target / minimum API | **20** (HarmonyOS 6.0.0 / OpenHarmony 6.0) |
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
├── AI_WORKFLOW.md                  # Required by the Huawei brief
└── README.md
```

## 2. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| macOS (Apple Silicon) | 27 | Development machine |
| DevEco Studio | TODO: exact version (6.x, with API 20 support) | Bundles the HarmonyOS SDK, hvigor, ohpm, hdc and the emulator |
| HarmonyOS SDK | 6.0.0(20) | Installed via DevEco SDK Manager or the command-line tools |
| Node.js | 18+ (tested with TODO) | Only needed for CLI builds outside DevEco |
| Java | 17 | TODO: confirm whether the CLI toolchain needs it |
| Git | any recent | |

> Local machine-specific toolchain files go in `.toolchain/`, which is git-ignored.

## 3. Setup

```bash
git clone TODO-public-repo-url
cd TODO-repo-dir

# TODO: exact commands to install the SDK and command-line tools (or "install DevEco Studio X.Y")
# TODO: export PATH for ohpm / hvigorw / hdc, e.g.
# export PATH="$PWD/.toolchain/TODO/command-line-tools/bin:$PATH"

ohpm install            # restores oh_modules/ (hypium, hamock)
```

**DevEco Studio:** File > Open > select this folder. Let it sync, then accept the SDK prompt for API 20.
DevEco creates `local.properties` (git-ignored) pointing at your SDK.

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

TODO: emulator setup steps (Device Manager > create/download image > start).

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
"compileSdkVersion": 20,
"compatibleSdkVersion": 20,
"targetSdkVersion": 20,
"runtimeOS": "OpenHarmony",
```

The OpenHarmony runtime uses integer API levels. The HarmonyOS runtime uses `"6.0.0(20)"` strings.
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
