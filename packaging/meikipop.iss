#ifndef AppVersion
  #error Pass AppVersion from pyproject.toml via Build-Windows.ps1
#endif

[Setup]
AppId={{C9D106CA-5A90-45D6-9634-669E3D971CE2}
AppName=Meikipop
AppMutex=Local\MeikipopDesktop
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
Filename: "{app}\Meikipop.exe"; Description: "Open Meikipop"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "meikipop"; Flags: uninsdeletevalue

[Code]
var
  RemoveUserData: Boolean;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Cleaned: Boolean;
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    RemoveUserData := ExpandConstant('{param:REMOVEUSERDATA|0}') = '1';
    if (not RemoveUserData) and (not UninstallSilent) then
      RemoveUserData := SuppressibleMsgBox(
        'Remove settings, language profiles, and downloaded data?' + #13#10 +
        'Dictionaries and models in Meikipop''s data folder will be deleted.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
  end;
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then
  begin
    Cleaned := True;
    if RegKeyExists(HKCU, 'Software\Meikipop') then
      Cleaned := RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Meikipop');
    DataDir := ExpandConstant('{localappdata}\meikipop');
    if DirExists(DataDir) then
      if not DelTree(DataDir, True, True, True) then Cleaned := False;
    DataDir := ExpandConstant('{userappdata}\meikipop');
    if DirExists(DataDir) then
      if not DelTree(DataDir, True, True, True) then Cleaned := False;
    if not Cleaned then
      SuppressibleMsgBox('Some Meikipop data could not be removed. Close Meikipop and remove the remaining data before reinstalling.',
        mbError, MB_OK, IDOK);
  end;
end;
