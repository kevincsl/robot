@echo off
setlocal
cd /d "%~dp0"

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
if defined PYTHONPATH (
  set "PYTHONPATH=%CD%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%CD%"
)
"%CD%\.venv\Scripts\teleapp.exe" "%TELEAPP_APP%" --python "%TELEAPP_PYTHON%"
