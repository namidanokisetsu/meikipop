#ifndef AppVersion
  #define AppVersion "2.0.4"
#endif

[Setup]
AppId={{58E3091B-9721-4B42-9FC9-03D77D4C24DC}
AppName=meikipop-turkish
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\meikipop-turkish
DefaultGroupName=meikipop-turkish
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=meikipop-turkish-{#AppVersion}-windows-x64-setup
SetupIconFile=..\src\meikipop\resources\icon.ico
UninstallDisplayIcon={app}\meikipop-turkish.exe
LicenseFile=..\LICENSE
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=meikipop-turkish.exe,meikipop-turkish-cli.exe

[Files]
Source: "..\dist\meikipop-turkish\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Desktop shortcut"; Flags: unchecked

[Icons]
Name: "{group}\meikipop-turkish"; Filename: "{app}\meikipop-turkish.exe"; AppUserModelID: "meikipop-turkish"
Name: "{autodesktop}\meikipop-turkish"; Filename: "{app}\meikipop-turkish.exe"; Tasks: desktopicon; AppUserModelID: "meikipop-turkish"

[Run]
Filename: "{app}\meikipop-turkish.exe"; Description: "Launch meikipop-turkish"; Flags: nowait postinstall skipifsilent
