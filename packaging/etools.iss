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
AppId={{8F3C2A10-9B7E-4D2A-9E5C-ETools000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ETools Contributors
AppPublisherURL=https://github.com/
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=
OutputDir={#OutputDir}
OutputBaseFilename={#InstallerBaseName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=
PrivilegesRequired=admin
CloseApplications=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Entire PyInstaller onedir tree
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
