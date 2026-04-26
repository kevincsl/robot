@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM Check if .venv exists
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run bootstrap_robot.bat first.
  exit /b 1
)

REM Function to start a single robot
if "%1"=="all" goto START_ALL
if "%1"=="" goto SHOW_HELP

REM Start single robot mode
set "CONFIG_NAME=%1"
set "ENV_FILE=.env.%CONFIG_NAME%"

if not exist "%ENV_FILE%" (
  echo Error: Configuration file %ENV_FILE% not found
  echo.
  echo Available configurations:
  for %%f in (.env.robot*) do (
    set "fname=%%~nxf"
    set "fname=!fname:.env.=!"
    echo   - !fname!
  )
  exit /b 1
)

echo Starting robot with config: %CONFIG_NAME%
echo Loading: %ENV_FILE%
echo.

call .venv\Scripts\activate.bat

REM Load environment from config file
for /f "usebackq tokens=1* delims==" %%a in ("%ENV_FILE%") do (
  if not "%%a"=="" if not "%%a:~0,1%"=="#" (
    set "%%a=%%b"
  )
)

REM Clear proxy settings
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="

REM Set teleapp environment
set "TELEAPP_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined TELEAPP_HOT_RELOAD set "TELEAPP_HOT_RELOAD=0"
if not defined TELEAPP_WATCH_MODE set "TELEAPP_WATCH_MODE=app-file-only"
if defined PYTHONPATH (
  set "PYTHONPATH=%CD%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%CD%"
)

echo Robot ID: %ROBOT_ID%
echo State file: .robot_state\robot_state_%ROBOT_ID%.json
echo.

"%TELEAPP_PYTHON%" -m teleapp "%TELEAPP_APP%" --python "%TELEAPP_PYTHON%"
goto END

:START_ALL
echo Starting all robots in background...
echo.

REM Create log directory if not exists
if not exist ".robot_state" mkdir .robot_state

set "COUNT=0"
for %%f in (.env.robot*) do (
  set "fname=%%~nxf"
  set "fname=!fname:.env.=!"

  REM Skip .example files
  echo !fname! | findstr /C:".example" >nul
  if errorlevel 1 (
    echo Starting robot: !fname!
    start "Robot-!fname!" /MIN cmd /c "%~f0" !fname! ^> .robot_state\!fname!.log 2^>^&1
    set /a COUNT+=1
    timeout /t 2 /nobreak >nul
  )
)

echo.
echo Started %COUNT% robot(s) in background
echo.
echo Management commands:
echo   manage_robots.bat status    - Check running robots
echo   manage_robots.bat stop ^<id^>  - Stop specific robot
echo   manage_robots.bat stopall   - Stop all robots
echo   manage_robots.bat logs ^<id^>  - View robot logs
goto END

:SHOW_HELP
echo Usage: start_robot.bat [config_name^|all]
echo.
echo Examples:
echo   start_robot.bat robot1    - Start robot with .env.robot1 config
echo   start_robot.bat robot2    - Start robot with .env.robot2 config
echo   start_robot.bat mybot     - Start robot with .env.mybot config
echo   start_robot.bat all       - Start all robots (scan .env.robot* files)
echo.
echo Available configurations:
for %%f in (.env.robot*) do (
  set "fname=%%~nxf"
  set "fname=!fname:.env.=!"
  echo   - !fname!
)
echo.
echo To create a new robot:
echo   1. Copy .env.robot1.example to .env.robotN
echo   2. Edit .env.robotN and set ROBOT_ID, TELEAPP_TOKEN, etc.
echo   3. Run: start_robot.bat robotN

:END
