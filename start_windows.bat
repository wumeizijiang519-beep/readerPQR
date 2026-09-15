@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto :python_missing
)
".venv\Scripts\python.exe" -c "import PySide6, pymupdf, httpx" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m readerpqr %*
if errorlevel 1 goto :failed
exit /b 0
:python_missing
echo Install Python 3.12 x64 from python.org, including the Python Launcher.
pause
exit /b 1
:failed
echo Startup failed. Please read the error above and docs\WINDOWS_GUIDE.md.
pause
exit /b 1
