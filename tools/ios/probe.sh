#!/usr/bin/env bash
# L1 probe：只做环境与工程完整性校验，不下载依赖、不编译、不生成 Xcode 工程。
# 目标 < 60 秒（不含 checkout）。任何一项不满足都会以非零码退出，
# 并在日志里打印 "[FAIL]" 与对应的常见原因/修复方法。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

FAIL=0
ok()   { printf '[ ok ] %s\n' "$*"; }
warn() { printf '[warn] %s\n' "$*"; }
bad()  { printf '[FAIL] %s\n' "$*" >&2; printf '::error::%s\n' "$*"; FAIL=1; }

echo "=== L1 probe: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# ---------- 1. 主机与工具链 ----------
if [[ "$(uname -s)" == "Darwin" ]]; then
  ok "系统: $(sw_vers -productVersion) ($(uname -m))"
else
  bad "当前不是 macOS（$(uname -s)）；probe 与 build 必须跑在 macos runner 上"
fi

swift --version 2>&1 | head -n 2 | sed 's/^/[info] /' || bad "swift 不可用"
xcodebuild -version 2>&1 | sed 's/^/[info] /' || bad "xcodebuild 不可用"

SDK_VERSION="$(xcrun --sdk iphoneos --show-sdk-version 2>/dev/null || true)"
if [[ -n "${SDK_VERSION}" ]]; then
  ok "iPhoneOS SDK: ${SDK_VERSION}"
else
  bad "找不到 iPhoneOS SDK；通常是 Xcode 未安装完整或 CommandLineTools 被 xcode-select 选中"
fi

if [[ -z "${DEVELOPER_DIR:-}" ]] && ! xcode-select -p >/dev/null 2>&1; then
  bad "xcode-select 未指向有效 Xcode"
fi

# ---------- 2. versions.json 与实际版本 ----------
if [[ ! -f versions.json ]]; then
  bad "缺少 versions.json"
else
  python3 - versions.json <<'PY'
import json
import platform
import re
import subprocess
import sys

path = sys.argv[1]
required = json.load(open(path))
for key in ("app", "xcode", "bazel", "macos"):
    if key not in required:
        print("[FAIL] versions.json 缺少字段 %s" % key)
        sys.exit(1)

def tuple_version(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])

raw = ""
try:
    raw = subprocess.check_output(["xcodebuild", "-version"], text=True)
except Exception as error:
    print("[FAIL] 无法执行 xcodebuild -version: %s" % error)
    sys.exit(1)
installed_xcode = re.search(r"Xcode\s+([\d.]+)", raw)
if not installed_xcode:
    print("[FAIL] 无法从 xcodebuild -version 解析 Xcode 版本")
    sys.exit(1)
xcode_now = tuple_version(installed_xcode.group(1))
xcode_req = tuple_version(required["xcode"])
if xcode_now < xcode_req:
    print("[FAIL] Xcode %s < versions.json 要求 %s；处理方式：在 runner 上安装对应 Xcode，"
          "或改用 macos-13/macos-14，或临时调低 versions.json（风险：rules_apple 兼容性）"
          % (installed_xcode.group(1), required["xcode"]))
    sys.exit(1)
print("[ ok ] Xcode %s >= 要求 %s" % (installed_xcode.group(1), required["xcode"]))

mac_now = tuple_version(platform.mac_ver()[0])
mac_req = tuple_version(required["macos"])
if mac_now < mac_req:
    print("[FAIL] macOS %s < versions.json 要求 %s" % (platform.mac_ver()[0], required["macos"]))
    sys.exit(1)
print("[ ok ] macOS %s >= 要求 %s" % (platform.mac_ver()[0], required["macos"]))
print("[info] Bazel 版本要求: %s（由 prepare 级下载）" % required["bazel"])
PY
  [[ $? -ne 0 ]] && FAIL=1
fi

# ---------- 3. 工程可枚举性 ----------
# Telegram-iOS 不提交 .xcodeproj（由 Bazel/rules_xcodeproj 生成），所以只在工程存在时才真正枚举。
PROJECT_FILE="$(find . -maxdepth 3 -name '*.xcodeproj' -not -path './build/*' 2>/dev/null | head -n 1)"
if [[ -n "${PROJECT_FILE}" ]]; then
  if xcodebuild -list -project "${PROJECT_FILE}" >/dev/null 2>&1; then
    ok "xcodebuild -list 可枚举: ${PROJECT_FILE}"
  else
    bad "xcodebuild -list 失败: ${PROJECT_FILE}（工程损坏或 Xcode 版本不兼容）"
  fi
else
  warn "仓库中没有预生成的 .xcodeproj（Bazel 构建时才生成）；target 枚举推迟到 L3，probe 跳过"
fi

# ---------- 4. 关键文件 ----------
REQUIRED_FILES=(
  "versions.json"
  "MODULE.bazel"
  "WORKSPACE"
  "Telegram/BUILD"
  "build-system/Make/Make.py"
  "build-system/Make/BuildConfiguration.py"
  "config/teamgram-ios.json"
  "tools/ios/apply-config.py"
  "tools/ios/make-unsigned-artifacts.sh"
  "tools/ios/restore-submodules.sh"
  "tools/ios/submodules.lock"
  ".github/workflows/ios-unsigned.yml"
)
for file in "${REQUIRED_FILES[@]}"; do
  if [[ -f "${file}" ]]; then
    ok "文件存在: ${file}"
  else
    bad "缺少关键文件: ${file}"
  fi
done

# 功能开关文件是 apply-config.py 在 prepare/build 阶段生成的新文件（子模块是 pristine gitlink），
# probe 阶段不存在属于正常情况，只要求生成逻辑在位。
if [[ -f "submodules/TelegramCore/Sources/TeamgramFeatureFlags.swift" ]]; then
  ok "功能开关文件已存在（本地已打过补丁）"
elif grep -q 'TeamgramFeatureFlags' tools/ios/apply-config.py; then
  warn "TeamgramFeatureFlags.swift 尚未生成；由 prepare/build 的 apply-config.py 自动创建"
else
  bad "apply-config.py 中没有 TeamgramFeatureFlags 生成逻辑"
fi

if [[ -d build-system/fake-codesigning/profiles ]]; then
  COUNT="$(find build-system/fake-codesigning/profiles -name '*.mobileprovision' | wc -l | tr -d ' ')"
  if [[ "${COUNT}" -ge 9 ]]; then
    ok "假签名 profile 数量: ${COUNT}"
  else
    bad "假签名 profile 只有 ${COUNT} 个（预期 >= 9）；缺 profile 会导致 copy_profiles_from_directory 静默跳过"
  fi
else
  bad "缺少 build-system/fake-codesigning/profiles"
fi

# ---------- 5. 脚本语法 ----------
if python3 -m py_compile tools/ios/apply-config.py; then
  ok "apply-config.py 语法通过"
else
  bad "apply-config.py 语法错误"
fi
for script in tools/ios/make-unsigned-artifacts.sh tools/ios/restore-submodules.sh tools/ios/select-xcode.sh; do
  if bash -n "${script}"; then
    ok "shell 语法通过: ${script}"
  else
    bad "shell 语法错误: ${script}"
  fi
done

# ---------- 6. submodule 声明 ----------
if [[ ! -f .gitmodules ]]; then
  bad "缺少 .gitmodules"
else
  python3 - <<'PY'
import os
import subprocess
import sys

text = open(".gitmodules", encoding="utf-8").read()
blocks = [b.strip() for b in text.split("[submodule") if b.strip()]
fail = False
declared = 0
for block in blocks:
    path = None
    url = None
    for line in block.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "path":
            path = value
        elif key == "url":
            url = value
    if path is None or url is None:
        continue
    declared += 1
    populated = os.path.isdir(path) and bool(os.listdir(path))
    if not populated:
        index = subprocess.run(
            ["git", "ls-files", "-s", path],
            capture_output=True,
            text=True,
        ).stdout.strip()
        gitlink = index.startswith("160000")
        if gitlink:
            print("[ ok ] %s 已声明为 gitlink（内容由 prepare 拉取）" % path)
        else:
            print("[FAIL] %s 既没有内容也不是 gitlink；.gitmodules 有声明但 index 缺失" % path)
            fail = True
    else:
        print("[ ok ] %s 内容已就绪" % path)
    if url.startswith("../"):
        print("[FAIL] %s 的 url 是相对路径 %s；GitHub 上无法解析，应改成 https://github.com/..." % (path, url))
        fail = True

if declared == 0:
    print("[FAIL] .gitmodules 中没有解析到任何 submodule")
    fail = True
print("[info] 共声明 %d 个 submodule" % declared)
sys.exit(1 if fail else 0)
PY
  [[ $? -ne 0 ]] && FAIL=1
fi

# ---------- 7. 构建期 bundle id 与假 profile 是否匹配 ----------
python3 - <<'PY'
import glob
import json
import plistlib
import subprocess
import sys

config = json.load(open("config/teamgram-ios.json"))
expected = "%s.%s" % (config["build_team_id"], config["build_bundle_id"])
profiles = sorted(glob.glob("build-system/fake-codesigning/profiles/*.mobileprovision"))
identifiers = []
fail = False
for path in profiles:
    try:
        data = subprocess.check_output(
            ["openssl", "smime", "-inform", "der", "-verify", "-noverify", "-in", path],
            stderr=subprocess.DEVNULL,
        )
        info = plistlib.loads(data)
        identifiers.append(info["Entitlements"]["application-identifier"])
    except Exception as error:
        print("[FAIL] 无法解析 %s: %s" % (path, error))
        fail = True

print("[info] 假 profile application-identifier: %s" % ", ".join(sorted(set(identifiers))))
main_profiles = [i for i in identifiers if i == expected]
if main_profiles:
    print("[ ok ] 主 App profile 与构建期 bundle id 匹配: %s" % expected)
else:
    print("[FAIL] 没有 profile 的 application-identifier 等于 %s；"
          "Make.py 会因找不到主 profile 直接退出。处理方式：改 config 的 build_bundle_id 为 %s，"
          "或重建 fake-codesigning" % (expected, identifiers[0].split(".", 1)[-1] if identifiers else "?"))
    fail = True
sys.exit(1 if fail else 0)
PY
[[ $? -ne 0 ]] && FAIL=1

# ---------- 8. 产物与预期 ----------
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## L1 probe"
    echo ""
    echo "- Xcode: $(xcodebuild -version 2>/dev/null | head -n 1)"
    echo "- SDK: ${SDK_VERSION:-unknown}"
    echo "- 结果: $([[ ${FAIL} -eq 0 ]] && echo 通过 || echo 失败)"
    echo ""
    echo "> probe 不下载依赖、不编译；依赖与 Bazel 由 L2 prepare 级完成。"
  } >> "${GITHUB_STEP_SUMMARY}"
fi

if [[ ${FAIL} -ne 0 ]]; then
  echo ""
  echo "=== L1 probe 失败 ==="
  echo "常见原因："
  echo "  1. Xcode 版本低于 versions.json（看到 Xcode 版本行）→ 换 runner 镜像或安装对应 Xcode"
  echo "  2. submodule 未声明/gitlink 缺失 → 检查 .gitmodules 与 git index 中的 160000 条目"
  echo "  3. 构建期 bundle id 与假 profile 不匹配 → 改 config/teamgram-ios.json 的 build_bundle_id"
  echo "  4. 假签名 profile 少于 9 个 → 从上游 build-system/fake-codesigning 恢复"
  exit 1
fi

echo "=== L1 probe 通过 ==="
