#ifndef AppVersion
  #define AppVersion "2.1.2"
#endif

[Setup]
AppId={{C9D106CA-5A90-45D6-9634-669E3D971CE2}
AppName=Meikipop
AppVersion={#AppVersion}
AppPublisher=Meikipop contributors
AppPublisherURL=https://github.com/namidanokisetsu/meikipop
DefaultDirName={localappdata}\Programs\Meikipop
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Meikipop-{#AppVersion}-windows-x64-setup
SetupIconFile=..\src\meikipop\resources\icon.ico
UninstallDisplayIcon={app}\Meikipop.exe
LicenseFile=..\LICENSE
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=Meikipop.exe,Meikipop-cli.exe

[Files]
Source: "..\dist\Meikipop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Desktop shortcut"; Flags: unchecked

[Icons]
Name: "{autoprograms}\Meikipop"; Filename: "{app}\Meikipop.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Meikipop"; Filename: "{app}\Meikipop.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Meikipop.exe"; Parameters: "--setup"; Description: "Set up Meikipop"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "meikipop"; Flags: uninsdeletevalue
