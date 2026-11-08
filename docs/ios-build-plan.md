# iOS 出包方案（GitHub Actions 优先）

> 本机是 Windows，**无法编译 iOS**。本文所有"能构建/产物路径"的结论均为静态分析 + 上游 CI 模板推断，
> **没有经过真编译、真机安装或签名验证**。凡是标注"未验证"的步骤，第一次跑时必须留足排查时间。

## 0. 当前状态

| 项目 | 状态 |
|---|---|
| `teamgram-ios` 源码 | 已下载并解压到本仓库（分支 `teamgram`，ZIP 快照） |
| 改造点清单 | 已完成：`docs/ios-change-checklist.md` |
| 重签交接清单 | 已完成：`docs/resign-handover.md` |
| GitHub Actions workflow | 已完成：`.github/workflows/ios-unsigned.yml`（三级：probe / prepare / build） |
| 环境探针 | 已完成：`tools/ios/probe.sh` + `tools/ios/select-xcode.sh` |
| 集中配置 | 已完成：`config/teamgram-ios.json` + `tools/ios/apply-config.py`（本机静态测试通过） |
| Mac | **没有** |
| Apple 开发者账号 | **没有** |
| GitHub 账号 | **没有**（用户先执行 `gh auth login`，之后由我们推送） |
| 实际编译验证 | **没有** |

## 1. 三条出包路线

### 路线 A：自有 Mac（最可控，成本最高的一次性投入）

- 硬件：Mac mini M1/M2（二手约 4000-6000 元），或借用现有 Mac；磁盘预留 ≥ 100 GB。
- 软件：macOS 13+、Xcode 15.2/15.4（Telegram-iOS 10.12 对 Xcode 版本敏感）、Python 3、Bazel 由 Make.py 自动下载。
- 账号：免费 Apple ID 可以本地调试签名（7 天有效、最多 3 台设备、**不支持 App Groups/Push**）；
  要长期安装/TestFlight 必须 Apple Developer Program（99 美元/年）。
- 优点：可以反复改代码、直接看 Xcode 报错、可做原生 `archive`。
- 缺点：本环境没有 Mac；首次全量编译 1-4 小时，Bazel 缓存占几十 GB。
- 适用：需要长期迭代 iOS 客户端，或 CI 反复失败需要本地对照排查。

### 路线 B：Codemagic（云 macOS，签名链路最顺）

- 免费额度：约 500 分钟/月 macOS 构建（机型系数与价格会调整，**以官网 Pricing 为准**）。
- 付费：Starter 约 99 美元/月起（含更多分钟），超出按分钟计费。
- 能力：macOS 虚拟机预装 Xcode，支持上传 `.p12` + `.mobileprovision`，也能接 App Store Connect API Key 自动签名。
- 限制：Bazel 工程不是默认模板，需要自己写 `scripts:`；Telegram 这种体量一次全量构建可能吃掉大部分免费额度。
- 适用：已经有 Apple 账号、想尽量少碰命令行签名的情况。

### 路线 C：GitHub Actions（当前选择）

- 成本结论：**公开仓库的 macOS runner 不扣免费分钟，成本为 0**；私有仓库按 10 倍分钟计费
  （每月 2000 分钟折算后约 200 分钟 macOS，超额约 0.08 美元/分钟，以官网为准）。
  因此本项目把仓库设为 public——GPL 派生代码本来也应公开。
- 限制：单个 job 最长 6 小时；公开仓库源码与配置公开（GPL 派生代码本来也应公开）；artifact 默认有保留期。
- 能力：`CODE_SIGNING_ALLOWED=NO` 思路 + 假证书构建 + 构建后剥离签名，可在**没有 Apple 账号**的情况下
  产出未签名 IPA 与 xcarchive；产物交给第三方签名方即可。
- 风险：首次构建可能卡在 submodule 拉取、Bazel 下载、Xcode 16/17 与旧源码不兼容、6 小时超时。
- 适用：当前没有 Mac、没有 Apple 账号，只想先把"除账号外的所有事"做完。

### 成本对比（量级，具体以各官网为准）

| 路线 | 一次性成本 | 持续成本 | 需要账号 | 能否出未签名包 | 能否 TestFlight |
|---|---|---|---|---|---|
| 自有 Mac | 4000-6000 元 | 电费/时间 | Apple ID（可选付费） | 能 | 需付费账号 |
| Codemagic | 0 | 约 99 美元/月起 | Apple 账号（签名时） | 能 | 能 |
| GitHub Actions | 0 | 公开仓库免费 | 仅 GitHub 账号 | 能 | 不能（需 Apple 账号后重签再上传） |

## 2. 当前缺什么

1. **GitHub 账号**：用户先在本机执行 `gh auth login`，之后我们执行 `gh repo create` + push。
2. **Apple 开发者账号**：影响 App ID、App Group、证书、描述文件、TestFlight；没有它只能出未签名包。
3. **真编译验证环境**：Windows 上无法验证 Xcode 版本、Swift 编译错误、Bazel 依赖。
4. **签名方信息**：分发方式、Team ID、证书、UDID（Ad Hoc）；见 `docs/resign-handover.md`。

## 3. workflow 做了什么：三级试跑

文件：`.github/workflows/ios-unsigned.yml`。手动触发时用 `stage` 参数选跑到第几级；
推 `ios-*` 标签则跑完整三级。每级都是独立 job，前一级失败后面不会启动，避免把时间烧在完整编译上。

| 级别 | job | 做什么 | 预估耗时（首次，不含排队） |
|---|---|---|---|
| L1 | `probe` | 只做环境与工程完整性校验：`swift --version`、`xcodebuild -version`、iPhoneOS SDK、`versions.json` 要求对比、关键文件、脚本语法、`.gitmodules`/gitlink、假 profile 数量与 `application-identifier` 匹配 | < 1 分钟（checkout 不拉 submodule） |
| L2 | `prepare` | 拉 submodule（失败按固定 SHA 用 codeload 补拉）、选 Xcode、下载 Bazel 101 MB、生成并校验构建配置、写入 Actions cache | 3-8 分钟 |
| L3 | `build` | Bazel `release_arm64` 完整构建、剥离假签名、组装未签名 IPA / xcarchive / dSYMs | 首次 40-90 分钟，命中 cache 后 10-25 分钟（均为估计） |

> 时间是按 Telegram-iOS 上游 CI 与当前 runner 规格的**估计**，不是实测值。

各步骤说明：

1. `tools/ios/select-xcode.sh` 从 `versions.json` 读要求，在 runner 上挑**能满足要求的最老 Xcode**，
   并写入 `DEVELOPER_DIR`（避开最新 Xcode 的兼容性问题）。
2. `actions/cache` 缓存 `build-input`（Bazel 本体）与 `build/bazel-cache`（Bazel disk cache），
   key 含 `versions.json` 与 `MODULE.bazel.lock` 的哈希。
3. `tools/ios/apply-config.py` 把 `config/teamgram-ios.json` + 本地文件 + Secrets 写成
   `build-system/teamgram-configuration.json`，并替换 `Network.swift` 的 DC、`Telegram/BUILD` 的显示名与
   URL scheme、可选替换 RSA 公钥。L2 会先校验 12 个必需字段，再让 L3 用同一份配置。
4. `Make.py build --configuration=release_arm64` 用仓库自带假证书/profile 构建，产出
   `build-output/Telegram.ipa` 与 `Telegram.DSYMs.zip`。
5. `tools/ios/make-unsigned-artifacts.sh`：
   - 删除 `embedded.mobileprovision`、`_CodeSignature`，对 Mach-O 与 bundle 执行 `codesign --remove-signature`；
   - 把构建期 id `ph.telegra.Telegraph` 改写为交付 id，含扩展/框架后缀与 Watch 伴生键；
   - 产出 `Teamgram-unsigned.ipa`、`<AppName>.xcarchive.zip`、`dSYMs.zip`、`SHA256SUMS.txt`。
6. 上传 artifact，保留 14 天。

### 如果第一级就挂了，通常是什么原因

| 日志里的表现 | 原因 | 怎么改 |
|---|---|---|
| `找不到 iPhoneOS SDK` / `xcodebuild: error` | runner 默认 Xcode 没装完整，或 `xcode-select` 指向 CommandLineTools | 保留 `select-xcode.sh`；必要时把 `runs-on` 改 `macos-14` |
| `Xcode X < versions.json 要求 Y` | 镜像里的 Xcode 太旧 | 换更新的 runner 镜像；或临时把 `versions.json` 的 `xcode` 下调（风险：rules_apple 兼容） |
| `submodule 既没有内容也不是 gitlink` | 仓库从 ZIP 建库时漏了 `160000` gitlink | 按 `docs/repo-setup.md` 的 `git update-index --cacheinfo 160000` 重建 |
| `url 是相对路径 ../xxx.git` | 上游 `.gitmodules` 的相对地址在 GitHub 上无法解析 | 改成 `https://github.com/teamgram/...`（已改 rlottie、tgcalls） |
| `没有 profile 的 application-identifier 等于 C67CF9S4VU.<id>` | 构建期 bundle id 与假 profile 不一致 | 保持 `build_bundle_id=ph.telegra.Telegraph`，交付 id 只用于产物后处理 |
| `假签名 profile 只有 N 个（预期 >= 9）` | 假签名目录被裁剪或 `.gitignore` 误删 | 从上游 `build-system/fake-codesigning` 恢复 |
| `apply-config.py 语法错误` / shell 语法错误 | 脚本被改坏或换行符被改 | 本地 `python3 -m py_compile`、`bash -n` 先过一遍 |

### 成本

公开仓库的 macOS runner **不扣免费分钟，成本为 0**；私有仓库按 **10 倍**分钟计费。
三级拆分的目的不是省钱，而是把失败代价从"几十分钟编译"降到"几十秒校验"。

## 4. 拿到账号后的执行顺序

### 阶段 0：现在就能做（无账号）

1. 本地 `git init` / 提交（见 `docs/repo-setup.md`）。
2. 用户执行 `gh auth login`。
3. 创建公开仓库并 push：
   ```bash
   gh repo create teamgram-ios --public --source=. --remote=origin --push
   ```
4. 在仓库 Settings → Secrets 配置 `TEAMGRAM_API_ID`、`TEAMGRAM_API_HASH`、`TEAMGRAM_DC_IP`（可选 `TEAMGRAM_DC_PORT`）。
5. 先手动触发 `stage=probe`，绿了再 `stage=prepare`，最后 `stage=build`；不要一上来就整包构建。
6. 下载 `Teamgram-unsigned.ipa`；若失败，按第 3 节的分级排查表定位。

### 阶段 1：有 Apple 账号（免费或付费）

1. 注册主 App 与扩展的 App ID，创建 App Group `group.<APP_ID>`。
2. 生成证书与描述文件；免费账号注意 7 天有效期、无 Push/App Groups。
3. 按 `docs/resign-handover.md` 重签（自有 Mac 或第三方签名方）。
4. 装到真机，验证登录页 + 验证码 `12345` + 收发消息。

### 阶段 2：分发（需付费账号）

1. App Store Connect 创建 App 记录（bundle id 与产物一致）。
2. 付费账号 + 分发证书 + App Store 描述文件重签，`xcodebuild -exportArchive` 出分发 IPA。
3. 上传 TestFlight；补齐隐私清单/审核信息。

## 5. 首次构建的风险与压缩手段

| 风险 | 现象 | 缓解 |
|---|---|---|
| Xcode 版本不兼容 | Swift 6 / SDK 报错 | workflow 自动挑最老可用 Xcode；必要时把 `runs-on` 改成 `macos-14` |
| submodule 拉取失败 | 目录为空、Bazel 找不到依赖 | `restore-submodules.sh` 按固定 SHA 用 codeload ZIP 补拉 |
| Bazel 下载慢 | 卡在 `Downloading Bazel` | 缓存 `build-input`；runner 到 GitHub 走内网通常较快 |
| 6 小时超时 | job 被取消 | 首次构建先只编必要 target（见下）；第二次靠 disk cache |
| 缓存超 10 GB | cache 保存失败 | 只缓存 `build-input` + 关键 action，或改用 artifact 传递 |
| 假 profile 与自定义 id 不匹配 | 构建期签名报错 | 构建期固定 `ph.telegra.Telegraph`，产物后处理再改 id（已内置） |

压缩首次构建的可选手段（写在 workflow 注释里，默认未开启）：

- 关闭不需要的 target：`--//Telegram:disableExtensions`（会同时失去 Share/Notification/Widget 等扩展，
  产物不能用于重签交接，只适合验证编译链路）。
- 关闭调试符号/裁剪：上游 BUILD 已有 `--//Telegram:disableStripping` 等开关，需按实际 BUILD 核对。
- 只编 arm64：`--configuration=release_arm64` 已经是单架构，不要改成多架构。

## 6. 明确未验证

1. 未在 macOS 上跑过 `Make.py build`，未确认 Xcode 16/17 能否编译该分支。
2. 未确认 `ph.telegra.Telegraph` + 假 profile 能否与自定义构建配置一起通过 rules_apple 的校验。
3. 未确认 `make-unsigned-artifacts.sh` 的 `codesign --remove-signature`、PlistBuddy 改写、xcarchive 组装
   在真实产物上的行为（脚本只在设计层面检查过）。
4. `apply-config.py` 的 DC / 显示名 / URL scheme / RSA 替换已在本机临时副本上静态跑通（替换数量分别为
   2/2/2/2），但**未在真实 Bazel 构建里验证编译结果**；`probe.sh`、`select-xcode.sh` 只做过 `bash -n`，
   未在 macOS runner 上实际执行。
5. workflow YAML 仅用 PyYAML 做过结构解析（三个 job、依赖关系正确），未在 GitHub 上真正运行过；
   GitHub Actions 的表达式与 job skip 行为仍需首次真跑确认。
6. 未验证真机安装、登录、推送、App Group/keychain 共享。
