# iOS 端改造点清单（对照 Android `feature-trim.md`）

> 状态说明：本文全部结论来自**静态阅读源码**。本机为 Windows，没有 Xcode，**没有任何一条经过真编译或真机验证**。
> 行号基于 `teamgram/teamgram-ios` 分支 `teamgram`（提交 `074a9be3`）的 ZIP 快照，上游更新后可能漂移。
> Android 侧对照文档：`teamgram-android/docs/feature-trim.md`。

## 0. 一句话结论

iOS 侧比 Android 集中得多：**bundle id / api_id / api_hash / URL scheme 已经由一份构建配置 JSON 驱动**，
DC 地址只有一处硬编码，RSA 公钥只有一处数组，显示名在 `Telegram/BUILD` 里。真正分散的是功能入口，
iOS 没有 Android `BuildVars` 那样的全局开关，必须逐个入口改。

## 1. 构建参数类改造点（可集中配置）

统一配置在 `config/teamgram-ios.json`，由 `tools/ios/apply-config.py` 写入/替换；本地真实值放
`config/teamgram-ios.local.json`（已 gitignore），CI 用 GitHub Secrets。

| # | 项目 | iOS 位置 | 当前值 | 目标 | 施加方式 | 验证状态 |
|---|---|---|---|---|---|---|
| 1 | bundle id（主 App） | `build-system/template_minimal_development_configuration.json` 的 `bundle_id`，经 Make.py 生成 `@build_configuration//:variables.bzl`，被 `Telegram/BUILD` 的 `telegram_bundle_id` 引用 | `org.{! random !}.Telegram` 模板占位 | 构建期用 `build_bundle_id`（默认 `ph.telegra.Telegraph`，用于匹配仓库自带假 profile）；交付 id 用 `final_bundle_id`（默认 `com.teamgram.messenger`），构建后重写 | `apply-config.py` 生成 `build-system/teamgram-configuration.json`；后处理脚本改写 Info.plist | 静态确认；未编译 |
| 2 | bundle id（扩展/框架） | `Telegram/BUILD`：`.Share` L1216、`.NotificationContent` L1322、`.Widget` L1427、`.SiriIntents` L1564、`.BroadcastUpload` L1600、`.watchkitapp` L778、`.watchkitapp.watchkitextension` L732；框架 `.MtProtoKit` L827、`.SwiftSignalKit` L868、`.Postbox` L909、`.TelegramApi` L953、`.TelegramCore` L994、`.TelegramUI` L1122 | 全部用 `{telegram_bundle_id}` + 后缀 | 跟随主 id 自动派生 | 无需逐个改；产物后处理会同步重写 | 静态确认；未编译 |
| 3 | 显示名 | `Telegram/BUILD` L1782-1787：`CFBundleDisplayName` / `CFBundleName` | `Teamgram` | `config.app_name` | `apply-config.py` 正则替换 | 静态确认；未编译 |
| 4 | URL scheme | `Telegram/BUILD` L400-425：`CFBundleURLSchemes` 两个数组，L409 = `telegram`，L419 = `tg`；另 `app_specific_url_scheme` 在构建配置 JSON | `telegram` / `tg` | `config.url_schemes`（需同时改构建配置与 Info.plist 两处，脚本已覆盖） | `apply-config.py` 顺序替换两个 `<string>` | 静态确认；未编译 |
| 5 | DC 地址 | `submodules/TelegramCore/Sources/Network/Network.swift` L525-547：`seedAddressList` 两个分支的 `1: ["43.155.11.190"]`（L529、L536）；端口在 L546 的 `MTDatacenterAddress(ip: $0, port: 10443, ...)` | `43.155.11.190:10443`（teamgram 演示服） | `config.dc.ip` / `config.dc.port` | `apply-config.py` 替换 seed 列表 IP + 端口字面量 | 静态确认；未编译 |
| 6 | RSA 公钥 / 指纹 | `submodules/MtProtoKit/Sources/MTDatacenterAuthMessageService.m` L46-75，testing 与 production 两个数组；指纹在 L41 由 `MTRsaFingerprint` 运行时计算 | 两处都已是 teamgram 公钥（模数与 `server_pkcs1.key` 相同，指纹 `0xa9e071c1771060cd`） | 仅在重新生成服务端密钥时才需要换 | `apply-config.py` 的 `rsa_public_key_pem`（可选） | 静态确认模数一致；**未做握手验证** |
| 7 | api_id / api_hash | 构建配置 JSON 的 `api_id` / `api_hash`，经 Make.py 写入 `variables.bzl`，由 `submodules/BuildConfig` 读取 | 模板为占位符 | 与服务端 `config.json` 一致（本机 Android 用 `4` / `014b...`） | CI 从 Secrets 注入；本地从 local.json 注入 | 静态确认；未编译 |
| 8 | team id | 构建配置 JSON 的 `team_id`；假签名 profile 内为 `C67CF9S4VU` | `C67CF9S4VU` | 构建期保持该值以匹配假 profile；交付后由签名方替换 | `apply-config.py` 固定写 `build_team_id` | 静态确认；未编译 |

> 真机注意：iOS **不能用 `10.0.2.2`**（那是 Android 模拟器到宿主机的映射）。真机要用局域网 IP；
> iOS 模拟器在 macOS 上可用 `127.0.0.1`，但本方案不在 Windows 上跑模拟器。

## 2. 功能入口隐藏（已实现）

开关唯一来源：`config/teamgram-ios.json` 的 `features` 段。`tools/ios/apply-config.py` 在构建前做两件事：
`patch_feature_sources` 在**上游 pristine 子模块源码**上打 26 处幂等入口补丁（新串已存在即跳过，
否则按锚点替换并校验命中次数），`patch_feature_flags` 改写
`submodules/TelegramCore/Sources/TeamgramFeatureFlags.swift` 的 5 个布尔值（CI 上该文件原本不存在，
由脚本按模板创建）。Swift 侧所有入口判断都引用这 5 个常量，没有第二处硬编码。

> 为什么必须这样做：`submodules/*` 在 git index 里是 gitlink（mode 160000），本地对子模块内部
> Swift 文件的修改**无法提交**；CI checkout 拿到的是上游代码。补丁写在 `apply-config.py` 里，
> 才能保证 CI 产物和本地一致。本地工作区已经打过补丁时，脚本会全部识别为 skipped。

| config key | Swift 常量 | 仓库默认值 | 关闭后的效果 |
|---|---|---|---|
| `stories` | `storiesEnabled` | `false` | 聊天列表顶部 Stories 栏、资料页发 Story、头像点开 Story、归档入口全部消失 |
| `private_calls` | `callsEnabled` | `false` | 通话 Tab 不加载、资料页语音/视频按钮消失、`requestCall` 兜底为 no-op |
| `group_calls_live` | `groupCallsEnabled` | `false` | 群/频道语音聊天按钮、聊天内群通话面板与入口、直播创建入口消失 |
| `premium_wallet_business` | `walletEnabled` | `false` | 设置页 Premium/Business/Premium Gift、附件菜单 Gift、输入框 Gift 快捷项消失 |
| `channels` | `channelsEnabled` | `false` | Compose「新建频道」入口消失 |

切换方式：只改 `config/teamgram-ios.json` 的布尔值，然后跑
`python3 tools/ios/apply-config.py --patch-sources ...`（CI 的 prepare/build 每次都会自动跑），**不要直接改 Swift**。

### 2.1 逐文件改动（行号为改后当前值）

| 文件 | 行号 | 改了什么 |
|---|---|---|
| `submodules/TelegramCore/Sources/TeamgramFeatureFlags.swift` | 1-15 | 新增：5 个 `Bool` 总开关，默认全 `true`，由脚本改写 |
| `submodules/TelegramUI/Sources/TelegramRootController.swift` | 197、237 | 底部 Tab：`if showCallsTab` → `if showCallsTab && callsEnabled`，通话 Tab 不再 append |
| `submodules/TelegramUI/Sources/AccountContext.swift` | 644 | 兜底：`requestCall` 在关闭私聊通话时直接 `completion()` 返回，任何残留入口都不会发起呼叫 |
| `.../PeerInfo/PeerInfoScreen/Sources/PeerInfoData.swift` | 1883 | `peerInfoHeaderButtons`：私聊「呼叫」按钮加 `callsEnabled` |
| 同上 | 1934、1989 | 群/频道「语音聊天」按钮加 `groupCallsEnabled` |
| `.../PeerInfoScreen/Sources/PeerInfoScreen.swift` | 977 | 设置页 Premium / Business / Premium Gift 三行加 `walletEnabled` |
| 同上 | 1220 | 资料页「最近通话」区块加 `callsEnabled` |
| 同上 | 4527 | 头像不复挂 `openStories`（关闭后头像不再显示 Story 环） |
| 同上 | 4769 | `openStories(fromAvatar:)` 兜底 `guard storiesEnabled else { return }` |
| 同上 | 6067 | 频道「编辑 Stories」管理行加 `storiesEnabled` |
| 同上 | 6817 | `requestCall` 兜底：关闭时 `result?(.dismissWithoutContent)` 并返回，避免菜单卡住 |
| 同上 | 6859 | `scheduleGroupCall` 兜底返回 |
| 同上 | 6866 | `createExternalStream`（直播）兜底返回 |
| 同上 | 6873 | `createAndJoinGroupCall` 兜底返回 |
| 同上 | 7740 | `openStoryArchive` 兜底返回 |
| 同上 | 7795 | `openVoiceChatOptions` 兜底返回（群通话菜单不再弹出） |
| 同上 | 11419、11421 | 资料页右上「发 Story」导航按钮加 `storiesEnabled` |
| `submodules/ChatListUI/Sources/ChatListControllerNode.swift` | 2013 | `shouldDisplayStoriesInChatListHeader` 关闭时直接 `return false`，顶部 Stories 栏/内边距/插入项一处全关 |
| `submodules/ChatListUI/Sources/ChatListController.swift` | 5897 | `isStoryPostingAvailable` 关闭时 `return false`，聊天列表右下角相机/发 Story 入口消失 |
| `submodules/TelegramUI/Sources/ChatController.swift` | 634 | 聊天页群通话顶部面板：关闭时固定 `.none` |
| 同上 | 921 | `case .groupPhoneCall / .inviteToGroupPhoneCall` 兜底 `return true`（吞掉点击） |
| 同上 | 10229 | `joinGroupCall` override 兜底返回 |
| `submodules/TelegramUI/Sources/ChatTextInputPanelNode.swift` | 4599 | 输入框 `SendMessageAction.gift` 加 `walletEnabled` |
| `submodules/TelegramUI/Sources/ChatControllerOpenAttachmentMenu.swift` | 221 | 附件菜单「Gift」按钮加 `walletEnabled` |
| `submodules/TelegramUI/Sources/ChatInterfaceInputContexts.swift` | 186 | 输入框上方 Gift 快捷项加 `walletEnabled` |
| `submodules/TelegramUI/Sources/ComposeControllerNode.swift` | 45-58 | 附加选项改为数组，`channelsEnabled` 为 false 时不 append「新建频道」 |
| `tools/ios/apply-config.py` | 198-559 | 新增 `FEATURE_SOURCE_PATCHES`（26 处幂等补丁）、`ensure_feature_flags_file`、`patch_feature_sources`；`--patch-sources` 时自动执行，CI 与本地共用同一份逻辑 |
| `tools/ios/probe.sh` | 104-133 | 不再把 `TeamgramFeatureFlags.swift` 当必存在文件（CI 上由脚本生成），改为「生成逻辑在位」只 warn |
| `config/teamgram-ios.json` | 21-27 | 5 个 `features` 布尔值全部置 `false`（一键开启只需改回 `true`） |

### 2.2 只隐藏入口、保留底层

- 未删除任何类：`CallListController`、`CallController`、`GroupCallScreen`、`StoryContainerScreen`、
  `CreateChannelController`、`PremiumIntroScreen` 等全部保留，关闭只影响入口装配。
- 已有内容仍可显示：历史通话消息、已存在的 Story、已加入的频道聊天不会因为开关而崩溃或消失。
- 服务端仍是第一道闸：建议同时用 `help.getAppConfig` 不下发 stories/premium 相关配置。

### 2.3 未覆盖面（有意保留）

| 项 | 原因 |
|---|---|
| 来电界面 | 不是「入口」，是被叫；强行拦截会影响已有通话状态机 |
| `t.me` 深链打开的频道 / giftcode | 走 `OpenUrl.swift`，属于外部跳转，未拦 |
| 聊天里已有的通话/礼物/Story 消息 | 内容驱动，不属入口 |
| 频道本身（创建入口已关，但已有频道可读） | iOS 频道与群组 UI 高度复用，删代码风险大于收益 |

### 2.4 静态检查结果（本机 Windows，未编译）

- 12 个改动文件/新增文件全部 `import TelegramCore`（`TeamgramFeatureFlags` 可见）。
- 用原版 ZIP 逐文件 diff 对比：仅上述 guard/条件改动，无其他副作用；`PeerInfoScreen.swift`
  改动前后 `{`/`}` 计数差同为 1（原文件本身即存在字符串内的 `{`），本次新增的 7 组均成对闭合。
- `apply-config.py` 在临时副本实测：`features` 全 true / 全 false 两种配置都能正确改写 5 个常量，且幂等。
- **补丁回放验证**：取上游 ZIP 的 pristine 文件重建一份目录，跑 `patch_feature_sources` 第一次
  26 处全部 `patched`，第二次 26 处全部 `skipped`（无重复插入）；回放结果与本地工作区逐文件
  逐字节一致（仅统一换行符后比较），说明「本地改动」与「CI 补丁」没有漂移。
- `probe.sh` 不再要求 `TeamgramFeatureFlags.swift` 预先存在（CI 上由 apply-config 生成），
  改为检查生成逻辑在位；`python3 -m py_compile apply-config.py`、`bash -n probe.sh` 通过。
- **没有 Swift 编译器**，因此「能编译」这一结论不成立，见第 4 节。

## 3. 与 Android `feature-trim.md` 的对应关系

| Android 项 | Android 做法 | iOS 对应 |
|---|---|---|
| Stories 入口 | `BuildVars` 开关 + 隐藏入口 | `shouldDisplayStoriesInChatListHeader` + `PeerInfoScreen` postStory/openStories |
| 通话 Tab / 呼叫按钮 | 隐藏 Tab + 屏蔽 `VoIPHelper` | `TelegramRootController` 的 `showCallsTab` + `PeerInfoScreen` call 按钮 + `requestCall` |
| 群通话 / 直播 | 隐藏入口 | `PeerInfoScreen.joinGroupCall` + `ChatController.groupPhoneCall` + `groupCallPanelSource` |
| 钱包 / Premium | 隐藏入口 | 无独立 Wallet 模块；`walletEnabled` 关掉设置页 payment 三行 + 附件/输入框 Gift |
| 频道 | 隐藏创建入口 | `ComposeControllerNode` 的「新建频道」项 + `CreateChannelController` 保留不删 |
| DC/RSA/api | `TeamgramConfig.h` 生成 | 构建配置 JSON + `Network.swift` + `MTDatacenterAuthMessageService.m` |

## 4. 明确未验证的部分

1. 第 2 节所有 Swift 改动**没有编译过**（Windows 上没有 Swift 工具链）。已做的是：`import TelegramCore`
   全部存在、与原版 ZIP 逐文件 diff 无多余改动、大括号成对、`apply-config.py` 两面跑通。
2. `TeamgramFeatureFlags` 位于 `TelegramCore`，依赖 TelegramCore 的模块都能看到；但 Swift 的
   `public enum` 跨模块可见性、以及 `-warnings-as-errors` 下是否触发警告，只有真编译才能确认。
3. `PeerInfoScreen.swift` 的 `guard ... result?(.dismissWithoutContent)` 依赖 `ContextMenuActionResult`
   已有该 case（与文件内其他调用一致），但未编译验证类型推断。
4. `isStoryPostingAvailable` 关闭后，聊天列表的相机构图入口是否还有第二条路径（例如 `ComposeController`
   的相机模式）未逐一核对。
5. 假签名 profile 的 `application-identifier` 是 `C67CF9S4VU.ph.telegra.Telegraph`，与自定义 bundle id 不匹配。
   因此 CI 构建期使用 `ph.telegra.Telegraph`，产物后处理再改成 `final_bundle_id`；这一步**未经过真编译验证**。
6. RSA 公钥模数与服务端 `server_pkcs1.key` 一致，但**没有做过一次真实 MTProto 握手**。
7. 没有验证 Xcode 16/17 能否编译 Telegram-iOS 10.12；workflow 会自动挑 runner 上最老的可用 Xcode。
