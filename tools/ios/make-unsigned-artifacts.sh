#!/usr/bin/env bash
# 把 Bazel 产出的（用假证书签名的）IPA 处理成：
#   1) 真正无签名的 IPA（去掉 profile / _CodeSignature / Mach-O 签名）
#   2) 由 .app + dSYM 组装的 .xcarchive（不是 Xcode archive 动作的原生产物）
# 仅在 macOS 上运行（需要 codesign / PlistBuddy / ditto），本机 Windows 未验证。
set -euo pipefail

IPA=""
OUT="artifacts"
RESOLVED="build/teamgram-resolved.json"
DSYM_DIR="build-output"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ipa) IPA="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --resolved) RESOLVED="$2"; shift 2 ;;
    --dsym-dir) DSYM_DIR="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -f "${IPA}" ]] || { echo "IPA not found: ${IPA}" >&2; exit 1; }
[[ -f "${RESOLVED}" ]] || { echo "resolved config not found: ${RESOLVED}" >&2; exit 1; }

json_value() {
  python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"
}

FINAL_ID="$(json_value "${RESOLVED}" final_bundle_id)"
APP_NAME="$(json_value "${RESOLVED}" app_name)"
mkdir -p "${OUT}"
OUT_ABS="$(cd "${OUT}" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

unzip -q "${IPA}" -d "${WORK}/ipa"
APP="$(find "${WORK}/ipa/Payload" -maxdepth 1 -name '*.app' | head -n 1)"
[[ -n "${APP}" ]] || { echo "Payload 下没有 .app" >&2; exit 1; }
OLD_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "${APP}/Info.plist")"
echo "build bundle id: ${OLD_ID} -> final: ${FINAL_ID}"

# 1. 重写主 App / 扩展 / Watch / Framework 的 bundle id
rewrite_plist() {
  local plist="$1"
  local current
  current="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "${plist}" 2>/dev/null || true)"
  [[ -n "${current}" ]] || return 0
  if [[ "${current}" == "${OLD_ID}" ]]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier ${FINAL_ID}" "${plist}"
  elif [[ "${current}" == "${OLD_ID}."* ]]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier ${FINAL_ID}${current#${OLD_ID}}" "${plist}"
  fi
}

rewrite_plist "${APP}/Info.plist"
while IFS= read -r -d '' plist; do
  rewrite_plist "${plist}"
done < <(find "${WORK}/ipa/Payload" -name Info.plist -print0)

# Watch 的伴生关系键
while IFS= read -r -d '' plist; do
  for key in WKCompanionAppBundleIdentifier WKAppBundleIdentifier; do
    value="$(/usr/libexec/PlistBuddy -c "Print :${key}" "${plist}" 2>/dev/null || true)"
    if [[ -n "${value}" && "${value}" == "${OLD_ID}"* ]]; then
      /usr/libexec/PlistBuddy -c "Set :${key} ${FINAL_ID}${value#${OLD_ID}}" "${plist}"
    fi
  done
done < <(find "${WORK}/ipa/Payload" -name Info.plist -print0)

# 2. 去掉描述文件与签名
find "${WORK}/ipa/Payload" -name embedded.mobileprovision -delete
find "${WORK}/ipa/Payload" -type d -name _CodeSignature -prune -exec rm -rf {} +

while IFS= read -r -d '' binary; do
  codesign --remove-signature "${binary}" >/dev/null 2>&1 || true
done < <(find "${WORK}/ipa/Payload" -type f -perm -111 -print0)

while IFS= read -r -d '' bundle; do
  codesign --remove-signature "${bundle}" >/dev/null 2>&1 || true
done < <(find "${WORK}/ipa/Payload" -type d \( -name '*.framework' -o -name '*.appex' \) -print0)

# 3. 未签名 IPA
(
  cd "${WORK}/ipa"
  rm -f "${OUT_ABS}/Teamgram-unsigned.ipa" 2>/dev/null || true
  zip -qry "${OUT_ABS}/Teamgram-unsigned.ipa" Payload
)

# 4. 组装 xcarchive
XCARCH="${WORK}/${APP_NAME}.xcarchive"
mkdir -p "${XCARCH}/Products/Applications" "${XCARCH}/dSYMs"
ditto "${APP}" "${XCARCH}/Products/Applications/$(basename "${APP}")"
if [[ -d "${DSYM_DIR}" ]]; then
  find "${DSYM_DIR}" -maxdepth 2 -name '*.dSYM' -exec ditto {} "${XCARCH}/dSYMs/" \;
fi
BUNDLE_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "${APP}/Info.plist" 2>/dev/null || echo 0)"
BUILD_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "${APP}/Info.plist" 2>/dev/null || echo 0)"
INFO="${XCARCH}/Info.plist"
cat > "${INFO}" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict/>
</plist>
PLIST
/usr/libexec/PlistBuddy \
  -c "Add :ArchiveVersion integer 2" \
  -c "Add :Name string ${APP_NAME}" \
  -c "Add :CreationDate string $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -c "Add :ApplicationProperties dict" \
  -c "Add :ApplicationProperties:CFBundleIdentifier string ${FINAL_ID}" \
  -c "Add :ApplicationProperties:CFBundleShortVersionString string ${BUNDLE_VERSION}" \
  -c "Add :ApplicationProperties:CFBundleVersion string ${BUILD_VERSION}" \
  -c "Add :ApplicationProperties:SigningIdentity string ''" \
  -c "Add :ApplicationProperties:Team string ''" \
  "${INFO}"
(
  cd "${WORK}"
  rm -f "${OUT_ABS}/${APP_NAME}.xcarchive.zip" 2>/dev/null || true
  ditto -c -k --sequesterRsrc --keepParent "${XCARCH}" "${OUT_ABS}/${APP_NAME}.xcarchive.zip"
)

# 5. dSYM 单独打包
if [[ -d "${DSYM_DIR}" ]] && find "${DSYM_DIR}" -maxdepth 2 -name '*.dSYM' | grep -q .; then
  mkdir -p "${WORK}/dSYMs"
  find "${DSYM_DIR}" -maxdepth 2 -name '*.dSYM' -exec ditto {} "${WORK}/dSYMs/" \;
  (
    cd "${WORK}/dSYMs"
    rm -f "${OUT_ABS}/dSYMs.zip" 2>/dev/null || true
    zip -qry "${OUT_ABS}/dSYMs.zip" .
  )
fi

echo "产物:"
ls -lh "${OUT}" | sed 's/^/  /'
