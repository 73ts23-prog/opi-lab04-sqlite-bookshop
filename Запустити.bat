@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create .venv and install requirements.txt first. See README.md.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:5004 in your browser.
echo Press Ctrl+C to stop the server.
".venv\Scripts\python.exe" app.py
pause
