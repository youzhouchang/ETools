@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================
REM  ETools Windows packaging (batch)
REM  Produces:
REM    - PyInstaller onedir app
REM    - Portable ZIP  (dist\ETools-portable-<ver>-win64.zip)
REM    - Installer EXE (Inno Setup or NSIS, if tool is on PATH)
REM
REM  Usage:
REM    packaging\package_windows.bat
REM    packaging\package_windows.bat --clean
REM    packaging\package_windows.bat --portable-only
REM ============================================================

set "ROOT=%~dp0.."
pushd "%ROOT%" >nul

set "APP_NAME=ETools"
set "CLEAN=0"
set "PORTABLE_ONLY=0"
set "INSTALLER=1"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--clean"  ( set "CLEAN=1" & shift & goto parse_args )
if /I "%~1"=="--portable-only" ( set "PORTABLE_ONLY=1" & set "INSTALLER=0" & shift & goto parse_args )
if /I "%~1"=="--no-installer"  ( set "INSTALLER=0" & shift & goto parse_args )
echo Unknown argument: %~1
echo Usage: package_windows.bat [--clean] [--portable-only] [--no-installer]
exit /b 2
:args_done

REM --- version from etools/__init__.py ---
set "VERSION=0.0.0"
for /f "tokens=2 delims== " %%A in ('findstr /R /C:"^__version__" etools\__init__.py') do (
  set "VERSION=%%~A"
)
set "VERSION=%VERSION:"=%"

echo ============================================================
echo  ETools Windows packaging  v%VERSION%
echo  Root: %CD%
echo ============================================================

REM --- locate python ---
set "PY=python"
if exist "%CD%\.venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
echo Using Python: %PY%
%PY% --version || (echo Python not found & exit /b 1)

echo.
echo [1/6] Installing packaging dependencies...
%PY% -m pip install -U pip >nul
%PY% -m pip install pyinstaller PySide6 pyocd pyserial paramiko || (echo pip install failed & exit /b 1)

if "%CLEAN%"=="1" (
  echo.
  echo [2/6] Cleaning build/dist...
  if exist build rmdir /s /q build
  if exist dist  rmdir /s /q dist
) else (
  echo.
  echo [2/6] Skip clean ^(use --clean^)
)

echo.
echo [3/6] Building PyInstaller onedir app...
%PY% -m PyInstaller --noconfirm --clean ^
  --distpath "%CD%\dist" ^
  --workpath "%CD%\build" ^
  packaging\etools.spec
if errorlevel 1 ( echo PyInstaller failed & exit /b 1 )

set "APP_DIR=%CD%\dist\%APP_NAME%"
set "APP_EXE=%APP_DIR%\%APP_NAME%.exe"
if not exist "%APP_EXE%" (
  echo FAIL: %APP_EXE% not found
  exit /b 1
)
echo       OK: %APP_EXE%

set "RELEASE_DIR=%CD%\dist\release"
if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"

if "%PORTABLE_ONLY%"=="1" goto portable_only

echo.
echo [4/6] Creating portable ZIP...
set "PORTABLE_ZIP=%RELEASE_DIR%\%APP_NAME%-portable-%VERSION%-win64.zip"
if exist "%PORTABLE_ZIP%" del /f /q "%PORTABLE_ZIP%"

REM Prefer tar (Win10+ ships bsdtar) for zip creation
where tar >nul 2>nul
if not errorlevel 1 (
  pushd dist >nul
  tar -a -cf "%PORTABLE_ZIP%" "%APP_NAME%"
  popd >nul
) else (
  REM Fallback: PowerShell Compress-Archive (works even if .ps1 is blocked)
  powershell -NoProfile -Command "Compress-Archive -Path '%APP_DIR%' -DestinationPath '%PORTABLE_ZIP%' -Force"
)
if not exist "%PORTABLE_ZIP%" (
  echo FAIL: portable zip not created
  exit /b 1
)
echo       OK: %PORTABLE_ZIP%

if "%INSTALLER%"=="0" goto summary

echo.
echo [5/6] Building installer EXE...

set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"

if defined ISCC (
  echo       Using Inno Setup: %ISCC%
  "%ISCC%" /DAppVersion=%VERSION% /DSourceDir="%APP_DIR%" /DOutputDir="%RELEASE_DIR%" packaging\etools.iss
  if errorlevel 1 (
    echo WARN: Inno Setup failed
  ) else (
    echo       OK: %RELEASE_DIR%\%APP_NAME%-setup-%VERSION%-win64.exe
  )
) else (
  where makensis >nul 2>nul
  if not errorlevel 1 (
    echo       Using NSIS...
    makensis /DAPP_VERSION=%VERSION% /DSOURCE_DIR=%APP_DIR% /DOUTPUT_DIR=%RELEASE_DIR% packaging\etools.nsi
    if errorlevel 1 (
      echo WARN: NSIS failed
    ) else (
      echo       OK: %RELEASE_DIR%\%APP_NAME%-setup-%VERSION%-win64.exe
    )
  ) else (
    echo       WARN: Neither Inno Setup ^(iscc^) nor NSIS ^(makensis^) found.
    echo       Install: winget install JRSoftware.InnoSetup
    echo       Portable ZIP is still available.
  )
)

goto summary

:portable_only
echo.
echo [4/6] Creating portable ZIP only...
set "PORTABLE_ZIP=%RELEASE_DIR%\%APP_NAME%-portable-%VERSION%-win64.zip"
if exist "%PORTABLE_ZIP%" del /f /q "%PORTABLE_ZIP%"
where tar >nul 2>nul
if not errorlevel 1 (
  pushd dist >nul
  tar -a -cf "%PORTABLE_ZIP%" "%APP_NAME%"
  popd >nul
) else (
  powershell -NoProfile -Command "Compress-Archive -Path '%APP_DIR%' -DestinationPath '%PORTABLE_ZIP%' -Force"
)
echo       OK: %PORTABLE_ZIP%

:summary
echo.
echo ============================================================
echo  Artifacts in dist\release\
echo ============================================================
if exist "%RELEASE_DIR%" (
  dir /b "%RELEASE_DIR%"
)
echo.
echo  Full app folder: dist\%APP_NAME%\%APP_NAME%.exe
echo ============================================================

popd >nul
endlocal
exit /b 0
