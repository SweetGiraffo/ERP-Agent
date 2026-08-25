#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env - fill in your credentials before running main.py"
fi
