# deveco-cli: What It Is and How to Deploy and Use

This document explains what **deveco-cli** (DevEco command line tools) is, and how to install, deploy, and use it. Reference:

- DevecoCli source: <https://gitcode.com/openharmony-sig/deveco-cli>

---

## Overview

**devecocli** is the official **HarmonyOS application development command line tool**. It packages the DevEco Studio build, deployment, device management, and debugging capabilities into a command line interface, so developers and automation scripts (such as CI pipelines or AI agents) can build, install, run, and debug HarmonyOS applications without opening the DevEco Studio IDE.

It is typically installed globally via `npm` and invoked with the command name `devecocli`.

```
$ devecocli -V
1.3.4
```

## Feature matrix

The matrix below records the current command availability.

| Command                               | Capability                                     | Availability |
| ------------------------------------- | ---------------------------------------------- | :----------: |
| `help`                                | Show CLI help and version information          |      ✅      |
| `init`                                | Configure Skills or MCP services               |      ✅      |
| `auth login`                          | Log in to a Huawei account                     |      ❌      |
| `auth status`                         | Show the current login status                  |      ✅      |
| `auth team list`                      | List teams for the current account             |      ❌      |
| `auth logout`                         | Log out of the current account                 |      ❌      |
| `docs search`                         | Search HarmonyOS documentation                 |      ✅      |
| `docs read`                           | Read a document by ID                          |      ✅      |
| `docs catalog`                        | List documentation categories                  |      ✅      |
| `create`                              | Create an Empty Ability project                |      ✅      |
| `build`                               | Build a project or selected module             |      ✅      |
| `build clean`                         | Clean project build outputs                    |      ✅      |
| `run`                                 | Build, install, and launch an app              |      ✅      |
| `log`                                 | Read HiLog and crash logs                      |      ✅      |
| `check lint`                          | Check and optionally fix ArkTS issues          |      ✅      |
| `check compat`                        | Check compatibility with an SDK version        |      ❌      |
| `signature generate`                  | Generate debugging signing material            |      ❌      |
| `emulator list`                       | List emulator instances                        |      ✅      |
| `emulator start`                      | Start an emulator                              |      ✅      |
| `emulator create`                     | Create an emulator instance                    |      ✅      |
| `emulator stop`                       | Stop an emulator                               |      ✅      |
| `emulator delete`                     | Delete an emulator                             |      ✅      |
| `emulator image list/download/remove` | Manage emulator images                         |      ✅      |
| `emulator license view/accept`        | View and accept emulator licenses              |      ✅      |
| `emulator shake/power/rotate`         | Control emulator motion, power, and rotation   |      ❌      |
| `emulator volume/fold/battery`        | Control emulator volume, fold, and battery     |      ❌      |
| `emulator geolocation/scene/sensor`   | Control emulator location, motion, and sensors |      ❌      |
| `device list`                         | List connected devices and emulators           |      ✅      |
| `device view`                         | Show detailed device information               |      ✅      |
| `skills list/find/add/remove`         | Discover and manage Skills                     |      ✅      |
| `ui layout/window list`               | Inspect UI layout and windows                  |      ✅      |
| `ui screenshot`                       | Capture a device screenshot                    |      ✅      |
| `ui click/doubleclick/longclick`      | Click a UI node or coordinate                  |      ✅      |
| `ui swipe/fling/dircfling/drag`       | Perform touch and gesture actions              |      ✅      |
| `ui text`                             | Input text into the current UI target          |      ✅      |
| `serve mcp`                           | Start the ArkTS/C/C++ checking MCP service     |      ✅      |
| `serve lsp`                           | Start the code intelligence LSP service        |      ✅      |
| `update`                              | Update DevEco CLI                              |      ✅      |

**Availability legend:** ✅ available; ⚠️ available with limitations; ❌ unavailable;
TBD not yet verified.

**Regional availability:** every entry marked unavailable is region-restricted: the
command is present, but it does not work outside mainland China. This is not a statement
that the CLI lacks the feature. For signing material, **use DevEco Studio instead of
`signature generate`**.

---

## How to deploy

### Install / update deveco-cli

Requires [Node.js](https://nodejs.org) and npm.

```bash
# Install globally
npm install -g @deveco/deveco-cli@1.3.4

# Verify
devecocli -V
```

The hackathon setup applies verified compatibility patches to the supported DevEco CLI version. Reinstalling the npm package or running `devecocli update` can overwrite those patches. Do not update it independently during the hackathon; rerun the setup prompt so it can reapply and verify the patches, or report that the newly installed version is not yet supported.

Check that the DevEco Studio toolchain (hvigor, ohpm, hdc, etc.) is available in the environment; `devecocli build` will automatically run `ohpm install` and the hvigor build.
