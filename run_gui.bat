@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m app gui --config config.yaml
) else (
  py -3.12 -m app gui --config config.yaml
)

if errorlevel 1 pause
