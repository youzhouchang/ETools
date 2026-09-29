; ETools — Inno Setup installer script
; Compile with:
;   iscc /DAppVersion=0.1.0 /DSourceDir=..\dist\ETools /DOutputDir=..\dist\release packaging\etools.iss
;
; Optional defines (defaults provided):
;   AppVersion, SourceDir, OutputDir, AppName

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef AppName
  #define AppName "ETools"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\ETools"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\release"
#endif

#define AppExeName AppName + ".exe"
#define InstallerBaseName AppName + "-setup-" + AppVersion + "-win64"

[Setup]
AppId={{8F3C2A10-9B7E-4D2A-9E5C-ETools000001}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ETools Contributors
AppPublisherURL=https://github.com/
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#InstallerBaseName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Brand icon for installer exe + Start/Programs shortcuts
SetupIconFile=..\docs\icons\png\etools.ico
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=admin
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Entire PyInstaller onedir tree
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  SHCNE_ASSOCCHANGED = $08000000;
  SHCNF_IDLIST = $0000;

procedure SHChangeNotify(wEventId: LongWord; uFlags: LongWord; dwItem1: LongWord; dwItem2: LongWord);
  external 'SHChangeNotify@shell32.dll stdcall';

procedure RefreshShellIconCache();
var
  ResultCode: Integer;
begin
  { Tell Explorer that icons / associations changed }
  SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0);
  { Rebuild the icon cache so desktop / taskbar pick up the new brand icon }
  if FileExists(ExpandConstant('{sys}\ie4uinit.exe')) then
  begin
    Exec(ExpandConstant('{sys}\ie4uinit.exe'), '-show', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec(ExpandConstant('{sys}\ie4uinit.exe'), '-ClearIconCache', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RefreshShellIconCache();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RefreshShellIconCache();
end;
