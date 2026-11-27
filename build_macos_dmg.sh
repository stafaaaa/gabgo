#!/usr/bin/env bash
# Builds the macOS disk image (requires macOS and JDK 21).
set -euo pipefail
cd "$(dirname "$0")"
if [ -z "${JAVA_HOME:-}" ] || ! "$JAVA_HOME/bin/java" -version 2>&1 | grep -q '"21'; then
  JAVA_HOME="$(/usr/libexec/java_home -v 21)" || { echo "JDK 21 nicht gefunden (z. B. brew install --cask temurin@21)."; exit 1; }
fi
export JAVA_HOME
./gradlew :composeApp:packageDmg
echo "DMG: $(ls composeApp/build/compose/binaries/main/dmg/*.dmg)"
