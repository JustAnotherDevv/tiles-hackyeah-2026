#!/usr/bin/env bash
# Build a signed debug .hap WITHOUT a Huawei ID: OpenHarmony public SDK (API 23) + the SDK's built-in debug keystore.
#
#   source .toolchain/env.sh          # no-login OpenHarmony toolchain (see .toolchain/README.md; git-ignored)
#   scripts/build-ohos-signed.sh      # -> release/tiles-debug-signed.hap
#
# The repository itself stays a HarmonyOS project (compile/target 6.1.1(24), minimum 6.0.0(20)). This script copies
# the sources to .toolchain/oniro-build/aegis-pocket (git-ignored), switches that copy to runtimeOS "OpenHarmony"
# (compile/target API 23, minimum API 20, deviceTypes "default"), runs `oniro-app sign` (offline debug keys and
# signingConfigs written only into the copy, never into the repo) and `oniro-app build --no-deps`.
# The resulting .hap installs and runs on the DevEco HarmonyOS 6.1.1 (API 24) phone emulator; verified 2026-10-04.
# Needs: java on PATH (for signing), python3, rsync.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
command -v oniro-app >/dev/null || { echo "oniro-app not on PATH: source .toolchain/env.sh first" >&2; exit 1; }
[ -n "${OHOS_BASE_SDK_HOME:-}" ] || { echo "OHOS_BASE_SDK_HOME unset: source .toolchain/env.sh first" >&2; exit 1; }
D=.toolchain/oniro-build/aegis-pocket
mkdir -p "$D"
rsync -a --delete --exclude build --exclude .hvigor --exclude oh_modules --exclude local.properties \
  AppScope entry hvigor hvigorfile.ts build-profile.json5 oh-package.json5 code-linter.json5 "$D/"
cd "$D"
python3 - <<'EOF'
import re
p = 'build-profile.json5'; s = open(p).read()
for a, b in [('"compileSdkVersion": "6.1.1(24)"', '"compileSdkVersion": 23'),
             ('"compatibleSdkVersion": "6.0.0(20)"', '"compatibleSdkVersion": 20'),
             ('"targetSdkVersion": "6.1.1(24)"', '"targetSdkVersion": 23'),
             ('"runtimeOS": "HarmonyOS"', '"runtimeOS": "OpenHarmony"')]:
    s = s.replace(a, b)
open(p, 'w').write(s)
p = 'oh-package.json5'; s = open(p).read()
open(p, 'w').write(re.sub(r'"devDependencies":\s*\{[^}]*\}', '"devDependencies": {}', s))
p = 'entry/src/main/module.json5'; s = open(p).read()
open(p, 'w').write(re.sub(r'"deviceTypes":\s*\[[^\]]*\]', '"deviceTypes": ["default"]', s))
EOF
echo "sdk.dir=$OHOS_BASE_SDK_HOME" > local.properties
oniro-app sign . 2>&1 | tail -3
oniro-app build --no-deps . 2>&1 | tail -15
HAP=entry/build/default/outputs/default/entry-default-signed.hap
[ -f "$HAP" ] || { echo "no signed .hap produced" >&2; exit 1; }
mkdir -p "$ROOT/release"
cp "$HAP" "$ROOT/release/tiles-debug-signed.hap"
echo "wrote release/tiles-debug-signed.hap"
