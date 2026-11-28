; Inno-Setup-Skript für Tankbelege. Kompilieren mit build_setup.bat (erzeugt Output\Tankbelege-Setup.exe).
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B0E5C1E-3F7A-4C2B-9D41-7A2E58C0B1F4}
AppName=Tankbelege
AppVersion={#AppVersion}
AppVerName=Tankbelege {#AppVersion}
DefaultDirName={autopf}\Tankbelege
DefaultGroupName=Tankbelege
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Tankbelege-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=assets\anna.ico
UninstallDisplayIcon={app}\Tankbelege.exe
UninstallDisplayName=Tankbelege

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\Tankbelege\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "Tanken_neu - Kopie.xlsx"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
#ifexist "vendor\tesseract\tesseract.exe"
Source: "vendor\tesseract\*"; DestDir: "{app}\tesseract"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
  #pragma warning "vendor\tesseract fehlt: Setup ohne Tesseract OCR (Bild-Scans brauchen dann eine eigene Tesseract-Installation)."
#endif

[Icons]
Name: "{autoprograms}\Tankbelege"; Filename: "{app}\Tankbelege.exe"
Name: "{autoprograms}\Tankbelege deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Tankbelege"; Filename: "{app}\Tankbelege.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Tankbelege.exe"; Description: "{cm:LaunchProgram,Tankbelege}"; Flags: nowait postinstall skipifsilent
