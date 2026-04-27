@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run bootstrap_robot.bat first.
  exit /b 1
)

if "%~1"=="" (
  ".venv\Scripts\python.exe" robotctl.py /h
  exit /b %ERRORLEVEL%
)

if /I "%~1"=="stopall" (
  shift
  ".venv\Scripts\python.exe" robotctl.py stop all %*
  exit /b %ERRORLEVEL%
)

".venv\Scripts\python.exe" robotctl.py %*
exit /b %ERRORLEVEL%
