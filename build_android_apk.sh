#!/usr/bin/env bash
# Builds the installable Android debug APK into releases/GabGo-Android.apk.
set -euo pipefail
cd "$(dirname "$0")"
./gradlew :composeApp:assembleDebug
mkdir -p releases
cp composeApp/build/outputs/apk/debug/composeApp-debug.apk releases/GabGo-Android.apk
echo "APK: releases/GabGo-Android.apk"
