# 仓库初始化与推送说明

本目录 `d:\chat\teamgram-ios` 是从 `teamgram/teamgram-ios`（分支 `teamgram`）的 codeload ZIP 解压得到的。
ZIP 不带 submodule 内容与 gitlink，本目录已经做了两件事：

1. 把 `.gitmodules` 的相对 URL（`../rlottie.git`、`../tgcalls.git`）改成上游绝对 URL；
2. 用 `tools/ios/submodules.lock` 记录 11 个 submodule 的固定提交号，供 `tools/ios/restore-submodules.sh` 兜底拉取。

## 1. 目录结构

```
teamgram-ios/
├─ .github/workflows/
│  └─ ios-unsigned.yml        # 唯一 CI：probe / prepare / build 三级，macos-latest
├─ config/
│  ├─ teamgram-ios.json       # 入库：公共默认配置（bundle id、显示名、scheme、DC 占位、功能开关）
│  └─ teamgram-ios.local.json.example  # 本地真实值的模板（复制后改名，已被 gitignore）
├─ docs/
│  ├─ ios-build-plan.md       # 三条路线、成本、执行顺序
│  ├─ ios-change-checklist.md # 改造点清单（对照 Android feature-trim）
│  ├─ resign-handover.md      # 给签名方的 bundle id / entitlements 清单
│  └─ repo-setup.md           # 本文
├─ tools/ios/
│  ├─ apply-config.py         # 集中配置 → 构建 JSON + 源码替换
│  ├─ probe.sh                # L1 环境校验（不编译、不拉依赖）
│  ├─ select-xcode.sh         # 按 versions.json 选择 Xcode
│  ├─ restore-submodules.sh   # 无 gitlink 时按固定 SHA 补拉 submodule
│  ├─ make-unsigned-artifacts.sh # 剥离签名、改写 id、组装 IPA/xcarchive
│  └─ submodules.lock         # 11 个 submodule 的 repo + commit
├─ build-system/ …            # 上游构建脚本（Make.py、假签名证书/profile）
├─ Telegram/ …                # 主 App target 与 BUILD
└─ submodules/ …              # TelegramCore / TelegramUI / MtProtoKit 等源码
```

## 2. 公开仓库红线（必须遵守）

**绝对不能入库**：

- 真实 `api_hash`、`api_id`（如果要保密）
- 真实服务器 IP / 域名 / 端口组合（公网地址）
- Apple 证书 `.p12`、`.mobileprovision`、私钥 `.pem` / `.key`
- 开发者账号、App Store Connect API Key、Team ID 的真实值（Team ID 本身不算秘密，但不要和账号信息一起放）
- 任何测试账号的手机号、验证码、session
- 构建产物：`.ipa`、`.xcarchive`、`dSYMs.zip`

**可以入库**：

- 公共占位配置 `config/teamgram-ios.json`
- workflow、脚本、文档
- RSA **公钥**（本来就是公开信息）
- 上游自带的假签名证书 `build-system/fake-codesigning/SelfSigned.p12`（仅用于 CI 构建，不是真实证书）

已被 `.gitignore` 排除：`config/teamgram-ios.local.json`、`build/`、`build-output/`、`artifacts/`、
`*.ipa`、`*.xcarchive`、`*.p12`、`*.mobileprovision`、`*.pem`、`*.key` 等。

## 3. 本地初始化（已执行）

`git init` 与 11 个 submodule 的 gitlink 已经在本地仓库里配置好（没有提交，等用户确认后再提交）。
如果之后重新从 ZIP 解压，需要重做（提交号来自 `tools/ios/submodules.lock`，与上游
`teamgram/teamgram-ios@074a9be35d7fdc4d2402c5f9a69bb8c7cf0e0bb1` 一致）：

```powershell
git init -b main
git config core.autocrlf false

# 11 个 gitlink（mode 160000 = submodule 指针，不含文件内容）
git update-index --add --cacheinfo 160000,67f103bc8b625f2a4a9e94f1d8c7bd84c5a08d1d,submodules/rlottie/rlottie
git update-index --add --cacheinfo 160000,37d98e984fd6fa389262307db826d52ab86c8241,submodules/TgVoip/libtgvoip
git update-index --add --cacheinfo 160000,814089b59311c0d59e22eb72e6cd070fbfbeb1d7,submodules/TgVoipWebrtc/tgcalls
git update-index --add --cacheinfo 160000,345b71fc226d79abfe180b27b7f8d711aa398bbd,build-system/bazel-rules/rules_apple
git update-index --add --cacheinfo 160000,72347ab6cb613b36039d43a071ac67f63f4de248,build-system/bazel-rules/rules_swift
git update-index --add --cacheinfo 160000,cf271a330b08a3bbd8ad61241d03787683d5a1c5,build-system/bazel-rules/apple_support
git update-index --add --cacheinfo 160000,77e00ae3fd2d7f6fae3790420bc95c8f7abb6f7b,build-system/bazel-rules/rules_xcodeproj
git update-index --add --cacheinfo 160000,a0bf60e1645869c6452c9f3b128362d433764f19,build-system/tulsi
git update-index --add --cacheinfo 160000,e7bfd8b6c230a6824e7fd1efa2378a7322986128,third-party/libvpx/libvpx
git update-index --add --cacheinfo 160000,e3dfe44d1aea15a1aabded19d71884412e772245,third-party/webrtc/webrtc
git update-index --add --cacheinfo 160000,5585eafe31c2299163dcb206e05e18be7dd93098,third-party/libx264/x264

# 脚本需要可执行位（Windows 上 git 默认不保留）
git add --chmod=+x tools/ios/apply-config.py tools/ios/*.sh
```

> 只有 gitlink 是不够的：`.gitmodules` 必须同时存在并写对 `url`，否则
> `actions/checkout --submodules recursive` 会拉不到内容，L1 probe 也会报"既没有内容也不是 gitlink"。

## 4. 用户先做的事：GitHub 登录

```powershell
gh auth login
gh auth status
```

登录后由我们执行仓库创建与推送。

## 5. 建仓 + 推送（完整命令序列）

```powershell
# 1) 进入仓库
cd d:\chat\teamgram-ios

# 2) 确认没有把本地敏感文件加进来
git status --short
git check-ignore -v config/teamgram-ios.local.json

# 3) 首次提交（公开仓库建议先确认内容）
git add -A
git commit -m "chore: teamgram-ios source + unsigned iOS CI + docs"

# 4) 创建公开仓库并推送（名字可改）
gh repo create teamgram-ios --public --source=. --remote=origin --push

# 5) 确认
gh repo view --web
```

如果仓库已存在，改用：

```powershell
git remote add origin https://github.com/<你的账号>/teamgram-ios.git
git branch -M main
git push -u origin main
```

## 6. 配置 Secrets（真实值只放这里）

```powershell
gh secret set TEAMGRAM_API_ID      --body "4"
gh secret set TEAMGRAM_API_HASH    --body "<真实 api_hash>"
gh secret set TEAMGRAM_DC_IP       --body "<服务端局域网或公网 IP>"
gh secret set TEAMGRAM_DC_PORT     --body "10443"   # 可选，缺省用 config 里的值
```

可选非敏感变量：

```powershell
gh variable set TEAMGRAM_FINAL_BUNDLE_ID --body "com.teamgram.messenger"
```

workflow 读取顺序：`config/teamgram-ios.json` → `config/teamgram-ios.local.json`（若存在）→ 环境变量/Secrets。
Secrets 只在 CI 生效，不会写回仓库文件。

## 7. 触发构建（三级，逐级放行）

```powershell
# L1：只做环境校验，几十秒；先跑这个
gh workflow run ios-unsigned.yml -f stage=probe

# L2：L1 + 拉依赖/下载 Bazel/生成配置，不编译
gh workflow run ios-unsigned.yml -f stage=prepare

# L3：完整构建并出产物
gh workflow run ios-unsigned.yml -f stage=build -f final_bundle_id=com.teamgram.messenger -f app_name=Teamgram

# 查看运行
gh run list --workflow=ios-unsigned.yml
gh run watch

# 下载产物
gh run download <run-id> -n teamgram-ios-unsigned-<run-number>
```

不传 `stage` 时默认只跑 `probe`，避免误触几十分钟的完整构建。推 `ios-*` 标签会自动跑完整三级。

产物在 artifact 的 `artifacts/` 目录：`Teamgram-unsigned.ipa`、`<AppName>.xcarchive.zip`、
`dSYMs.zip`、`SHA256SUMS.txt`。

## 8. 成本

公开仓库的 macOS runner **不扣免费分钟，成本为 0**；私有仓库按 **10 倍**分钟计费，
所以这个仓库必须保持 public。三级拆分的目的不是省钱，而是让失败停在几十秒的 L1，而不是几十分钟的 L3。

## 9. Submodule 策略

- 正常 `git clone --recursive` / Actions 的 `submodules: recursive` 会按 gitlink 拉取。
- 如果拉取失败，workflow 的 `Ensure submodules` 步骤会调用 `restore-submodules.sh`，
  用 `codeload.github.com/<repo>/zip/<commit>` 下载固定提交，不依赖 git 协议。
- 11 个 submodule 的清单与提交号在 `tools/ios/submodules.lock`；升级上游时同步更新该文件与 gitlink。

## 10. 公开仓库的代价

- 源码（含 GPL 派生部分）公开可见；Telegram-iOS 本身是 GPLv2，公开是合规做法。
- 任何人都可以 fork、发起 PR、消耗 Actions 分钟（公开仓库免费但有公平使用限制）。
- 建议在仓库设置里限制 Actions 只允许维护者触发（Settings → Actions → General）。
- 真实密钥只走 Secrets；不要为了省事在 workflow 里 echo 出来（GitHub 会自动脱敏，但仍应避免）。
