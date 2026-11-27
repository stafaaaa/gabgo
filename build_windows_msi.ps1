# Builds the Windows installer (MSI with start-menu shortcut). Requires JDK 21.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Test-Jdk21($dir) { $dir -and (Test-Path "$dir\release") -and (Select-String -Path "$dir\release" -Pattern 'JAVA_VERSION="21' -Quiet) }
if (-not (Test-Jdk21 $env:JAVA_HOME)) {
    $jdk = Get-ChildItem 'C:\Program Files\Eclipse Adoptium', 'C:\Program Files\Java' -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^jdk-?21' } | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $jdk) { throw 'JDK 21 nicht gefunden. Installiere Temurin 21 (winget install EclipseAdoptium.Temurin.21.JDK) oder setze JAVA_HOME.' }
    $env:JAVA_HOME = $jdk.FullName
}
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
.\gradlew.bat :composeApp:packageMsi
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Get-ChildItem composeApp\build\compose\binaries\main\msi\*.msi | ForEach-Object { "MSI: $($_.FullName)" }
