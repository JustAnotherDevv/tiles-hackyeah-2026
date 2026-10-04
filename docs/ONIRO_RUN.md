# Aegis Pocket on OpenHarmony / Oniro (no-login fallback toolchain)

Run on 2026-10-04 (about 02:35 to 03:20) by an AI agent (Claude Code), using the toolchain in `.toolchain/`
(see `.toolchain/README.md`: OpenHarmony 6.1 public SDK API 23, hvigor 6.26.8, `oniro-app` 0.11.0, Oniro v6.1
x86_64 emulator under QEMU TCG). `.toolchain/` is gitignored, so none of the build output or signing material is in git.

## Result

| Step | Result |
|---|---|
| Build against the OpenHarmony SDK (API 23 compile, API 20 minimum) | **Passed.** `BUILD SUCCESSFUL in 2 min 5 s`, 0 errors, 0 warnings |
| Sign with the OpenHarmony SDK debug keystore (`oniro-app sign`, no Huawei ID) | **Passed.** `entry-default-signed.hap` (932,871 bytes) |
| HAP metadata | `bundleName com.hackyeah.aegispocket`, `minAPIVersion 20`, `targetAPIVersion 23`; extensions `PostureFormAbility` (form), `RefreshWorkAbility` (workScheduler), `EntryBackupAbility` |
| Source stubs needed | **None.** Every kit the app imports exists in the OpenHarmony 6.1 SDK, including `@kit.UserAuthenticationKit`, `@kit.FormKit`, `@kit.SensorServiceKit`, `@kit.BackgroundTasksKit` and `@kit.NotificationKit`, and the app compiled unchanged |
| Boot the Oniro emulator, install, launch, screenshots | **Not done: the emulator did not finish booting.** See below |

So there are **no on-device screenshots yet**, and `docs/screenshots/oniro/` was not created. Install, launch and runtime
behaviour on OpenHarmony remain unverified.

## What was changed in the build copy (not in the main project)

The main project stays HarmonyOS. The build ran in a copy at `.toolchain/oniro-build/aegis-pocket/` (gitignored), with these changes:

1. `build-profile.json5`: `compileSdkVersion 23`, `compatibleSdkVersion 20`, `targetSdkVersion 23`, `runtimeOS "OpenHarmony"`
   (was `6.1.1(24)` / `6.0.0(20)` / `6.1.1(24)` / `HarmonyOS`). `signingConfigs` was filled in by `oniro-app sign`.
2. `oh-package.json5`: emptied `devDependencies` (`@ohos/hypium`, `@ohos/hamock`). `ohpm` is not available without a login,
   and these packages are only used by the test target.
3. `entry/src/main/module.json5`: `deviceTypes ["phone"]` became `["default"]`. With `"phone"`, the OpenHarmony SDK fails at
   `SyscapTransform` with error `00303060`: "The intersection of the system capability sets configured for multiple devices is empty."
4. `local.properties`: `sdk.dir=$OHOS_BASE_SDK_HOME`.

No ArkTS source file was changed or stubbed.

## Why the emulator run did not complete

- The emulator was started with the local-only script at 2 GB RAM and 4 vCPUs (`run-local.sh`, which binds VNC and the serial console to 127.0.0.1).
- The guest kernel came up and `hdcd` answered once. However, after about 35 minutes `bootevent.boot.completed` was still not set.
  Inside the guest, `free -m` showed 1570 of 1974 MB used. The guest also took more than 10 seconds to answer a serial command.
- The host had 8 GB of RAM and was out of memory. macOS swap was 11.8 of 12.3 GB used. DevEco Studio held about 3.1 GB, and
  browsers plus a parallel screen-recording job held several GB more. macOS kept the QEMU guest paged out (resident size 55 to 180 MB),
  so TCG emulation made almost no progress.
- The earlier Hello World smoke test booted in about 2 to 3 minutes with 3 GB guest RAM on a less loaded host.
- The emulator and the agent's private `hdc` server were stopped afterwards. DevEco Studio's own `hdc` server (port 8710) was left alone.

**To get the screenshots:** quit DevEco Studio and pause the other heavy jobs. Then rerun the commands below with `-m 3072M`.

## Exact commands

```sh
cd <repo root>
source .toolchain/env.sh

# 1. OpenHarmony build copy (keeps the main project HarmonyOS)
D=.toolchain/oniro-build/aegis-pocket; mkdir -p $D
rsync -a --delete --exclude build --exclude .hvigor --exclude oh_modules --exclude local.properties \
  AppScope entry hvigor hvigorfile.ts build-profile.json5 oh-package.json5 code-linter.json5 $D/
cd $D
python3 - <<'EOF'
import re
p='build-profile.json5'; s=open(p).read()
for a,b in [('"compileSdkVersion": "6.1.1(24)"','"compileSdkVersion": 23'),
            ('"compatibleSdkVersion": "6.0.0(20)"','"compatibleSdkVersion": 20'),
            ('"targetSdkVersion": "6.1.1(24)"','"targetSdkVersion": 23'),
            ('"runtimeOS": "HarmonyOS"','"runtimeOS": "OpenHarmony"')]: s=s.replace(a,b)
open(p,'w').write(s)
p='oh-package.json5'; s=open(p).read()
open(p,'w').write(re.sub(r'"devDependencies":\s*\{[^}]*\}','"devDependencies": {}',s))
EOF
sed -i '' 's/"phone"$/"default"/' entry/src/main/module.json5
echo "sdk.dir=$OHOS_BASE_SDK_HOME" > local.properties

# 2. Sign (SDK debug keystore, no account) and build
oniro-app sign .
oniro-app build --no-deps .     # -> entry/build/default/outputs/default/entry-default-signed.hap
cd -

# 3. Emulator (LOCAL-ONLY script; never the stock run.sh, which exposes VNC and a root console on 0.0.0.0)
memory_pressure | tail -1       # need several GB free
(cd .toolchain/oniro-emulator/images && ./run-local.sh --headless -m 3072M -s 4 \
   --connect 127.0.0.1:55556 --vnc-display 1 > ../boot.log 2>&1 &)

# A private hdc server, so DevEco Studio's hdc server (port 8710) is not restarted or replaced.
# hdc allows one server per TMPDIR, so give this one its own TMPDIR.
export TMPDIR=$PWD/.toolchain/hdctmp; mkdir -p $TMPDIR
(nohup hdc -m -s 127.0.0.1:8720 > $TMPDIR/server.log 2>&1 &)
H() { hdc -s 127.0.0.1:8720 "$@"; }
H tconn 127.0.0.1:55556
H -t 127.0.0.1:55556 shell param get bootevent.boot.completed     # repeat until "true"
H -t 127.0.0.1:55556 shell "power-shell wakeup; uinput -T -m 180 650 180 150 300"   # swipe away the lock screen

# 4. Install, launch, capture
H -t 127.0.0.1:55556 install -r $D/entry/build/default/outputs/default/entry-default-signed.hap
H -t 127.0.0.1:55556 shell aa start -a EntryAbility -b com.hackyeah.aegispocket
H -t 127.0.0.1:55556 shell snapshot_display -f /data/local/tmp/home.jpeg
H -t 127.0.0.1:55556 file recv /data/local/tmp/home.jpeg docs/screenshots/oniro/home.jpeg
# The bottom tab bar has 4 tabs (Home, Inbox, Preview, Settings). On the 360x720 display they sit at
# about x = 45/135/225/315, near the bottom edge. Confirm with: H shell uitest dumpLayout
H -t 127.0.0.1:55556 shell uitest uiInput click 135 690      # Inbox; then tap a row to open the detail screen
H -t 127.0.0.1:55556 shell uitest uiInput click 225 690      # Preview (data leaving the device)
H -t 127.0.0.1:55556 shell hilog -x | grep -iE "aegispocket|E/|FATAL" | tail -100

# 5. Clean up
pkill -f qemu-system-x86_64; H kill
```
