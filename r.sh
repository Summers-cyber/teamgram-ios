python3 build-system/Make/Make.py \
    --overrideXcodeVersion \
    --cacheDir="$HOME/telegram-bazel-cache2" \
    generateProject \
    --configurationPath=build-system/appstore-configuration.json \
    --codesigningInformationPath=build-system/fake-codesigning \
    --disableExtensions \
    --disableProvisioningProfiles
