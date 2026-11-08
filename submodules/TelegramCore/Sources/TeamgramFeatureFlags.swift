import Foundation

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
