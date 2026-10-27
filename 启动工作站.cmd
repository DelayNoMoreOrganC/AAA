@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Workstation runtime is missing. Please contact the installer.
  pause
  exit /b 1
)
set PYTHONUTF8=1
".venv\Scripts\python.exe" workstation_entry.py
if errorlevel 1 pause
