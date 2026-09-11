; ETools — NSIS installer script
; Compile with:
;   makensis /DAPP_VERSION=0.1.0 /DSOURCE_DIR=..\dist\ETools /DOUTPUT_DIR=..\dist\release packaging\etools.nsi

!ifndef APP_VERSION
  !define APP_VERSION "0.1.0"
!endif
!ifndef APP_NAME
  !define APP_NAME "ETools"
!endif
!ifndef SOURCE_DIR
  !define SOURCE_DIR "..\dist\ETools"
!endif
!ifndef OUTPUT_DIR
  !define OUTPUT_DIR "..\dist\release"
!endif

!define EXE_NAME "${APP_NAME}.exe"
!define INSTALLER_NAME "${APP_NAME}-setup-${APP_VERSION}-win64.exe"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${OUTPUT_DIR}\${INSTALLER_NAME}"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel admin
Unicode True
SetCompressor /SOLID lzma

Page directory
Page components
Page instfiles

UninstPage uninstConfirm
UninstPage instfiles

Section "Install ${APP_NAME}" SEC_MAIN
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*.*"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
    "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
    "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
    "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
    "DisplayIcon" "$INSTDIR\${EXE_NAME}"

  CreateShortCut "$SMPROGRAMS\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
SectionEnd

Section "Desktop shortcut" SEC_DESK
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR"
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  DeleteRegKey HKLM "Software\${APP_NAME}"
SectionEnd
