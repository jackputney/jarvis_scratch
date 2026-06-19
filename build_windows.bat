@echo off
REM build_windows.bat — Build a double-clickable Jarvis.exe for Windows (PyInstaller).
REM
REM Produces:  dist\Jarvis\Jarvis.exe
REM User data:  %APPDATA%\Jarvis\
REM Logs:       %APPDATA%\Jarvis\logs\jarvis.log
REM
REM Usage: build_windows.bat
REM
REM macOS dev is unchanged — keep using build_mac.sh / run.sh.
setlocal EnableExtensions
cd /d "%~dp0"

if /i not "%OS%"=="Windows_NT" (
  echo ERROR: build_windows.bat is Windows only.
  echo        On macOS, use ./build_mac.sh to launch from source.
  exit /b 1
)

echo Building Jarvis.exe with PyInstaller...

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtualenv ^(.venv^)...
  python -m venv .venv
  if errorlevel 1 (
    echo ERROR: Could not create .venv — install Python 3.11+ from python.org
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"

echo Installing build dependencies...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
python -m pip install pyinstaller -q
if errorlevel 1 exit /b 1

echo Cleaning previous build artefacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Running PyInstaller ^(this may take several minutes^)...
python -m PyInstaller jarvis_windows.spec --noconfirm --clean
if errorlevel 1 exit /b 1

if not exist "dist\Jarvis\Jarvis.exe" (
  echo ERROR: Build failed — dist\Jarvis\Jarvis.exe not found.
  exit /b 1
)

echo.
echo Built: dist\Jarvis\Jarvis.exe
echo    * Copy the dist\Jarvis folder anywhere, then double-click Jarvis.exe
echo    * First run opens the setup wizard ^(Anthropic key -^> optional Cartesia^)
echo    * Global hotkey ^(Ctrl+Shift+Space^) registers automatically
echo    * User data: %APPDATA%\Jarvis\
echo    * Logs: %APPDATA%\Jarvis\logs\jarvis.log
echo.
echo    Windows may ask for Microphone permission on first use.
endlocal
