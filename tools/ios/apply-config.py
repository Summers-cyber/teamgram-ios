#!/usr/bin/env python3
"""把 config/teamgram-ios.json（可叠加本地/环境变量）应用到 iOS 工程。

只做文本替换，不依赖 Mac 环境，可在 Windows / Linux / macOS 上运行。
所有改动都是静态的，未经过真机或真编译验证。
"""

import argparse
import copy
import json
import os
import re
import sys

EXTENSION_SUFFIXES = [
    ".Share",
    ".NotificationContent",
    ".NotificationService",
    ".Widget",
    ".SiriIntents",
    ".BroadcastUpload",
    ".watchkitapp",
    ".watchkitapp.watchkitextension",
]

FRAMEWORK_SUFFIXES = [
    ".MtProtoKit",
    ".SwiftSignalKit",
    ".Postbox",
    ".TelegramApi",
    ".TelegramCore",
    ".TelegramUI",
]


def deep_merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def read_json(path):
    # utf-8-sig 兼容 Windows 记事本保存的带 BOM 的 JSON
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path, payload):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def env_overrides():
    result = {}
    mapping = {
        "TEAMGRAM_API_ID": ("api_id", int),
        "TEAMGRAM_API_HASH": ("api_hash", str),
        "TEAMGRAM_APP_NAME": ("app_name", str),
        "TEAMGRAM_FINAL_BUNDLE_ID": ("final_bundle_id", str),
        "TEAMGRAM_URL_SCHEME": ("_primary_url_scheme", str),
    }
    for name, (key, caster) in mapping.items():
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        result[key] = caster(raw)
    dc_ip = os.environ.get("TEAMGRAM_DC_IP", "").strip()
    if dc_ip:
        result.setdefault("dc", {})["ip"] = dc_ip
    dc_port = os.environ.get("TEAMGRAM_DC_PORT", "").strip()
    if dc_port:
        result.setdefault("dc", {})["port"] = int(dc_port)
    return result


def patch_network(repo_root, dc):
    path = os.path.join(repo_root, "submodules/TelegramCore/Sources/Network/Network.swift")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    # 源码结构：seedAddressList = [1: ["43.155.11.190"]]，地址在 L529/L536，
    # 端口在 L546 的 MTDatacenterAddress(ip: $0, port: 10443, ...)。
    ip_pattern = re.compile(r'(?m)^(\s*\d+:\s*\[)"[^"]*"')
    text, ip_count = ip_pattern.subn(lambda match: match.group(1) + '"%s"' % dc["ip"], text)
    if ip_count < 2:
        raise RuntimeError("Network.swift 中只找到 %d 处 seedAddressList IP，预期至少 2 处" % ip_count)

    port_pattern = re.compile(r'MTDatacenterAddress\(ip: \$0, port: \d+')
    text, port_count = port_pattern.subn(
        'MTDatacenterAddress(ip: $0, port: %d' % int(dc["port"]), text
    )
    if port_count < 1:
        raise RuntimeError("Network.swift 中没有找到 MTDatacenterAddress(ip: $0, port: ...)")

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return {"ip": ip_count, "port": port_count}


def patch_display_name(repo_root, app_name):
    path = os.path.join(repo_root, "Telegram/BUILD")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    # BUILD 里各扩展/watch target 也有 CFBundleName，不能全文件替换。
    # 主 App 的 Info.plist 片段特征是：DisplayName 之后紧跟
    # CFBundleIdentifier = {telegram_bundle_id}，再跟 CFBundleName。
    pattern = re.compile(
        r"(<key>CFBundleDisplayName</key>\s*<string>)[^<]*(</string>"
        r"\s*<key>CFBundleIdentifier</key>\s*<string>\{telegram_bundle_id\}</string>"
        r"\s*<key>CFBundleName</key>\s*<string>)[^<]*(</string>)"
    )

    def replace(match):
        return match.group(1) + app_name + match.group(2) + app_name + match.group(3)

    text, count = pattern.subn(replace, text)
    if count != 1:
        raise RuntimeError("Telegram/BUILD 中主 App 显示名片段匹配 %d 处，预期 1 处" % count)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return count * 2


def patch_url_schemes(repo_root, schemes):
    path = os.path.join(repo_root, "Telegram/BUILD")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    block_pattern = re.compile(
        r"(<key>CFBundleURLSchemes</key>\s*<array>\s*<string>)[^<]*(</string>)"
    )
    matches = block_pattern.findall(text)
    if len(matches) < 2:
        raise RuntimeError("Telegram/BUILD 中 CFBundleURLSchemes 少于 2 处")
    if len(schemes) < len(matches):
        raise RuntimeError(
            "url_schemes 只有 %d 个，但 BUILD 里有 %d 处 URL scheme（主 scheme + 兼容 scheme）"
            % (len(schemes), len(matches))
        )
    index = {"value": 0}

    def replace(match):
        scheme = schemes[index["value"]]
        index["value"] += 1
        return match.group(1) + scheme + match.group(2)

    text = block_pattern.sub(replace, text)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return len(matches)


def patch_rsa_key(repo_root, pem):
    path = os.path.join(repo_root, "submodules/MtProtoKit/Sources/MTDatacenterAuthMessageService.m")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    body = []
    for line in pem.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("-----"):
            continue
        body.append(line)
    if not body:
        raise RuntimeError("rsa_public_key_pem 内容为空")
    payload = "".join(body)
    chunks = [payload[i:i + 64] for i in range(0, len(payload), 64)]
    literal_lines = ['@"-----BEGIN RSA PUBLIC KEY-----\\n"']
    literal_lines.extend('"%s\\n"' % chunk for chunk in chunks)
    literal_lines.append('"-----END RSA PUBLIC KEY-----"')
    replacement = "\n             ".join(literal_lines)

    pattern = re.compile(
        r'@"-----BEGIN RSA PUBLIC KEY-----\\n".*?"-----END RSA PUBLIC KEY-----"',
        re.DOTALL,
    )
    text, count = pattern.subn(lambda _: replacement, text)
    if count < 2:
        raise RuntimeError("MTDatacenterAuthMessageService.m 中只替换了 %d 处公钥，预期 2 处" % count)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return count


FEATURE_FLAGS = {
    "stories": "storiesEnabled",
    "private_calls": "callsEnabled",
    "group_calls_live": "groupCallsEnabled",
    "premium_wallet_business": "walletEnabled",
    "channels": "channelsEnabled",
}

FEATURE_FLAGS_FILE = "submodules/TelegramCore/Sources/TeamgramFeatureFlags.swift"

# 子模块是 gitlink，CI 拿到的是上游 pristine 代码，本地改动不会随仓库发布。
# 所以入口隐藏必须在这里以「幂等文本补丁」的形式存在：already-new 就跳过，
# 否则按 pristine 锚点替换并校验命中次数。old 全部取自上游 zip 快照。
FEATURE_SOURCE_PATCHES = [
    # 底部 Tab：通话 Tab
    {
        "file": "submodules/TelegramUI/Sources/TelegramRootController.swift",
        "old": "if showCallsTab {",
        "new": "if showCallsTab && TeamgramFeatureFlags.callsEnabled {",
        "count": 2,
    },
    # 兜底：任何残留的通话入口调用到这里都会变成 no-op
    {
        "file": "submodules/TelegramUI/Sources/AccountContext.swift",
        "old": "public func requestCall(peerId: PeerId, isVideo: Bool, completion: @escaping () -> Void) {\n",
        "new": (
            "public func requestCall(peerId: PeerId, isVideo: Bool, completion: @escaping () -> Void) {\n"
            "        guard TeamgramFeatureFlags.callsEnabled else {\n"
            "            completion()\n"
            "            return\n"
            "        }\n"
        ),
        "count": 1,
    },
    # 个人页：私聊呼叫 / 语音聊天按钮
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoData.swift",
        "old": "if callsAvailable {",
        "new": "if TeamgramFeatureFlags.callsEnabled && callsAvailable {",
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoData.swift",
        "old": "if hasVoiceChat || canStartVoiceChat {",
        "new": "if TeamgramFeatureFlags.groupCallsEnabled && (hasVoiceChat || canStartVoiceChat) {",
        "count": 2,
    },
    # 个人页：钱包 / Premium / 最近通话 / Stories
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "if !premiumConfiguration.isPremiumDisabled {",
        "new": "if TeamgramFeatureFlags.walletEnabled && !premiumConfiguration.isPremiumDisabled {",
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "if !callMessages.isEmpty {",
        "new": "if TeamgramFeatureFlags.callsEnabled && !callMessages.isEmpty {",
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "if self.headerNode.avatarListNode.openStories == nil {",
        "new": "if TeamgramFeatureFlags.storiesEnabled && self.headerNode.avatarListNode.openStories == nil {",
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "private func openStories(fromAvatar: Bool) {\n",
        "new": (
            "private func openStories(fromAvatar: Bool) {\n"
            "        guard TeamgramFeatureFlags.storiesEnabled else {\n"
            "            return\n"
            "        }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "if channel.hasPermission(.editStories) {",
        "new": "if TeamgramFeatureFlags.storiesEnabled && channel.hasPermission(.editStories) {",
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": (
            "private func requestCall(isVideo: Bool, gesture: ContextGesture? = nil, "
            "contextController: ContextControllerProtocol? = nil, result: ((ContextMenuActionResult) -> Void)? = nil, "
            "backAction: ((ContextControllerProtocol) -> Void)? = nil) {\n"
        ),
        "new": (
            "private func requestCall(isVideo: Bool, gesture: ContextGesture? = nil, "
            "contextController: ContextControllerProtocol? = nil, result: ((ContextMenuActionResult) -> Void)? = nil, "
            "backAction: ((ContextControllerProtocol) -> Void)? = nil) {\n"
            "        guard TeamgramFeatureFlags.callsEnabled || TeamgramFeatureFlags.groupCallsEnabled else {\n"
            "            result?(.dismissWithoutContent)\n"
            "            return\n"
            "        }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "private func scheduleGroupCall() {\n",
        "new": (
            "private func scheduleGroupCall() {\n"
            "        guard TeamgramFeatureFlags.groupCallsEnabled else {\n"
            "            return\n"
            "        }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "private func createExternalStream(credentialsPromise: Promise<GroupCallStreamCredentials>?) {\n",
        "new": (
            "private func createExternalStream(credentialsPromise: Promise<GroupCallStreamCredentials>?) {\n"
            "        guard TeamgramFeatureFlags.groupCallsEnabled else {\n"
            "            return\n"
            "        }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "private func createAndJoinGroupCall(peerId: PeerId, joinAsPeerId: PeerId?) {\n",
        "new": (
            "private func createAndJoinGroupCall(peerId: PeerId, joinAsPeerId: PeerId?) {\n"
            "        guard TeamgramFeatureFlags.groupCallsEnabled else {\n"
            "            return\n"
            "        }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "private func openStoryArchive() {\n",
        "new": (
            "private func openStoryArchive() {\n"
            "        guard TeamgramFeatureFlags.storiesEnabled else {\n"
            "            return\n"
            "        }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": (
            "private func openVoiceChatOptions(defaultJoinAsPeerId: PeerId?, gesture: ContextGesture? = nil, "
            "contextController: ContextControllerProtocol? = nil) {\n"
        ),
        "new": (
            "private func openVoiceChatOptions(defaultJoinAsPeerId: PeerId?, gesture: ContextGesture? = nil, "
            "contextController: ContextControllerProtocol? = nil) {\n"
            "        guard TeamgramFeatureFlags.groupCallsEnabled else {\n"
            "            return\n"
            "        }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": "if let data = self.data, !data.isPremiumRequiredForStoryPosting",
        "new": "if TeamgramFeatureFlags.storiesEnabled, let data = self.data, !data.isPremiumRequiredForStoryPosting",
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoScreen.swift",
        "old": (
            "                } else if self.isMyProfile {\n"
            "                    rightNavigationButtons.insert(PeerInfoHeaderNavigationButtonSpec(key: .postStory, isForExpandedView: false), at: 0)\n"
        ),
        "new": (
            "                } else if TeamgramFeatureFlags.storiesEnabled && self.isMyProfile {\n"
            "                    rightNavigationButtons.insert(PeerInfoHeaderNavigationButtonSpec(key: .postStory, isForExpandedView: false), at: 0)\n"
        ),
        "count": 1,
    },
    # 会话列表：顶部 Stories 栏 / 右下角发 Story
    {
        "file": "submodules/ChatListUI/Sources/ChatListControllerNode.swift",
        "old": "func shouldDisplayStoriesInChatListHeader(storySubscriptions: EngineStorySubscriptions, isHidden: Bool) -> Bool {\n",
        "new": (
            "func shouldDisplayStoriesInChatListHeader(storySubscriptions: EngineStorySubscriptions, isHidden: Bool) -> Bool {\n"
            "    if !TeamgramFeatureFlags.storiesEnabled {\n"
            "        return false\n"
            "    }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/ChatListUI/Sources/ChatListController.swift",
        "old": "    var isStoryPostingAvailable: Bool {\n",
        "new": (
            "    var isStoryPostingAvailable: Bool {\n"
            "        if !TeamgramFeatureFlags.storiesEnabled {\n"
            "            return false\n"
            "        }\n"
        ),
        "count": 1,
    },
    # 聊天页：群通话面板 / 群通话消息 / 加入群通话
    {
        "file": "submodules/TelegramUI/Sources/ChatController.swift",
        "old": "groupCallPanelSource = .peer(peerId)",
        "new": "groupCallPanelSource = TeamgramFeatureFlags.groupCallsEnabled ? .peer(peerId) : .none",
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Sources/ChatController.swift",
        "old": "                        case .groupPhoneCall, .inviteToGroupPhoneCall:\n",
        "new": (
            "                        case .groupPhoneCall, .inviteToGroupPhoneCall:\n"
            "                            guard TeamgramFeatureFlags.groupCallsEnabled else {\n"
            "                                return true\n"
            "                            }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Sources/ChatController.swift",
        "old": "public override func joinGroupCall(peerId: PeerId, invite: String?, activeCall: EngineGroupCallDescription) {\n",
        "new": (
            "public override func joinGroupCall(peerId: PeerId, invite: String?, activeCall: EngineGroupCallDescription) {\n"
            "        guard TeamgramFeatureFlags.groupCallsEnabled else {\n"
            "            return\n"
            "        }\n"
        ),
        "count": 1,
    },
    # 聊天页：礼物入口（钱包）
    {
        "file": "submodules/TelegramUI/Sources/ChatTextInputPanelNode.swift",
        "old": (
            "                case .gift:\n"
            "                    self.interfaceInteraction?.openPremiumGift()\n"
        ),
        "new": (
            "                case .gift:\n"
            "                    if TeamgramFeatureFlags.walletEnabled {\n"
            "                        self.interfaceInteraction?.openPremiumGift()\n"
            "                    }\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Sources/ChatControllerOpenAttachmentMenu.swift",
        "old": (
            "            if !premiumGiftOptions.isEmpty {\n"
            "                buttons.insert(.gift, at: 1)\n"
        ),
        "new": (
            "            if TeamgramFeatureFlags.walletEnabled && !premiumGiftOptions.isEmpty {\n"
            "                buttons.insert(.gift, at: 1)\n"
        ),
        "count": 1,
    },
    {
        "file": "submodules/TelegramUI/Sources/ChatInterfaceInputContexts.swift",
        "old": "if isTextEmpty, showPremiumGift, let peer",
        "new": "if TeamgramFeatureFlags.walletEnabled, isTextEmpty, showPremiumGift, let peer",
        "count": 1,
    },
    # 新建会话：频道入口
    {
        "file": "submodules/TelegramUI/Sources/ComposeControllerNode.swift",
        "old": (
            "        self.contactListNode = ContactListNode(context: context, presentation: .single(.natural(options: [\n"
            "            ContactListAdditionalOption(title: self.presentationData.strings.Compose_NewGroup, icon: .generic(UIImage(bundleImageName: \"Contact List/CreateGroupActionIcon\")!), action: {\n"
            "                openCreateNewGroupImpl?()\n"
            "            }),\n"
            "            ContactListAdditionalOption(title: self.presentationData.strings.NewContact_Title, icon: .generic(UIImage(bundleImageName: \"Contact List/AddMemberIcon\")!), action: {\n"
            "                openCreateContactImpl?()\n"
            "            }),\n"
            "            ContactListAdditionalOption(title: self.presentationData.strings.Compose_NewChannel, icon: .generic(UIImage(bundleImageName: \"Contact List/CreateChannelActionIcon\")!), action: {\n"
            "                openCreateNewChannelImpl?()\n"
            "            })\n"
            "        ], includeChatList: false, topPeers: .none)), onlyWriteable: false, isGroupInvitation: false, displayPermissionPlaceholder: false)\n"
        ),
        "new": (
            "        var additionalOptions: [ContactListAdditionalOption] = [\n"
            "            ContactListAdditionalOption(title: self.presentationData.strings.Compose_NewGroup, icon: .generic(UIImage(bundleImageName: \"Contact List/CreateGroupActionIcon\")!), action: {\n"
            "                openCreateNewGroupImpl?()\n"
            "            }),\n"
            "            ContactListAdditionalOption(title: self.presentationData.strings.NewContact_Title, icon: .generic(UIImage(bundleImageName: \"Contact List/AddMemberIcon\")!), action: {\n"
            "                openCreateContactImpl?()\n"
            "            })\n"
            "        ]\n"
            "        if TeamgramFeatureFlags.channelsEnabled {\n"
            "            additionalOptions.append(ContactListAdditionalOption(title: self.presentationData.strings.Compose_NewChannel, icon: .generic(UIImage(bundleImageName: \"Contact List/CreateChannelActionIcon\")!), action: {\n"
            "                openCreateNewChannelImpl?()\n"
            "            }))\n"
            "        }\n"
            "        \n"
            "        self.contactListNode = ContactListNode(context: context, presentation: .single(.natural(options: additionalOptions, includeChatList: false, topPeers: .none)), onlyWriteable: false, isGroupInvitation: false, displayPermissionPlaceholder: false)\n"
        ),
        "count": 1,
    },
]

FEATURE_FLAGS_TEMPLATE = """import Foundation

/// 功能入口总开关。
///
/// 值的唯一来源是 `config/teamgram-ios.json` 的 `features` 段，由
/// `tools/ios/apply-config.py` 在构建前改写；**不要手工修改本文件**。
/// 这里只控制入口是否展示，底层实现类全部保留，关闭后不会影响已存在的会话。
public enum TeamgramFeatureFlags {
    public static let storiesEnabled: Bool = true
    public static let callsEnabled: Bool = true
    public static let groupCallsEnabled: Bool = true
    public static let walletEnabled: Bool = true
    public static let channelsEnabled: Bool = true
}
"""


def ensure_feature_flags_file(repo_root):
    """CI 上的子模块是上游 pristine 代码，没有这个新文件，需要先落盘再改写布尔值。"""
    path = os.path.join(repo_root, FEATURE_FLAGS_FILE)
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(FEATURE_FLAGS_TEMPLATE)
    return True


XCODE16_COMPAT_FILES = (
    "submodules/MtProtoKit/Sources/PingFoundation.h",
    "submodules/MtProtoKit/Sources/PingFoundation.m",
)
XCODE16_ENCODE_FILE = "submodules/Postbox/Sources/Utils/Encoder/AdaptedPostboxUnkeyedEncodingContainer.swift"
XCODE16_RETROACTIVE = (
    ("submodules/Display/Source/KeyShortcut.swift", "extension UIKeyModifierFlags: Hashable {", "extension UIKeyModifierFlags: @retroactive Hashable {"),
    ("submodules/LocationUI/Sources/LocationUtils.swift", "extension CLLocationCoordinate2D: Equatable {", "extension CLLocationCoordinate2D: @retroactive Equatable {"),
)


def patch_xcode16_compat(repo_root):
    """Xcode 16 工具链的两处兼容改动：sa_family_t 不再隐式可见；Swift 6 要求 Data 编码方法私有化。"""
    changed = []
    for relative in XCODE16_COMPAT_FILES:
        path = os.path.join(repo_root, relative)
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        text, count = re.subn(r"\bsa_family_t\b", "uint8_t", text)
        if count == 0:
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        changed.append({"file": relative, "count": count})

    path = os.path.join(repo_root, XCODE16_ENCODE_FILE)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    old = "    func encode(_ value: Data) throws {"
    new = "    private func encode(_ value: Data) throws {"
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError("Data 编码方法 %d 处，预期 1 处" % text.count(old))
        text = text.replace(old, new, 1)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        changed.append({"file": XCODE16_ENCODE_FILE, "count": 1})

    for relative, old, new in XCODE16_RETROACTIVE:
        path = os.path.join(repo_root, relative)
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if new in text:
            continue
        if text.count(old) != 1:
            raise RuntimeError("%s 中 retroactive 锚点 %d 处，预期 1 处" % (relative, text.count(old)))
        text = text.replace(old, new, 1)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        changed.append({"file": relative, "count": 1})
    return changed if changed else "skipped"


def patch_feature_flags(repo_root, features):
    """把 config 的 features 段写进 TelegramCore 的总开关，默认全开（缺字段不关）。"""
    path = os.path.join(repo_root, FEATURE_FLAGS_FILE)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    result = {}
    for key, name in FEATURE_FLAGS.items():
        enabled = bool(features.get(key, True))
        result[key] = enabled
        pattern = re.compile(r"(public static let %s: Bool = )(true|false)" % name)
        text, count = pattern.subn(lambda match: match.group(1) + ("true" if enabled else "false"), text)
        if count != 1:
            raise RuntimeError("TeamgramFeatureFlags.swift 中 %s 匹配 %d 处，预期 1 处" % (name, count))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return result


def patch_feature_sources(repo_root):
    """在 pristine 子模块源码上打入口隐藏补丁；已打过（新串存在）则跳过，可重复执行。"""
    result = []
    for patch in FEATURE_SOURCE_PATCHES:
        path = os.path.join(repo_root, patch["file"])
        if not os.path.exists(path):
            raise RuntimeError("缺少待打补丁的源文件: %s" % patch["file"])
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        expected = int(patch.get("count", 1))
        if patch["new"] in text:
            result.append({"file": patch["file"], "state": "skipped"})
            continue
        occurrences = text.count(patch["old"])
        if occurrences != expected:
            raise RuntimeError(
                "%s 中锚点匹配 %d 处，预期 %d 处（上游可能已改代码）"
                % (patch["file"], occurrences, expected)
            )
        text = text.replace(patch["old"], patch["new"])
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        result.append({"file": patch["file"], "state": "patched", "count": occurrences})
    return result


def build_configuration(config):
    schemes = config.get("url_schemes") or ["tg"]
    return {
        "bundle_id": config["build_bundle_id"],
        "api_id": str(config.get("api_id", 0)),
        "api_hash": config.get("api_hash", ""),
        "team_id": config["build_team_id"],
        "app_center_id": str(config.get("app_center_id", "0")),
        "is_internal_build": "true",
        "is_appstore_build": "false",
        "appstore_id": "0",
        "app_specific_url_scheme": schemes[0],
        "premium_iap_product_id": "",
        "enable_siri": False,
        "enable_icloud": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="config/teamgram-ios.json")
    parser.add_argument("--local", default="config/teamgram-ios.local.json")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--build-config-out", default="build-system/teamgram-configuration.json")
    parser.add_argument("--resolved-out", default="build/teamgram-resolved.json")
    parser.add_argument("--patch-sources", action="store_true")
    parser.add_argument("--env", action="store_true")
    args = parser.parse_args()

    config = read_json(args.base)
    if args.local and os.path.exists(args.local):
        print("使用本地配置: %s" % args.local)
        config = deep_merge(config, read_json(args.local))
    if args.env:
        config = deep_merge(config, env_overrides())
    if config.get("_primary_url_scheme"):
        config["url_schemes"] = [config["_primary_url_scheme"]] + list(config.get("url_schemes") or [])[1:]
        config.pop("_primary_url_scheme", None)

    if args.patch_sources:
        patched = {}
        patched["dc"] = patch_network(args.repo_root, config["dc"])
        patched["xcode16_compat"] = patch_xcode16_compat(args.repo_root)
        patched["name"] = patch_display_name(args.repo_root, config["app_name"])
        patched["schemes"] = patch_url_schemes(args.repo_root, config["url_schemes"])
        patched["feature_flags_file"] = "created" if ensure_feature_flags_file(args.repo_root) else "exists"
        patched["feature_sources"] = patch_feature_sources(args.repo_root)
        patched["features"] = patch_feature_flags(args.repo_root, config.get("features") or {})
        if config.get("rsa_public_key_pem"):
            patched["rsa"] = patch_rsa_key(args.repo_root, config["rsa_public_key_pem"])
        print("已修改源文件: %s" % json.dumps(patched, ensure_ascii=False))

    build_config = build_configuration(config)
    write_json(args.build_config_out, build_config)

    resolved = {
        "final_bundle_id": config["final_bundle_id"],
        "app_name": config["app_name"],
        "url_schemes": config["url_schemes"],
        "extension_suffixes": EXTENSION_SUFFIXES,
        "framework_suffixes": FRAMEWORK_SUFFIXES,
        "features": config.get("features", {}),
        "api_id_set": int(config.get("api_id", 0)) > 0,
        "api_hash_set": bool(config.get("api_hash")),
    }
    write_json(args.resolved_out, resolved)

    print("构建用 bundle id: %s" % build_config["bundle_id"])
    print("交付用 bundle id: %s" % resolved["final_bundle_id"])
    print("显示名: %s" % resolved["app_name"])
    print("DC: %s:%s" % (config["dc"]["ip"], config["dc"]["port"]))
    if not resolved["api_id_set"] or not resolved["api_hash_set"]:
        print("警告: api_id/api_hash 未设置，编译可以完成，但产物无法登录任何服务端。")
    if config["final_bundle_id"] == config["build_bundle_id"]:
        print("提示: build_bundle_id 与 final_bundle_id 相同，将跳过产物重命名。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001
        print("失败: %s" % error, file=sys.stderr)
        sys.exit(1)
