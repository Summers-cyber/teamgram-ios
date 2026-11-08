load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive", "http_file")

http_archive(
    name = "bazel_features",
    sha256 = "0f23d75c7623d6dba1fd30513a94860447de87c8824570521fcc966eda3151c2",
    strip_prefix = "bazel_features-1.4.1",
    url = "https://github.com/bazel-contrib/bazel_features/archive/refs/tags/v1.4.1.tar.gz",
)

# 预声明 bazel_skylib，走 GitHub archive（带 .tar.gz 后缀）而非 releases CDN，
# 避免 rules_* 依赖里 GitHub release 资产的 504；后续 _maybe 声明会因已存在而跳过。
http_archive(
    name = "bazel_skylib",
    sha256 = "de9d2cedea7103d20c93a5cc7763099728206bd5088342d0009315913a592cc0",
    strip_prefix = "bazel-skylib-1.4.2",
    url = "https://github.com/bazelbuild/bazel-skylib/archive/refs/tags/1.4.2.tar.gz",
)

# rules_swift 的 swift_runner 硬依赖 index-import（只在 index_while_building_v2 时使用），
# 但仓库声明阶段就会去 GitHub releases 拉；预声明成 mirror.bazel.build 优先，绕开 504。
http_archive(
    name = "build_bazel_rules_swift_index_import",
    build_file = "@build_bazel_rules_swift//third_party:build_bazel_rules_swift_index_import/BUILD.overlay",
    canonical_id = "index-import-5.8",
    sha256 = "28c1ffa39d99e74ed70623899b207b41f79214c498c603915aef55972a851a15",
    urls = [
        "https://mirror.bazel.build/github.com/MobileNativeFoundation/index-import/releases/download/5.8.0.1/index-import.tar.gz",
        "https://github.com/MobileNativeFoundation/index-import/releases/download/5.8.0.1/index-import.tar.gz",
    ],
)

local_repository(
    name = "rules_xcodeproj",
    path = "build-system/bazel-rules/rules_xcodeproj",
)

local_repository(
    name = "build_bazel_rules_apple",
    path = "build-system/bazel-rules/rules_apple",
)

local_repository(
    name = "build_bazel_rules_swift",
    path = "build-system/bazel-rules/rules_swift",
)

local_repository(
    name = "build_bazel_apple_support",
    path = "build-system/bazel-rules/apple_support",
)

http_file(
    name = "cmake_tar_gz",
    urls = [
        "https://cmake.org/files/v3.23/cmake-3.23.1-macos-universal.tar.gz",
        "https://github.com/Kitware/CMake/releases/download/v3.23.1/cmake-3.23.1-macos-universal.tar.gz",
    ],
    sha256 = "f794ed92ccb4e9b6619a77328f313497d7decf8fb7e047ba35a348b838e0e1e2",
)

http_archive(
    name = "appcenter_sdk",
    urls = ["https://github.com/microsoft/appcenter-sdk-apple/releases/download/4.1.1/AppCenter-SDK-Apple-4.1.1.zip"],
    sha256 = "032907801dc7784744a1ca8fd40d3eecc34a2e27a93a4b3993f617cca204a9f3",
    build_file = "@//third-party/AppCenter:AppCenter.BUILD",
)

load(
    "@rules_xcodeproj//xcodeproj:repositories.bzl",
    "xcodeproj_rules_dependencies",
)

xcodeproj_rules_dependencies()

load("@bazel_features//:deps.bzl", "bazel_features_deps")

bazel_features_deps()

load(
    "@build_bazel_rules_apple//apple:repositories.bzl",
    "apple_rules_dependencies",
)

apple_rules_dependencies()

load(
    "@build_bazel_rules_swift//swift:repositories.bzl",
    "swift_rules_dependencies",
)

swift_rules_dependencies()

load(
    "@build_bazel_rules_swift//swift:extras.bzl",
    "swift_rules_extra_dependencies",
)

swift_rules_extra_dependencies()

load(
    "@build_bazel_apple_support//lib:repositories.bzl",
    "apple_support_dependencies",
)

apple_support_dependencies()

load("@bazel_skylib//:workspace.bzl", "bazel_skylib_workspace")

bazel_skylib_workspace()

load("@build_bazel_rules_apple//apple:apple.bzl", "provisioning_profile_repository")
provisioning_profile_repository(
    name = "local_provisioning_profiles",
)
