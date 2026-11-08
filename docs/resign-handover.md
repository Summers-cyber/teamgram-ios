# 重签交接清单（可直接发给签名方）

> 产物由 `.github/workflows/ios-unsigned.yml` 生成：`Teamgram-unsigned.ipa`（已剥离签名与描述文件）、
> `Teamgram.xcarchive.zip`（由 `.app` + dSYM 组装，非 Xcode archive 原生动作）、`dSYMs.zip`。
> **本清单基于静态分析整理，没有经过真机安装或真实重签验证。**

## 1. 交付物

| 文件 | 说明 |
|---|---|
| `Teamgram-unsigned.ipa` | `Payload/*.app` 内已删除 `embedded.mobileprovision`、`_CodeSignature`，并对 Mach-O 执行了 `codesign --remove-signature` |
| `Teamgram.xcarchive.zip` | `Products/Applications/*.app` + `dSYMs/` + `Info.plist`，`SigningIdentity` 与 `Team` 为空 |
| `dSYMs.zip` | 崩溃符号，重签后仍可用（前提是二进制未被裁剪） |
| `SHA256SUMS.txt` | 校验和 |

## 2. Bundle ID 对照表

主 App id 以下记为 `<APP_ID>`（本方案默认 `com.teamgram.messenger`，以最终 `config/teamgram-ios.json` 为准）。

| Target | Bundle ID | 类型 | 备注 |
|---|---|---|---|
| 主 App | `<APP_ID>` | iOS App | 唯一需要推送能力的目标 |
| Share | `<APP_ID>.Share` | App Extension | 分享扩展 |
| Notification Content | `<APP_ID>.NotificationContent` | App Extension | 通知内容扩展 |
| Notification Service | `<APP_ID>.NotificationService` | App Extension | 通知服务扩展（可改推送内容） |
| Widget | `<APP_ID>.Widget` | App Extension | 桌面小组件 |
| Siri Intents | `<APP_ID>.SiriIntents` | App Extension | 快捷指令 |
| Broadcast Upload | `<APP_ID>.BroadcastUpload` | App Extension | 录屏上传扩展 |
| Watch App | `<APP_ID>.watchkitapp` | watchOS App | 若构建时未禁用 Watch |
| Watch Extension | `<APP_ID>.watchkitapp.watchkitextension` | watchOS Extension | 同上 |
| MtProtoKit | `<APP_ID>.MtProtoKit` | Framework | 动态库，需随主包重签 |
| SwiftSignalKit | `<APP_ID>.SwiftSignalKit` | Framework | 同上 |
| Postbox | `<APP_ID>.Postbox` | Framework | 同上 |
| TelegramApi | `<APP_ID>.TelegramApi` | Framework | 同上 |
| TelegramCore | `<APP_ID>.TelegramCore` | Framework | 同上 |
| TelegramUI | `<APP_ID>.TelegramUI` | Framework | 同上 |

> 构建期使用的 id 是 `ph.telegra.Telegraph`（为了匹配仓库自带的假描述文件），
> 产物后处理脚本会把上表全部改写成 `<APP_ID>` 前缀。签名前请用
> `codesign -d --info` / `PlistBuddy` 再核对一次，不要只信本文。

## 3. Entitlements 需求

### 3.1 主 App

| Key | 值 | 必需 | 说明 |
|---|---|---|---|
| `application-identifier` | `<TEAM_ID>.<APP_ID>` | 是 | Xcode 自动生成 |
| `com.apple.developer.team-identifier` | `<TEAM_ID>` | 是 | Xcode 自动生成 |
| `com.apple.security.application-groups` | `group.<APP_ID>` | 是 | 主 App 与所有扩展共享数据；需先在开发者后台注册 App Group |
| `keychain-access-groups` | `<TEAM_ID>.<APP_ID>` | 是 | Telegram 用 keychain 存账号/授权；扩展也要能读同一组 |
| `aps-environment` | `production`（分发）/ `development`（调试） | 是（若要推送） | 上游假 profile 中只有主 App 带此权限 |
| `get-task-allow` | `false`（分发）/ `true`（调试） | 是 | 分发签名必须为 false |
| `beta-reports-active` | `true` | 仅 TestFlight | App Store Connect 分发时加 |
| `com.apple.developer.associated-domains` | 不添加 | 否 | 上游只对官方 bundle id 启用 |
| `com.apple.developer.icloud-*` | 不添加 | 否 | 构建配置 `enable_icloud=false` |
| `com.apple.developer.siri` | 不添加 | 否 | 构建配置 `enable_siri=false` |

### 3.2 扩展

| Target | App Group | keychain-access-groups | aps-environment |
|---|---|---|---|
| Share | `group.<APP_ID>` | `<TEAM_ID>.<APP_ID>` | 不需要 |
| NotificationContent | `group.<APP_ID>` | `<TEAM_ID>.<APP_ID>` | 不需要 |
| NotificationService | `group.<APP_ID>` | `<TEAM_ID>.<APP_ID>` | 不需要（推送由主 App 接收） |
| Widget | `group.<APP_ID>` | `<TEAM_ID>.<APP_ID>` | 不需要 |
| SiriIntents | `group.<APP_ID>` | `<TEAM_ID>.<APP_ID>` | 不需要 |
| BroadcastUpload | `group.<APP_ID>` | `<TEAM_ID>.<APP_ID>` | 不需要 |
| WatchApp / WatchExtension | `group.<APP_ID>` | `<TEAM_ID>.<APP_ID>` | 不需要 |

> 上游假 profile 对扩展只给了 App Group（`group.ph.telegra.Telegraph`）和通配 keychain（`C67CF9S4VU.*`），
> 没有 aps-environment。给扩展显式加 `<TEAM_ID>.<APP_ID>` 的 keychain 组是为了让 `BuildConfig`
> 能解析出主 App 的 bundle id；如果签名方使用通配 keychain 组（`<TEAM_ID>.*`），也可行，但 App Store
> 分发通常要求显式 App ID，建议按上表逐项配置。

## 4. 签名顺序（务必由内到外）

1. 解压 `Teamgram-unsigned.ipa`，得到 `Payload/<App>.app`。
2. 逐个替换 `Payload/**/embedded.mobileprovision`（主 App + 每个 appex + Watch）。
3. 先签 **Frameworks**：`Frameworks/*.framework` 内的可执行文件与 framework 目录本身。
4. 再签 **App Extensions**（`.appex`）、**Watch Extension**、**Watch App**。
5. 最后签 **主 App**。
6. 重新压缩为 IPA（`Payload` 必须在 zip 根目录），或直接做 `xcodebuild -exportArchive`。

参考命令（`<BUNDLE>`、`<ENTITLEMENTS>` 按上表替换）：

```bash
codesign --force --timestamp --sign "<证书名>" \
  --entitlements "<BUNDLE>.entitlements" "<BUNDLE>"

codesign --verify --deep --strict --verbose=2 Payload/<App>.app
codesign -d --entitlements :- Payload/<App>.app
```

## 5. 重签前必须向签名方确认

- [ ] 分发方式：Ad Hoc / Enterprise / TestFlight / App Store
- [ ] Team ID 与证书类型（Apple Distribution / Enterprise / Development）
- [ ] 上表所有 App ID 是否已在开发者后台注册（至少主 App + 5 个常用扩展 + 2 个 Watch target）
- [ ] App Group `group.<APP_ID>` 是否已创建，并勾选到所有 target
- [ ] 推送：是否有 APNs 证书/密钥；teamgram 服务端当前**没有配置 APNs**，没有的话建议签名时保留
      `aps-environment` 但接受推送注册失败，或从主 App entitlements 移除该项
- [ ] Ad Hoc 需要收集设备 UDID
- [ ] 是否保留 Watch target；不需要的话构建时加 `--//Telegram:disableExtensions` 之外的 Watch 裁剪（未验证）
- [ ] 重签后 bundle id 是否允许与构建期不同（本产物已改写，签名方直接按最终 id 建 profile 即可）

## 6. 装包后验证清单

1. 能安装、能启动，不闪退（重点检查 `Frameworks` 是否全部重签）。
2. 进入登录页，输入手机号能收到服务端验证码（本机 teamgram 测试环境验证码固定 `12345`）。
3. 登录后能收发消息、下拉刷新、切换会话。
4. 分享扩展、通知扩展能被系统调起（App Group 是否正确）。
5. 如果启用了推送：确认主 App entitlements 的 `aps-environment` 与描述文件一致。
6. 检查 `Console.app` 是否有 `keychain` / `app group` 相关报错。

## 7. 已知风险

- 本产物是用 Bazel + 假证书构建后**剥离签名**得到的，不是 Xcode 原生 `archive`；个别签名工具可能要求
  存在原始 `_CodeSignature` 结构。若遇到，改用一条 Mac 上的 `xcodebuild archive CODE_SIGNING_ALLOWED=NO`
  路线重新出包（见 `ios-build-plan.md`）。
- 产物中的二进制未做 bitcode/裁剪处理；dSYM 与二进制必须成对使用。
- 所有 bundle id、entitlements 结论均为静态整理，**未在真机上验证过**。
