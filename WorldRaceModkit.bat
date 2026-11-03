@echo off
where uv >nul 2>nul
if errorlevel 1 (
  echo World Race Mod Manager needs uv, which is not installed.
  echo Install it once by running this in PowerShell, then start this file again:
  echo.
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
  echo.
  pause
  exit /b 1
)
start "" uvw run --script "%~dp0worldrace.py"
