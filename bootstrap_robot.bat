@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install wheel
python -m pip install --no-build-isolation -c constraints.txt -e .
python scripts\setup_env.py
