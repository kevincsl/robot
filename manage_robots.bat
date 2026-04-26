@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "COMMAND=%1"

if "%COMMAND%"=="" goto SHOW_HELP
if "%COMMAND%"=="status" goto STATUS
if "%COMMAND%"=="stop" goto STOP
if "%COMMAND%"=="stopall" goto STOPALL
if "%COMMAND%"=="logs" goto LOGS
goto SHOW_HELP

:STATUS
echo Checking running robots...
echo.

set "FOUND=0"
for /f "tokens=2" %%a in ('tasklist /FI "WINDOWTITLE eq Robot-*" /NH 2^>nul ^| find "cmd.exe"') do (
  set "FOUND=1"
)

if "%FOUND%"=="0" (
  echo No robots running.
  goto END
)

echo Running robot processes:
echo.
tasklist /FI "WINDOWTITLE eq Robot-*" /V | findstr /C:"Robot-"
echo.

REM Check state files
echo Robot states:
echo.
for %%f in (.robot_state\robot_state_*.json) do (
  set "fname=%%~nxf"
  set "robot_id=!fname:robot_state_=!"
  set "robot_id=!robot_id:.json=!"
  echo   [!robot_id!] State file: %%f
)
goto END

:STOP
if "%2"=="" (
  echo Error: Please specify robot ID
  echo Usage: manage_robots.bat stop ^<robot_id^>
  exit /b 1
)

set "ROBOT_ID=%2"
echo Stopping robot: %ROBOT_ID%

REM Find and kill the process with matching window title
for /f "tokens=2" %%a in ('tasklist /FI "WINDOWTITLE eq Robot-%ROBOT_ID%" /NH 2^>nul ^| find "cmd.exe"') do (
  echo Killing process: %%a
  taskkill /PID %%a /T /F
)

echo Robot %ROBOT_ID% stopped.
goto END

:STOPALL
echo Stopping all robots...
echo.

set "COUNT=0"
for /f "tokens=2" %%a in ('tasklist /FI "WINDOWTITLE eq Robot-*" /NH 2^>nul ^| find "cmd.exe"') do (
  echo Killing process: %%a
  taskkill /PID %%a /T /F
  set /a COUNT+=1
)

if "%COUNT%"=="0" (
  echo No robots running.
) else (
  echo Stopped %COUNT% robot(s).
)
goto END

:LOGS
if "%2"=="" (
  echo Available log files:
  echo.
  for %%f in (.robot_state\*.log) do (
    echo   %%f
  )
  echo.
  echo Usage: manage_robots.bat logs ^<robot_id^>
  exit /b 1
)

set "ROBOT_ID=%2"
set "LOG_FILE=.robot_state\%ROBOT_ID%.log"

if not exist "%LOG_FILE%" (
  echo Error: Log file %LOG_FILE% not found
  exit /b 1
)

echo Showing logs for robot: %ROBOT_ID%
echo Log file: %LOG_FILE%
echo.
echo ========================================
type "%LOG_FILE%"
goto END

:SHOW_HELP
echo Robot Management Tool
echo.
echo Usage: manage_robots.bat ^<command^> [options]
echo.
echo Commands:
echo   status              - Show all running robots
echo   stop ^<robot_id^>     - Stop a specific robot
echo   stopall             - Stop all running robots
echo   logs ^<robot_id^>     - Show logs for a specific robot
echo.
echo Examples:
echo   manage_robots.bat status
echo   manage_robots.bat stop robot1
echo   manage_robots.bat stopall
echo   manage_robots.bat logs robot1

:END
