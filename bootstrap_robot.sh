#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  python -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install wheel
python -m pip install --no-build-isolation -c constraints.txt -e .
python scripts/install_robotctl_shims.py
python scripts/setup_env.py
