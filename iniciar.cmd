@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=
if not exist ".venv\Scripts\python.exe" (
  echo Crie o ambiente .venv conforme README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app.py
pause
