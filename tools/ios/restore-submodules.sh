#!/usr/bin/env bash
# 兜底恢复 submodule 内容。
# 正常情况下 git checkout 时已通过 gitlink + .gitmodules 拉取；本脚本用于
# 「源码来自 ZIP、没有 gitlink」或 submodule 拉取失败的场景。
# 实际编译仅在 macOS runner 上执行，本机 Windows 未验证。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCK="${ROOT}/tools/ios/submodules.lock"
TMP="${ROOT}/build/submodule-cache"
mkdir -p "${TMP}"

while IFS='|' read -r path repo commit; do
  [[ -z "${path}" || "${path}" == \#* ]] && continue
  target="${ROOT}/${path}"
  if [[ -d "${target}" && -n "$(ls -A "${target}" 2>/dev/null || true)" ]]; then
    echo "skip ${path}"
    continue
  fi
  echo "fetch ${repo}@${commit} -> ${path}"
  archive="${TMP}/$(echo "${repo}" | tr '/' '_')-${commit}.zip"
  if [[ ! -f "${archive}" ]]; then
    curl -fsSL --retry 4 --retry-all-errors \
      "https://codeload.github.com/${repo}/zip/${commit}" -o "${archive}"
  fi
  mkdir -p "${TMP}/unpack-${commit}"
  unzip -q -o "${archive}" -d "${TMP}/unpack-${commit}"
  mkdir -p "${target}"
  # ZIP 顶层是 <repo>-<sha>/，把内容铺到目标目录
  cp -R "${TMP}/unpack-${commit}"/*/. "${target}/"
done < "${LOCK}"

echo "submodules ready"
