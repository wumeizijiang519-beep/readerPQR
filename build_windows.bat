@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" scripts\build_windows.py
if errorlevel 1 goto :failed
echo Build complete: dist\readerPQR\readerPQR.exe
echo Keep the entire readerPQR folder, including _internal.
pause
exit /b 0
:failed
echo Build failed. Please inspect the error above.
pause
exit /b 1
