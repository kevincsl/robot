@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run bootstrap_robot.bat first.
  exit /b 1
)
".venv\Scripts\python.exe" robotctl.py start default %*
exit /b %ERRORLEVEL%
