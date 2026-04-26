@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run bootstrap_robot.bat first.
  exit /b 1
)

call .venv\Scripts\activate.bat

REM Load environment from .env.robot2
if exist ".env.robot2" (
  for /f "usebackq tokens=1* delims==" %%a in (".env.robot2") do (
    if not "%%a"=="" if not "%%a:~0,1%"=="#" (
      set "%%a=%%b"
    )
  )
) else (
  echo Missing .env.robot2 configuration file
  exit /b 1
)

set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
set "TELEAPP_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined TELEAPP_HOT_RELOAD set "TELEAPP_HOT_RELOAD=0"
if not defined TELEAPP_WATCH_MODE set "TELEAPP_WATCH_MODE=app-file-only"
if defined PYTHONPATH (
  set "PYTHONPATH=%CD%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%CD%"
)

echo Starting Robot ID: %ROBOT_ID%
echo State file: .robot_state\robot_state_%ROBOT_ID%.json
echo.

"%TELEAPP_PYTHON%" -m teleapp "%TELEAPP_APP%" --python "%TELEAPP_PYTHON%"
