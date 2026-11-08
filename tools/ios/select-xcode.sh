#!/usr/bin/env bash
# 在 macOS runner 上挑选 Xcode：优先最新的 16.x（SDK 平台完整），否则取 >= versions.json 要求的最老版本。
# 同时把 DEVELOPER_DIR / XCODE_VERSION 写进 GITHUB_ENV（本地运行时自动跳过）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REQ="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["xcode"])' "${ROOT}/versions.json")"

CHOSEN="$(python3 - "${REQ}" <<'PY'
import glob
import os
import subprocess
import sys

req = tuple(int(x) for x in sys.argv[1].split("."))
candidates = []
for app in sorted(glob.glob("/Applications/Xcode*.app")):
    plist = os.path.join(app, "Contents/Info.plist")
    try:
        version = subprocess.check_output(
            ["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleShortVersionString", plist],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        parsed = tuple(int(x) for x in version.split("."))
    except Exception:
        continue
    candidates.append((parsed, version, app))

if not candidates:
    raise SystemExit("runner 上没有找到任何 /Applications/Xcode*.app")

usable = [item for item in candidates if item[0] >= req]
preferred = [item for item in usable if item[0][0] == 16]
if preferred:
    chosen = sorted(preferred)[-1]
elif usable:
    chosen = sorted(usable)[0]
else:
    chosen = sorted(candidates)[-1]
print("%s|%s" % (chosen[1], chosen[2]))
PY
)"

XCODE_VERSION="${CHOSEN%%|*}"
XCODE_APP="${CHOSEN#*|}"

echo "versions.json 要求 Xcode >= ${REQ}，选中 ${XCODE_VERSION}: ${XCODE_APP}"
sudo xcode-select -s "${XCODE_APP}"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  echo "DEVELOPER_DIR=${XCODE_APP}/Contents/Developer" >> "${GITHUB_ENV}"
  echo "XCODE_VERSION=${XCODE_VERSION}" >> "${GITHUB_ENV}"
fi

xcodebuild -version
xcrun --sdk iphoneos --show-sdk-version
