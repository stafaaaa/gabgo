# GabGo – KI-Event-, Ausgeh- & Familien-Finder

`de.gabbas.gabgo` · Kotlin Multiplatform + Compose Multiplatform (Material 3) für **Android, Windows, macOS und iOS/iPadOS** (Linux-Desktop läuft mit).

GabGo findet echte Events, Ausflugsziele und Familienaktivitäten über **Live-Websuche** (Google Gemini mit `google_search`-Grounding oder Perplexity `sonar`/`sonar-pro`). Ohne Live-Quellen werden keine Ergebnisse angezeigt.

## Funktionen

| Bereich | Inhalt |
|---|---|
| GabGo-Radar | Stadt, Umkreis, Zeitraum (Presets + Kalender), Budget, Stimmung, Kategorien, eigene Tags, Freitext |
| Familie & Tagesausflug | Musik-unabhängiger Modus mit Altersgruppen (Kleinkinder, Kinder, Teenager, Erwachsene/Paare) |
| Anti-Halluzination | Strenger System-Prompt, JSON-Ausgabe, `ResultParser` verwirft alles ohne Datum, Ort oder HTTP(S)-Quelle bzw. außerhalb des Zeitraums |
| Fallback | Primärer Anbieter + optionaler Fallback auf den zweiten |
| Unsere Vibes | Vibe-Profil → komprimierter Code `GV1.…` (Deflate + Base64url) + QR-Code, Import per Scan (Android/iOS) oder Einfügen; Gruppen-Match ohne Server |
| Event-Karten | `.ics`-Export, Route (Apple Karten auf Apple-Geräten, sonst Google Maps), Uber-Deeplink, Merkliste, Quelle/Tickets |
| Themes | GabGo Pulse, Midnight Gold, Ocean Glass, Clean Light – live umschaltbar |
| Lizenz | Demo: 3 Suchen, Gruppen bis 2 Personen, 2 Themes · Pro: unbegrenzt; Ed25519-Offline-Prüfung |

## Projektstruktur

```
composeApp/src/
  commonMain/   gesamte Logik + UI (ai, calendar, data, license, links, model, platform, ui, vibes)
  commonTest/   Unit-Tests (Lizenz/Ed25519, ICS, Vibe-Code & Merge, ResultParser)
  androidMain/  MainActivity, SharedPreferences, Intents, FileProvider, ZXing-Scanner
  desktopMain/  main.kt, Properties-Datei im App-Datenordner, Browser/Datei öffnen
  iosMain/      MainViewController, NSUserDefaults, UIActivityViewController, zlib, CommonCrypto
iosApp/         Xcode-Projekt (SwiftUI + ComposeUIViewController, AVFoundation-QR-Scanner, Info.plist)
branding_assets/  Original-Icons (unverändert)
generate_gabgo_license.py  Lizenz-Generator (Ed25519)
```

## Voraussetzungen

- JDK 21 (Temurin), Android SDK 35
- macOS + Xcode 15+ für iOS und `packageDmg`, Windows für `packageMsi`

## Bauen

```bash
./gradlew :composeApp:testDebugUnitTest :composeApp:compileKotlinDesktop :composeApp:assembleDebug

./gradlew :composeApp:run                    # Desktop starten
./gradlew :composeApp:createDistributable    # App-Image für das aktuelle OS
./gradlew :composeApp:packageMsi             # Windows-Installer (auf Windows, mit Startmenü-Eintrag)
./gradlew :composeApp:packageDmg             # macOS (auf macOS)
./gradlew :composeApp:assembleRelease        # Android Release (Signatur über keystore.properties)
```

iOS: `iosApp/iosApp.xcodeproj` in Xcode öffnen, in `iosApp/Configuration/Config.xcconfig` die `TEAM_ID` setzen und starten. Die Build-Phase ruft `./gradlew :composeApp:embedAndSignAppleFrameworkForXcode` auf.

Android-Release-Signatur: `keystore.properties` im Projektstamm (nicht eingecheckt):

```properties
storeFile=/pfad/gabgo.jks
storePassword=…
keyAlias=gabgo
keyPassword=…
```

## API-Keys (BYOK)

In der App unter **Einstellungen → KI-Live-Suche** eintragen. Keys werden nur lokal gespeichert.

- Gemini: https://aistudio.google.com/apikey (Standardmodell `gemini-2.5-flash`)
- Perplexity: https://www.perplexity.ai/settings/api (`sonar` oder `sonar-pro`)

## Lizenzen

Format: `GABGO1-<base64url(payload-json)>.<base64url(ed25519-signatur)>`. Der öffentliche Schlüssel steckt in `license/LicensePublicKey.kt`; der private Schlüssel (`gabgo_private.pem`) gehört **nicht** ins Repository.

```bash
pip install cryptography
python3 generate_gabgo_license.py --new-keypair              # einmalig; danach Public Key in LicensePublicKey.kt eintragen
python3 generate_gabgo_license.py --print-public-key
python3 generate_gabgo_license.py --name "Max Muster" --email max@example.com [--expires 2027-12-31] [--count 3]
python3 generate_gabgo_license.py --verify GABGO1-…
```
