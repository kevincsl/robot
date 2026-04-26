@echo off
setlocal
cd /d "%~dp0"

if "%1"=="" (
  echo Usage: start_robot_multi.bat ^<robot_id^> [bot_token]
  echo.
  echo Example:
  echo   start_robot_multi.bat robot-1
  echo   start_robot_multi.bat robot-2 YOUR_BOT_TOKEN_HERE
  echo.
  echo This will start a robot instance with:
  echo   - ROBOT_ID=%1
  echo   - State file: .robot_state/robot_state_%1.json
  echo   - Optional: TELEAPP_TOKEN=%2 (if provided)
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run bootstrap_robot.bat first.
  exit /b 1
)

call .venv\Scripts\activate.bat
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
set "TELEAPP_APP=robot.py"
set "TELEAPP_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined TELEAPP_HOT_RELOAD set "TELEAPP_HOT_RELOAD=0"
if not defined TELEAPP_WATCH_MODE set "TELEAPP_WATCH_MODE=app-file-only"
if defined PYTHONPATH (
  set "PYTHONPATH=%CD%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%CD%"
)

set "ROBOT_ID=%1"

if not "%2"=="" (
  set "TELEAPP_TOKEN=%2"
)

echo Starting robot with ID: %ROBOT_ID%
echo State file: .robot_state\robot_state_%ROBOT_ID%.json
echo.

"%TELEAPP_PYTHON%" -m teleapp "%TELEAPP_APP%" --python "%TELEAPP_PYTHON%"
