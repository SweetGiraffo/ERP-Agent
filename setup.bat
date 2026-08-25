@echo off
python -m venv .venv
call .venv\Scripts\activate.bat

pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium

if not exist .env (
  copy .env.example .env
  echo Created .env - fill in your credentials before running main.py
)
